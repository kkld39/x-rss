# 取得・生成の検証記録

実施日: 2026-09-24（UTC）。手元のWindows環境、Python 3.10で確認。

## Xへの直接接続

リクエスト先:

```text
GET https://syndication.twitter.com/srv/timeline-profile/screen-name/Mazda_PR
```

Cookie、Authorization、Xアカウントのログインは使用していません。取得先はX自身のドメインです。Nitter、XCancel、外部の投稿キャッシュは使用していません。

| 試行 | 結果 |
| --- | --- |
| 14:35 UTC、Mazda_PR | HTTP 429、`Rate limit exceeded` |
| 14:36 UTC、OpenAI | HTTP 429 |
| 14:39:05 UTC、Mazda_PR | HTTP 200、HTML 161,015 bytes、タイムライン20件 |
| Pythonアプリによる追加の実接続 | HTTP 429を検出して終了コード1、空RSS・空履歴は作成されない |

上記の成功レスポンスは `curl` で取得し、実装したPythonパーサーに入力しました。`__NEXT_DATA__` 内の `props.pageProps.timeline.entries[].content.tweet` が実在し、本文、`id_str`、`created_at`、`user`、`extended_entities.media`、返信・リポストのデータを確認しました。数値の `id` が0でも `id_str` に正しいIDが入っていたため、IDは文字列を優先しています。

この実レスポンスからの解析・生成結果:

- 20件の投稿（リポスト5件、返信4件）。
- リポスト元の画像も含めると画像のある投稿は16件。
- デフォルト設定でRSSに11件を出力し、そのうち8件に画像。
- UTF-8のRSS 2.0をXMLパーサーで読み戻し、生成処理の終了コード0を確認。

この結果は、この時刻のこの接続元での取得成功を示します。継続的な取得、他の全アカウント、全件回収、GitHub ActionsのIPからの取得を保証しません。HTTP 429も実際に観測しています。

## 自動テスト

`python -m unittest discover -s tests -v` で以下を確認します。ネット接続は使用しません。

- 実レスポンスと同じ構造の合成データを使った通常投稿・返信・リポスト・引用の解析。
- `retweeted` とリポスト種別の区別、文字列ID、画像、Unicode。
- 空・ログインページ・不正なJSON構造や日時の失敗判定。
- 429を再試行しないこと、一時的な通信エラーを再試行すること、Cookie・認証ヘッダーを送らないこと。
- RSSの日時、GUID、投稿者名、画像、HTMLエスケープ、不正なXML制御文字の除去。
- IDでの重複排除、内容更新、日時順、保存上限。
- 1アカウント失敗後の継続、全件失敗時の非ゼロ終了。
- 失敗したアカウントの既存JSON・RSSがバイト単位で変わらないこと。
- 初回失敗時に空RSSを作らないこと、壊れた履歴を上書きしないこと。
- 保存済み投稿へのフィルター変更の適用と引用ポストの保持。
- 危険なパス・重複アカウント・不正な設定値の拒否。

## GitHub Actions / Pages / Inoreader

配置先は [kkld39/x-rss](https://github.com/kkld39/x-rss) です。[GitHub Actions上のTests](https://github.com/kkld39/x-rss/actions/runs/36018109707) が成功しました。

[2026-09-24 15:11 UTCのProbe](https://github.com/kkld39/x-rss/actions/runs/36018231564) はUbuntu 24.04 / Python 3.12.14のGitHub-hosted runner（Azure centralus）から実行し、XからHTTP 429が返りました。Xが返したリセット時刻はUnix秒 `1790262958` です。即時再試行はしていません。

同日14:39 UTCの実取得レスポンスを初期履歴として `data/Mazda_PR.json` に20件保存し、`https://kkld39.github.io/x-rss/feeds/Mazda_PR.xml` 用のRSSを11件生成しました。最終取得成功日時は元の取得時刻を保持し、最新試行は上記Probeの失敗として別に記録しています。初期履歴を最新取得成功のようには扱っていません。

PagesへのデプロイとInoreaderへの実登録の確認は、以下に追記します。

リポジトリに配置した後、まず `Probe X connectivity` を手動実行してください。対象runnerからの結果、取得件数、最新投稿日時、エラーをSummaryに出します。その後 `Update X RSS` を実行し、公開RSSをInoreaderへ登録してください。

## 選定時に確認した資料

- [Syndicationクライアント実装のスキーマとURL](https://github.com/Lqm1/X-ActivityPub-Bridge/blob/main/src/x/syndication_twitter.ts): エンドポイントとJSON構造の存在を調査。実装は本プロジェクト用に作成。
- [TwittxrのREADME](https://github.com/Owen3H/twittxr): Cookieが必要になる場合などの制約を確認。記載だけで動作可否を断定せず直接接続で検証。
- [GitHub Actionsの無料利用条件](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub Pagesの利用条件と上限](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [GitHubスケジュール実行の制限](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

単一投稿用のSyndication APIは投稿IDが既知である必要があり、アカウントの新着IDを列挙する代替にはならないため採用していません。Syndicationのタイムライン取得が実測で成功したため、未検証のguest token / GraphQLフォールバックは追加していません。
