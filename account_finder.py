"""
account_finder.py

X標準の検索機能(通常のブラウザ操作)を利用し、
調査セット(surveys.py)で指定された名前のパターンに一致するscreen_nameを持つ
アカウントを、画面上に表示された範囲内で収集するスクリプト。
(名前のパターンと検索の文字列は、引数で受け取る。省略した場合は、従来の
 "AmandaGarc" + 数字 が使われる。)

方針:
- 検索結果ページを開き、通常のスクロール操作相当で表示内容を取得するのみ。
- APIへの直接アクセスや非公開エンドポイントの呼び出しは行わない。
- アクセス制限・エラーらしき表示を検知した場合は、そのクエリの処理を打ち切り、
  ログに記録して次のクエリに進む(全体は止めない)。

検索方法について:
- "AmandaGarc" 単体で検索すると、X側の検索結果表示件数の制限により、
  スクロールしても一定件数までしか候補が見つからない場合がある。
- そこで "AmandaGarc1" 〜 "AmandaGarc9" のように、末尾の数字の先頭1桁を
  変えた9通りのクエリで個別に検索することで、より多くの候補を
  取りこぼしなく収集できるようにしている。
"""

import re
import time
import logging
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

STORAGE_STATE_PATH = Path("auth_state.json")

# 対象ユーザーネームの判定パターン(既定値)。
# 調査セットを指定して実行する場合は、そちらのパターンが引数で渡されるため使われない。
# "AmandaGarc" の直後に数字が1つ以上続き、それ以外の文字を含まないもの
USERNAME_PATTERN = re.compile(r"^AmandaGarc\d+$")

BLOCKED_MARKERS = ["Something went wrong", "Rate limit", "アクセスがブロック"]

