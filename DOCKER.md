# Docker Desktop で動かす手順

このシステムを、**Docker Desktop**(WindowsやMacのパソコン上のDocker)で動かすための手引きです。
Dockerを使ったことがない前提で、用語から説明します。

> **この手順は、実際にDockerでビルドして確認したものではありません**(作成した環境にDockerがなかったため)。
> 箱の中で動く部分(起動スクリプト・ブラウザ)は、Dockerの外で再現して確認しましたが、
> `docker compose build` などは、初めて実行するのが、あなたのパソコンになります。
> エラーが出たら、表示された内容を、そのまま教えてください。

---

## 1. Dockerとは(用語)

| 用語 | 意味 |
|---|---|
| **Docker** | プログラムを、動かすのに必要な環境ごと「箱」に入れて、動かす仕組み |
| **Docker Desktop** | WindowsやMacで、Dockerを使うためのアプリ(画面つき) |
| **イメージ** | 箱の「ひな形」。Dockerfileという設計図から作る。一度作れば、何度でも使える |
| **コンテナ** | イメージから作られて、実際に動いている「箱」。終わったら消せる |
| **Dockerfile** | イメージの設計図(どんな環境を入れるかの手順書) |
| **docker compose** | イメージの作り方や起動の設定(`compose.yaml`)を、短いコマンドで使うための道具 |
| **ビルド(build)** | Dockerfileから、イメージを作ること。最初の1回は、数分〜十数分かかる |
| **ボリューム(フォルダ共有)** | お手元のフォルダを、箱の中に見せる仕組み。箱を消しても、データが残る |

### このシステムでの考え方

```
 お手元のフォルダ                          Docker の箱(コンテナ)
 ┌──────────────────────────┐   共有   ┌───────────────────────────┐
 │ main.py など(プログラム)   │ ───────→ │ /app として見える            │
 │ surveys.py(設定)          │         │                            │
 │ auth_state.json(ログイン)  │         │ 箱の中にあるもの:           │
 │ accounts.csv(収集結果)     │ ←─────── │  ・Python と各種パッケージ    │
 │ scraper.log               │  書き込み │  ・ブラウザ(Chromium)       │
 └──────────────────────────┘         │  ・仮想ディスプレイ(Xvfb)    │
                                       └───────────────────────────┘
```

- **箱の中には「環境」だけ**を入れます(Python・ブラウザなど)
- **データ・ログ・ログイン状態は、お手元のフォルダに残ります**。箱を消しても、消えません
- `surveys.py` などを、お手元で編集すると、**すぐ箱の中にも反映されます**(作り直し不要)

---

## 2. 準備(最初に1回)

### 2-1. Docker Desktop をインストールする

1. https://www.docker.com/products/docker-desktop/ からダウンロードして、インストールする
2. Windowsの場合、**WSL 2** が必要です。インストーラーの指示に従って、有効にする(再起動を求められることがあります)
3. 起動すると、画面の左下に、クジラのアイコンと **「Engine running」**(緑)が出ます。これが、使える状態です

> **注意**: 研究室・大学のパソコンでは、Docker Desktopのライセンス(大規模な組織では有料の場合がある)や、
> インストールの許可が必要な場合があります。先輩や管理者に確認してください。

### 2-2. 動作確認

PowerShell(Windows)またはターミナル(Mac)を開いて、次を実行します。

```powershell
docker --version
docker compose version
```

どちらもバージョンが表示されれば、OKです。
`docker : 用語 'docker' は...` や、`Cannot connect to the Docker daemon` と出る場合は、Docker Desktopが起動していません。アプリを起動して、「Engine running」になるまで待ってください。

### 2-3. フォルダの場所

このシステムのフォルダ(`Dockerfile` と `compose.yaml` があるフォルダ)を、PowerShellで開きます。

```powershell
cd C:\work\senior_thesis      # ← 自分のフォルダに読み替える
dir                            # Dockerfile, compose.yaml, main.py などが見えること
```

> **以降のコマンドは、すべて、この「Dockerfile と compose.yaml があるフォルダ」で実行します。**

### 2-4. ログイン状態のファイル

`auth_state.json` を、このフォルダに置きます(これまでと同じ手順で作成したもの)。
**ログイン済みのセッションそのものなので、他人に渡さないでください。**
(`.dockerignore` に入れてあるため、イメージには入りません。)

---

## 3. 箱(イメージ)を作る — 最初に1回

> **このバージョン(グラフ作成を除いた版)に更新した場合は、もう一度、作り直してください**
> (入れるパッケージと、起動スクリプトが変わったため)。2回目以降で、パッケージが減る分、前より軽くなります。

```powershell
docker compose build
```

- 最初は、**5〜15分かかります**(Pythonのイメージ、ブラウザ、パッケージを、インターネットからダウンロードするため)
- 約1〜2GBのディスク容量を使います
- 最後に `Image x-research:latest Built` のように出れば、完了です
- **2回目以降は、変更した部分だけなので、すぐ終わります**

