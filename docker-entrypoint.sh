#!/usr/bin/env bash
# docker-entrypoint.sh
#
# Dockerの箱の中で、最初に実行されるスクリプト。
# 短いコマンド名で、収集・図の作成・環境の確認を実行できるようにする。
#
#   collect  [引数...]  収集(フリーズ時の自動再起動つき)。引数は main.py に渡される
#   main     [引数...]  収集(自動再起動なし)
#   check    [引数...]  環境の確認(check_env.py)
#   surveys             調査セットの一覧と、設定の検証
#   backfill [引数...]  プロフィールリンクの取り直し
#   shell               箱の中で、シェル(bash)を開く
#   help                この説明を表示する
#   それ以外            そのコマンドを、そのまま実行する
#
# 画面(ディスプレイ)がない箱の中で、ブラウザを使うコマンドは、仮想ディスプレイ(Xvfb)の中で
# 実行する。ヘッドレスで実行したい場合は、環境変数 X_SCRAPER_HEADLESS=1 を付ける。
set -euo pipefail

APP_DIR="${APP_DIR:-/app}"
cd "$APP_DIR"
export PYTHONUTF8=1

usage() {
  cat <<'MSG'
使い方: docker compose run --rm app <コマンド> [引数...]

  collect  [--prefix 英字 | --survey 名前] [--max-accounts N]   収集(フリーズ時に自動再起動)
  main     [--prefix 英字 | --survey 名前] [--max-accounts N]   収集(自動再起動なし)
  check    [--check-network]                    環境の確認
  surveys                                       調査セットの一覧と検証
  backfill [--prefix 英字 | --survey 名前]      プロフィールリンクの取り直し
  shell                                         箱の中でシェルを開く

例:
  docker compose run --rm app check
  docker compose run --rm app collect --max-accounts 3
  docker compose run --rm app collect --prefix StephanieL --max-accounts 3
MSG
}

# ブラウザを使うコマンドを、画面がなければ、仮想ディスプレイの中で実行する
run_with_display() {
  if [ -z "${DISPLAY:-}" ] && [ "${X_SCRAPER_HEADLESS:-}" != "1" ]; then
    exec xvfb-run -a --server-args="-screen 0 1280x1024x24" python "$@"
  fi
  exec python "$@"
}

cmd="${1:-help}"
if [ $# -gt 0 ]; then shift; fi

case "$cmd" in
  collect)         run_with_display run_with_watchdog.py "$@" ;;
  main)            run_with_display main.py "$@" ;;
  backfill)        run_with_display backfill_profile_links.py "$@" ;;
  check)           exec python check_env.py "$@" ;;
  surveys)         exec python survey_config.py "$@" ;;
  shell|bash)      exec bash ;;
  help|-h|--help)  usage ;;
  *)               exec "$cmd" "$@" ;;
esac
