# Yahoo! Shopping MCP

Yahoo!ショッピング 商品検索 API v3 を MCP サーバーとして公開・自前運用できるプロジェクトです。`search_products` を公開で提供しつつ、Yahoo 側保護のための直列化、429 リトライ、短期キャッシュ、日次利用量監視、アプリケーション全体のグローバルレートリミットを実装しています。

このリポジトリ自体はオープンソースで、ローカル実行と Docker / Cloudflare Tunnel の両方に対応しています。

## 公開エンドポイント

現在、非公式の公開 MCP サーバーを次で案内しています。

- MCP endpoint: `https://non-official-yahoo-shopping-mcp.notelligent.app/mcp`
- Health check: `https://non-official-yahoo-shopping-mcp.notelligent.app/healthz`
- Root health check: `https://non-official-yahoo-shopping-mcp.notelligent.app/`

## まず知っておいてほしいこと

- この公開エンドポイントは **非公式** です
- 作者都合で **停止・再起動・終了** することがあります
- 一時的に応答しない場合は、短時間に連打せず **少し時間を置いて再試行** してください
- 安定稼働や継続利用が必要なら、**自分でホストする前提** で使うのをおすすめします

目安としては、ヘルスチェックが落ちているときや `/mcp` 接続が失敗するときは、数分から少し時間を空けて再試行してください。長期的に安定利用したい場合は、このリポジトリを使ってローカルまたは自前インフラへデプロイしてください。

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

## 認証

このサーバーは認証を実装していません。API キー、OAuth、JWT、セッションログインは使いません。MCP エンドポイントは公開で、その代わりに全体レートリミットだけを適用します。

## 使い方

### ChatGPT や他の MCP クライアントから使う

MCP サーバー URL に次を指定します。

```text
https://non-official-yahoo-shopping-mcp.notelligent.app/mcp
```

ローカル compose で試すならこちらです。

```text
http://127.0.0.1:18000/mcp
```

ローカルで直接 `make run` した場合はこちらです。

```text
http://127.0.0.1:8000/mcp
```

認証ヘッダは不要です。クライアントから `search_products` をそのまま呼び出せます。

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

返却される `usage.global_rate_limit` には次が入ります。

- `limit`
- `remaining`
- `window_seconds`
- `reset_at`

主な出力:

ChatGPT 互換性のため、商品データは MCP tool result の `content[0].text` に JSON として返します。
`structuredContent` / `outputSchema` だけに商品データを置くと、一部の MCP host では検索結果本文として認識されず、メタ情報だけが会話側に露出することがあります。
そのため、このサーバーではモデルが読む本文として `content[0].text` を正とし、商品リストを先頭の `results` に置きます。
`YAHOO_SHOPPING_MCP_TOOL_RESPONSE_MODE=chatgpt` を使うと ChatGPT 向けに `content[0].text` 優先、`structured` を使うと従来の `structuredContent` 併用に戻せます。
本番の ChatGPT 接続では `chatgpt` を維持してください。ここを `structured` に戻すと、今回のように ChatGPT 側で検索結果を本文として拾えず、再発する可能性があります。
この設定を変更する場合は、`outputSchema` が OFF になっていることと、`content[0].text` の `results` が実際に返ることをライブ環境で確認してから反映してください。

- `results`: `id`, `title`, `url`, `text`, `metadata` を含む商品検索結果リスト
- `display_summary`: MCP クライアントや LLM が読み取りやすい検索結果サマリー
- `items`: Yahoo!ショッピング API の商品 `hits` を MCP 向けに snake_case へ正規化した詳細リスト
- `debug`: 上流 URL、HTTP status、上流キー、`hits` 件数、整形後件数、キャッシュヒット有無
- `no_items_reason`: 商品がない場合の理由。例: `upstream_hits_empty`

`results[*].metadata` には `price`, `price_text`, `seller_name`, `image_url`, `badges` が入ります。
`debug` は原因切り分け用で、商品が見えない場合に上流 `hits` 件数、整形後件数、キャッシュヒット有無を確認するためのものです。

