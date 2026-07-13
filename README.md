# Yahoo! Shopping MCP

Yahoo!ショッピング 商品検索 API v3 を MCP サーバーとして公開・自前運用できるプロジェクトです。`search_products` を公開で提供しつつ、Yahoo 側保護のための直列化、429 リトライ、短期キャッシュ、日次利用量監視、アプリケーション全体のグローバルレートリミットを実装しています。

このリポジトリ自体はオープンソースで、ローカル実行と Docker / Cloudflare Tunnel の両方に対応しています。

## 公開方針

このリポジトリは、Yahoo!ショッピングの公式サービスではなく、Yahoo!デベロッパーネットワークのAPIを利用するオープンソースのMCPサーバーです。LINEヤフー株式会社、Yahoo!ショッピング、OpenAIとの提携・承認・保証を示すものではありません。

共有ホストの継続提供はこのプロジェクトの保証範囲外です。利用者は自分のYahoo! Developer Client IDを設定し、必要な規約・クレジット表示・利用制限を確認したうえで、自分の環境にホストしてください。

ローカル利用が既定です。インターネットへ公開する場合は、認証なしのMCPエンドポイントになるため、レート制限、Host/Origin制限、ログとデータ保持を確認してください。

## 機能

- `search_products` による Yahoo!ショッピング商品検索
- キーワード、JAN、価格帯、在庫、商品状態、送料条件、ソート、ページング
- Yahoo 向けの 1 req/sec ベース直列化
- 429 の指数バックオフ再試行
- 同一クエリの短期キャッシュ
- 同一クエリの同時 miss を 1 回の upstream call に束ねる singleflight
- SQLite ベースの日次利用量監視
- SQLite ベースのアプリケーション全体のグローバルレートリミット
- `GET /`, `GET /healthz`, `POST/GET/DELETE /mcp` だけを公開
- OpenAIの安全ガイドラインに合わせ、危険な商品検索や不正な外部URLは返しません

## ローカル Plugin パッケージ

リポジトリ直下に、ローカル利用向けの Plugin メタデータを含めています。

- `.codex-plugin/plugin.json`: Plugin名、説明、starter prompts、ロゴ、参照文書
- `.mcp.json`: `http://127.0.0.1:8000/mcp` を参照するMCP設定
- `assets/logo.svg`: 商品検索を表すロゴ

このパッケージはStore公開や共有ホストを前提にしていません。利用前に利用者自身がMCPサーバーを起動し、Yahoo Client IDを設定してください。ChatGPTアプリIDに依存する`.app.json`は意図的に含めていません。

## 認証

このサーバーは認証を実装していません。API キー、OAuth、JWT、セッションログインは使いません。MCP エンドポイントは公開で、その代わりに全体レートリミットだけを適用します。

## 使い方

### ChatGPT Developer Mode や他の MCP クライアントから使う

自分で起動したMCPサーバーのURLを指定します。ローカル実行時は次のいずれかです。

```text
http://127.0.0.1:18000/mcp
```

ローカルで直接 `make run` した場合はこちらです。

```text
http://127.0.0.1:8000/mcp
```

認証ヘッダは不要です。これは自分で管理する環境での利用を前提にした設計です。公開ホストへ配置する場合は、インフラ側のアクセス制御とレート制限を別途設定してください。

### `search_products` の主な入力

- `query`
- `jan_code`
- `price_from`
- `price_to`
- `in_stock`
- `condition`
- `shipping`
- `sort`
- `genre_category_ids`（カテゴリ ID の OR 指定）
- `brand_ids`（ブランド ID の OR 指定）
- `seller_id`
- `image_size`（`76`, `106`, `132`, `146`, `300`, `600`）
- `is_discounted`
- `results`
- `start`

`query` または `jan_code` のどちらかは必須です。

`genre_category_ids` と `brand_ids` は配列で指定し、Yahoo API にはカンマ区切りの OR 条件として送信します。`preorder`、`payment`、配送日指定などの追加フィルタは公開しません。

### 呼び出し例

```json
{
  "query": "desk lamp",
  "in_stock": true,
  "sort": "-score",
  "results": 10,
  "start": 1
}
```

主な出力:

ChatGPT が読む商品データは MCP tool result の `content[0].text` に JSON として返し、先頭キーを `results` にします。
カルーセル用データは `structuredContent.products` に返し、tool の `outputSchema` も同じ `{ products: [...] }` に限定します。

### 商品カルーセル（MCP Apps）

`search_products` は MCP Apps UI Resource `ui://yahoo-shopping/product-carousel-v4.html` に紐付いています。ChatGPT では、検索結果を横スクロールの商品カードとして表示します。画像は Yahoo API の `exImage` を優先し、なければ `image.medium` / `image.small` を使います。

- `content[0].text`: ChatGPT が本文として読む `results` JSON
- `structuredContent.products`: カルーセルが描画する商品データ
- `resources/read`: カルーセル HTML を `text/html;profile=mcp-app` として返す
- CSP: Yahoo 画像 CDN `https://item-shopping.c.yimg.jp` だけを許可する
- Yahoo!デベロッパーネットワークのクレジットをカルーセル下部に表示する

