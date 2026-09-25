# X → RSS / GitHub Actions + Pages

公開Xアカウントの投稿をXへ直接アクセスして取得し、RSS 2.0として公開します。Python＋PyYAMLのみを使用し、Xへのログイン・Cookie・有料API・Nitter・XCancelには依存しません。

- Pages: https://kkld39.github.io/x-rss/
- Mazda_PRのInoreader登録URL: https://kkld39.github.io/x-rss/feeds/Mazda_PR.xml
- [取得ログの調査と代替方式の検証](docs/operations-audit.md)

## 通常運用

| 項目 | 動作 |
| --- | --- |
| 定期実行 | 毎時37分（`37 * * * *`）。UTCでも日本時間でも37分 |
| Xへのアクセス | 1アカウントにつき1回のGET。再試行・リダイレクト追従・追加の投稿単体取得なし |
| 取得待機中 | 保存された待機時刻より前なら0リクエスト |
| 手動取得 | Actions → Update X RSS → Run workflow。通常の待機制御を尊重 |
| push時 | テストと保存済みRSSのPages公開のみ。Xにはアクセスしない |
| Probe | 手動診断専用。明示的な確認チェックが必要。通常運用では使用不要 |
| 429・一時的な障害 | 有効な保存済みJSONとRSSがあれば警告で正常終了し、そのまま配信 |
| 要対応の障害 | コード異常、JSON/RSS破損、生成失敗、403/404、応答形式変更、履歴のpush失敗、Pages公開失敗などはFailure |

GitHubのスケジュールは遅延・取りこぼしがあり、厳密な毎時実行ではありません。[scheduleの仕様](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)では、Publicリポジトリの活動が60日ない場合の無効化にも注意が必要です。

## アカウントを追加・削除する

[accounts.yml](accounts.yml) の `accounts:` に、ユーザー名を1行ずつ追加してcommitします。Pythonの編集は不要です。

```yaml
accounts:
  - Mazda_PR
  # 次の行に「  - 実在するユーザー名」を追加（@やURLは不要）

include_reposts: false
include_replies: false
max_posts: 300
site_url: ""
```

追加したアカウントの取得は次の定期実行、または明示した手動実行で始まります。設定をpushしただけではXへアクセスしません。初回成功後に `feeds/ユーザー名.xml` ができます。

- 通常投稿・引用ポストを既定で含め、返信・リポストを除外します。
- `include_reposts` / `include_replies` を `true` にすると、その種別もRSSに含めます。
- 履歴にはフィルター前の投稿を保存します。設定変更は次の取得成功時に履歴全体へ適用します。一時失敗中は既存RSSのバイト列を維持します。
- `max_posts` は200〜500。既定300件で、返信・リポストも含む履歴の合計件数です。
- URLの大文字・小文字は区別されるので、設定した表記を使って購読してください。
- アカウントを削除すると取得とトップページ掲載を停止します。保存済みJSON・XMLの自動削除はしません。公開も停止したい場合は該当JSONと `public/feeds/対象.xml` を削除してcommitしてください。

## 429時の動作

1. その実行では再試行しません。5xxや通信タイムアウトも再試行しません。
2. 既存の投稿JSONとRSSを変更せず、診断情報とトップページのみ更新します。
3. キャッシュが有効ならアプリは終了コード0。Job SummaryとActionsのWarning注記で取得失敗を知らせます。全アカウントが429でも同じ扱いです。
4. 待機時刻をリポジトリに保存します。一時失敗から1時間後、Xの `x-rate-limit-reset`、`Retry-After` のうち最も遅い時刻までは、次回の手動・定期実行でもXへのアクセスを省略します。日付形式と秒数形式のRetry-Afterに対応します。
5. reset時刻と次回アクセス可能時刻を、トップページに日本時間で表示します。HTTPステータス・生のreset値・Retry-Afterなどの詳細は折りたたみ表示です。