`requirements-docker.txt` や `Dockerfile` を変更した場合だけ、もう一度、実行します。

---

## 4. 動かす

### 4-1. 環境の確認

```powershell
docker compose run --rm app check
```

- Python・パッケージ・ブラウザ・調査セットの設定を、確認します(Xには接続しません)
- `[NG]` が出なければ、OKです
- `auth_state.json` が無い場合は `[注意]` になります

> `--rm` は、「終わったら、箱を自動で消す」という意味です。付けておくのが基本です。
> `app` は、`compose.yaml` で決めたサービスの名前です。`check` が、箱の中で実行する命令です。

### 4-1b. ブラウザの動作確認(Xには接続しない)

`check` で確認できるのは、ブラウザの**ヘッドレス**での起動だけです。収集では、仮想ディスプレイの中で
**画面あり**で起動するため、そちらも確認します。

```powershell
docker compose run --rm app xvfb-run -a python check_env.py --headed
```

- `[OK] Chromium を画面ありで起動できます (DISPLAY=:99)` と出れば、OKです
- 同時に、**共有メモリ(`/dev/shm`)の大きさ**も表示されます。`compose.yaml` の `shm_size: "1gb"` が効いていれば、約1000MBです。小さい場合は、ブラウザが落ちる原因になります

#### `auth_state.json の権限は、箱の中からは確認できません (0o777)` と出た場合

**異常ではありません。** Docker Desktop で、Windowsのフォルダを箱に共有すると、箱の中からは、すべてのファイルが
常に `0o777` に見えます。箱の中で `chmod 600` を実行しても変わりません(実際の権限は、Windows側のものが適用されます)。
Windows側で、このフォルダが、他のユーザーに共有されていないことを確認してください。

### 4-2. 調査セットの確認

```powershell
docker compose run --rm app surveys
```

### 4-2b. 調べる名前を、英字だけで指定する(おすすめ)

`surveys.py` を編集しなくても、**英字部分をコマンドで指定するだけ**で、別の名前を調べられます。

```powershell
docker compose run --rm app collect --prefix StephanieL --max-accounts 3
```

自動で決まるもの(英字が `StephanieL` の場合):

| 項目 | 内容 |
|---|---|
| 対象の名前 | `StephanieL` の後ろに数字が続くもの(`StephanieL55648` など)。**大文字・小文字は区別しません**(Xのアカウント名が区別しないため) |
| 検索の文字列 | `StephanieL1` 〜 `StephanieL9` |
| 記録先 | `accounts_stephaniel.csv`(英字は小文字になる) |

- 同じ英字で、もう一度実行すると、**前回の続きから**進みます
- 最初に調べるアカウントを指定する場合: `--seed StephanieL55648`(複数回指定できます)
- 英字は、**3〜14文字**の、英字で始まる英数字です(短いと、無関係なアカウントが大量に該当するため)
- `surveys.py` に定義済みの英字(例: `--prefix AmandaGarc`)を指定すると、**新しいCSVを作らず、その調査セット(`accounts.csv`)を使います**
- `--survey` とは、同時に指定できません
- これまでに `--prefix` で作った記録は、`docker compose run --rm app surveys` で一覧できます

複雑なパターン(複数の検索文字列など)が必要な場合だけ、`surveys.py` に調査セットを定義します。

### 4-3. 少数で試す(まず3件)

```powershell
docker compose run --rm app collect --max-accounts 3
```

- 3アカウントだけ調べて、終了します
- 終わったら、お手元のフォルダの `accounts.csv` と `scraper.log` を確認します
- 調査セットを指定する場合: `collect --survey 名前 --max-accounts 3`

### 4-4. 本番の収集

```powershell
docker compose run --rm app collect --survey 名前 --max-accounts 200
```

- 途中で止めたいときは、**`Ctrl + C`** を押します(それまでの分は、保存されています)
- もう一度、同じコマンドを実行すると、**続きから**再開します
- PowerShellの窓を閉じると、収集も止まります(閉じずに置いておくか、次の「4-5」を使います)

### 4-5. 窓を閉じても動かし続ける(バックグラウンド)

```powershell
docker compose run -d --name collect app collect --survey 名前 --max-accounts 500
docker logs -f collect        # 経過を見る(Ctrl+C で、見るのをやめるだけ。収集は止まらない)
docker stop collect           # 止める
docker rm collect             # 止めた後、箱を片付ける(同じ名前で、もう一度動かす前に必要)
```

### 4-6. 箱の中を直接見たいとき

```powershell
docker compose run --rm app shell
```

箱の中のbashが開きます。`exit` で抜けます。

---

## 5. 画面でも操作できる(Docker Desktop)

Docker Desktop の画面でも、状態の確認と停止ができます。

