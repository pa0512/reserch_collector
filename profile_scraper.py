"""
profile_scraper.py

指定したscreen_nameのプロフィールページを開き、
画面上に公開表示されている情報のみを取得するスクリプト。

取得項目:
- screen_name
- アカウント作成日 (プロフィール上の "Joined ..." 表示。年月程度の粒度)
- 外部リンク (プロフィールに設定されている場合のみ)
- フォロー数
- フォロワー数

注意事項:
- Xの仕様変更によりページ構造(CSSセレクタ等)が変わると、
  取得に失敗する場合があります。その場合は項目を空欄にし、
  警告としてログに記録します(処理全体は継続)。
- 非公開(鍵)アカウントの情報は取得せず、スキップしてログに記録します。
- アカウントが存在しない場合もスキップしてログに記録します。

フォロー数/フォロワー数の取得方法について:
- リンク内の特定のspan要素だけを狙うと、アイコン用の空spanなど
  意図しない要素を拾ってしまい、値が空になったり誤った値になったりすることがある。
  そのため、リンク要素のテキスト全体を取得し、そこから数字部分だけを
  正規表現で抜き出す方式にしている(例: "1,234 Following" -> "1,234")。
- フォロワー数は "/followers"(通常のフォロワー数)を優先し、
  それが見つからない場合のみ "/verified_followers"(認証済みフォロワーのみの数、
  多くのアカウントで0になる)を使う。以前は逆の優先順位になっており、
  実際のフォロワー数があるのに0と記録されるケースがあった。
"""

import re
import logging
from playwright.sync_api import Page, TimeoutError as PWTimeout

logging.basicConfig(
    filename="scraper.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# 先頭の数字部分(カンマ区切り・小数・K/M単位の略記に対応)を抜き出す正規表現
# 例: "1,234" "12.3K" "1.2M" "530"
COUNT_PATTERN = re.compile(r"[\d,]+(?:\.\d+)?[KkMm]?")


def _extract_count(
    page: Page, screen_name: str, hrefs: list[str], retries: int = 2, retry_wait_ms: int = 1500
) -> str:
    """
    指定したhref候補を優先順位順に試し、最初に見つかったリンクの
    テキスト全体から数字部分を抜き出して返す。
    読み込みタイミングの問題で一時的に空振りすることがあるため、
    見つからなかった場合は少し待って再試行する。
    どうしても見つからない場合は空文字を返す。
    """
    for attempt in range(retries + 1):
        for href in hrefs:
            try:
                el = page.locator(f"a[href='{href}']").first
                if el.count() == 0:
                    continue
                text = el.inner_text(timeout=5000)
            except Exception:
                continue

            if not text:
                continue

            match = COUNT_PATTERN.search(text)
            if match:
                return match.group(0)
            # 数字が見つからなければ、テキストそのものを返す(調査用に残す)
            return text.strip()

        if attempt < retries:
            page.wait_for_timeout(retry_wait_ms)

    return ""


# 日本語表示の年月部分("2023年1月"など、日が付いていても年月だけを抜き出す)
_JP_YEAR_MONTH_PATTERN = re.compile(r"\d{4}年\d{1,2}月")

# 英語表示の月+年部分("January 2023"など)。
# 日にちが挟まる形式("January 15, 2023")にも対応し、月と年だけを抜き出す。
_EN_MONTH_YEAR_PATTERN = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+\d{1,2},?)?\s+(\d{4})"
)


def _clean_joined_date(raw_text: str) -> str:
    """
    UserJoinDate要素から取得した文字列を整形し、年月までの粒度に統一して返す。
    仮に「日」まで含む表記が混ざっていても、年月の部分だけを正規表現で
    抜き出すことで、必ず月までの粒度に揃える。

    例:
      "2023年1月からXを利用しています"    -> "2023年1月"
      "2023年1月15日からXを利用しています" -> "2023年1月" (日が含まれていても除去)
      "Joined January 2023"              -> "January 2023"
    """
    if not raw_text:
        return raw_text

    jp_match = _JP_YEAR_MONTH_PATTERN.search(raw_text)
    if jp_match:
        return jp_match.group(0)

    en_match = _EN_MONTH_YEAR_PATTERN.search(raw_text)
    if en_match:
        month, year = en_match.group(1), en_match.group(2)
        return f"{month} {year}"

    # どちらのパターンにも一致しない場合のフォールバック
    # (想定外の表示形式の場合、従来通りの簡易処理で最善を尽くす)
    if "から" in raw_text:
        return raw_text.split("から")[0].strip()
    if raw_text.startswith("Joined "):
        return raw_text[len("Joined "):].strip()

    return raw_text.strip()