resetはXが提示した時刻であり、その時刻に制限が解除される保証ではありません。数時間空けても失敗する実測があり、共有IP帯などによる制限の可能性があります。原因は断定していません。

初回取得で429となり、配信可能な保存済みJSON・RSSがない場合はFailureにします。配信できるものがない状態を成功として隠さないためです。429以外でも、コード・データ・RSSの異常は一時的なアクセス制限と区別してFailureにします。複数アカウントの処理は継続し、1件でも要対応エラーがあれば最終的にFailureです。

## トップページとRSS

スマートフォンで横スクロールせず読めるカード表示です。各カードにはRSSリンク、取得状態、最終取得成功、最終アクセス、取得件数を表示します。長いエラー文は「詳細を表示」で開けます。

RSSには以下を含めます。

- 本文、元投稿URL、RFC 822形式のUTC投稿日時
- 投稿IDを使う安定したGUID（同じ投稿を重複登録しない）
- Dublin Coreの `dc:creator` による投稿者名
- 取得できた画像のHTML表示と引用元URL

RSSの `author` はメールアドレスを要求するため使用せず、`dc:creator` を使います。XML/HTMLをエスケープし、不正なXML制御文字を除去します。画像は保存せずXの画像配信URLを参照します。新規生成RSSの `ttl` は60分です。失敗中の既存RSSにあるttlなどは保護のため書き換えません。

Inoreaderの購読追加に上記XML URLを貼り付けてください。HTTP 200・`application/xml` での外部取得と、GUID・日時・投稿者・本文を含むRSS 2.0の構造を確認しています。Inoreaderアカウント内部での実登録操作は行っていません。Inoreader側の更新頻度は同サービスの設定に従います。

## Workflowの役割

- **Update X RSS**: 毎時37分と手動実行のみ。X取得 → マージ → RSS生成 → 履歴commit → Pages公開。取得時の警告は正常終了、要対応エラーは公開可能な状態を保持したうえで最後にFailureにします。
- **Publish saved RSS (no X access)**: コード・設定・公開ファイルのpushと手動実行。保存済みRSSと状態を読み、トップページを再構築してPagesへ公開します。Xには接続せず、投稿JSON、RSS、最終取得成功時刻を書き換えません。
- **Tests**: ネット接続なしのテストと設定検証。Xには接続しません。
- **Probe X connectivity**: 手動で追加アクセスを明示したときだけ動く診断用です。通常運用で実行する必要はありません。独立診断なので通常Workflowの永続待機制御を使わず、アカウントごとに1リクエスト発生します。

コードの修正確認やデザイン変更で `Update X RSS` / Probe を手動実行しないでください。公開の更新だけなら `Publish saved RSS (no X access)` を使用します。

取得Workflowと公開専用Workflowは同じconcurrencyグループで直列化します。強制pushは行わず、リポジトリ更新との競合はFailureにして次回に回します。履歴保存に失敗した場合、Pagesだけを先に公開しません。

## 診断情報

`data/_meta/status.json` は現在の状態、`data/_meta/requests/ユーザー名.json` は直近120回の実行・スキップ履歴です。

記録するのは試行日時、リクエスト数、結果、HTTPステータス、サーバー日時、rate-limit値、reset日時、Retry-After、Xのtransaction ID / CF-Ray、Actions run IDです。Cookie・認証情報・生のレスポンス本文は記録しません。ヘッダーがない項目は未通知として扱います。

既存の過去ログには、当時記録していたHTTPステータスとresetしかありません。改修前の未記録ヘッダーを推測で補完しません。過去の取得成功時刻は上書きせず、取得失敗が続いていることをトップページから確認できます。

## 無料で使うための初期セットアップ

このリポジトリは設定済みです。別のリポジトリへコピーする場合:

