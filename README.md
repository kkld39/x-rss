# X → RSS / GitHub Actions + Pages

公開Xアカウントの投稿をXへ直接アクセスして取得し、RSS 2.0として公開します。Python＋PyYAMLのみを使用し、Xへのログイン・Cookie・有料API・Nitter・XCancelには依存しません。

- Pages: https://kkld39.github.io/x-rss/
- 各アカウントのRSS: Pagesの「現在の監視対象」→「RSSを購読」から確認
- [取得ログの調査と代替方式の検証](docs/operations-audit.md)

## はじめて使う方へ

### 公開ページとGitHub Pagesの管理画面を開く

公開ページは [こちら](https://kkld39.github.io/x-rss/) です。RSS一覧や取得状態を見る場所と、GitHub側の設定画面は別です。

1. [リポジトリ](https://github.com/kkld39/x-rss) を開き、GitHubにログインします。
2. 上部の **Settings** を押します。狭い画面では「…」メニュー内にあります。
3. 左側の **Code and automation → Pages** を選びます。[Pages管理画面への直接リンク](https://github.com/kkld39/x-rss/settings/pages)も使えます。
4. **Visit site** で公開ページを開けます。公開方式は **Build and deployment → Source: GitHub Actions** にします（このリポジトリは設定済み）。Settingsは管理権限がある人にのみ表示されます。

About欄にも公開ページのリンクを置けます。リポジトリの **Code** 画面右側の **About横の歯車 → Website** に `https://kkld39.github.io/x-rss/` を入力し、**Save changes** を押します。「Use your GitHub Pages website」が表示される場合はそれを選んでも構いません。今回の接続にはWebsite変更APIがなく、操作用ブラウザーも未ログインのため、このAbout設定のみ手動操作が必要です。

### InoreaderにRSSを登録する

1. 公開ページの「現在の監視対象」から読みたいアカウントを探します。
2. **RSSを購読** を右クリックしてリンクをコピーします。スマートフォンでは長押しでコピー、またはリンクを開いてアドレス欄をコピーします。XMLの文字が表示されても正常です。
3. Inoreaderにログインし、**＋ / Add feed（フィードを追加）** を開きます。
4. **Website** の検索欄にコピーしたRSS URLを貼り付け、検索します。
5. 表示されたフィードの **Follow / Subscribe（購読）** を押します。複数アカウントはそれぞれのRSSを登録してください。

説明用の架空URLは `https://kkld39.github.io/x-rss/feeds/example_account.xml` です。これは実際の購読先ではありません。必ず公開ページの実リンクを使ってください。XのプロフィールURLやPagesのトップURLではなく、末尾が `.xml` のURLを登録します。[Inoreader公式ガイド](https://www.inoreader.com/blog/2024/11/getting-started-with-inoreader.html)

### accounts.ymlをGitHub上で編集・追加する

1. リポジトリ上部の **Code** を選び、ファイル一覧の **accounts.yml** を開きます。
2. 右上の鉛筆アイコン **Edit this file** を押します。
3. `accounts:` の下に `  - ユーザー名` を1行追加します。先頭は**半角スペース2個、半角ハイフン、半角スペース1個**です。タブは使わないでください。
4. ユーザー名はXプロフィールのURLの末尾です。表示名ではなく、**@もURL全体も不要**です。
5. **Commit changes…** を押し、変更理由を入力して **Commit directly to the main branch → Commit changes** で保存します。ここでいうcommitは変更内容の保存です。
6. 保存直後はXに接続しません。順番が回って初回取得に成功すると、公開ページにRSSリンクが表示されます。

下の `example_account` は説明用の架空名です。実際に監視したいユーザー名に置き換えてください。現在登録済みのアカウントを例の名前で上書きする必要はありません。

### アカウントを削除する

同じ鉛筆アイコンから、そのアカウントの `  - ユーザー名` の行だけを削除して **Commit changes** します。他の設定行は残します。次回から取得対象外になり、公開ページの一覧からも消えます。既存のJSONとRSSは保護のため残るので、既存購読者には最後のRSSが配信され続けます。

すべての監視を停止する場合は、**Actions → Update X RSS → 右上の「…」→ Disable workflow** を使ってください。現在の設定はアカウントを1件以上必要とするため、空の `accounts:` では設定エラーになります。

### 手動で新着確認する

**リポジトリ → Actions → 左側の Update X RSS → Run workflow → Branch: main → Run workflow** を押します。対象は自動選択の1件だけで、待機中なら0件です。手動でも15分・60分・429待機期限を無視しません。実行後は実行名を開き、**Summary** で選ばれたアカウントと警告を確認できます。

ページ表示だけ更新したい場合は **Publish saved RSS (no X access)** を手動実行します。Probeは通常運用では使いません。

## 複数アカウントの時間分散

毎時 **7・22・37・52分** に起動し、待機期限を過ぎた対象から**未取得を優先、次に最終アクセスが古い順**で最大1件を選びます。同時刻なら `accounts.yml` の順です。成功時刻ではなく試行時刻で順番を決めるので、失敗したアカウントばかりを連続取得しません。未選択のアカウントの状態・RSS・投稿履歴は変更しません。

- リポジトリ全体で実アクセスの間隔を最低15分空けます。前回Workflowが遅れて次の起動と接近した場合は、その回をスキップし、sleepや追いつくための連続取得はしません。
- 同一アカウントは最低60分空けます。429等の待機期限が先なら、その期限も尊重します。
- 状態は `data/_meta/status.json` に保存し、次のrunner・手動実行でも使います。削除したアカウントの直近のアクセスも全体の間隔判定に含めます。
- HTTP接続前にデータ破損などで失敗した対象も、検査時刻を記録して順番を後ろに回します。他のアカウントを妨げず、失敗した対象の再検査は最低60分空けます。
- 通常の取得Workflow全体で**1時間最大4リクエスト**、1アカウントは最大1リクエストです。対象なしの回は0件で、履歴commitとPagesデプロイも省略します。
- 公開・取得Workflowは同じconcurrencyグループで直列化します。通常運用の上限は状態保存が正常に続くことが前提です。状態ファイルの削除、独立したローカル実行や手動Probeは別なので、通常運用では行わないでください。

下表は全アカウントが取得可能で、Workflowが予定どおり起動する場合の例です。A1等は架空のアカウントを表します。

| 登録数 | 初回巡回の例（09:07開始） | A1の次回 | 1アカウントの更新間隔目安 |
| --- | --- | --- | --- |
| 1〜4 | A1 09:07、A2 09:22、A3 09:37、A4 09:52（存在する分だけ） | 10:07 | 約60分 |
| 5 | A1 09:07 → 15分おき → A5 10:07 | 10:22 | 約75分 |
| 10 | A1 09:07 → 15分おき → A10 11:22 | 11:37 | 約150分（2時間30分） |
| 20 | A1 09:07 → 15分おき → A20 13:52 | 14:07 | 約300分（5時間） |

目安は `max(60分, 15分 × アカウント数)` です。GitHubの起動遅延・取りこぼし、全体の間隔チェック、429によってさらに長くなります。期限は「その時刻以降に選択可能」の意味で、取得時刻の予約ではありません。

長時間sleepやアカウントごとのmatrix jobを使わず、短い1ジョブを最大96回/日起動する設計です。標準のPublicリポジトリrunnerで運用し、空振り時の再デプロイを省きます。ただしアカウントが少ない場合にも起動・依存インストール・テストの負荷はあります。

時間分散は、このリポジトリ自身の集中アクセスを抑える対策です。実測では数時間空けても429があり、共有IP帯やX側の制限が原因なら解消しません。IP変更・プロキシでの回避は行いません。[最新の検討・テスト記録](docs/multi-account.md)

## 通常運用

| 項目 | 動作 |
| --- | --- |
| 定期実行 | 毎時7・22・37・52分（`7,22,37,52 * * * *`）。UTCでも日本時間でも同じ分 |
| Xへのアクセス | 1回のWorkflowで全体最大1回のGET。再試行・リダイレクト追従・追加の投稿単体取得なし |
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
  - example_account
  # 次の行に「  - 実在するユーザー名」を追加（@やURLは不要）

include_reposts: false
include_replies: false
max_posts: 300
site_url: ""
```

追加したアカウントは取得の順番待ちに入り、定期実行または手動実行で選ばれた際に取得します。設定をpushしただけではXへアクセスしません。初回成功後に `feeds/ユーザー名.xml` ができます。

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

初回取得で429となり、配信可能な保存済みJSON・RSSがない場合はFailureにします。配信できるものがない状態を成功として隠さないためです。429以外でも、コード・データ・RSSの異常は一時的なアクセス制限と区別してFailureにします。対象に選ばれたアカウントに要対応エラーがあればFailureです。試行時刻を保存して次の実行では別のアカウントに順番が回るため、失敗した1件で他のアカウントが停止しません。

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

- **Update X RSS**: 毎時7・22・37・52分と手動実行のみ。待機制御と対象1件の選択 → X取得 → マージ → RSS生成 → 履歴commit → Pages公開。取得時の警告は正常終了、要対応エラーは公開可能な状態を保持したうえで最後にFailureにします。
- **Publish saved RSS (no X access)**: コード・設定・公開ファイルのpushと手動実行。保存済みRSSと状態を読み、トップページを再構築してPagesへ公開します。Xには接続せず、投稿JSON、RSS、最終取得成功時刻を書き換えません。
- **Tests**: ネット接続なしのテストと設定検証。Xには接続しません。
- **Probe X connectivity**: 手動で追加アクセスを明示したときだけ動く診断用です。通常運用で実行する必要はありません。独立診断なので通常Workflowの永続待機制御を使わず、アカウントごとに1リクエスト発生します。

コードの修正確認やデザイン変更で `Update X RSS` / Probe を手動実行しないでください。公開の更新だけなら `Publish saved RSS (no X access)` を使用します。

取得Workflowと公開専用Workflowは同じconcurrencyグループで直列化します。強制pushは行わず、リポジトリ更新との競合はFailureにして次回に回します。履歴保存に失敗した場合、Pagesだけを先に公開しません。

## 診断情報

`data/_meta/status.json` は現在の状態、`data/_meta/requests/ユーザー名.json` は直近120回の取得処理履歴（分散スケジューラーの未選択・待機は書き込まない）です。

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
xrss/scheduler.py                  全体15分・個別60分の制御、対象1件の選択
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
