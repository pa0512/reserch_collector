"""
main.py

使い方:
    python main.py                       # 既定の調査セット(従来どおり accounts.csv に記録)
    python main.py --survey 名前         # surveys.py に定義した調査セットで収集
    python main.py --prefix 英字         # 英字部分だけを指定して収集(surveys.py への記載は不要)
    python main.py --prefix 英字 --seed アカウント名   # 最初に調べるアカウントも指定
    python main.py --list-surveys        # 定義済みの調査セットを一覧表示
    python main.py --max-accounts 200    # 1回の実行で調べる新規アカウント数の上限(既定: 10)

    調査セット(surveys.py)ごとに、名前の判定パターン・検索の文字列・記録先のCSVが
    分かれる。別の調査セットを指定すると、別のCSV(accounts_名前.csv)に記録される。

処理の流れ:
1. 調査セットを決める(設定に誤りがあれば、ここで止まる)
2. auth_state.json の存在確認 (なければ login.py の実行を促す)
3. 既存のCSVがあれば読み込み、調査済みのscreen_nameを把握する
4. 調査セットの seeds → 既存データのフォロー/フォロワー欄 → 既知アカウント名での検索 →
   調査セットの検索の文字列、の順に、アカウント候補を探す
   (すでに調査済みのものは対象から除外する)
5. 新規アカウントのプロフィール情報・フォロー一覧・フォロワー一覧を取得
6. 「既存の調査済みデータ」+「新規に調査したデータ」をまとめて
   調査セットのCSVに保存 (UTF-8 BOM付き = utf-8-sig)
   フォロー一覧・フォロワー一覧は、それぞれ1つのセルにカンマ区切りで格納する。

件数を増やす際の設計方針:
- 新規アカウントを1件処理し終えるたびに、CSV全体(既存分+ここまでの新規分)を
  書き直して保存する(逐次保存)。途中でエラーや制限に遭遇して処理が止まっても、
  それまでの分は accounts.csv に残るようにするため。
- アカウントとアカウントの間に待機時間を入れる。
- 実行するたびに、既に調べたアカウントは再調査しない(重複調査の回避)。
"""

import argparse
import csv
import logging
import random
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

import process_lock
import survey_config
from browser_launch import launch_chromium
from account_finder import find_candidate_usernames, is_target_username, STORAGE_STATE_PATH
from profile_scraper import scrape_profile
from list_scraper import collect_following, collect_followers