logging.basicConfig(
    filename="scraper.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def is_target_username(screen_name: str, pattern: re.Pattern | None = None) -> bool:
    """
    対象ユーザーネーム形式かどうかを判定する。
    pattern を省略した場合は、既定の USERNAME_PATTERN(AmandaGarc+数字)を使う。
    """
    return bool((pattern or USERNAME_PATTERN).match(screen_name))


def build_search_queries() -> list[str]:
    """
    "AmandaGarc1" 〜 "AmandaGarc9" の9通りの検索クエリを生成する。
    """
    return [f"AmandaGarc{d}" for d in range(1, 10)]


def _search_one_query(
    page: Page, query: str, max_scrolls: int, pattern: re.Pattern | None = None
) -> set[str]:
    """1つの検索クエリについて、画面をスクロールしながら候補を収集する"""
    found: set[str] = set()
    search_url = f"https://x.com/search?q={quote(query)}&src=typed_query&f=user"

    try:
        page.goto(search_url, timeout=30000)
        page.wait_for_timeout(3000)
    except PWTimeout:
        logging.error(f"[検索:{query}] ページの読み込みでタイムアウトしました。このクエリをスキップします。")
        return found, 0

    # ログインページにリダイレクトされていないか確認する。
    # セッション(auth_state.json)が期限切れになっていると、検索結果が
    # 空になったり、意図しないページに飛ばされたりすることがあるため。
    current_url = page.url
    if "/login" in current_url or "/i/flow/login" in current_url:
        logging.error(
            f"[検索:{query}] ログインページにリダイレクトされました(セッション切れの可能性)。"
            f"auth_state.json を再取得してください(login.py を再実行、"
            f"または通常ブラウザで再ログイン後にCookieを再エクスポート)。"
        )
        return found, 0

    page_text = page.content()
    if any(marker in page_text for marker in BLOCKED_MARKERS):
        logging.error(f"[検索:{query}] アクセス制限が疑われる表示を検知したため打ち切ります。")
        return found, 0

    # 診断用: このページ全体でどれだけの/始まりのリンクが見つかったか記録する。
    # 0件が続く場合、検索結果自体が描画されていない(UI仕様変更や
    # セッションの問題)可能性が高いと判断できる。
    initial_links = page.eval_on_selector_all(
        "a[href^='/']",
        "els => els.map(e => e.getAttribute('href'))",
    )
    logging.info(
        f"[検索:{query}] 初回読み込み時点でページ内に見つかったリンク数: {len(initial_links)}"
    )
    if len(initial_links) == 0:
        logging.warning(
            f"[検索:{query}] ページ内にリンクが1つも見つかりませんでした。"
            f"検索結果が描画されていない可能性があります(URL: {current_url})"
        )

    prev_count = -1
    stable_rounds = 0

    for i in range(max_scrolls):
        links = page.eval_on_selector_all(
            "a[href^='/']",
            "els => els.map(e => e.getAttribute('href'))",
        )
        for href in links:
            if not href:
                continue
            candidate = href.strip("/").split("/")[0]
            if candidate and is_target_username(candidate, pattern):
                found.add(candidate)

        page_text = page.content()
        if any(marker in page_text for marker in BLOCKED_MARKERS):
            logging.error(f"[検索:{query}] スクロール中にアクセス制限が疑われる表示を検知したため打ち切ります。")
            break

        # これ以上スクロールしても新規候補が増えなければ打ち切る
        if len(found) == prev_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        prev_count = len(found)
        if stable_rounds >= 3:
            break

        # 通常のブラウジング相当のスクロール + 待機(サーバー負荷をかけない)
        page.mouse.wheel(0, 2000)
        time.sleep(2)

    logging.info(f"[検索:{query}] {len(found)} 件の候補を検出しました。")
    return found, len(initial_links)


def find_candidate_usernames(
    max_scrolls: int = 5,
    target_new_count: int | None = None,
    exclude: set[str] | None = None,
    queries: list[str] | None = None,
    pattern: re.Pattern | None = None,
) -> list[str]:
    """
    指定されたクエリ群で順に検索し、見つかった候補をまとめて返す(重複は除去される)。

    queries を省略した場合は、デフォルトの "AmandaGarc1"〜"AmandaGarc9" の
    9通りのクエリを使う(調査セットを使う場合は、main.pyが queries を渡す)。
    既知のアカウント名をqueriesとして渡すこともでき、
    その場合は「既知のアカウント名で検索すると、関連する他のアカウントが
    検索結果に現れる」という発見方法として使える。

    pattern: 候補として採用する名前の正規表現。省略時は既定の USERNAME_PATTERN。

    target_new_count を指定すると、exclude(既に調査済み・選定済み)を
    除いた「新規」候補がその件数に達した時点で、残りのクエリは
    実行せずに打ち切る(必要以上に検索を続けない)。
    """
    if not STORAGE_STATE_PATH.exists():
        raise FileNotFoundError(
            "auth_state.json が見つかりません。先に login.py を実行してください。"
        )

    exclude = exclude or set()
    all_found: set[str] = set()
    queries = queries if queries is not None else build_search_queries()

    # 「0件かつページ内のリンク数が少ない」状態が連続した場合、
    # 検索結果自体が描画されていない(検索機能がソフト的に制限されている)
    # とみなし、残りのクエリを実行しても無駄になる可能性が高いため打ち切る。
    LOW_LINK_THRESHOLD = 40
    CONSECUTIVE_LIMIT = 2
    consecutive_empty_low_link = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(STORAGE_STATE_PATH))
        page = context.new_page()
        page.set_default_timeout(30000)

        for query in queries:
            found, initial_link_count = _search_one_query(page, query, max_scrolls, pattern)
            all_found |= found

            if len(found) == 0 and initial_link_count < LOW_LINK_THRESHOLD:
                consecutive_empty_low_link += 1
            else:
                consecutive_empty_low_link = 0

            if consecutive_empty_low_link >= CONSECUTIVE_LIMIT:
                logging.warning(
                    f"[検索] {consecutive_empty_low_link}回連続で「0件かつリンク数僅少"
                    f"({initial_link_count}件)」の結果が続いたため、検索機能が"
                    f"一時的に制限されている可能性が高いとみなし、残りのクエリを"
                    f"省略します(クエリ「{query}」まで実行)。時間を置いて再実行することを推奨します。"
                )
                break

            if target_new_count is not None:
                new_count = len(all_found - exclude)
                if new_count >= target_new_count:
                    logging.info(
                        f"新規候補が目標件数({target_new_count}件)に達したため、"
                        f"残りのクエリは省略します(クエリ「{query}」まで実行)。"
                    )
                    break

            # クエリ切り替えの間の待機時間。
            # 短すぎると検索機能がソフト的に制限されやすくなるため、間隔を空ける。
            time.sleep(8)

        browser.close()

    logging.info(f"検索完了: 合計 {len(all_found)} 件の対象アカウント候補を検出しました。")
    return sorted(all_found)


if __name__ == "__main__":
    accounts = find_candidate_usernames()
    print("検出された対象アカウント:")
    for a in accounts:
        print(" -", a)