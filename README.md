# X → RSS / GitHub Actions + Pages

公開XアカウントのタイムラインをXのSyndicationサービスから直接取得し、アカウント別のRSS 2.0をGitHub Pagesで公開するPythonアプリです。Inoreaderへの登録を想定しています。

**Xへのログイン、Cookie、APIキー、有料API、Nitter、XCancel、外部RSSサービスは使用しません。** 依存ライブラリは設定ファイル用のPyYAMLのみです。

## 動作確認と制約

2026-09-24に、以下の実在するエンドポイントから、Cookie・認証ヘッダーなしで `Mazda_PR` の20件の投稿を取得できました。最初はHTTP 429で、後にHTTP 200になりました。Xのアクセス制限により、常に成功するわけではありません。

```text
https://syndication.twitter.com/srv/timeline-profile/screen-name/Mazda_PR
```

HTML中の `__NEXT_DATA__` → `props.pageProps.timeline.entries[].content.tweet` を解析します。取得実測と検証範囲は [docs/verification.md](docs/verification.md) を参照してください。

`kkld39/x-rss` に配置し、GitHub Actions上で自動テスト13件の成功を確認しました。2026-09-24 15:11 UTCの直接取得テストはHTTP 429でしたが、Xが示したリセット時刻を過ぎた15:16 UTCの生成Workflowでは、認証・Cookieなしで20件の取得、11件のRSS生成、履歴のcommitに成功しました。初期履歴は同日14:39 UTCの実取得レスポンスから保存したもので、その後runnerからの取得成功で更新しています。

公開先は `https://kkld39.github.io/x-rss/feeds/Mazda_PR.xml` です。現時点ではPagesの初回有効化が必要で、生成Workflowの公開部分はその設定待ちです。Settings → Pages → Sourceを **GitHub Actions** にすると公開を進められます。

これは非公式エンドポイントです。将来、認証要求・仕様変更・IP制限などで動作しなくなる可能性があります。最近の全投稿を取得できる保証もありません。Syndicationが返す件数・順序・本文の長さはX次第で、長文やリポストが省略される場合があります。返されない返信・リポストは設定を有効にしても取得できません。guest token / GraphQLは、今回Syndicationで実データが取得できたため使用していません。

## 初期セットアップ

1. GitHubで **Publicリポジトリ** を作り、このフォルダーのファイルをアップロードまたはpushします。`.github/workflows/` も含めてください。既存リポジトリをforkする場合は、ActionsタブでWorkflowを有効にします。
2. `accounts.yml` を編集し、監視したい公開アカウントを登録します。
3. リポジトリの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** にします。
4. **Settings → Actions → General** でGitHub公式Actionsが許可されていることを確認します。Workflowがデフォルトブランチへ履歴をcommit・pushできる必要があります。このWorkflowは `contents: write` を明示しています。組織の制限やブランチ保護がpushを拒否する場合は、専用リポジトリなどで書き込みを許可してください。
5. **Actions → Probe X connectivity → Run workflow** を選択して接続を確認します。Pagesの設定なしでも実行でき、履歴は変更しません。
6. **Actions → Update X RSS → Run workflow** を、**デフォルトブランチ** を選んで実行します。成功すると `data/` と `public/` がリポジトリにcommitされ、Pagesに公開されます。
7. Workflow内の `Deploy Pages` または **Settings → Pages** から公開URLを確認します。

個別のPersonal Access TokenやX関連のSecretsは不要です。自動発行の `GITHUB_TOKEN` とPages用OIDCを利用します。独自ドメインを使わなければ `site_url` の設定も不要です。

### 無料範囲

