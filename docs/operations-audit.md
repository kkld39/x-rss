# 運用ログ調査・改修検証（2026-09-25）

## 既存Actionsログを使った調査

Xへの再アクセスではなく、既存の全取得実行6件（うち定期実行3件）を調べました。以下はUTCです。

| 実取得日時 | Azure runner地域 | Xの結果 | Xが示したreset (UTC) | 実行 |
| --- | --- | --- | --- | --- |
| 09-24 15:11:01 | centralus | HTTP 429 | 09-24 15:15:58 | [Probe](https://github.com/kkld39/x-rss/actions/runs/36018231564) |
| 09-24 15:16:32 | westcentralus | 20件取得成功 | 成功時ヘッダー未記録 | [Update](https://github.com/kkld39/x-rss/actions/runs/36018938493) |
| 09-24 15:29:58 | westus | HTTP 429 | 09-24 15:34:31 | [手動](https://github.com/kkld39/x-rss/actions/runs/36020597966) |
| 09-24 19:28:05 | eastus | HTTP 429 | 09-24 19:32:15 | [定期](https://github.com/kkld39/x-rss/actions/runs/36048324666) |
| 09-24 22:41:59 | centralus | HTTP 429 | 09-24 22:48:47 | [定期](https://github.com/kkld39/x-rss/actions/runs/36068869973) |
| 09-25 01:23:43 | northcentralus | 20件取得、新規1件、保存21件、RSS11件 | 成功時ヘッダー未記録 | [定期・公開成功](https://github.com/kkld39/x-rss/actions/runs/36081802051) |

429のRetry-Afterは4回ともログ上「不明」です。以前の実装はHTTPステータスとreset以外のrate-limitヘッダー、送信元グローバルIPを記録していなかったため、後から数値を補うことはできません。

### 判断

- 約4時間・約3時間空けても429でした。したがって、このリポジトリからの短時間アクセスだけで説明できるとは言えません。
- 各429のresetは次の試行までに過ぎています。それでも次回429になっています。reset到達での復旧は保証されません。
- runner地域が変わり、成功と429が混在しています。GitHub/Azureの共有IP帯に対する制限、他利用者との共有枠、X側の接続元判定などは候補ですが、公開IP・X内部の判定は観測できていないため断定できません。地域とIPは同じ意味ではありません。
- GitHub-hosted runnerから利用できる実測はありますが、6回中成功2回、定期3回中成功1回という少数の履歴です。安定して毎時新着を取得できるとは判断できません。サンプルが少なく、将来の成功率の推定にも使えません。
- スケジュール自体にも大きな間隔がありました。cronを毎時37分にしても、GitHubの実行遅延・取りこぼしまで解消するものではありません。

## 代替の直接取得方式

既存の実装例を調べ、存在が確認できないAPIは追加していません。候補の評価は以下です。

| 候補 | 調査・実測 | 本番判断 |
| --- | --- | --- |
| Syndicationのプロフィールタイムライン | 上記のGitHub runner実測で成功・429が混在 | 現方式を維持し、アクセス削減とキャッシュ配信を強化 |
| `https://x.com/Mazda_PR` の公開HTML | 09-25 03:06:51 UTC、手元から認証・CookieなしでGETを1回。HTTP 200、210,150 bytes、正しいプロフィールタイトル、5個の投稿IDと本文フィールドを確認 | 有力な候補。ただしGitHub runnerからの到達性・継続性は未検証で、返った本文フィールドも5件。現方式の20件より少なく、データ構造が異なるため今回は差し替えない |
| guest token + Web GraphQL | [公開クライアントの説明](https://github.com/tamnd/x-cli/blob/main/README.md)と[内部APIのサンプル](https://github.com/fa0311/TwitterInternalAPIDocument/blob/master/sample.py)に実装例あり | token取得・ユーザー解決・タイムライン等でリクエストが増えうる。今回の環境での稼働・安定性は未検証。追加アクセスを避け、未検証のquery IDや自動fallbackを導入しない |
| 単一投稿Syndication / oEmbed | [Syndication実装](https://github.com/Lqm1/X-ActivityPub-Bridge/blob/main/src/x/syndication_twitter.ts)などを確認。既知の投稿ID/URLを読むもの | 新着投稿IDを列挙する代替にはならない |
| 同じSyndicationのuser-id形式 | 既存実装には存在するが同じ配信サービス | 制限が回避できる根拠なし。2本目のリクエストになるので導入しない |

プロフィールHTMLにはReact/Relay系の直列化された投稿データが含まれていました。スクリプトを実行したり、ブラウザーへのログインやCookieを送ったりはしていません。[HTML取得の実装例](https://github.com/tamnd/x-cli/blob/main/x/webpage.go)は調査資料として読み、コードはコピーしていません。

今回Xへ送った追加の調査リクエストは、上記プロフィールHTMLへの1回のみです。Syndicationへの追加テストは0回、プロフィールHTMLのリトライも0回です。手元でのHTML成功をGitHub上の安定動作と混同していません。

## 改修内容

- cronを `37 * * * *` に変更。取得WorkflowとProbeからpushトリガーを削除。
- 通常取得は各アカウント1回のGETのみ。5xx・通信失敗・429すべて再試行なし。リダイレクトも追従しない。
- 429などの一時エラーは、有効な履歴とRSSがあればWarning＋終了コード0。コード・生成・データ異常、恒久的と考えるHTTPエラー、配信できる初期キャッシュがない場合はFailure。
- 失敗から1時間、reset、Retry-Afterの最も遅い時刻を永続化。待機中は0リクエスト。
- 安全なレスポンスヘッダーだけを現在状態・直近120回の診断履歴に記録。本文やCookieは記録しない。
- Pagesのみ再構築する `--publish-only` と専用Workflowを追加。push後の公開ではXに接続しない。
- スマートフォン向けカード表示、HTTPエラー詳細の折りたたみ、JSTのreset表示。

## 検証

- 公開RSSを外部から取得し、HTTP 200・Content-Type `application/xml` を確認。
- RSS 2.0の11項目について、GUIDの一意性、投稿日時、元URL、本文、投稿者をXMLパーサーで確認。Inoreader内へのログインや実登録操作は行っていない。
- 通常成功・429・503・タイムアウトが1リクエスト以内で終わること、待機中0回、push時0回をネット接続なしのテストで確認。
- 全アカウント429でもキャッシュが有効なら正常終了し、Job Summaryに警告が出ることを確認。
- 失敗時のJSON/RSSのバイト一致、最終成功時刻の保持、コード・RSS生成異常のFailureを検証。
- 公開専用処理が取得元を呼ばず、RSS・履歴・取得時刻を書き換えないことを検証。
- モバイル幅375px（スクロールバーを除く表示領域360px）で、長い429詳細が初期状態では閉じていること、展開しても横にはみ出さないこと、RSSリンクが `feeds/Mazda_PR.xml` を指すことをブラウザーで確認。

公開URL: https://kkld39.github.io/x-rss/

Inoreader登録URL: https://kkld39.github.io/x-rss/feeds/Mazda_PR.xml
