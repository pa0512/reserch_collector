"""
survey_config.py

「調査セット」(surveys.py に定義)を読み込み、検証するモジュール。
収集(main.py など)から使う。
標準ライブラリだけを使うため、ブラウザ用ライブラリがない環境でも読み込める。

単独で実行すると、定義済みの調査セットの一覧と、設定の検証結果を表示する:
    python survey_config.py
"""

import csv
import dataclasses
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import surveys

# 設定の誤りで終了するときの終了コード。
# run_with_watchdog.py は、この終了コードの場合、再実行しても無駄なので再起動しない。
CONFIG_ERROR_EXIT_CODE = 2

# 調査セット名に使える文字(ファイル名・フォルダ名の一部になるため、安全な文字だけにする)
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# search_prefix の後ろに付けて検索する文字(従来の AmandaGarc1〜9 と同じ方式)
_QUERY_SUFFIXES = "123456789"

# --prefix で指定する英字部分の条件
_PREFIX_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
MIN_PREFIX_LENGTH = 3    # 短すぎると、無関係なアカウントが大量に該当してしまう
MAX_PREFIX_LENGTH = 14   # Xのアカウント名は15文字まで。末尾に、数字が最低1桁必要


class SurveyError(Exception):
    """調査セットの設定に誤りがある。メッセージには、直し方を含める。"""


@dataclass(frozen=True)
class Survey:
    name: str
    description: str
    pattern_text: str
    pattern: re.Pattern
    search_queries: tuple      # Xの検索に使う文字列(空の場合、検索による探索は行わない)
    seeds: tuple               # 最初に調べるアカウント名
    csv_path: Path             # 収集結果の記録先
    note: str = ""             # 実行時の表示用の補足(--prefix から自動で作った場合など)

    def matches(self, screen_name: str) -> bool:
        """screen_name が、この調査セットの対象かどうか"""
        return bool(self.pattern.match(screen_name))


def _spec_of(name: str) -> dict:
    if name not in surveys.SURVEYS:
        defined = ", ".join(surveys.SURVEYS) or "(なし)"
        raise SurveyError(
            f"調査セット '{name}' は、surveys.py に定義されていません。\n"
            f"  定義済み: {defined}\n"
            f"  新しく追加する場合は、surveys.py の SURVEYS に追加してください。"
        )
    return surveys.SURVEYS[name]


def _resolve_csv_path(name: str, spec: dict) -> Path:
    """記録先のCSVを決める。省略時は、調査セット名から決まる"""
    if name == surveys.DEFAULT_SURVEY:
        default_csv = "accounts.csv"                              # 従来どおり
    else:
        default_csv = f"accounts_{name}.csv"
    return Path(spec.get("csv", default_csv))


def load_survey(name: str) -> Survey:
    """調査セットを読み込む。設定に誤りがある場合は SurveyError を送出する"""
    if not _NAME_PATTERN.match(name):
        raise SurveyError(
            f"調査セット名 '{name}' に使えない文字が含まれています。"
            f"半角の英数字・アンダースコア・ハイフンだけにしてください"
            f"(ファイル名の一部になるため)。"
        )

    spec = _spec_of(name)

    # ── pattern ──
    pattern_text = spec.get("pattern")
    if not pattern_text:
        raise SurveyError(
            f"調査セット '{name}' に pattern(対象の名前を表す正規表現)がありません。\n"
            f'  例: "pattern": r"^JohnSmith\\d+$"'
        )
    try:
        pattern = re.compile(pattern_text)
    except re.error as e:
        raise SurveyError(
            f"調査セット '{name}' の pattern が、正規表現として正しくありません: {e}\n"
            f"  pattern = {pattern_text!r}"
        )

    # ── examples / non_examples(pattern の書き間違いの検出) ──
    for example in spec.get("examples", []):
        if not pattern.match(example):
            raise SurveyError(
                f"調査セット '{name}' の examples に書かれた '{example}' が、"
                f"pattern に一致しません。pattern か examples を直してください。\n"
                f"  pattern = {pattern_text!r}"
            )
    for example in spec.get("non_examples", []):
        if pattern.match(example):
            raise SurveyError(
                f"調査セット '{name}' の non_examples に書かれた '{example}' が、"
                f"pattern に一致してしまいます(一致しないはずの名前です)。"
                f"pattern を直してください。\n  pattern = {pattern_text!r}"
            )

    # ── seeds ──
    seeds = tuple(spec.get("seeds", []))
    for seed in seeds:
        if not pattern.match(seed):
            raise SurveyError(
                f"調査セット '{name}' の seeds に書かれた '{seed}' が、pattern に一致しません。"
                f"seeds は、pattern に一致する名前にしてください。\n  pattern = {pattern_text!r}"
            )

    # ── 検索の文字列 ──
    if spec.get("search_queries"):
        queries = tuple(spec["search_queries"])
    elif spec.get("search_prefix"):
        queries = tuple(f"{spec['search_prefix']}{d}" for d in _QUERY_SUFFIXES)
    else:
        queries = ()

    # ── 記録先 ──
    csv_path = _resolve_csv_path(name, spec)

    # 別の調査セットと同じCSVを指していると、データが混ざってしまう
    for other_name, other_spec in surveys.SURVEYS.items():
        if other_name == name:
            continue
        if _resolve_csv_path(other_name, other_spec) == csv_path:
            raise SurveyError(
                f"調査セット '{name}' と '{other_name}' が、同じCSV({csv_path})を使う設定になっています。"
                f"データが混ざらないよう、どちらかの csv を変えてください。"
            )

    return Survey(
        name=name,
        description=spec.get("description", ""),
        pattern_text=pattern_text,
        pattern=pattern,
        search_queries=queries,
        seeds=seeds,
        csv_path=csv_path,
    )


