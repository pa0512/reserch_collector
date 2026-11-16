"""
browser_launch.py

ブラウザ(Chromium)の起動方法を1か所にまとめたモジュール。
収集のスクリプト(main.py など)は、ここを通してブラウザを起動する。

■ 画面のない環境(研究室のサーバーなど)で動かす場合
  既定では、従来どおり「画面あり」でブラウザを起動する。画面(ディスプレイ)が
  ないLinuxサーバーでは、次のどちらかが必要になる。

  A. 仮想ディスプレイ(Xvfb)の中で、画面ありのまま動かす
       xvfb-run -a python main.py ...
       (run_collect.sh は、画面がなく xvfb-run がある場合に、自動でこちらを使う)
  B. ヘッドレスモードで動かす
       環境変数 X_SCRAPER_HEADLESS=1 を付けて実行する

  AとBのどちらでも、X側から見た動作は同じ「ブラウザの操作」だが、
  Xが両者を同じように扱うかどうかは、確認できていない。
  従来(画面あり)に最も近いのはAなので、まずAを試すことを推奨する。
"""

import os
import sys

HEADLESS_ENV = "X_SCRAPER_HEADLESS"

# 設定の誤り(実行環境の不備)で終了するときの終了コード。
# run_with_watchdog.py は、この終了コードの場合、再実行しても無駄なので再起動しない。
CONFIG_ERROR_EXIT_CODE = 2


def is_headless() -> bool:
    """環境変数 X_SCRAPER_HEADLESS が 1/true/yes/on なら、ヘッドレスで起動する"""
    return os.environ.get(HEADLESS_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _has_display() -> bool:
    """画面(ディスプレイ)を使える環境か。Linux以外(Windows/Mac)は、常に使える"""
    if not sys.platform.startswith("linux"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def launch_chromium(playwright):
    """
    Chromiumを起動して返す。

    画面のないLinuxで、画面ありのまま起動しようとした場合は、Playwrightの分かりにくい
    エラーで止まる前に、原因と対処を表示して終了する(終了コード2)。
    """
    headless = is_headless()

    if not headless and not _has_display():
        print(
            "[ブラウザ起動エラー] 画面(ディスプレイ)がない環境で、画面ありのブラウザを起動しようとしました。\n"
            "  次のどちらかで実行してください。\n"
            "    A. 仮想ディスプレイ内で実行(推奨):  xvfb-run -a python main.py ...\n"
            "       (または ./run_collect.sh を使う。xvfb-run がなければ、sudo apt install xvfb など)\n"
            f"    B. ヘッドレスで実行:  {HEADLESS_ENV}=1 python main.py ...\n"
            "  詳しくは SERVER_SETUP.md を参照してください。"
        )
        sys.exit(CONFIG_ERROR_EXIT_CODE)

    mode = "ヘッドレス" if headless else "画面あり"
    print(f"ブラウザ: Chromium({mode})")
    return playwright.chromium.launch(headless=headless)