logging.basicConfig(
    filename="scraper.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# 記録先のCSV。既定値で、main() の最初に、調査セットのCSVに置き換わる。
ACCOUNTS_CSV = Path("accounts.csv")

# 1回の実行で新規に調査するアカウント数の上限。
# 一気に増やさず、例えば 5 -> 10 -> 20 のように段階的に上げ、
# そのたびに scraper.log で制限やエラーが頻発していないか確認することを推奨。
MAX_ACCOUNTS = 10

# アカウント候補を探すための検索結果スクロール回数(クエリごと)。
ACCOUNT_SEARCH_SCROLLS = 8

# 「既知のアカウント名で検索」する際に、1回の実行で種として使うアカウント数。
# 多すぎると検索回数が増えて時間がかかるため、少数に絞ってランダムに選ぶ。
KNOWN_ACCOUNT_SEARCH_SEEDS = 3

# アカウントを1件処理し終えるごとに、次に進む前に空ける待機時間(秒)。
PAUSE_BETWEEN_ACCOUNTS_MIN = 5
PAUSE_BETWEEN_ACCOUNTS_MAX = 12

CSV_FIELDNAMES = [
    "screen_name",
    "account_created_at",
    "profile_link",
    "following_count",
    "followers_count",
    "following_screen_names",
    "followers_screen_names",
]


def load_existing_accounts() -> list[dict]:
    """
    既存の accounts.csv があれば読み込み、行のリストとして返す。
    ファイルが存在しない場合は空リストを返す。
    """
    if not ACCOUNTS_CSV.exists():
        return []

    with open(ACCOUNTS_CSV, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def build_account_row(
    data: dict, following_names: list[str], follower_names: list[str]
) -> dict:
    """
    プロフィール情報 + フォロー一覧 + フォロワー一覧を、
    accounts.csv 1行分(1アカウント1行)に変換する。
    フォロー/フォロワーのscreen_nameはカンマ区切りで1セルにまとめる。
    """
    return {
        "screen_name": data["screen_name"],
        "account_created_at": data["account_created_at"],
        "profile_link": data["profile_link"],
        "following_count": data["following_count"],
        "followers_count": data["followers_count"],
        "following_screen_names": ",".join(following_names),
        "followers_screen_names": ",".join(follower_names),
    }


def extract_candidates_from_existing_relations(
    existing_rows: list[dict], pattern: re.Pattern | None = None
) -> set[str]:
    """
    既に収集済みの following_screen_names / followers_screen_names の中から、
    調査セットの名前のパターン(省略時は既定の AmandaGarc+数字)に
    一致するscreen_nameを抜き出す。

    Botネットワークは互いにフォローし合っていることが多く、
    既存データの中に、まだプロフィールを直接調査していない対象アカウントが
    含まれていることが多い。検索(X標準の検索機能)より追加のアクセスが
    不要なため、優先的にこちらから新規候補を探す。
    """
    candidates: set[str] = set()
    for row in existing_rows:
        for col in ("following_screen_names", "followers_screen_names"):
            raw = row.get(col, "") or ""
            for name in raw.split(","):
                name = name.strip()
                if name and is_target_username(name, pattern):
                    candidates.add(name)
    return candidates


def save_accounts_csv(rows: list[dict]) -> None:
    """
    accounts.csv をUTF-8 BOM付きで(既存分+新規分をまとめて)保存し直す。
    既存ファイルを都度上書きすることで、BOMの重複や文字化けを避ける。
    """
    # 既存のCSVに、このプログラムが知らない列(手で足した列など)があっても、
    # DictWriterがエラーで止まらないよう、そのまま末尾に残す。
    fieldnames = list(CSV_FIELDNAMES)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with open(ACCOUNTS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    global ACCOUNTS_CSV, MAX_ACCOUNTS

    parser = argparse.ArgumentParser(description="Xのアカウントを収集し、調査セットごとのCSVに記録します")
    survey_config.add_survey_arguments(parser)
    parser.add_argument(
        "--max-accounts", type=int, default=None, metavar="N",
        help=f"1回の実行で調べる新規アカウント数の上限。省略すると {MAX_ACCOUNTS}",
    )
    args = parser.parse_args()
    if args.max_accounts is not None:
        if args.max_accounts < 1:
            parser.error("--max-accounts には1以上の整数を指定してください")
        MAX_ACCOUNTS = args.max_accounts

    # 調査セットを最初に決める。設定に誤りがある場合は、ここで内容を表示して止まる
    # (ブラウザを起動してから設定ミスに気づく、という無駄を避けるため)。
    survey = survey_config.resolve_survey(args)
    ACCOUNTS_CSV = survey.csv_path
    print(survey_config.describe(survey))
    print(f"1回の実行で調べる新規アカウント数の上限: {MAX_ACCOUNTS}")

    # 同じCSVに、別のプログラムが同時に書き込むとデータが失われるため、二重起動を防ぐ
    process_lock.acquire(ACCOUNTS_CSV)

    if not STORAGE_STATE_PATH.exists():
        print("auth_state.json が見つかりません。")
        print("先に `python login.py` を実行し、手動ログインを完了してください。")
        return

    existing_rows = load_existing_accounts()
    already_processed = {row["screen_name"] for row in existing_rows}
    if already_processed:
        print(f"調査済みアカウント: {len(already_processed)} 件({ACCOUNTS_CSV}から読み込み)")

    # 0. 調査セットの seeds(最初に調べるアカウント)を、最優先の候補にする
    initial_seeds = [name for name in survey.seeds if name not in already_processed]
    if initial_seeds:
        print(f"調査セットの seeds から {len(initial_seeds)} 件を最優先の候補にします。")

    # 1. 次に、既に収集済みのフォロー/フォロワー欄から新規候補を探す
    #    (追加のアクセスが不要で、検索より効率的)
    relation_candidates = extract_candidates_from_existing_relations(existing_rows, survey.pattern)
    relation_candidates -= already_processed | set(initial_seeds)
    if relation_candidates:
        print(f"既存のフォロー/フォロワー欄から新規候補 {len(relation_candidates)} 件を検出しました。")

    new_candidates = (initial_seeds + sorted(relation_candidates))[:MAX_ACCOUNTS]

    # 2. まだ枠が余っていれば、「既に調査済みのアカウント名」で検索し、
    #    関連して現れる他のアカウントを探す。
    #    (Xで特定のアカウント名を検索すると、類似・関連するアカウントが
    #     結果に現れることがある。これは以前手動で行っていた発見方法に相当する)
    if len(new_candidates) < MAX_ACCOUNTS and already_processed:
        remaining = MAX_ACCOUNTS - len(new_candidates)
        already_selected = already_processed | set(new_candidates)

        seed_accounts = random.sample(
            sorted(already_processed), min(KNOWN_ACCOUNT_SEARCH_SEEDS, len(already_processed))
        )
        print(
            f"既知のアカウント名({', '.join(seed_accounts)})で検索し、"
            f"関連アカウントを探しています(残り必要件数: {remaining})..."
        )
        try:
            searched = find_candidate_usernames(
                max_scrolls=ACCOUNT_SEARCH_SCROLLS,
                target_new_count=remaining,
                exclude=already_selected,
                queries=seed_accounts,
                pattern=survey.pattern,
            )
        except FileNotFoundError as e:
            print(str(e))
            return

        for c in searched:
            if len(new_candidates) >= MAX_ACCOUNTS:
                break
            if c not in already_selected:
                new_candidates.append(c)
                already_selected.add(c)

    # 3. それでもまだ枠が余っていれば、調査セットの検索の文字列(search_prefix+1〜9 など)で補う。
    #    検索の文字列が設定されていない調査セットでは、行わない(ブラウザの無駄な起動を避ける)。
    if len(new_candidates) < MAX_ACCOUNTS and survey.search_queries:
        remaining = MAX_ACCOUNTS - len(new_candidates)
        already_selected = already_processed | set(new_candidates)
        print(f"対象アカウント候補をX検索(調査セットの検索の文字列)でも探しています(残り必要件数: {remaining})...")
        try:
            searched = find_candidate_usernames(
                max_scrolls=ACCOUNT_SEARCH_SCROLLS,
                target_new_count=remaining,
                exclude=already_selected,
                queries=list(survey.search_queries),
                pattern=survey.pattern,
            )
        except FileNotFoundError as e:
            print(str(e))
            return

        for c in searched:
            if len(new_candidates) >= MAX_ACCOUNTS:
                break
            if c not in already_selected:
                new_candidates.append(c)
                already_selected.add(c)

    if not new_candidates:
        if not existing_rows and not survey.seeds and not survey.search_queries:
            print(
                f"調査セット '{survey.name}' には、探索の起点がありません。\n"
                f"surveys.py の '{survey.name}' に、search_prefix(検索の起点)か、"
                f"seeds(最初に調べるアカウント)を追加してください。"
            )
        else:
            print("新規の対象アカウントが見つかりませんでした。scraper.log を確認してください。")
        return

    new_candidates = new_candidates[:MAX_ACCOUNTS]
    print(f"新たに {len(new_candidates)} 件のアカウントを対象に情報取得を行います。")

    all_rows = list(existing_rows)  # 既存分をベースに、新規分を追記していく

    with sync_playwright() as p:
        browser = launch_chromium(p)
        context = browser.new_context(storage_state=str(STORAGE_STATE_PATH))
        page = context.new_page()
        # すべての操作に明示的なデフォルトタイムアウトを設定する。
        # (タイムアウト未指定の呼び出しがあっても、無期限に固まらないようにするため)
        page.set_default_timeout(30000)

        for i, screen_name in enumerate(new_candidates, start=1):
            print(f"[{i}/{len(new_candidates)}] 取得中(プロフィール): {screen_name}")
            try:
                data = scrape_profile(page, screen_name)
                if not data:
                    print(" -> スキップ/失敗(詳細は scraper.log を参照)")
                    continue

                print(f"取得中(フォロー一覧): {screen_name}")
                following_names = collect_following(
                    page, screen_name, expected_count=data["following_count"]
                )
                print(f" -> {len(following_names)} 件")

                print(f"取得中(フォロワー一覧): {screen_name}")
                follower_names = collect_followers(
                    page, screen_name, expected_count=data["followers_count"]
                )
                print(f" -> {len(follower_names)} 件")

                row = build_account_row(data, following_names, follower_names)
                all_rows.append(row)

                # 1件処理し終えるたびに、既存分+ここまでの新規分をまとめて保存する
                save_accounts_csv(all_rows)

            except Exception as e:
                logging.error(f"[{screen_name}] 想定外のエラーが発生したためスキップ: {e}")
                print(" -> エラーのためスキップ(詳細は scraper.log を参照)")

            if i < len(new_candidates):
                pause = random.uniform(
                    PAUSE_BETWEEN_ACCOUNTS_MIN, PAUSE_BETWEEN_ACCOUNTS_MAX
                )
                time.sleep(pause)

        browser.close()

    new_count = len(all_rows) - len(existing_rows)
    print(f"新規に {new_count} 件を追加し、合計 {len(all_rows)} 件を {ACCOUNTS_CSV} に保存しました。")


if __name__ == "__main__":
    main()