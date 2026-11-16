"""
run_with_watchdog.py

main.py を子プロセスとして実行し、scraper.log の更新が一定時間止まったら
(=ブラウザやページが無応答になってフリーズしたとみなし)、
そのプロセスを強制終了して自動的に再実行する監視スクリプトです。

main.py は「処理済みのアカウントはスキップし、CSVへ逐次保存する」設計に
なっているため、途中で強制終了・再実行しても、それまでの成果は失われません。
再実行時は続きから(未処理のアカウントから)再開されます。

使い方:
    python run_with_watchdog.py                      # 既定の調査セット
    python run_with_watchdog.py --survey 名前        # 指定した調査セットで収集

    引数は、そのまま main.py に渡されます。
    Ctrl+C で監視ごと停止できます。
"""

import subprocess
import sys
import time
from pathlib import Path

MAIN_SCRIPT = "main.py"

# main.py が、調査セットの設定の誤りで終了するときの終了コード(survey_config.pyと同じ値)
CONFIG_ERROR_EXIT_CODE = 2
LOG_PATH = Path("scraper.log")

# scraper.log の最終更新からこの秒数以上、更新が無ければ
# フリーズとみなしてプロセスを再起動する。
STALE_THRESHOLD_SECONDS = 180

# ログの更新有無をチェックする間隔(秒)
CHECK_INTERVAL_SECONDS = 15

# 連続で再起動した場合、ここまで到達したら一旦停止する(無限ループ防止)
MAX_CONSECUTIVE_RESTARTS = 10


def log_mtime() -> float:
    """scraper.log の最終更新時刻(UNIX時間)を返す。存在しない場合は現在時刻を返す。"""
    if not LOG_PATH.exists():
        return time.time()
    return LOG_PATH.stat().st_mtime


def run_once() -> int:
    """
    main.py を1回実行し、フリーズを検知したら強制終了する。
    戻り値: プロセスの終了コード(強制終了させた場合は特別な値-1を返す)
    """
    print(f"=== {MAIN_SCRIPT} を起動します ===")
    proc = subprocess.Popen([sys.executable, MAIN_SCRIPT, *sys.argv[1:]])

    start_time = time.time()
    baseline_mtime = log_mtime()

    while True:
        time.sleep(CHECK_INTERVAL_SECONDS)

        # 正常終了(または異常終了)していないか確認
        ret = proc.poll()
        if ret is not None:
            print(f"=== {MAIN_SCRIPT} が終了しました(終了コード: {ret}) ===")
            return ret

        current_mtime = log_mtime()
        if current_mtime > baseline_mtime:
            # ログが更新されていれば正常に動作しているとみなす
            baseline_mtime = current_mtime
            continue

        stalled_seconds = time.time() - max(baseline_mtime, start_time)
        if stalled_seconds >= STALE_THRESHOLD_SECONDS:
            print(
                f"=== scraper.log が {int(stalled_seconds)} 秒間更新されていません。"
                f"フリーズとみなし、プロセスを強制終了します ==="
            )
            proc.kill()
            proc.wait()
            return -1


def main():
    consecutive_restarts = 0

    while True:
        ret = run_once()

        if ret == 0:
            print("=== 正常に完了しました ===")
            break

        if ret == CONFIG_ERROR_EXIT_CODE:
            # 調査セットの設定の誤り。何度再実行しても同じ結果になるため、再起動しない
            print("=== 設定に誤りがあるため、再実行せずに終了します。上の内容を直してください ===")
            break

        if ret == -1:
            consecutive_restarts += 1
            print(f"=== フリーズを検知したため再実行します({consecutive_restarts}回目) ===")
        else:
            # main.py自体がエラーで終了した場合も再実行を試みる
            consecutive_restarts += 1
            print(
                f"=== {MAIN_SCRIPT} が異常終了しました(終了コード: {ret})。"
                f"再実行します({consecutive_restarts}回目) ==="
            )

        if consecutive_restarts >= MAX_CONSECUTIVE_RESTARTS:
            print(
                f"=== 再起動が{MAX_CONSECUTIVE_RESTARTS}回連続したため、"
                f"監視を停止します。scraper.log を確認してください ==="
            )
            break

        # 再起動前に少し待機する(Xのアクセス制限等が原因の場合、間隔を空ける意味もある)
        time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n=== ユーザーにより中断されました ===")