def extract_profile_links(page: Page, screen_name: str) -> list[str]:
    """
    プロフィールに設定されている外部リンク(UserUrl)と、
    自由記述欄(bio、UserDescription)内に含まれるリンクの両方を収集し、
    重複を除いたリストとして返す。

    どちらも見つからない場合は空リストを返す(プロフィールにリンクが
    一切設定されていない、正常なケース)。
    """
    links: list[str] = []
    seen: set[str] = set()

    def _add(href: str | None):
        if href and href not in seen:
            seen.add(href)
            links.append(href)

    # 外部リンク(プロフィール上部の専用欄。UserUrlというdata-testidで表示される)
    try:
        url_container = page.locator("[data-testid='UserUrl']")
        if url_container.count() > 0:
            url_el = url_container.locator("a").first
            if url_el.count() > 0:
                _add(url_el.get_attribute("href", timeout=5000))
    except Exception as e:
        logging.warning(f"[{screen_name}] 外部リンク(UserUrl)の取得に失敗: {e}")

    # 自由記述欄(bio)内のリンク。UserDescriptionというdata-testidで囲まれた
    # 領域の中にある、http(s)から始まる<a>タグをすべて対象にする。
    try:
        bio_container = page.locator("[data-testid='UserDescription']")
        if bio_container.count() > 0:
            bio_links = bio_container.locator("a[href^='http']")
            bio_link_count = bio_links.count()
            for idx in range(bio_link_count):
                try:
                    href = bio_links.nth(idx).get_attribute("href", timeout=3000)
                    _add(href)
                except Exception:
                    continue
    except Exception as e:
        logging.warning(f"[{screen_name}] 自由記述欄のリンク取得に失敗: {e}")

    return links


def _scrape_profile_once(page: Page, screen_name: str) -> dict | None:
    """
    1アカウント分のプロフィール情報を、1回だけ取得を試みる。
    (全体の再試行制御は呼び出し元の scrape_profile が行う)
    """
    url = f"https://x.com/{screen_name}"
    try:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(2000)
    except PWTimeout:
        logging.error(f"[{screen_name}] プロフィールページの読み込みタイムアウト")
        return None

    # プロフィールヘッダーが描画されるまで少し待つ。
    # 以前は「フォローリンク(a[href='/screen_name/following'])」の描画を
    # 基準にしていたが、フォロー数が0のアカウントでは、Xがこのリンクを
    # 通常と異なる形(リンクなしのspan等)でレンダリングしている可能性があり、
    # 常にタイムアウトしてしまうケースが確認された。
    # そのため、フォロー数に関係なく必ず存在するはずのアカウント名表示部分
    # (data-testid="UserName")の描画を基準にする。
    try:
        page.wait_for_selector("[data-testid='UserName']", timeout=8000)
    except PWTimeout:
        logging.warning(
            f"[{screen_name}] プロフィールヘッダー(UserName)の描画待ちでタイムアウトしました"
        )

    page_text = page.content()

    # 非公開アカウント(鍵アカウント)の判定
    if "These posts are protected" in page_text or "このポストは非公開" in page_text:
        logging.info(f"[{screen_name}] 非公開アカウントのためスキップします")
        return None

    # アカウントが存在しない場合
    if "This account doesn" in page_text or "アカウントは存在しません" in page_text:
        logging.info(f"[{screen_name}] アカウントが存在しません")
        return None

    # 診断用: フォロー/フォロワーのリンクがそもそも<a>タグとして
    # 存在しているかどうかを記録する。
    # フォロワー数のリンクは、通常のフォロワー数("/followers")か
    # 認証済みフォロワー数("/verified_followers")のどちらかで表示される。
    has_following_link = page.locator(f"a[href='/{screen_name}/following']").count() > 0
    has_followers_link = (
        page.locator(f"a[href='/{screen_name}/followers']").count() > 0
        or page.locator(f"a[href='/{screen_name}/verified_followers']").count() > 0
    )
    if not has_following_link or not has_followers_link:
        logging.info(
            f"[{screen_name}] 診断: following用リンクの存在={has_following_link}, "
            f"followers用リンクの存在={has_followers_link}"
        )

    result = {
        "screen_name": screen_name,
        "account_created_at": "",
        "profile_link": "",
        "following_count": "",
        "followers_count": "",
        # フォロー用/フォロワー用のリンクが両方とも存在しない場合のフラグ。
        # 制限アカウント等、通常と異なるプロフィール構造である可能性の判定に使う。
        "_stats_links_missing": (not has_following_link) and (not has_followers_link),
    }

    # アカウント作成日
    # 表示言語によって "Joined ..." (英語) や "...からXを利用しています" (日本語)
    # のように文言が変わるため、テキスト内容ではなく、Xがこの項目専用に
    # 付与している data-testid="UserJoinDate" を直接指定して取得する。
    # 取得したテキストには「からXを利用しています」等の説明文が付いてくるため、
    # 年月(日本語の場合)/月年(英語の場合)の部分だけを残すよう整形する。
    try:
        joined_el = page.locator("[data-testid='UserJoinDate']").first
        if joined_el.count() > 0:
            raw_text = joined_el.inner_text(timeout=5000).strip()
            result["account_created_at"] = _clean_joined_date(raw_text)
        else:
            logging.warning(f"[{screen_name}] 作成日の要素(UserJoinDate)が見つかりませんでした")
    except Exception as e:
        logging.warning(f"[{screen_name}] 作成日の取得に失敗: {e}")

    # プロフィールリンク(外部リンク + 自由記述欄内のリンク)
    # 複数見つかった場合はカンマ区切りで1つのフィールドにまとめる
    links = extract_profile_links(page, screen_name)
    result["profile_link"] = ",".join(links)
    if not links:
        logging.info(f"[{screen_name}] プロフィールリンクは見つかりませんでした(未設定の可能性が高い)")

    # フォロー数
    try:
        result["following_count"] = _extract_count(
            page, screen_name, [f"/{screen_name}/following"]
        )
        if not result["following_count"]:
            logging.warning(f"[{screen_name}] フォロー数が取得できませんでした(空欄)")
    except Exception as e:
        logging.warning(f"[{screen_name}] フォロー数の取得に失敗: {e}")

    # フォロワー数
    # 通常のフォロワー数("/followers")を優先し、
    # 見つからない場合のみ認証済みフォロワー数("/verified_followers")を使う
    try:
        result["followers_count"] = _extract_count(
            page,
            screen_name,
            [f"/{screen_name}/followers", f"/{screen_name}/verified_followers"],
        )
        if not result["followers_count"]:
            logging.warning(f"[{screen_name}] フォロワー数が取得できませんでした(空欄)")
    except Exception as e:
        logging.warning(f"[{screen_name}] フォロワー数の取得に失敗: {e}")

    return result


