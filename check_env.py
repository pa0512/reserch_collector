"""
check_env.py

収集システムを動かす環境(研究室のサーバーなど)の、事前確認スクリプト。
不足しているものを、一度に洗い出す。Xのページには一切アクセスしない。

使い方:
    python check_env.py                  # 基本の確認
    python check_env.py --check-network  # 加えて、x.com への接続可否(名前解決とTCP接続のみ)を確認
    python check_env.py --headed         # 加えて、画面ありでのChromiumの起動を確認

結果の見方:
    [OK]   問題なし
    [注意] 動作はするが、確認・対応が望ましい
    [NG]   このままでは動かない(対処が必要)。1つでもあれば、終了コード1で終了する
"""

import argparse
import importlib
import json
import os
import shutil
import socket
import stat
import sys
import tempfile
import time
from pathlib import Path

MIN_PYTHON = (3, 10)
PACKAGES = ["playwright"]
MIN_FREE_GB = 1.0

_results = {"OK": 0, "注意": 0, "NG": 0}


def report(level: str, title: str, detail: str = "") -> None:
    _results[level] += 1
    print(f"[{level}] {title}")
    for line in detail.splitlines():
        print(f"       {line}")


def check_python() -> None:
    v = sys.version_info
    text = f"Python {v.major}.{v.minor}.{v.micro}  ({sys.executable})"
    if (v.major, v.minor) >= MIN_PYTHON:
        report("OK", text)
    else:
        report("NG", text, f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 以上が必要です(コードの型ヒントの書き方のため)。\n"
                           f"新しいPythonで、仮想環境を作り直してください(SERVER_SETUP.md 参照)。")


def check_packages() -> None:
    for name in PACKAGES:
        try:
            module = importlib.import_module(name)
            version = getattr(module, "__version__", None)
            if version is None and name == "playwright":
                try:
                    from importlib.metadata import version as meta_version
                    version = meta_version("playwright")
                except Exception:
                    version = "不明"
            report("OK", f"パッケージ {name} {version}")
        except ImportError:
            report("NG", f"パッケージ {name} がインストールされていません",
                   "pip install -r requirements.txt を実行してください。")


def check_encoding() -> None:
    enc = sys.stdout.encoding or "不明"
    utf8_mode = bool(getattr(sys.flags, "utf8_mode", 0))
    if enc.lower().replace("-", "") in ("utf8",) or utf8_mode:
        report("OK", f"文字コード: 標準出力={enc} (UTF-8)")
    else:
        report("注意", f"文字コード: 標準出力={enc}",
               "日本語のログが文字化けする、または出力時にエラーになる可能性があります。\n"
               "環境変数 PYTHONUTF8=1 を付けて実行してください(run_collect.sh は自動で付けます)。")