# ══════════════════════════════════════════════════════════════════
# コマンドライン用の補助
# ══════════════════════════════════════════════════════════════════

def add_survey_arguments(parser) -> None:
    """argparseのパーサーに、調査セットを選ぶための引数を追加する"""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--survey", default=None, metavar="名前",
        help=f"調査セット名(surveys.py に定義)。省略すると '{surveys.DEFAULT_SURVEY}'",
    )
    group.add_argument(
        "--prefix", default=None, metavar="英字",
        help="調べるアカウント名の英字部分(例: StephanieL)。surveys.py に書かずに、"
             "『英字+数字』の名前を調べる。記録先は accounts_英字(小文字).csv に自動で決まる",
    )
    parser.add_argument(
        "--seed", action="append", default=None, metavar="アカウント名",
        help="--prefix と一緒に使う。最初に調べるアカウント名(複数回指定できる)",
    )
    parser.add_argument(
        "--list-surveys", action="store_true",
        help="定義済みの調査セットを一覧表示して終了する",
    )


def _count_rows(csv_path: Path):
    """記録済みのアカウント数(データ行の数)。ファイルがなければ None"""
    if not csv_path.exists():
        return None
    try:
        with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
            return sum(1 for _ in csv.DictReader(f))
    except (OSError, csv.Error):
        return None


def print_survey_list() -> None:
    """定義済みの調査セットと、設定の検証結果を表示する"""
    print("定義済みの調査セット:")
    for name in surveys.SURVEYS:
        mark = "  (引数なしのとき使われる)" if name == surveys.DEFAULT_SURVEY else ""
        print(f"\n  ■ {name}{mark}")
        try:
            s = load_survey(name)
        except SurveyError as e:
            print(f"    [設定エラー] {e}")
            continue
        rows = _count_rows(s.csv_path)
        recorded = "まだ記録なし" if rows is None else f"{rows}件記録済み"
        print(f"    説明      : {s.description or '(なし)'}")
        print(f"    パターン  : {s.pattern_text}")
        print(f"    記録先CSV : {s.csv_path}  ({recorded})")
        print(f"    検索の起点: 検索 {len(s.search_queries)}件 / seeds {len(s.seeds)}件")

    # surveys.py に無い記録(--prefix で作られたもの)も、見つかれば表示する
    defined_csvs = {str(_resolve_csv_path(n, spec)) for n, spec in surveys.SURVEYS.items()}
    extra = sorted(p for p in Path(".").glob("accounts_*.csv") if str(p) not in defined_csvs)
    if extra:
        print("\n  ■ --prefix で作られた記録(英字部分の大文字・小文字は区別されません)")
        for p in extra:
            name = p.stem[len("accounts_"):]
            rows = _count_rows(p)
            print(f"    {p}  ({'?' if rows is None else rows}件記録済み)  ->  --prefix {name}")
    print()


def _validate_prefix(prefix: str) -> None:
    if not _PREFIX_PATTERN.match(prefix):
        raise SurveyError(
            f"--prefix '{prefix}' に使えない文字が含まれています。"
            f"半角の英字で始まり、英数字とアンダースコアだけにしてください(例: StephanieL)。"
        )
    if len(prefix) < MIN_PREFIX_LENGTH:
        raise SurveyError(
            f"--prefix '{prefix}' が短すぎます({MIN_PREFIX_LENGTH}文字以上にしてください)。"
            f"短いと、無関係なアカウントが大量に該当してしまいます。"
        )
    if len(prefix) > MAX_PREFIX_LENGTH:
        raise SurveyError(
            f"--prefix '{prefix}' が長すぎます({MAX_PREFIX_LENGTH}文字以下にしてください)。"
            f"Xのアカウント名は15文字までで、末尾に数字が最低1桁必要なためです。"
        )