GitHub Freeで利用する場合は **Publicリポジトリ＋標準の `ubuntu-latest` runner** を前提とします。[標準runnerのPublicリポジトリでの実行は無料](https://docs.github.com/en/actions/concepts/billing-and-usage)で、[GitHub PagesもPublicリポジトリで利用可能](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)です。Privateリポジトリや有料の大型runnerを選ばないでください。

保存する投稿数は各アカウント最大300件（変更可）です。画像はダウンロードせず、RSS内でXの画像URLを参照します。Pages artifactの保持は1日です。Pagesの容量・転送量やリポジトリ全体の容量には上限があるため、対象を極端に増やさず利用してください。JSONの件数上限はgitの過去commitの容量までは制限しません。

## 監視アカウント・表示設定

```yaml
accounts:
  - Mazda_PR
  # - 実在する別アカウントのユーザー名

include_reposts: false
include_replies: false
max_posts: 300
site_url: ""
```

`accounts` に行を追加・削除してcommitすれば、次の実行から反映されます。`@`、URL、日本語の表示名は入れず、Xのユーザー名を指定してください。サンプルの `example_account` は実在確認していないため初期設定には入れていません。

| 設定 | 既定値 | 内容 |
| --- | --- | --- |
| `include_reposts` | `false` | `true` でリポストもRSSに含める |
| `include_replies` | `false` | `true` で返信もRSSに含める |
| `max_posts` | `300` | アカウントごとの履歴上限。200〜500 |
| `site_url` | 空文字 | PagesのサイトURLを自動取得。独自ドメインなどの場合のみ指定 |

通常投稿と引用ポストはデフォルトで含めます。引用元URLが取れる場合はリンクを付けます。リポストは構造化データを優先し、投稿者と監視対象の不一致・`RT @` 表記も手がかりにします。後者はXの返すデータによって誤判別する可能性があります。返信は返信先フィールドと会話IDで判別します。

履歴にはフィルター前の投稿を保存し、RSS生成時にフィルターを適用します。このため `true` に切り替えると、保存済みの返信・リポストも次の**取得成功時**に表示できます。失敗時はRSSをそのまま維持するため、設定変更も成功まで反映されません。履歴上限は通常投稿・引用・返信・リポストの合計です。

アカウントを削除すると取得とトップページへの掲載を停止します。誤削除を防ぐため、保存済みJSONとRSSは自動削除しません。公開も停止したい場合は `data/対象.json` と `public/feeds/対象.xml` を手動で削除してcommitし、Workflowを実行してください。URLの大文字・小文字は区別されるため、設定した表記のRSS URLを登録してください。

## Inoreaderに登録

公開サイトの「RSSを購読」リンクのURLをコピーして、Inoreaderの購読追加で貼り付けます。

```text
https://USERNAME.github.io/REPOSITORY/feeds/Mazda_PR.xml
```

`USERNAME` と `REPOSITORY` を実際の値に置き換えてください。`USERNAME.github.io` というユーザーサイト用リポジトリでは `REPOSITORY/` が付きません。正確なURLはトップページのRSSリンクで確認できます。

RSSには本文、UTCの投稿日時、元投稿URL、投稿IDに基づく固定GUID、`dc:creator` による投稿者名、取得できた画像を含めます。RSSの `author` はメールアドレスを要求するため使用していません。文字はXML/HTMLとしてエスケープし、外部スクリプトを挿入しません。画像の表示はInoreaderの画像設定やX側の配信状況にも依存します。

## 実行タイミングと手動実行

`Update X RSS` は `7,37 * * * *`、つまり毎時7分・37分（UTC基準）に実行します。日本時間でも毎時7分・37分です。`main` の `accounts.yml` または生成Workflowを変更した場合も実行します。`Probe X connectivity` は手動のほか、`main` の取得モジュール・接続確認Workflowを変更した場合に実行します。別のデフォルトブランチで使う場合は、両Workflowの `push.branches` も変更してください。

手動では **Actions → Update X RSS → Run workflow → デフォルトブランチ → Run workflow** を選びます。接続だけを試す場合は **Probe X connectivity** を選んでください。

GitHubのスケジュール実行には遅延や取りこぼしがあり、厳密な30分周期を保証しません。また、Publicリポジトリのスケジュールは60日間活動がない場合に無効化されることがあります。停止した場合はActions画面で再有効化してください。[GitHubのschedule仕様](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## 保存・エラー時の動作

```text
accounts.yml                       監視対象・フィルター設定
xrss/source.py                     取得処理（差し替え箇所）
xrss/model.py                      取得元に依存しないPost形式
xrss/storage.py                    原子的なファイル置換・IDマージ
xrss/render.py                     RSSとトップページ
xrss/app.py                        アカウント別処理・ログ・終了コード
xrss/probe.py                      認証不要の実接続確認
data/Mazda_PR.json                 投稿履歴（初回成功時に生成）
data/_meta/status.json                   最終試行・最終成功・失敗理由
public/feeds/Mazda_PR.xml          RSS（初回成功時に生成）
public/index.html                  状況ページ
.github/workflows/update-feeds.yml 定期取得・履歴commit・公開
.github/workflows/probe.yml        手動の実接続テスト
.github/workflows/test.yml         ネット接続なしの自動テスト
tests/test_system.py               取得解析・RSS・履歴保護のテスト
```

- 投稿IDで重複排除し、同じIDの内容は新しい取得結果で更新。投稿日時順に保持します。Xから返らなくなった投稿も上限内なら残ります。
- 1アカウントのエラー後も残りを処理します。失敗したアカウントの既存JSON・RSSは取得結果で上書きしません。履歴JSONが破損していても空に初期化しません。
- HTTP 200でも空タイムライン・解析不能は失敗です。投稿のない新規アカウントも保守的に失敗扱いになります。初回失敗時は空のRSSを作らず「初回取得待ち」と表示します。
- HTTP 429は即時再試行せず、リセット時刻をログに表示して次回実行を待ちます。タイムアウト・5xxは短いバックオフで最大3回試行します。
- 成功・新規取得件数・失敗理由はログとActionsのSummaryで確認できます。「新規」はフィルター前の未保存ID数です。
- 全件失敗時も既存フィードと失敗情報を公開してからWorkflowをfailureにします。公開済みRSSを空にしません。設定不正など実行全体の異常時は公開処理自体を行いません。
- 履歴のpushに失敗した場合はPages公開を止めます。同時実行は直列化し、別のcommitと競合したときは強制pushせず失敗します。次回実行で最新の履歴から再開します。
- Pagesが未設定でも取得と履歴保存を先に行います。Pages設定の確認は保存後です。標準の公開URLはリポジトリ名から組み立て、独自ドメインは `site_url` に指定します。

最終取得成功日時は「その時刻にXがデータを返した」ことを表します。最新投稿まで揃っているという意味ではありません。X側のキャッシュや固定投稿などにより、古い投稿だけが返ることもあります。

## ローカル実行

Python 3.10以上（Actionsでは3.12）で実行します。

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m xrss.probe
python -m xrss.app --site-url https://USERNAME.github.io/REPOSITORY
python -m unittest discover -s tests -v
```

ローカルの試行を本番データと分ける場合:

```bash
python -m xrss.app --data-dir _local/data --output _local/public --site-url http://localhost:8000
python -m http.server 8000 --directory _local/public
```

アプリの終了コードは、少なくとも1件成功なら `0`、全件取得失敗なら `1`、設定や実行全体の異常なら `2` です。テストは合成レスポンスを使用し、Xに接続しません。接続成功は `probe` で別途確認します。

## トラブルシューティング

| 症状 | 確認・対応 |
| --- | --- |
| HTTP 429 | Xの制限です。連続して手動実行せず次回を待ちます。監視アカウント数を減らす、実行間隔を広げることも検討してください。 |
| 403 / 404 / ログインページ | Xの制限、アカウントの削除・非公開化、エンドポイントの変更を確認します。手元で成功してもGitHubのIPだけ制限されることがあります。 |
| `__NEXT_DATA__` がない / 構造を解釈できない | `xrss/source.py` の取得処理がXの新形式に追従する必要があります。既存履歴・RSSは保持されます。 |
| 全件失敗 | Summaryを確認します。以前のRSSは引き続き配信されます。初回から失敗する環境では本方式で更新できません。 |
| Pages設定の取得に失敗 | Settings → PagesのSourceをGitHub Actionsにし、Pagesの利用可否・Actions許可を確認します。 |
| `git push` が拒否される | `contents: write`、組織ポリシー、ブランチ保護、同時に行われた手動commitを確認します。自動で保護を解除したり強制pushしたりはしません。 |
| RSSが404 | 初回取得成功・Deploy Pages成功を確認。URLは `public/feeds/` ではなく `feeds/`。アカウント名の大文字小文字にも注意してください。 |
| Inoreaderが更新しない | トップページの最終成功日時とRSS中の投稿日時を確認します。Inoreader側の取得間隔・キャッシュによる遅延もあります。 |
| 一部の投稿がない | Xが返す最近の範囲とフィルターを確認。過去全件の復元や取得間隔内に流れた全投稿の回収はできません。 |
| 古い投稿・削除済み投稿が残る | 履歴保持による仕様です。削除を反映するには履歴JSONの該当投稿を削除して再生成してください。Xが再度返せば復活します。 |
| 設定したのに実行されない | 設定・Workflowがデフォルトブランチにあるか、forkのActionsが有効か、スケジュールが無効化されていないかを確認します。 |

## 取得方式を差し替える

`xrss/source.py` の `Source` インターフェースは `fetch(handle) -> list[Post]` です。別の取得元を実装し、`app.py` の `SyndicationSource()` を差し替えれば、JSON履歴・RSS・Pages処理を再利用できます。失敗は `FetchError` として報告し、空配列を成功として返さないでください。実際に利用可能と検証していないGraphQL IDやguest token向けAPIを固定値で追加しないでください。