def scrape_profile(page: Page, screen_name: str) -> dict | None:
    """
    1アカウント分のプロフィール情報を取得する。
    取得に失敗した項目は空文字とし、ログに警告を記録する。
    ページ自体が開けない等の致命的なエラーの場合はNoneを返す。

    作成日・フォロー数・フォロワー数が「すべて」空になった場合は、
    プロフィール上部の統計情報エリアがまだ描画されていないタイミングで
    取得してしまった可能性が高いため、ページを読み込み直して1回だけ再試行する。
    """
    result = _scrape_profile_once(page, screen_name)

    if result is None:
        return None

    key_fields_empty = (
        not result["account_created_at"]
        and not result["following_count"]
        and not result["followers_count"]
    )

    if key_fields_empty and result["_stats_links_missing"]:
        # フォロー用/フォロワー用のリンクが両方とも存在しない状態は、
        # 読み込みタイミングの問題ではなく、Xがこのアカウントを
        # 制限対象(一時的な機能制限等)として扱っており、通常の
        # プロフィール統計情報エリア自体が表示されていない可能性が高い。
        # 読み込み直しても改善する見込みが薄いため、再試行はせず、
        # その旨をログに記録するだけに留める。
        logging.info(
            f"[{screen_name}] フォロー/フォロワーの統計リンクが両方とも存在しないため、"
            f"作成日・フォロー数・フォロワー数を空欄のまま記録します"
            f"(Xによる制限アカウントの可能性。フォロー/フォロワー一覧の取得自体は続行します)"
        )
    elif key_fields_empty:
        logging.warning(
            f"[{screen_name}] 作成日・フォロー数・フォロワー数がすべて空だったため、"
            f"プロフィールページを読み込み直して再試行します"
        )
        page.wait_for_timeout(3000)
        retry_result = _scrape_profile_once(page, screen_name)
        if retry_result is not None:
            result = retry_result
            still_empty = (
                not result["account_created_at"]
                and not result["following_count"]
                and not result["followers_count"]
            )
            if still_empty:
                logging.error(
                    f"[{screen_name}] 再試行後も作成日・フォロー数・フォロワー数が"
                    f"すべて空でした(ページ構造の変化等、根本的な問題の可能性があります)"
                )

    # 内部判定用フラグはCSVには不要なので取り除く
    result.pop("_stats_links_missing", None)

    return result