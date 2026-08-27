# 3コマ漫画 自動投稿システム

毎日きまった時刻に、3コマ漫画を **Threads**（3枚のツリー）と **Instagram**（3枚のカルーセル）へ自動で投稿します。
パソコンの電源が入っていなくても、GitHub というサービス上で勝手に動きます。

**今の設定：Threads ＋ Instagram。** X（旧Twitter）も後から足せるようになっています（→[X を後から足す](#x-を後から足す)）。

---

## 今の状態

| | 内容 |
|---|---|
| 画像 | **78枚**（`images/` に入っています） |
| 投稿文 | **78本分**（26日 × 3枚）、`posts.csv` に作成済み |
| 投稿予定 | **2026年8月23日 〜 9月17日**（1日1回・3枚のツリー投稿） |
| 投稿時刻 | 日本時間 **朝6:00** |
| 投稿先 | Threads **@hiromi.lifeplan**（同じアカウントセンターに削除予定の shu1_omatomepan があるので取り違え注意） |

1日分は `N-1` `N-2` `N-3` の3枚セットで、この順にツリーになります。

1. `1-1` 〜 `14-3`（14日分）… 資産家との出会いから始まる長編＋退職後のお金の話（8/23〜9/5）
2. `15-1` 〜 `26-3`（12日分）… 少し先を歩く人から学ぶ／借入の考え方／学びを人に返す（9/6〜9/17）

---

## 毎日やること：なし

一度セットアップが終わったら、日々の作業はありません。
**新しい漫画を足すときだけ**、次の3ステップをやります。

### 新しい漫画を追加する手順（3ステップ）

**ステップ1：`C:\AI\manga` に画像を入れる**

いつも漫画を作っている `C:\AI\manga` フォルダに、新しい画像をそのまま入れてください。

> ファイル名は **`27-1.png` `27-2.png` `27-3.png`** のように、
> **「番号 - 枚数」** の形にしてください。この3枚が1日分（1つのツリー）になります。
>
> 番号は続きから振ります（今は26まで使っているので、次は27です）。
> サイズは気にしなくて大丈夫です。次のステップで自動的に調整されます。

**ステップ2：変換スクリプトを1回実行する**

PowerShell を開いて、次の1行を実行します。

```bash
powershell -ExecutionPolicy Bypass -File C:\AI\manga-autopost\tools\add-manga.ps1
```

これだけで、

- Threads用の画像（`images/`）
- Instagram用の4:5画像（`images_ig/`）

の両方が作られます。さらに、**新しく増えた画像を見つけて、`posts.csv` と `instagram.csv` に貼り付ける雛形を日付つきで表示**してくれます。

**ステップ3：文章を書いて、アップロードする**

表示された雛形の「ここにThreads本文」などを実際の文章に置き換えて、

- `posts.csv` の一番下（3行）
- `instagram.csv` の一番下（1行）

に貼り付けて保存します。そのあと次を実行するとGitHubに反映され、指定日の朝6時に自動投稿されます。

```bash
powershell -ExecutionPolicy Bypass -File C:\AI\manga-autopost\tools\add-manga.ps1 -Push
```

> 文章を考えるのが大変なときは、画像を `C:\AI\manga` に入れた状態で
> 「漫画を追加したので投稿文を作って」と Claude Code に頼めば、
> 中身を読んで文案を作り、CSVへの追加とアップロードまでやってもらえます。

---

## `posts.csv` の書き方

| 列 | 内容 | 例 |
|---|---|---|
| 投稿日 | いつ投稿するか | `2026-08-25` |
| 画像ファイル | 画像の場所 | `images/1.jpg` |
| X本文 | Xに出す文（日本語140文字まで） | `今日もおつかれさま。` |
| Threads本文 | Threadsに出す文（500文字まで） | `みんなはどうしてる？` |
| ステータス | **空のままでOK**（投稿されると自動で「済」が入る） | |

> X本文は今は使われませんが、あとで X を足したときにそのまま使えるよう、42本すべて書いてあります。

### 気をつけること

- 文の中に **カンマ `,`** や **改行** を入れたいときは、その文全体を **`"`（半角ダブルクォート）** で囲んでください
  例: `2026-10-06,images/34.jpg,"朝、起きられない。","朝、起きられない人、いる？",`
- 投稿日が今日ではない行は無視されます。その日の行がなくても、エラーにはなりません
- **URLは入れないでください。** Threadsでは問題ありませんが、X を足したときに料金が1件 $0.015 → **$0.20（13倍）** に跳ね上がります

---

## 画像を小さくする

`tools/resize-images.ps1` を使うと、フォルダの中の画像をまとめて縮小して `images/` に書き出せます。
（横幅1440px・JPEG品質90 に変換します。だいたい1枚 700KB になります）

PowerShell を開いて、次を実行します。

```bash
powershell -ExecutionPolicy Bypass -File tools\resize-images.ps1 -Source "C:\AI\manga"
```

`-Source` のあとに、元の画像が入っているフォルダを指定してください。
**元の画像はそのまま残ります。**

---

## 投稿時刻を変える

`.github/workflows/daily-post.yml` の中の、この行を書き換えます。

```
- cron: '0 21 * * *'
```

GitHub は世界標準時（UTC）で動くので、**日本時間から9時間引いた数字**を書きます。

| 日本時間 | 書く数字 |
|---|---|
| 6:00 | `'0 21 * * *'` ←今これ |
| 7:00 | `'0 22 * * *'` |
| 12:00 | `'0 3 * * *'` |
| 20:00 | `'0 11 * * *'` |
| 21:30 | `'30 12 * * *'` |

書き方は `分 時 * * *` です。

> GitHub の混雑によって、実際の投稿は **5〜30分ほど遅れることがあります**。
> 「20:00ちょうど」ではなく「20時台」と考えてください。

---

## 投稿がうまくいったか確認する

1. GitHub のリポジトリ上部の **「Actions」** タブをクリック
2. 「毎日の自動投稿」の一覧を見る
   - **緑のチェック** … 成功
   - **赤いバツ** … 失敗（登録メールアドレスに通知メールも届きます）
3. 行をクリックすると、何が起きたか日本語のログで見られます

投稿の記録は `logs/posted.csv` にも残ります（日時・SNS・成功か失敗か・エラー内容）。

---

## 手動で試したいとき（テスト投稿）

1. **「Actions」** タブ → 左の **「毎日の自動投稿」** をクリック
2. 右の **「Run workflow」** ボタンをクリック
3. 入力欄が出てきます

| 欄 | 使い方 |
|---|---|
| date | 試したい行の投稿日を入れる（例 `2026-08-25`） |
| dry_run | **チェックを入れると、実際には投稿せず内容チェックだけ**します。まずはこれで確認 |
| only | `threads` または `x` を選ぶと、片方だけに投稿します |

4. 緑の **「Run workflow」** を押す

---

## よくあるエラーと対処

| ログに出るメッセージ | 意味と対処 |
|---|---|
| Threadsのアクセストークンが切れました | Meta for Developers でトークンを取り直し、Secrets の `THREADS_ACCESS_TOKEN` を更新 |
| Threadsが画像を読み込めませんでした | 画像がまだアップロードされていない／ファイル名が違う／**リポジトリが private になっている**。3つとも確認 |
| 画像が見つかりません → images/34.jpg | `posts.csv` に書いたファイル名と、実際の画像のファイル名が違う（大文字小文字も区別されます） |
| X本文が長すぎます | 日本語140文字を超えている。短くする |
| Xの認証に失敗しました | Xのキーが違うか、アプリの権限が「Read」だけ。Developer Portal で **Read and write** に変更 |
| Xの残高（クレジット）が足りません | X Developer Portal でクレジットを追加 |

---

## 料金について

| | 料金 |
|---|---|
| GitHub Actions | **無料**（publicリポジトリなら無制限） |
| Threads API | **無料** |
| X API（今は未使用） | 1投稿 $0.015／URLを含むと $0.20 |

**今の構成の実費は $0（無料）です。**

---

## 登録が必要な情報（GitHub Secrets）

リポジトリの **Settings → Secrets and variables → Actions** に登録します。
⚠️ **この値をチャットやメールに貼らないでください。** Secrets の画面に直接入力してください。

| 名前 | 何のキーか | 今すぐ必要? |
|---|---|---|
| `THREADS_USER_ID` | ThreadsのユーザーID | — 不要（トークンから自動取得します） |
| `THREADS_ACCESS_TOKEN` | Threadsの長期アクセストークン | ○ 必須 |
| `GH_PAT` | GitHubの個人アクセストークン（下記） | △ 推奨 |
| `X_API_KEY` 他3つ | X のキー | ✕ Xを足すときだけ |

### トークンの自動更新（`GH_PAT`）

Threadsのトークンは **60日で切れます**。
`GH_PAT` を登録しておくと、毎週月曜の朝に自動で延長されるので、手作業の更新が不要になります。

作り方：

1. GitHub 右上の自分のアイコン → **Settings**（リポジトリのSettingsではなく、アカウントの方）
2. 左の一番下 **Developer settings**
3. **Personal access tokens → Fine-grained tokens** → **Generate new token**
4. Repository access で **Only select repositories** → このリポジトリを選ぶ
5. Permissions → Repository permissions の **Secrets** を **Read and write** にする
6. **Generate token** を押して出てきた文字列をコピー
7. リポジトリの Settings → Secrets に `GH_PAT` という名前で貼り付ける

---

## X を後から足す

1. X Developer Portal で開発者登録し、クレジットを購入する
2. アプリの権限を **Read and write** にして、4つのキーを取得する
3. GitHub の Secrets に `X_API_KEY` `X_API_SECRET` `X_ACCESS_TOKEN` `X_ACCESS_TOKEN_SECRET` を登録する
4. `.github/workflows/daily-post.yml` の `ENABLE_X: 'false'` を **`'true'`** に書き換える

`posts.csv` の X本文は42本すべて用意済みなので、4だけで投稿が始まります。

---

## ファイルの説明

```
manga-autopost/
├── images/                        漫画の画像（78枚）
├── posts.csv                      投稿スケジュールと本文
├── post.py                        投稿の本体（触らなくてOK）
├── refresh_threads_token.py       Threadsトークンの自動延長（触らなくてOK）
├── requirements.txt               必要な部品の一覧（触らなくてOK）
├── instagram.csv                  Instagramのキャプション（1日1行）
├── images_ig/                     Instagram用の4:5画像（自動生成）
├── tools/add-manga.ps1            漫画を追加するとき実行する道具
├── tools/resize-images.ps1        Threads用に縮小（add-manga から呼ばれます）
├── tools/make-instagram-images.ps1 Instagram用に4:5化（同上）
├── logs/posted.csv                投稿の記録（自動で作られます）
└── .github/workflows/
    ├── daily-post.yml             毎日の実行設定（時刻・X切替はここ）
    └── refresh-token.yml          トークン延長の実行設定
```

---

## Instagram について

Threadsと同じ日に、**その日の3枚を1つのカルーセル投稿**（横スワイプ）としてInstagramにも投稿できます。
Instagramには「ツリー返信」がないため、カルーセルがツリーの代わりになります。

### 画像が別フォルダになっている理由

Instagramは**縦横比 4:5 までしか受け付けません**。漫画は 2:3 とそれより縦長なので、
そのままだと上下が切れてしまいます。

そのため `images_ig/` に、左右へ白い余白を足して 4:5 にした画像を用意しています。
**漫画そのものは一切切れていません。**

新しい漫画を足したら、次を実行して `images_ig/` も更新してください。

```bash
powershell -ExecutionPolicy Bypass -File tools\make-instagram-images.ps1
```

### キャプションは `instagram.csv`

Instagramのキャプションは `instagram.csv` に、**1日1行**で書いてあります。

| 列 | 内容 |
|---|---|
| 投稿日 | `2026-08-25` 形式（`posts.csv` の日付と合わせる） |
| キャプション | Instagramに載せる文（2200文字まで） |

Threadsとは文面を変えてあります（Instagramは最初の2行しか表示されないため、
フックを先頭に置き、ハッシュタグを末尾にまとめています）。

その日の行がない場合は、Threads本文を3枚分つないだものが自動で使われます。

### Instagramを有効にする手順

1. Instagramアカウントを**プロアカウント**（ビジネス／クリエイター）にする
2. Meta for Developers のアプリに **Instagram** のユースケースを追加する
3. `instagram_business_basic` と `instagram_business_content_publish` の権限を追加する
4. アクセストークンを発行し、GitHub の Secrets に `INSTAGRAM_ACCESS_TOKEN` として登録する
5. `.github/workflows/daily-post.yml` の `ENABLE_INSTAGRAM: 'false'` を **`'true'`** に書き換える

> Instagramの投稿は **1日25件まで**という上限があります。1日1投稿なので問題ありません。

---

## 夜のテキスト投稿（1日2回運用）

朝の漫画とは別に、**毎晩21時に文章だけの投稿**をThreadsへ自動投稿します。

| | 朝6時 | 夜21時 |
|---|---|---|
| 内容 | 漫画3枚のツリー | 文章だけ2〜3本のツリー |
| 投稿先 | Threads ＋ Instagram | Threads のみ |
| 元データ | `posts.csv` / `instagram.csv` | **`text-posts.csv`** |
| 立ち位置 | 学びを届ける | **まだ途中の自分を見せる** |

Instagramは画像がないと投稿できないため、夜はThreadsだけです。

### なぜ役割を分けているか

Threadsのバズ投稿を20件調べたところ、この分野では
**「解決した話」より「まだ困っている話」のほうが100倍近く伸びる**ことがわかりました。

- 弱さの告白＋仲間探し … 平均2,867いいね
- 実績報告・成功報告 … 平均29〜170いいね

漫画は「学びを届ける」内容なので、拡散という面では不利な型です。
そこで夜のテキストでは、あえて**まだ迷っている自分**を書いています。

詳しい分析は [research/buzz-analysis-20260826.md](research/buzz-analysis-20260826.md) にあります。

### `text-posts.csv` の書き方

| 列 | 内容 |
|---|---|
| 投稿日 | `2026-08-27` 形式。**同じ日付を2〜3行**書くとツリーになります |
| 本文 | 投稿する文章。**1本目を短いフックに**すると伸びやすいです（上限500字） |

改行やカンマを含む場合は、全体を `"` で囲んでください。

### 時刻を変える

`.github/workflows/evening-post.yml` の `- cron: '0 12 * * *'` を書き換えます。
UTC 12:00 が日本時間21:00です。20時にするなら `'0 11 * * *'` です。

### 手動で試す

**Actions → 「夜のテキスト投稿」→ Run workflow** から実行できます。
`dry_run` にチェックを入れると、投稿せず内容だけ確認できます。