def check_browser() -> None:
    """Chromiumを、ヘッドレスで起動できるか。ローカルのページを開くだけで、外部には接続しない"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report("NG", "ブラウザの起動確認をスキップ(playwright が未インストール)")
        return
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            version = browser.version
            page = browser.new_page()
            page.goto("data:text/html,<title>ok</title>")
            title = page.title()
            browser.close()
        if title == "ok":
            report("OK", f"Chromium をヘッドレスで起動できます (バージョン {version})")
        else:
            report("NG", "Chromium は起動しましたが、ページを正しく開けませんでした")
    except Exception as e:
        first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        report("NG", "Chromium を起動できません",
               f"{first}\n"
               "対処: python -m playwright install chromium でブラウザを取得してください。\n"
               "それでも失敗する場合は、システムのライブラリが不足しています。\n"
               "  sudo python -m playwright install-deps chromium   (root権限が必要。SERVER_SETUP.md 参照)")


def check_display() -> None:
    """画面あり(従来どおり)で動かすために、画面(または仮想ディスプレイ)が使えるか"""
    headless_env = os.environ.get("X_SCRAPER_HEADLESS", "").strip().lower() in ("1", "true", "yes", "on")
    if not sys.platform.startswith("linux"):
        report("OK", f"画面: {sys.platform} では、画面ありで起動できます")
        return
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    xvfb = shutil.which("xvfb-run")
    if has_display:
        report("OK", f"画面: ディスプレイが使えます (DISPLAY={os.environ.get('DISPLAY', '')})")
    elif headless_env:
        report("OK", "画面: ディスプレイはありませんが、X_SCRAPER_HEADLESS=1 でヘッドレス実行する設定です")
    elif xvfb:
        report("OK", f"画面: ディスプレイはありませんが、xvfb-run が使えます ({xvfb})",
               "./run_collect.sh(Dockerでは docker-entrypoint.sh)が、自動で仮想ディスプレイの中で実行します。")
    else:
        report("注意", "画面: ディスプレイも xvfb-run もありません",
               "このままでは、収集を画面ありで起動できません。次のどちらかが必要です。\n"
               "  A. xvfb をインストールして、仮想ディスプレイで実行する(例: sudo apt install xvfb)\n"
               "  B. X_SCRAPER_HEADLESS=1 を付けて、ヘッドレスで実行する\n"
               "(./run_collect.sh は、xvfb-run がない場合、自動でBにします)")


def _in_container() -> bool:
    """Docker などの、コンテナの中で動いているか"""
    return os.path.exists("/.dockerenv")


def check_shm() -> None:
    """
    共有メモリ(/dev/shm)の大きさ。ブラウザ(Chromium)は、これを多く使う。
    Dockerの既定(64MB)だと小さく、「ページがクラッシュした」というエラーで落ちることがある。
    """
    shm = Path("/dev/shm")
    if not sys.platform.startswith("linux") or not shm.exists():
        return
    mb = shutil.disk_usage(shm).total / 1024 ** 2
    if mb >= 512:
        report("OK", f"共有メモリ(/dev/shm): {mb:.0f} MB")
    else:
        report("注意", f"共有メモリ(/dev/shm)が小さい: {mb:.0f} MB",
               "ブラウザが、収集中に「ページがクラッシュした」というエラーで落ちる可能性があります。\n"
               "Docker の場合は、compose.yaml の shm_size を大きくしてください(例: \"1gb\")。")


def check_browser_headed() -> None:
    """
    画面ありで、Chromiumを起動できるか(--headed を付けたときだけ実行)。
    収集は、画面あり(画面がなければ、仮想ディスプレイの中)で動かすため、ヘッドレスの確認とは別に必要。
    ローカルのページを開くだけで、外部には接続しない。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report("NG", "画面ありのブラウザの確認をスキップ(playwright が未インストール)")
        return
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto("data:text/html,<title>ok</title>")
            title = page.title()
            browser.close()
        display = os.environ.get("DISPLAY", "(なし)")
        if title == "ok":
            report("OK", f"Chromium を画面ありで起動できます (DISPLAY={display})")
        else:
            report("NG", "画面ありでChromiumは起動しましたが、ページを正しく開けませんでした")
    except Exception as e:
        first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        report("NG", "画面ありでChromiumを起動できません",
               f"{first}\n"
               "画面(ディスプレイ)がない場合は、仮想ディスプレイの中で実行してください:\n"
               "  xvfb-run -a python check_env.py --headed")


def check_workdir() -> None:
    cwd = Path.cwd()
    try:
        with tempfile.NamedTemporaryFile(dir=cwd, prefix=".write_test_", delete=True) as f:
            f.write(b"x")
        report("OK", f"作業フォルダに書き込めます: {cwd}")
    except OSError as e:
        report("NG", f"作業フォルダに書き込めません: {cwd}", str(e))
    free_gb = shutil.disk_usage(cwd).free / 1024 ** 3
    if free_gb >= MIN_FREE_GB:
        report("OK", f"空き容量: {free_gb:.1f} GB")
    else:
        report("注意", f"空き容量が少ない: {free_gb:.2f} GB", "ログとCSVの保存に、余裕を持たせてください。")

    # 実行場所に依存するため、必要なファイルが、いまのフォルダにあるかを確認する
    needed = ["main.py", "surveys.py", "survey_config.py", "account_finder.py", "list_scraper.py", "profile_scraper.py"]
    missing = [n for n in needed if not (cwd / n).exists()]
    if missing:
        report("NG", "必要なファイルが、いまのフォルダにありません", f"不足: {', '.join(missing)}\n"
               "システム一式を置いたフォルダに移動してから実行してください。")


