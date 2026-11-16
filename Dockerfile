# Dockerfile
#
# 収集システム(ブラウザを使ったアカウント情報の収集)を動かす「箱」の設計図。
# 箱の中には「環境」(Python・パッケージ・ブラウザ・仮想ディスプレイ)だけを入れる。
# 収集結果(CSV)・ログ・ログイン状態(auth_state.json)は、箱の外(お手元のフォルダ)に置く。
#
# 注意: このDockerfileは、Dockerがない環境で作成したため、実際のビルドは未検証。

# ── 1. ベースイメージ ──────────────────────────────────────────
# Debian 12 (bookworm) を明示する。Playwrightが公式にサポートしているOSで、
# 「python:3.12-slim」だけの指定だと、新しいDebianになり、ブラウザの依存ライブラリの
# 導入に失敗する可能性があるため。Pythonは3.10以上が必須(3.12で確認)。
FROM python:3.12-slim-bookworm

# ── 2. 環境変数 ────────────────────────────────────────────────
#   PYTHONUTF8              : 日本語のログが文字化けしないように、UTF-8にする
#   PYTHONUNBUFFERED        : ログを、すぐ画面(docker logs)に出す
#   PYTHONDONTWRITEBYTECODE : __pycache__ を、共有フォルダに作らない
#   TZ                      : ログの時刻を日本時間にする
#   PLAYWRIGHT_BROWSERS_PATH: ブラウザの置き場所
ENV PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Tokyo \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# ── 3. 仮想ディスプレイ(Xvfb)と時刻データ ───────────────────────
# 画面のない箱の中で、画面ありのブラウザを動かすために、仮想ディスプレイを入れる。
# xauth は、xvfb-run に必要(--no-install-recommends だと入らないため、明示する)。
RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb xauth tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── 4. パッケージとブラウザ ────────────────────────────────────
# 先に依存関係だけを入れる(コードを書き換えても、この重い手順を、やり直さずに済む)。
# playwright install --with-deps は、Chromium本体と、動作に必要なシステムのライブラリを入れる。
COPY requirements-docker.txt /tmp/requirements-docker.txt
RUN pip install -r /tmp/requirements-docker.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

# ── 5. 起動用のスクリプト ──────────────────────────────────────
# Windowsで編集されたファイルの改行コード(CRLF)が混ざっていると、Linuxで
# 「bad interpreter」エラーになるため、改行コードをそろえ、実行権限も付ける。
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

# ── 6. プログラム本体 ──────────────────────────────────────────
# .dockerignore により、秘密情報(auth_state.json)・収集データ・ログは、箱に入らない。
# (通常は、docker compose が、お手元のフォルダをここに重ねるため、この内容は使われない。
#  箱だけを他の場所に持ち出して動かす場合のために、入れてある。)
COPY . /app

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["help"]