def find_survey_by_prefix(prefix: str):
    """定義済みの調査セットのうち、search_prefix が同じ(大文字・小文字は区別しない)ものの名前"""
    for name, spec in surveys.SURVEYS.items():
        search_prefix = spec.get("search_prefix")
        if search_prefix and search_prefix.lower() == prefix.lower():
            return name
    return None


def build_prefix_survey(prefix: str, seeds=()) -> Survey:
    """
    英字部分(prefix)だけから、調査セットを作る。surveys.py への記載は不要。

    - パターン    : prefix の後ろに数字が続く名前(大文字・小文字は区別しない。Xのアカウント名は区別しないため)
    - 検索の文字列: prefix + 1〜9
    - 記録先      : accounts_<prefix(小文字)>.csv
    同じ英字の調査セットが surveys.py に定義済みなら、新しく作らず、そちらを使う
    (同じアカウント群のデータが、2つのCSVに分かれないようにするため)。
    """
    _validate_prefix(prefix)
    seeds = tuple(dict.fromkeys(seeds))      # 重複を除く(順序は保つ)

    existing = find_survey_by_prefix(prefix)
    if existing:
        base = load_survey(existing)
        for seed in seeds:
            if not base.matches(seed):
                raise SurveyError(f"--seed '{seed}' が、調査セット '{existing}' のパターンに一致しません。\n"
                                  f"  pattern = {base.pattern_text!r}")
        return dataclasses.replace(
            base,
            seeds=tuple(dict.fromkeys(base.seeds + seeds)),
            note=f"--prefix {prefix} に対応する、定義済みの調査セット '{existing}' を使います",
        )

    name = prefix.lower()
    if name in surveys.SURVEYS:
        raise SurveyError(
            f"--prefix '{prefix}' から作る名前 '{name}' が、surveys.py の別の調査セットと重なっています。\n"
            f"  その調査セットを使う場合は --survey {name}、別の英字を調べる場合は、別の --prefix を指定してください。"
        )

    pattern_text = rf"(?i)^{re.escape(prefix)}\d+$"
    pattern = re.compile(pattern_text)
    for seed in seeds:
        if not pattern.match(seed):
            raise SurveyError(f"--seed '{seed}' が、--prefix '{prefix}' + 数字 の形になっていません。")

    csv_path = Path(f"accounts_{name}.csv")
    for other_name, other_spec in surveys.SURVEYS.items():
        if _resolve_csv_path(other_name, other_spec) == csv_path:
            raise SurveyError(
                f"--prefix '{prefix}' の記録先({csv_path})が、"
                f"調査セット '{other_name}' と重なっています。別の --prefix を指定してください。"
            )

    return Survey(
        name=name,
        description=f"--prefix {prefix}(英字部分 {prefix} + 数字)",
        pattern_text=pattern_text,
        pattern=pattern,
        search_queries=tuple(f"{prefix}{d}" for d in _QUERY_SUFFIXES),
        seeds=seeds,
        csv_path=csv_path,
        note=f"--prefix {prefix} から、調査セットを自動で作りました(surveys.py への記載は不要です)",
    )


def resolve_survey(args) -> Survey:
    """
    コマンドライン引数から調査セットを決める。
    --list-surveys の場合は、一覧を表示して終了する。
    設定に誤りがある場合は、メッセージを表示して、終了コード2で終了する。
    """
    if getattr(args, "list_surveys", False):
        print_survey_list()
        sys.exit(0)

    prefix = getattr(args, "prefix", None)
    seeds = getattr(args, "seed", None) or []
    if seeds and not prefix:
        print("[調査セットの設定エラー] --seed は、--prefix と一緒に指定してください。"
              "(--survey の場合は、surveys.py の seeds に書きます)")
        sys.exit(CONFIG_ERROR_EXIT_CODE)

    name = args.survey or surveys.DEFAULT_SURVEY
    try:
        if prefix:
            return build_prefix_survey(prefix, seeds)
        return load_survey(name)
    except SurveyError as e:
        print(f"[調査セットの設定エラー] {e}")
        sys.exit(CONFIG_ERROR_EXIT_CODE)


def describe(survey: Survey) -> str:
    """実行の最初に表示する、調査セットの要約(どの設定で動いているかを明示するため)"""
    text = (
        f"調査セット: {survey.name}  /  パターン: {survey.pattern_text}\n"
        f"記録先CSV: {survey.csv_path}"
    )
    if survey.note:
        text += f"\n({survey.note})"
    return text


if __name__ == "__main__":
    print_survey_list()