1. **Publicリポジトリ** を作り、`.github/workflows/` も含めて配置します。
2. `accounts.yml` を設定します。
3. **Settings → Pages → Build and deployment → Source → GitHub Actions** にします。
4. GitHub公式Actionsを許可し、取得Workflowの `contents: write` による履歴commitが許されるようにします。ブランチ保護・組織ポリシーで拒否される場合は、専用リポジトリ等で適切な書き込み権限を設定します。
5. **Actions → Update X RSS → Run workflow** をデフォルトブランチで1回実行します。
6. PagesのトップページからRSSリンクを確認してInoreaderに登録します。

個別のPATやX関連のSecretsは不要です。自動のGITHUB_TOKENとPages用OIDCを利用します。標準URLはリポジトリ名から組み立てます。独自ドメインは `site_url` に指定してください。`main` 以外で運用する場合は公開専用Workflowの `push.branches` を変更します。

[Publicリポジトリの標準runnerは無料](https://docs.github.com/en/actions/concepts/billing-and-usage)です。[Pagesの容量・転送量などの上限](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)は適用されます。有料の大型runnerやPrivateリポジトリを前提としていません。artifactの保持は1日です。現在のJSON件数上限はgitの過去commit容量までは制限しません。

## ローカル検証

Python 3.10以上（Actionsは3.12）。依存ライブラリはPyYAMLのみです。

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v

# Xに接続しない公開確認
python -m xrss.app --publish-only
python -m http.server 8000 --directory public

# 明示的にXへ接続する場合のみ
python -m xrss.app --site-url https://USERNAME.github.io/REPOSITORY
```

終了コード0は「正常更新、または有効なキャッシュで一時障害を継続運用」、1はアカウントごとの要対応エラー、2は設定・実行全体の異常です。0が新着取得成功を意味するとは限りません。最終成功時刻も確認してください。

## ファイル構成

```text
accounts.yml                       対象と表示フィルター
xrss/source.py                     差し替え可能な取得処理・HTTP診断
xrss/runtime.py                    待機制御・警告/異常分類・保存処理
xrss/app.py                        CLI（--publish-onlyは接続なし）
xrss/model.py                      投稿データモデル
xrss/storage.py                    IDマージ・原子的なファイル置換
xrss/render.py                     RSSとモバイル対応トップページ
data/ユーザー名.json                投稿履歴
data/_meta/status.json             現在の取得状態
data/_meta/requests/ユーザー名.json  直近120回の診断履歴
public/feeds/ユーザー名.xml          公開RSS
public/index.html                  状況ページ
tests/                            ネット接続なしの自動テスト
docs/operations-audit.md           失敗ログ分析・代替方式調査
```

## トラブルシューティングと限界

- **数時間経っても429**: 短時間アクセスだけが原因とは限りません。手動再実行を繰り返さず、診断履歴と最終成功時刻を見てください。IP制限を回避するためのプロキシやrunner変更は実装していません。
- **403/404、ログインページ、解析不能、空応答**: 非公開化・削除・Xの仕様変更等を確認してください。正常な空フィードとして上書きしません。
- **RSSが404**: 初回取得とPages公開の成功を確認。パスは `public/feeds/` ではなく `feeds/` です。
- **Git pushが拒否される**: 書き込み権限、ブランチ保護、同時commitを確認。自動で保護を解除しません。
- **古い投稿や削除済み投稿が残る**: 履歴保持の仕様です。Xから返らなくても上限内なら保持します。
- **投稿が抜ける**: 埋め込み用タイムラインの件数・順序・本文の長さはX次第です。全投稿の回収や、取得間隔内に流れた投稿の復元は保証しません。
- **返信・リポスト判別**: 構造化データを優先し、会話ID・投稿者・RT表記も使用します。X側のデータ次第では誤判別がありえます。
- **将来止まる可能性**: 非公式エンドポイントの継続提供・無認証利用・共有runnerからの到達性は保証されません。取得を減らす改修は成功率の保証ではありません。

取得元は `Source.fetch(handle) -> list[Post]` で独立しています。未検証の内部APIや自動フォールバックは追加していません。代替方式は [調査記録](docs/operations-audit.md) を参照してください。