def check_auth_state() -> None:
    """ログイン状態のファイル。中身(Cookieの値)は表示しない。期限の確認だけ行う"""
    path = Path("auth_state.json")
    if not path.exists():
        report("注意", "auth_state.json がありません(ログイン状態が未設定)",
               "収集を実行するには、ログイン済みの auth_state.json をこのフォルダに置く必要があります。\n"
               "サーバーでは手動ログインできないため、お手元のPCで作成して、scp等で転送します(SERVER_SETUP.md 参照)。")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
    except (OSError, ValueError) as e:
        report("NG", "auth_state.json を読み込めません", str(e))
        return

    x_cookies = [c for c in cookies if "x.com" in c.get("domain", "") or "twitter.com" in c.get("domain", "")]
    auth = [c for c in x_cookies if c.get("name") == "auth_token"]
    if not x_cookies:
        report("NG", "auth_state.json に、x.com のCookieが入っていません")
    elif not auth:
        report("注意", f"auth_state.json: x.com のCookie {len(x_cookies)}件ありますが、ログインを示す auth_token がありません",
               "ログイン済みのブラウザから、Cookieを取り直す必要があるかもしれません。")
    else:
        expires = auth[0].get("expires", -1)
        if expires and expires > 0:
            days = (expires - time.time()) / 86400
            when = time.strftime("%Y-%m-%d", time.localtime(expires))
            if days < 0:
                report("NG", f"auth_state.json のログインの期限が切れています ({when})", "Cookieを取り直してください。")
            elif days < 14:
                report("注意", f"auth_state.json のログインの期限が近いです ({when}、残り約{days:.0f}日)")
            else:
                report("OK", f"auth_state.json: ログイン情報あり (期限 {when}、残り約{days:.0f}日)")
        else:
            report("OK", "auth_state.json: ログイン情報あり (期限の情報なし)")

    # 権限: ログイン済みのCookieは、パスワードと同等の機密。他のユーザーに読めないようにする
    if os.name == "posix":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            if _in_container() and mode == 0o777:
                # Docker Desktop(Windows/Mac)の共有フォルダは、箱の中からは、常に 0o777 に見える。
                # 箱の中で chmod しても変わらず、Windows側の権限が、実際には適用されている。
                report("注意", f"auth_state.json の権限は、箱の中からは確認できません ({oct(mode)})",
                       "Docker Desktop(Windows/Mac)の共有フォルダでは、常にこの表示になります(chmod では変わりません)。\n"
                       "その場合は、Windows側で、このフォルダが他のユーザーに共有されていないことを確認してください。\n"
                       "Linuxのサーバーで Docker を使っている場合は、ホスト側で chmod 600 auth_state.json を実行してください。")
            else:
                report("注意", f"auth_state.json の権限が緩いです ({oct(mode)})",
                       "他のユーザーに読まれると、ログインを乗っ取られます。次を実行してください:\n"
                       "  chmod 600 auth_state.json")
        else:
            report("OK", f"auth_state.json の権限: {oct(mode)} (本人のみ)")


def check_surveys() -> None:
    try:
        import survey_config
        import surveys
    except ImportError as e:
        report("NG", "調査セットの設定を読み込めません", str(e))
        return
    for name in surveys.SURVEYS:
        try:
            s = survey_config.load_survey(name)
            report("OK", f"調査セット '{name}': 設定OK (記録先 {s.csv_path})")
        except survey_config.SurveyError as e:
            report("NG", f"調査セット '{name}' の設定に誤りがあります", str(e))


def check_network() -> None:
    """x.com に、名前解決とTCP接続ができるか。ページの取得(HTTP通信)は行わない"""
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if os.environ.get(var):
            report("注意", f"プロキシの環境変数があります: {var}",
                   "Playwright(ブラウザ)は、この環境変数を自動では使いません。\n"
                   "このサーバーが、プロキシ経由でしか外部に出られない場合は、設定の追加が必要です。")
            break
    host = "x.com"
    try:
        ip = socket.gethostbyname(host)
    except OSError as e:
        report("NG", f"{host} の名前解決に失敗しました", f"{e}\nサーバーから外部のインターネットに出られない可能性があります。")
        return
    try:
        with socket.create_connection((host, 443), timeout=8):
            pass
        report("OK", f"{host} ({ip}) の443番ポートに接続できます")
    except OSError as e:
        report("NG", f"{host} ({ip}) の443番ポートに接続できません", f"{e}\nファイアウォールで遮断されている可能性があります。")


def main() -> int:
    parser = argparse.ArgumentParser(description="収集システムの実行環境を確認します")
    parser.add_argument("--check-network", action="store_true",
                        help="x.com への接続可否(名前解決とTCP接続のみ)も確認する")
    parser.add_argument("--headed", action="store_true",
                        help="画面ありでのChromiumの起動も確認する(画面がなければ、xvfb-run の中で実行する)")
    args = parser.parse_args()

    print("=" * 60)
    print("環境の事前確認(Xのページには、アクセスしません)")
    print("=" * 60)
    check_python()
    check_packages()
    check_encoding()
    check_workdir()
    check_display()
    check_browser()
    if args.headed:
        check_browser_headed()
    check_shm()
    check_surveys()
    check_auth_state()
    if args.check_network:
        check_network()

    print("=" * 60)
    print(f"結果: OK {_results['OK']}件 / 注意 {_results['注意']}件 / NG {_results['NG']}件")
    if _results["NG"]:
        print("NG の項目を直してから、収集を実行してください。")
    elif _results["注意"]:
        print("動作はしますが、[注意] の項目を確認してください。")
    else:
        print("すべて問題ありません。")
    print("=" * 60)
    return 1 if _results["NG"] else 0


if __name__ == "__main__":
    sys.exit(main())