カルーセルは MCP Apps の `ui/*` bridge で ChatGPT と通信します。`search_products` 実行後にカードの「Yahoo!ショッピングで見る」から商品ページを開けます。

- `results`: `id`, `title`, `url`, `text`, `metadata` を含む商品検索結果リスト
- `display_summary`: MCP クライアントや LLM が読み取りやすい検索結果サマリー
- `no_items_reason`: 商品がない場合の理由。例: `upstream_hits_empty`

`results[*].metadata` には `price`, `price_text`, `seller_name`, `image_url`, `badges` が入ります。
詳細なYahoo APIの内部フィールドや診断情報は、公開MCPの本文には返しません。

## キャッシュとプライバシー

このサーバーは同一検索条件に対して短期キャッシュを共有します。ただし、キャッシュファイルには **安全フィルタ後のYahoo APIレスポンス由来データだけ** を保存し、`query` や `jan_code` などの入力文字列はディスクへ保存しません。

検索語はリクエストとしてMCPサーバーとYahoo APIへ送信されます。会話履歴、認証情報、決済情報、政府識別子、検索語を含むアプリケーションログは保存しません。厳密なプライバシー要件がある場合は、必ず自分でホストし、データディレクトリとプロキシのログを管理してください。

詳細は [プライバシー通知](PRIVACY.md)、[データ取り扱い](docs/DATA_HANDLING.md)、[利用上の注意](TERMS.md)、[セキュリティ方針](SECURITY.md)、[サポート](SUPPORT.md) を参照してください。

## 安全ポリシー

成人向け商品、武器、薬物、タバコ、ギャンブル、マルウェア・監視用品、偽造品などに該当する検索語や商品は返却しません。これはキーワードとYahoo APIレスポンスの保守的な判定であり、Yahoo!ショッピングの商品分類を完全に保証するものではありません。

検索結果はYahoo!ショッピングの商品ページへのリンクとして扱い、購入・注文・アカウント変更は実行しません。

## 必要なもの

- Python 3.12 以上
- `uv`
- Yahoo!ショッピング API の `appid`

## ローカルセットアップ

依存同期:

```bash
make sync-dev
```

起動:

```bash
YAHOO_SHOPPING_APP_ID="your-app-id" make run
```

ホストやポートを変える場合:

```bash
YAHOO_SHOPPING_APP_ID="your-app-id" make run HOST=0.0.0.0 PORT=8080
```

デフォルト URL:

- MCP endpoint: `http://127.0.0.1:8000/mcp`
- Health check: `http://127.0.0.1:8000/healthz`

## Docker / Cloudflare セットアップ

`.env` 作成:

```bash
make init-env
```

最低限の設定:

- `YAHOO_SHOPPING_APP_ID`
- `ALLOWED_HOSTS`
- `ALLOWED_ORIGINS`

`CLOUDFLARE_TUNNEL_TOKEN`は`make up-tunnel`を使う場合だけ必要です。

任意の主な設定:

- `YAHOO_SHOPPING_MCP_GLOBAL_RATE_LIMIT`
- `YAHOO_SHOPPING_MCP_GLOBAL_WINDOW_SECONDS`
- `YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS`
- `YAHOO_SHOPPING_MCP_BASE_RATE_SECONDS`

ローカル compose 起動:

```bash
make up
```

Named Tunnel 付き起動:

```bash
make up-tunnel
```

停止:

```bash
make down
```

ローカル compose の公開 URL:

- MCP endpoint: `http://127.0.0.1:18000/mcp`
- Health check: `http://127.0.0.1:18000/healthz`
- Root health check: `http://127.0.0.1:18000/`

## 任意のCloudflare Tunnel設定

Cloudflare Tunnelは開発者が任意で使える公開手段です。ローカル実行や他のクラウド/リバースプロキシは必須ではありません。

`make up-tunnel`を使う場合だけ、CloudflareのTunnel Tokenを設定してください。

`.env.example`:

```env
YAHOO_SHOPPING_APP_ID=replace-with-your-yahoo-app-id
CLOUDFLARE_TUNNEL_TOKEN=replace-with-your-cloudflare-tunnel-token
ALLOWED_HOSTS=localhost:18000,127.0.0.1:18000
ALLOWED_ORIGINS=http://localhost:18000,http://127.0.0.1:18000
YAHOO_SHOPPING_MCP_GLOBAL_RATE_LIMIT=60
YAHOO_SHOPPING_MCP_GLOBAL_WINDOW_SECONDS=60
```

## 開発

よく使うコマンド:

```bash
make sync-dev
make run
make test
make up
make up-tunnel
make down
make clean
```

## 確認

- `/healthz` と `/` が `200` を返す
- `/mcp` の `initialize` と `tools/list` が成功する
- `search_products` が商品データを `content[0].text` とUI用の構造化データに返す
- クレジット表示、危険商品フィルタ、外部URL検証が機能する
- 詳細な手順は [MCP検証手順](docs/VERIFICATION.md) を参照する
- 審査用の再現ケースは [レビュー用テストケース](docs/SUBMISSION_TEST_CASES.md) を参照する

## テスト

```bash
make test
```

テストでは Yahoo! への実通信を行いません。`httpx.MockTransport` でダミーレスポンスを返します。

## ライセンス

[MIT](LICENSE)
