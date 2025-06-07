r"came\s+back\s+to\s+standby\s+pos.*?totalangle:\s*([-+]?\d+(?:\.\d+)?)",# -*- coding: utf-8 -*-


# ===== rewriten header (Mac / Raspberry Pi 両対応) =====
import sys
import glob
import random
import time
import threading
import pandas as pd
# ==== 追加：グローバル変数とロック ============================
from threading import Timer, Lock
song_lock = Lock()          # 送信競合防止
songs_since_long_rest = 0   # 直近で何曲歌ったか
next_long_rest_after = random.randint(10, 15)   # 次に長休憩を入れる曲数
# =============================================================
# === 追加インポート =========================
import re
import argparse, sys

# 「song done … msec … totalAngle: …」を拾うパターン
#DONE_RE = re.compile(
#    r"came\s+back\s+to\s+standby\s+pos.*?totalangle:\s*([-+]?\d+(?:\.\d+)?)",
#    re.IGNORECASE
#)
# ==========================================
CAME_BACK_RE = re.compile(r"came\s+back\s+to\s+standby\s+pos", re.IGNORECASE)


try:
    import serial         # PySerial
except ImportError as e:
    raise ImportError(
        "PySerial が入っていません。`pip3 install pyserial` を実行してください。"
    ) from e


def auto_detect_port() -> str:
    """
    macOS なら /dev/tty.usbserial-* や /dev/tty.usbmodem*  
    Linux（Raspberry Pi）なら /dev/ttyUSB* /dev/ttyACM* を自動検出。
    最初に見つかった 1 本を返す。見つからなければ RuntimeError。
    """
    if sys.platform.startswith("darwin"):
        candidates = glob.glob("/dev/tty.usbserial-*") + glob.glob("/dev/tty.usbmodem*")
    elif sys.platform.startswith("linux"):
        candidates = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")

    if not candidates:
        raise RuntimeError("USB-Serial デバイスが見つかりません")

    return candidates[0]


PORT    = auto_detect_port()   # 自動検出（固定したい場合は直接文字列を入れても OK）
BAUD    = 115200
TIMEOUT = 1                    # 秒

ser = serial.Serial(PORT, BAUD, timeout=TIMEOUT)
ser.reset_input_buffer()
ser.reset_output_buffer()
print(f"[INFO] Opened {PORT} @ {BAUD} bps")
# =========================================


# 受信処理用スレッド停止用フラグ
stop_serial_thread = False

# def serial_reader():
#     """シリアルポートから常に受信するスレッド（受信データがあれば表示）"""
#     while not stop_serial_thread:
#         if ser.in_waiting > 0:
#             try:
#                 data = ser.readline().decode('utf-8', errors='replace').strip()
#                 if data:
#                     print("受信:", data)
#             except Exception as e:
#                 print("受信エラー:", e)
#         time.sleep(0.1)  # 0.1秒ポーリング

def serial_reader():
    """
    シリアルポートから常に受信するスレッド
    "song done" を含む行を検知したら次の曲をタイマーで送信
    """
    global songs_since_long_rest, next_long_rest_after

    while not stop_serial_thread:
        if ser.in_waiting > 0:
            try:
                raw = ser.readline().decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                print("受信:", raw)

                # ▼ "song done" 行を正規表現で判定
                m = CAME_BACK_RE.search(raw)
                if m:
                    print("[DEBUG] came back detected")
                    #took_ms     = int(m.group(1))     # 再生時間 [ms]
                    #total_angle = float(m.group(2))   # totalAngle
                    #print(f"[DEBUG] took={took_ms} ms, totalAngle={total_angle}")

                    # ─── 休憩長さを決定 ─────────────────
                    songs_since_long_rest += 1
                    if songs_since_long_rest >= next_long_rest_after:
                        delay = 60        # 1 分休憩
                        songs_since_long_rest = 0
                        next_long_rest_after = random.randint(10, 15)
                        print(f"[INFO] Long rest {delay}s  (next long after {next_long_rest_after} songs)")
                    else:
                        delay = random.uniform(4, 6)
                        print(f"[INFO] Short rest {delay:.1f}s")

                    # タイマーで非同期送信
                    Timer(delay, generate_and_send_song).start()

            except Exception as e:
                print("受信エラー:", e)

        time.sleep(0.1)


# 統計データの読み込みと前処理
file_path = './Nightingale song analysis.xlsx'
df = pd.read_excel(file_path)

# rep と dur のペアを集める
rep_data_combined = []
dur_data_combined = []
for index, row in df.iterrows():
    num_elements = row['num of element']
    for i in range(1, int(num_elements) + 1):
        rep_col = f'el:{i} rep'
        dur_col = f'el:{i} dur'
        if pd.notna(row[rep_col]) and pd.notna(row[dur_col]):
            rep_data_combined.append(row[rep_col])
            dur_data_combined.append(row[dur_col])

# データのグループ化
duration_bins = [0, 500, 1500, 2500, 3500]
duration_groups = pd.cut(dur_data_combined, bins=duration_bins)
repetition_distribution = pd.crosstab(duration_groups, rep_data_combined, normalize='index')

