# 返信先リスト 2026-09-06

## この調査でわかったこと（技術面）

- **Threads公式APIのキーワード検索は使えない。**
  `GET /keyword_search` は存在するが、他人の投稿を検索するには `threads_keyword_search` 権限の
  **App Review（＋事業者確認）** が必要。承認前は「自分の投稿だけ」しか返らない。
  https://developers.facebook.com/docs/threads/keyword-search
- **Threadsの検索ページはログインなしで読める。** ただし中身はJavaScriptで描画されるため、
  curl や requests では空のHTMLしか取れない（実測：HTTP 200 / 269KB / 本文0件）。
  収集にはヘッドレスブラウザが必要で、GitHub Actions から毎日回すと
  Meta側の変更やIPブロックで壊れやすい。毎朝エラーメールが飛ぶ運用は避ける。
- **結論：収集はブラウザ操作で都度行う。** 「今日の返信先を出して」で更新する。

## 収集条件

検索URL: `https://www.threads.com/search?q=<キーワード>&serp_type=default&filter=recent`
キーワード: 老後資金 / 貯金できない / 教育資金

## 選定基準

1. 新しい（数時間〜数日以内）… 古い投稿に返信しても誰も見ない
2. 問いかけで終わっている（「みんなどうしてる？」「教えて」）… 返信が歓迎される
3. 返信数がいいね数に対して多い … 会話が起きている投稿は露出しやすい
4. 発信者アカウント（集客目的）は除外 … 返信しても読者にはつながらない

## 抽出結果

| 鮮度 | アカウント | 内容 | いいね/返信 | URL |
|---|---|---|---|---|
| 47分 | mami_0202_ | 住宅ローン・教育資金・老後5000万で手一杯 | 1/- | https://www.threads.com/@mami_0202_/post/Dc8d2hFiaZK |
| 50分 | mini.mini.pon.kun | 学資保険 月3万？「みなさんどんなもんですか？」 | 7/8 | https://www.threads.com/@mini.mini.pon.kun/post/Dc8df41EieR |
| 1時間 | sora_mako_bee | 一時払養老保険1000万を検討中「アドバイス下さい」 | -/- | https://www.threads.com/@sora_mako_bee/post/Dc8aIJOk0B- |
| 7時間 | mydiarylife_777 | 50歳3児。教育費と老後資金のあいだで悩む | 2/- | https://www.threads.com/@mydiarylife_777/post/Dc7v2x9iT3a |
| 23時間 | uni.corn2059 | 「逆に何にお金使ってるの？」 | 129/206 | https://www.threads.com/@uni.corn2059/post/Dc6AIC8k_R0 |
| 1日 | cocochan5103 | 母子家庭。家賃が手取りの半分になりそう | 17/8 | https://www.threads.com/@cocochan5103/post/Dc3fW5WGRZu |
| 2日 | n_ew_mylife | 浪費癖・推し活「どうやってみんな貯金してるの」 | 18/5 | https://www.threads.com/@n_ew_mylife/post/Dc1CWB_n7ii |
| 4日 | sakekasu29.1 | 「うちだけなの？みんなどうやって生きてるの？」 | 83/4 | https://www.threads.com/@sakekasu29.1/post/DcxNwyBiWZZ |
| 4日 | hajimetenoikuji2025.12 | 一時払終身保険を勧められた、どうなのか | -/- | https://www.threads.com/@hajimetenoikuji2025.12/post/Dcv4boKE-uh |
| 6日 | restart_53 | 53歳、家が競売になるかもしれない | 256/45 | https://www.threads.com/@restart_53/post/Dcrryu6k-Dj |
| 6日 | mizuho4282 | アラ還。子2人を大学まで出したら一文も残らず | 2182/176 | https://www.threads.com/@mizuho4282/post/DcswAUAmfeg |
| 8/30 | segg2192 | NISA・教育費・老後、何から準備してる？ | 3/9 | https://www.threads.com/@segg2192/post/DcqHRM-Gp9U |
| 8/28 | fp_kamikawa_dayo | いくら必要か分かったら嬉しい？みんな興味ない？ | 34/26 | https://www.threads.com/@fp_kamikawa_dayo/post/Dck4vtjk7kj |
| 8/27 | bigb.minima | 給料が支払いで消える「同じ人いますか？」 | 4665/175 | https://www.threads.com/@bigb.minima/post/DciYHZXI7pW |
| 8/13 | 1111_toto_1111 | 家計の内訳を全部公開「皆さんどんな感じですか？」 | 604/46 | https://www.threads.com/@1111_toto_1111/post/Db-TsSZEydy |

## 返信のルール（このアカウント用）

- 3行以内。90字を超えない
- リンクを貼らない（初回の返信で誘導すると通報・ミュートの対象になりやすい）
- 「〜すべき」と言い切らない。「私はこうした」で止める
- 金融商品の良し悪しを断定しない。有資格の助言と受け取られる表現を避ける
- 全員に同じ文を送らない。相手の言葉を1つ拾って入れる

## フォローしておくとよいアカウント

同じ立場・同じ悩みで発信していて、相互に見合える相手。

- nisa50life（50代パート主婦、NISAで老後資金）
- mydiarylife_777（50歳3児、教育費と老後資金）
- fp_kamikawa_dayo（お金の必要額を発信）
