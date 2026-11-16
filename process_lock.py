"""
process_lock.py

同じ調査セットのCSVに対して、収集プログラムを二重に起動しないための排他ロック。

■ なぜ必要か
  収集プログラムは、1アカウント処理するたびに、CSV全体を「自分のメモリ上のデータ」で
  書き直す。同じCSVに対して2つのプログラムが同時に動くと、後から書いた方が先の方の
  新しいデータを消してしまう。複数人で使うサーバーで、うっかり二重に起動した場合の
  データ消失を防ぐ。

■ 仕組み
  CSVと同じ場所に「<CSV名>.lock」というファイルを作り、OSのファイルロック(flock)を
  かけたまま、プログラムの終了まで保持する。
  - 別のプログラムが既にロックを持っていれば、起動を断る(終了コード3)
  - ロックに対応していない場所(Dockerのフォルダ共有など)では、警告を出して、そのまま続ける
  - プログラムが異常終了しても、OSがロックを自動で解放する。古いロックファイルが
    残っていても、次回の起動を妨げない(.lockファイルは、削除しても問題ない)

■ 対応環境
  Linux / macOS のみ有効。Windowsでは何もしない(従来どおりの動作)。
"""

import os
import sys
from pathlib import Path

# 既に別のプログラムが動いているときの終了コード。
# run_with_watchdog.py は、この終了コードの場合、再起動しない。
ALREADY_RUNNING_EXIT_CODE = 3

_held_files = []   # ロックを持っているファイルを、プログラムの終了まで保持しておく


def acquire(csv_path) -> bool:
    """
    csv_path に対応するロックを取得する。
    既に別のプログラムが持っている場合は、メッセージを表示して、終了コード3で終了する。
    ロックを取得できた(またはWindowsなどで対象外だった)場合は、True を返す。
    """
    if os.name != "posix":
        return True

    import fcntl

    lock_path = Path(str(csv_path) + ".lock")
    try:
        f = open(lock_path, "a+")
    except OSError as e:
        # ロックファイルを作れない(書き込み権限がない等)。止めずに、警告だけ出して続ける
        print(f"[警告] ロックファイル {lock_path} を作れないため、二重起動の防止は無効です: {e}")
        return False

    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # 別のプログラムが、既にロックを持っている(これだけが「使用中」を意味する)
        f.seek(0)
        holder = f.read().strip() or "(不明)"
        f.close()
        print(
            f"[二重起動の防止] {csv_path} は、別のプログラムが使用中です(PID: {holder})。\n"
            f"  同じCSVに同時に書き込むとデータが失われるため、このプログラムは終了します。\n"
            f"  実行中のプログラムを確認してください(例: ps aux | grep main.py)。"
        )
        sys.exit(ALREADY_RUNNING_EXIT_CODE)
    except OSError as e:
        # 「使用中」ではなく、この場所がflockに対応していない(Dockerのフォルダ共有、一部のネットワーク
        # ドライブなど)。誰も使っていないのに、起動できなくなるのを避けるため、止めずに続ける。
        f.close()
        print(f"[警告] この場所では、ファイルロックを使えないため、二重起動の防止は無効です: {e}")
        return False

    # ロックを取得できた。持ち主のPIDを書き込んでおく(別のプログラムが、エラー表示に使う)
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    _held_files.append(f)   # 閉じずに保持する(閉じるとロックが解放される)
    return True
