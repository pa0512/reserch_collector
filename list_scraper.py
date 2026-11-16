"""
list_scraper.py

対象アカウントの「フォロー一覧」「フォロワー一覧」ページを開き、
画面上に表示されたユーザーのscreen_name(@は含まない)を収集するスクリプト。

設計方針(profile_scraper.pyと同様):
- 通常のスクロール操作相当でページを読み進めるのみ。
- APIへの直接アクセスや非公開エンドポイントの呼び出しは行わない。
- アクセス制限・エラーらしき表示を検知した場合は、その時点で処理を打ち切り、
  ログに記録して次のアカウントに進む(全体を止めない)。
- 非公開(鍵)アカウントの一覧は取得しない。

収集件数のズレ検知について:
- プロフィールに表示されているフォロー数/フォロワー数(expected_count)を
  渡すと、実際に収集できた件数との差を計算し、10件を超えるズレがあれば
  scraper.log に警告として記録する。
"""

import re
import time
import logging
from playwright.sync_api import Page, TimeoutError as PWTimeout

logging.basicConfig(
    filename="scraper.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# Xのユーザー名として有効な文字列(英数字とアンダースコア、最大15文字)
VALID_SCREEN_NAME = re.compile(r"^\w{1,15}$")

# ユーザー一覧に混ざりうる、アカウント名ではないパス(誤検出防止用)
NON_USER_PATHS = {
    "home", "explore", "notifications", "messages", "i", "search",
    "settings", "compose", "login", "logout", "search-home",
}

BLOCKED_MARKERS = ["Something went wrong", "Rate limit", "アクセスがブロック"]

# ズレを警告としてログに記録する閾値(件数)
COUNT_MISMATCH_THRESHOLD = 10

_COUNT_PATTERN = re.compile(r"^([\d.]+)\s*([KkMm]?)$")


def _is_blocked(page_text: str) -> bool:
    return any(marker in page_text for marker in BLOCKED_MARKERS)


def _parse_count(text: str | None) -> int | None:
    """
    "1,234" "12.3K" "1.2M" のような表示用の文字列を整数に変換する。
    変換できない場合は None を返す。
    """
    if not text:
        return None

    cleaned = text.strip().replace(",", "")
    match = _COUNT_PATTERN.match(cleaned)
    if not match:
        return None

    number = float(match.group(1))
    suffix = match.group(2).upper()
    if suffix == "K":
        number *= 1_000
    elif suffix == "M":
        number *= 1_000_000

    return int(round(number))


def _collect_user_list(
    page: Page,
    target_screen_name: str,
    list_type: str,
    max_scrolls: int = 80,
    scroll_pause: float = 2.5,
    stable_rounds_to_stop: int = 5,
    expected_count: str | None = None,
) -> list[str]:
    """
    list_type: "following" または "followers"
    対象一覧ページを開き、表示されたユーザーのscreen_nameを収集して返す。
    expected_count(プロフィール上の表示件数)を渡すと、収集件数との
    ズレをログに記録する。
    """
    assert list_type in ("following", "followers")

    url = f"https://x.com/{target_screen_name}/{list_type}"
    try:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(2000)
    except PWTimeout:
        logging.error(f"[{target_screen_name}] {list_type}一覧ページの読み込みタイムアウト")
        return []

    page_text = page.content()

    # 非公開アカウント(鍵アカウント)の場合、一覧は表示されない
    if "These posts are protected" in page_text or "このポストは非公開" in page_text:
        logging.info(f"[{target_screen_name}] 非公開アカウントのため{list_type}一覧をスキップします")
        return []

    if _is_blocked(page_text):
        logging.error(
            f"[{target_screen_name}] {list_type}一覧取得中にアクセス制限らしき表示を検知したため中止します"
        )
        return []

    collected: set[str] = set()
    prev_count = -1
    stable_rounds = 0
    stopped_early_due_to_block = False
    reached_bottom_rounds = 0

    # プロフィール表示件数がわかっている場合、そこに近づくまでは
    # 通常より長めにスクロールを粘る(取りこぼしをできるだけ減らすため)。
    expected_int_for_patience = _parse_count(expected_count)
    # 通常の打ち切り基準に加えて、粘るために許容する追加スクロール回数の上限
    max_extra_patience_scrolls = 20

    for i in range(max_scrolls):
        # ユーザー1件分を表すセルを取得する。
        # サイドバーの「おすすめアカウント」を除外するため、
        # メインの一覧が表示される領域(primaryColumn)内だけに絞り込む。
        cells = page.locator("[data-testid='primaryColumn'] [data-testid='UserCell']")
        count = cells.count()

        for idx in range(count):
            cell = cells.nth(idx)
            try:
                link = cell.locator("a[href^='/']").first
                href = link.get_attribute("href", timeout=2000)
            except Exception:
                continue

            if not href:
                continue

            candidate = href.strip("/").split("/")[0].split("?")[0]
            if (
                candidate
                and candidate.lower() not in NON_USER_PATHS
                and candidate != target_screen_name
                and VALID_SCREEN_NAME.match(candidate)
            ):
                collected.add(candidate)

        # 制限らしき表示が出ていないか、スクロールのたびに確認する
        page_text = page.content()
        if _is_blocked(page_text):
            logging.error(
                f"[{target_screen_name}] {list_type}一覧取得中にアクセス制限らしき表示を検知したため打ち切ります"
                f"({len(collected)}件取得済み)"
            )
            stopped_early_due_to_block = True
            break

        # これ以上スクロールしても新規ユーザーが増えない場合は末尾に到達したとみなす
        if len(collected) == prev_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        prev_count = len(collected)

        if stable_rounds >= stable_rounds_to_stop:
            # プロフィール表示件数にまだ届いていない場合は、
            # 上限(max_extra_patience_scrolls)まで、もう少し粘ってスクロールを続ける。
            # ただし、粘っても件数が全く動いていない(prev_countが同じ)場合は
            # 技術的な限界(仮想スクロールの都合等)である可能性が高いため、
            # 上限に達していなくてもそこで打ち切る。
            still_short = (
                expected_int_for_patience is not None
                and len(collected) < expected_int_for_patience - COUNT_MISMATCH_THRESHOLD
            )
            if still_short and max_extra_patience_scrolls > 0:
                max_extra_patience_scrolls -= 1
                stable_rounds = 0  # 打ち切り判定をリセットして続行
            else:
                break

        # ページの最下部に本当に到達しているかどうかを直接確認する。
        # 最下部に到達した後もスクロールを送り続けると、Xページ側の
        # 挙動(再読み込みの無限リトライ等)によりブラウザが無応答になる
        # ことが確認されているため、最下部到達を検知したら、それ以上
        # スクロールを試みずに直ちにループを抜ける。
        at_bottom = page.evaluate(
            "() => (window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 10)"
        )
        if at_bottom:
            reached_bottom_rounds += 1
        else:
            reached_bottom_rounds = 0

        if reached_bottom_rounds >= 2:
            logging.info(
                f"[{target_screen_name}] {list_type}一覧: ページ最下部への到達を検知したため、"
                f"これ以上のスクロールを行わずに終了します({len(collected)}件取得済み)"
            )
            break

        # スクロールは小刻みに行う。
        # 一度に大きくスクロールすると、Xの仮想スクロール(画面外の要素を
        # DOMから間引く仕組み)により、一部のユーザーが一度も描画されないまま
        # 通り過ぎてしまい、収集漏れの原因になる。
        #
        # mouse.wheel()はマウスカーソルの現在位置にホイールイベントを送るため、
        # ページ構造によっては一覧の外側(スクロールしない領域)にイベントが
        # 飛んでしまい、実質的に何も進まなくなることがある。
        # window.scrollBy()をJS側で直接実行する方式なら、カーソル位置に
        # 依存せず確実にページ全体をスクロールできる。
        for _ in range(2):
            page.evaluate("window.scrollBy(0, 1200)")
            page.wait_for_timeout(400)
        time.sleep(scroll_pause)

    collected_count = len(collected)
    logging.info(
        f"[{target_screen_name}] {list_type}一覧から{collected_count}件のscreen_nameを収集しました"
    )

    # プロフィール表示件数との差をチェックし、10件を超えるズレがあれば警告として記録する
    expected_int = _parse_count(expected_count)
    if expected_int is not None:
        diff = abs(collected_count - expected_int)
        if diff > COUNT_MISMATCH_THRESHOLD:
            reason = "アクセス制限による早期打ち切り" if stopped_early_due_to_block else "原因不明(仕様上の限界の可能性あり)"
            logging.warning(
                f"[{target_screen_name}] {list_type}件数のズレを検知: "
                f"プロフィール表示={expected_int}件, 収集={collected_count}件, 差={diff}件 ({reason})"
            )

    return sorted(collected)


def collect_following(
    page: Page, target_screen_name: str, expected_count: str | None = None
) -> list[str]:
    """対象アカウントがフォローしているユーザーのscreen_name一覧を取得する"""
    return _collect_user_list(
        page, target_screen_name, "following", expected_count=expected_count
    )


def collect_followers(
    page: Page, target_screen_name: str, expected_count: str | None = None
) -> list[str]:
    """対象アカウントをフォローしているユーザーのscreen_name一覧を取得する"""
    return _collect_user_list(
        page, target_screen_name, "followers", expected_count=expected_count
    )