| 場所 | できること |
|---|---|
| **Containers** | 動いている箱の一覧。**▶/■ で止められる**。名前をクリックすると**ログ**が見られる |
| **Images** | 作ったイメージの一覧(`x-research`)。不要なら、ゴミ箱で削除 |
| **Settings → Resources** | 箱に使わせる、CPU・メモリ・ディスクの上限 |
| **Settings → Resources → Proxies** | プロキシが必要なネットワーク(大学・研究室)のとき、設定する |

---

## 6. 困ったとき

| 症状 | 原因と対処 |
|---|---|
| `Cannot connect to the Docker daemon` / `error during connect` | Docker Desktopが起動していない。アプリを起動して「Engine running」になるまで待つ |
| `docker : 用語 'docker' は...認識されません` | インストール直後は、PowerShellを開き直す。それでも出る場合は、インストールが完了していない |
| ビルドが途中で失敗する(ダウンロードに失敗) | ネットワークの問題。プロキシが必要な環境では、Docker Desktopのプロキシ設定をする。時間をおいて、もう一度 `docker compose build` |
| `WSL 2 ...` のエラー(Windows) | WSL 2が無効。Docker Desktopの案内に従って、WSL 2を有効にして、再起動する |
| `no space left on device` | ディスクが足りない。`docker system prune`(使っていない箱やイメージを削除)で空ける。**実行前に、削除の内容を確認する** |
| 収集中に `Page crashed` などで落ちる | ブラウザのメモリ不足。`compose.yaml` の `shm_size` を大きくする(例: `"2gb"`)。Docker Desktopのメモリ上限(Settings → Resources)も増やす |
| `別のプログラムが使用中です`(終了コード3) | 同じ調査セットの収集が、既に動いている。`docker ps` で動いている箱を確認し、`docker stop 名前` で止める |
| `auth_state.json` の権限が `0o777` と表示される | Docker Desktop(Windows/Mac)では、常にその表示になる。異常ではない(4-1b を参照) |
| `auth_state.json が見つかりません` | ファイルが、このフォルダにない。置いてから、もう一度実行する |
| `bad interpreter` や `^M` という表示 | 改行コードの問題。Dockerfileの手順で、自動で直しているはず。出た場合は、教えてください |
| ログの時刻が、日本時間と合わない | `compose.yaml` の `TZ` を確認する |
| ファイルを保存する場所で `Permission denied` | フォルダ共有の権限の問題。フォルダを、`C:\work` など、ユーザーのフォルダ以外に移して、試す |

### 便利な確認コマンド

```powershell
docker ps                 # 今、動いている箱の一覧
docker ps -a              # 止まっている箱も含めた一覧
docker images             # 作ったイメージの一覧
docker logs 名前           # 箱のログを見る
docker stop 名前           # 箱を止める
docker rm 名前             # 止まっている箱を削除する
docker compose build --no-cache    # イメージを、最初から作り直す(うまくいかないとき)
```

---

## 7. 注意事項

- **ログイン状態(`auth_state.json`)を、イメージや箱に入れないでください。** `.dockerignore` で除外していますが、`Dockerfile` を書き換えて `COPY` する場合などは、注意してください
- **作ったイメージを、外部のサービス(Docker Hubなど)に公開しないでください。** 収集用のコードが含まれます。データは含まれませんが、公開する理由はありません
- **Dockerに入れても、Xの利用規約や、収集に伴うリスクは、変わりません。** 研究室・所属機関の方針に従ってください(詳細は README.md)
- **`login.py`(手動ログイン)は、Dockerの中では使えません**(画面が必要なため)。ログイン状態の作成は、これまでどおり、お手元のパソコンで行います
- **速度は上げない・並列実行しない**: 待機時間は、負荷を抑えるために、意図的に入れています。変えないでください

---

## 8. Dockerfile の構成(何が書いてあるか)

| 順 | 内容 | 理由 |
|---|---|---|
| 1 | `FROM python:3.12-slim-bookworm` | Python 3.12 の入った、軽い土台。OSは、Playwrightが公式対応する Debian 12 を明示 |
| 2 | `ENV ...` | 日本語のログの文字化け防止、ログの即時表示、日本時間、ブラウザの置き場所 |
| 3 | `apt-get install xvfb xauth tzdata` | 仮想ディスプレイ(画面のない箱で、画面ありのブラウザを動かすため)と、時刻データ |
| 4 | `pip install -r requirements-docker.txt` + `playwright install --with-deps chromium` | パッケージ(版を固定)と、ブラウザ本体・必要なシステムのライブラリ |
| 5 | `COPY docker-entrypoint.sh` + 改行コードの修正 + 実行権限 | `collect` や `check` などの短いコマンドで動かすための、起動スクリプト |
| 6 | `COPY . /app` | プログラム本体(`.dockerignore` で、秘密情報・データは除外) |
| 7 | `ENTRYPOINT` / `CMD` | 起動したとき、`docker-entrypoint.sh` を実行する(何も指定しなければ、使い方を表示) |

「重い手順(3〜4)」を先に、「よく変わるもの(6)」を後に置くのは、プログラムを書き換えても、
ブラウザなどを、入れ直さずに済むようにするためです。