# Repetitionの生成関数
def biased_choice(options, weights, fallback_range=None):
    """偏りを付けた選択を行う関数"""
    if fallback_range is None or random.random() < 0.8:
        return int(random.choices(options, weights=weights, k=1)[0])
    else:
        return random.randint(fallback_range[0], fallback_range[1])

def generate_repetition_based_on_stats(duration, distribution):
    if duration <= 500:
        return biased_choice(
            list(distribution.loc[pd.Interval(0, 500)].index),
            distribution.loc[pd.Interval(0, 500)].values
        )
    elif duration <= 1500:
        return biased_choice(
            list(distribution.loc[pd.Interval(500, 1500)].index),
            distribution.loc[pd.Interval(500, 1500)].values
        )
    elif duration <= 2500:
        return biased_choice(
            list(distribution.loc[pd.Interval(1500, 2500)].index),
            distribution.loc[pd.Interval(1500, 2500)].values
        )
    else:
        # 最後の範囲では均等に1〜16を生成（必要に応じてフォールバック範囲を指定）
        return biased_choice(
            list(distribution.loc[pd.Interval(2500, 3500)].index),
            distribution.loc[pd.Interval(2500, 3500)].values,
            fallback_range=(12, 16)
        )

def generate_and_send_song():
    # """1 曲分のパラメータを生成して ESP に送信"""
    with song_lock:  # 同時実行されないよう排他制御
        # 送信前に受信バッファをクリア
        ser.reset_input_buffer()
        
        # Total Duration と構造数（セグメント数）の生成
        total_duration = random.randint(1750, 4750)
        num_elements = random.randint(5, 10)
        
        # 各構造に Duration を割り当てる
        remaining_duration = total_duration
        durations = []
        for i in range(num_elements):
            if i == num_elements - 1:
                durations.append(remaining_duration)
            else:
                max_duration = remaining_duration // (num_elements - i)
                d = random.randint(100, max_duration)
                durations.append(d)
                remaining_duration -= d
        
        # 各構造の Repetition を生成
        repetitions = [generate_repetition_based_on_stats(d, repetition_distribution) for d in durations]
        
        # posTop と posBack の生成
        posTop = [random.randint(50, 200) for _ in range(num_elements)]
        posBack = [random.randint(top, top + 300) for top in posTop]
        
        # 追加：sValvPttn（0〜3の乱数）と bValvPttn（0〜2の乱数）の生成
        # sValvPttn = [random.randint(0, 3) for _ in range(num_elements)]
        # bValvPttn = [random.randint(0, 2) for _ in range(num_elements)]
        
        # 追加：pumpFlowRate（20〜50の乱数）
        # pumpFlowRate = [random.randint(20, 40) for _ in range(num_elements)]

        # 送信メッセージの生成（CSV形式）
        # 順番は： total_duration, num_elements, durations, repetitions, posTop, posBack, sValvPttn, bValvPttn
        message_parts = [total_duration, num_elements] + durations + repetitions + posTop + posBack
        message_str = ','.join(map(str, message_parts)) + "\n"
        
        print("送信メッセージ:", message_str)
        ser.write(message_str.encode('utf-8'))

# if __name__ == '__main__':
#     # 受信スレッド開始
#     serial_thread = threading.Thread(target=serial_reader, daemon=True)
#     serial_thread.start()
#      # ★ ここで 1 曲だけ自動送信（最初の一発）
#     generate_and_send_song()

#     print("プログラム開始。's'を入力して曲を生成送信します。終了する場合は'q'を入力してください。")
#     try:
#         while True:
#             user_input = input("コマンド入力 ('s' = sing, 'q' = quit): ").strip().lower()
#             if user_input == 's':
#                 generate_and_send_song()
#             elif user_input == 'q':
#                 print("プログラム終了。")
#                 break
#             else:
#                 print("認識できない入力です。's'か'q'を入力してください。")
#     except KeyboardInterrupt:
#         print("\nプログラム中断。")
#     finally:
#         # 終了処理：受信スレッドに終了を伝える
#         stop_serial_thread = True
#         serial_thread.join()
#         ser.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true',
                        help='対話なしで自動運転する')
    args = parser.parse_args()

    # 受信スレッド開始
    serial_thread = threading.Thread(target=serial_reader, daemon=True)
    serial_thread.start()

    # 最初の 1 曲
    generate_and_send_song()

    if args.headless or not sys.stdin.isatty():
        # ひたすら常駐（Ctrl-C や systemd の stop で落とす）
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        # 従来の手動入力モード
        print("プログラム開始。's' を入力すると曲を送信、'q' で終了。")
        try:
            while True:
                cmd = input("コマンド ('s'=sing, 'q'=quit): ").strip().lower()
                if cmd == 's':
                    generate_and_send_song()
                elif cmd == 'q':
                    break
        except KeyboardInterrupt:
            pass
    # 終了処理
    stop_serial_thread = True
    serial_thread.join()
    ser.close()
