"""
surveys.py

「調査セット」の設定ファイル。

調査セットとは、1つの調査(=1種類の命名パターンを持つアカウント群)について、
次のものをひとまとめにした単位です。

    - どんな名前のアカウントを対象にするか(名前の判定パターン)
    - 探索の起点(検索に使う文字列、最初に調べるアカウント)
    - 収集結果を記録するCSV

調査セットを分けておくと、対象を変えても、記録(CSV)が別々になり、
他の調査のデータと混ざりません。

■ もっと簡単な方法: --prefix
    英字部分を指定するだけなら、この設定ファイルへの記載は不要です。
        python main.py --prefix StephanieL
    (パターン・検索の文字列・記録先は、英字から自動で決まります。詳しくは README.md を参照)
    --prefix では足りない場合(複雑なパターン、複数の検索文字列など)に、下の調査セットを定義します。

■ 使い方
    # 収集(調査セットを指定。省略すると、DEFAULT_SURVEYが使われます)
    python main.py --survey johnsmith
    python run_with_watchdog.py --survey johnsmith      # フリーズ時の自動再起動つき


    # 定義済みの調査セットの確認
    python survey_config.py

■ 新しい調査セットの追加方法
    下の SURVEYS に、コメントアウトされている例をコピーして、書き換えてください。
    書き方に誤りがあると、実行時に、どこを直すべきかを表示して止まります。

■ 各項目の説明
    description   : メモ(省略可)
    pattern       : 対象のアカウント名を表す正規表現(必須)。^ と $ を付けて、
                    名前全体に一致するようにしてください。
                    例: r"^JohnSmith\\d+$"  ->  JohnSmith12345 には一致、JohnSmith には一致しない
    search_prefix : 検索の起点となる文字列(省略可)。この後ろに 1〜9 を付けた9通り
                    (JohnSmith1 〜 JohnSmith9)で、Xの検索を行って、アカウントを探します
    search_queries: 検索する文字列を、直接リストで指定する場合(省略可)。
                    指定すると、search_prefix より優先されます
    seeds         : 最初に調べるアカウント名のリスト(省略可)。patternに一致している必要が
                    あります。検索で見つけにくい場合は、ここに実在するアカウントを
                    1〜2件書くと、そのフォロー・フォロワーから、芋づる式に探せます
    examples      : patternに一致するはずの名前の例(省略可)。patternの書き間違いを
                    検出するための確認用です
    non_examples  : patternに一致しないはずの名前の例(省略可)。同上
    csv           : 記録先のCSVファイル名(省略可)。省略すると accounts_調査セット名.csv

    ※ search_prefix・search_queries・seeds のいずれも指定しない場合、最初の収集で、
      探索の起点がなく、アカウントを1件も見つけられません
      (既に収集済みのCSVがある場合は、そのフォロー・フォロワーから探せます)。
"""

# 引数なしで実行したときに使う調査セット
# (従来どおり: accounts.csv に記録します)
DEFAULT_SURVEY = "amanda"

SURVEYS = {
    "amanda": {
        "description": "AmandaGarc+数字 のアカウント群(従来の調査)",
        "pattern": r"^AmandaGarc\d+$",
        "search_prefix": "AmandaGarc",
        "examples": ["AmandaGarc38852", "AmandaGarc1"],
        "non_examples": ["AmandaGarc", "AmandaGarcABC"],
    },

    # ── 新しい調査セットの例(先頭の # を外して、書き換えて使います) ──
    # "johnsmith": {
    #     "description": "JohnSmith+数字 のアカウント群",
    #     "pattern": r"^JohnSmith\d+$",
    #     "search_prefix": "JohnSmith",
    #     "seeds": ["JohnSmith12345"],            # 最初に調べるアカウント(省略可)
    #     "examples": ["JohnSmith12345"],
    #     "non_examples": ["JohnSmith"],
    # },
}
