#!/usr/bin/env bash
# setup_server.sh
#
# サーバー上で、収集システムの実行環境(Python仮想環境・パッケージ・ブラウザ)を作る。
# このスクリプトは、sudo(root権限)を必要としない。システムのライブラリが不足している
# 場合の対処は、最後に表示される。
#
# 使い方:   ./setup_server.sh
#           PYTHON=python3.12 ./setup_server.sh      # 使うPythonを指定する場合
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo "== 1. Python のバージョン確認 =="
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[NG] $PYTHON が見つかりません。PYTHON=python3.12 のように、使うPythonを指定してください。"
  exit 1
fi
"$PYTHON" - <<'PYEOF'
import sys
v = sys.version_info
print(f"   {sys.executable}  (Python {v.major}.{v.minor}.{v.micro})")
if (v.major, v.minor) < (3, 10):
    print("[NG] Python 3.10 以上が必要です。新しいPythonを用意して、PYTHON=... で指定してください。")
    sys.exit(1)
PYEOF

echo "== 2. 仮想環境(.venv)の作成 =="
if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
  echo "   作成しました"
else
  echo "   既にあります(再利用します)"
fi
# shellcheck disable=SC1091
. .venv/bin/activate

echo "== 3. パッケージのインストール =="
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

echo "== 4. ブラウザ(Chromium)の取得 =="
python -m playwright install chromium

echo "== 5. 環境の確認 =="
set +e
PYTHONUTF8=1 python check_env.py
status=$?
set -e

cat <<'MSG'

------------------------------------------------------------
次の手順(詳細は SERVER_SETUP.md):
  1. [NG] が出た場合は、内容に従って対処する
     - Chromium を起動できない場合(システムのライブラリ不足)は、管理者(root)権限で:
         sudo .venv/bin/python -m playwright install-deps chromium
     - 画面(ディスプレイ)がない場合の [注意] は、xvfb のインストール(sudo apt install xvfb)
       または、ヘッドレス実行(run_collect.sh が自動で切り替え)で対応できる
  2. ログイン状態のファイル auth_state.json を、お手元のPCから転送する
       scp auth_state.json ユーザー@サーバー:このフォルダ/   その後  chmod 600 auth_state.json
  3. もう一度  .venv/bin/python check_env.py  で確認する
  4. 少数で試す:  ./run_collect.sh --max-accounts 3
------------------------------------------------------------
MSG
exit $status