`items[*]` には既存の `name`, `url`, `price`, `in_stock`, `condition`, `image`, `review`, `seller`, `description` に加えて、次の追加フィールドが入ります。Yahoo API 側で該当フィールドが欠損している場合は `null` または空リストになります。

- `code`: Yahoo API `code`
- `headline`: Yahoo API `headLine`
- `price_label`: Yahoo API `priceLabel`。`default_price`, `discounted_price`, `fixed_price`, `period_start`, `period_end`
- `ex_image`: Yahoo API `exImage`。`url`, `width`, `height`
- `genre_category`: Yahoo API `genreCategory`。`id`, `name`, `depth`
- `parent_genre_categories`: Yahoo API `parentGenreCategories`
- `brand`: Yahoo API `brand`。`id`, `name`
- `parent_brands`: Yahoo API `parentBrands`
- `jan_code`: Yahoo API `janCode`
- `delivery`: Yahoo API `delivery`。`area`, `deadline`, `day`

今回返却対象に含めていない Yahoo API フィールドは `point.lyLimited*`, `shipping`, `payment`, `seller.sellerId`, `seller.review` です。

## 公開サーバー利用時の注意

公開サーバーは「お試し用」「疎通確認用」と考えてください。

- 作者都合で停止することがあります
- 一時停止中は health check も失敗します
- 失敗したときは短時間で何度も叩かず、時間を置いて再試行してください
- 継続的な利用、社内利用、組み込み用途、安定 SLA が必要な用途では自前運用してください

また、サーバーは公開 MCP として動作するため、機密性の高い運用では自前ホストを推奨します。

## キャッシュとプライバシー

このサーバーは同一検索条件に対して短期キャッシュを共有します。ただし、キャッシュファイルには **Yahoo API のレスポンス由来データだけ** を保存し、`query` や `jan_code` などの入力文字列はディスクへ保存しません。

それでも、公開サーバー利用時は検索語そのものがリクエストとしてサーバーと Yahoo に送られるため、厳密なプライバシー要件がある場合は自前でホストしてください。

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
- `CLOUDFLARE_TUNNEL_TOKEN`
- `ALLOWED_HOSTS`
- `ALLOWED_ORIGINS`

任意の主な設定:

- `YAHOO_SHOPPING_MCP_GLOBAL_RATE_LIMIT`
- `YAHOO_SHOPPING_MCP_GLOBAL_WINDOW_SECONDS`
- `YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS`
- `YAHOO_SHOPPING_MCP_BASE_RATE_SECONDS`
- `YAHOO_SHOPPING_MCP_TOOL_RESPONSE_MODE`

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

## Cloudflare の公開設定

Named Tunnel の `Published application`:

- Hostname: `non-official-yahoo-shopping-mcp.notelligent.app`
- Service URL: `http://app:8000`
- Path: 空欄

`.env.example`:

```env
YAHOO_SHOPPING_APP_ID=replace-with-your-yahoo-app-id
CLOUDFLARE_TUNNEL_TOKEN=replace-with-your-cloudflare-tunnel-token
ALLOWED_HOSTS=localhost:*,127.0.0.1:*,non-official-yahoo-shopping-mcp.notelligent.app
ALLOWED_ORIGINS=http://localhost:18000,http://127.0.0.1:18000,https://non-official-yahoo-shopping-mcp.notelligent.app,https://chatgpt.com,https://chat.openai.com
YAHOO_SHOPPING_MCP_GLOBAL_RATE_LIMIT=60
YAHOO_SHOPPING_MCP_GLOBAL_WINDOW_SECONDS=60
YAHOO_SHOPPING_MCP_TOOL_RESPONSE_MODE=chatgpt
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

## 実運用時の確認項目

- `https://non-official-yahoo-shopping-mcp.notelligent.app/healthz` が `200` を返す
- Cloudflare 側の `Published application` が `http://app:8000` を向いている
- `/mcp` 経由で `search_products` が呼べる
- `usage.global_rate_limit` が返る

## テスト

```bash
make test
```

テストでは Yahoo! への実通信を行いません。`httpx.MockTransport` でダミーレスポンスを返します。

## ライセンス

[MIT](LICENSE)
