# AGENTS.md

## Project Summary

このリポジトリは Yahoo!ショッピング 商品検索 API v3 を安全にラップする MCP サーバーです。
主な責務は次の 3 つです。

- MCP ツール `search_products` の提供
- Yahoo API 呼び出しのレート制御、キャッシュ、日次利用量監視
- アプリケーション全体に対するグローバルレート制限

サーバー本体は `FastMCP` を使っており、`Streamable HTTP` で公開します。公開 HTTP ルートは `/`, `/healthz`, `/mcp` のみです。`/` は `/healthz` と同じヘルス応答を返します。

## Common Commands

- 初回セットアップ: `make sync-dev`
- 起動: `YAHOO_SHOPPING_APP_ID=... make run`
- コンテナ起動: `make init-env && make up`
- Named Tunnel 起動: `make up-tunnel`
- コンテナ停止: `make down`
- テスト: `make test`
- 依存だけ同期: `make sync`
- ローカル状態を掃除: `make clean`

デフォルトのホストとポートは `127.0.0.1:8000` です。変更したい場合は `make run HOST=0.0.0.0 PORT=8080` のように上書きします。

## Environment Variables

必須:

- `YAHOO_SHOPPING_APP_ID`

主要な任意設定:

- `YAHOO_SHOPPING_MCP_HOST`
- `YAHOO_SHOPPING_MCP_PORT`
- `YAHOO_SHOPPING_MCP_DATA_DIR`
- `YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS`
- `YAHOO_SHOPPING_MCP_BASE_RATE_SECONDS`
- `YAHOO_SHOPPING_MCP_WARNING_THRESHOLD`
- `YAHOO_SHOPPING_MCP_HARD_LIMIT`
- `YAHOO_SHOPPING_MCP_GLOBAL_RATE_LIMIT`
- `YAHOO_SHOPPING_MCP_GLOBAL_WINDOW_SECONDS`
- `YAHOO_SHOPPING_MCP_ALLOWED_HOSTS`
- `YAHOO_SHOPPING_MCP_ALLOWED_ORIGINS`
- `CLOUDFLARE_TUNNEL_TOKEN`

## Project Structure

- `src/yahoo_shopping_mcp/server.py`
  MCP サーバー生成、lifespan 管理、HTTP ルート、ツール定義
- `src/yahoo_shopping_mcp/yahoo_api.py`
  Yahoo API 呼び出し、直列レート制御、リトライ、レスポンス整形
- `src/yahoo_shopping_mcp/global_rate_limiter.py`
  アプリケーション全体のグローバルレート制限
- `src/yahoo_shopping_mcp/storage.py`
  JSON 永続化、原子的書き込み、日次利用量、キャッシュ
- `src/yahoo_shopping_mcp/models.py`
  入出力モデル、永続化モデル
- `tests/test_http_routes.py`
  HTTP ルートと公開 MCP 呼び出しの統合テスト
- `tests/test_yahoo_api.py`
  Yahoo ラッパーのテスト
- `Dockerfile`
  本番用コンテナイメージ
- `compose.yaml`
  ローカル公開と Named Tunnel を含む compose 構成
- `.env.example`
  Compose 用の環境変数テンプレート

## Development Guidelines

- Yahoo への実リクエストをテストで送らないこと。テストは `httpx.MockTransport` でダミーレスポンスを返す。
- レート制限を変える場合は、成功系だけでなく拒否系も追加でテストする。
- `search_products` の入力契約を変える場合は、`models.py`、README、テストを同時に更新する。
- `search_products` の返却では、商品データを MCP tool result の `content[0].text` に JSON として含めること。ChatGPT では `structuredContent` / `outputSchema` だけに置いた商品データが会話本文として認識されず、metadata だけが露出することがある。
- `content[0].text` の JSON は、先頭キー `results` に `id`, `title`, `url`, `text`, `metadata` を持つ商品リストを置く。`metadata` には少なくとも `price`, `price_text`, `seller_name`, `image_url`, `badges` を含める。
- `YAHOO_SHOPPING_MCP_TOOL_RESPONSE_MODE=chatgpt` は ChatGPT 向けの安全側設定として扱うこと。これを `structured` に戻すと、ChatGPT 側で検索結果本文を拾えず再発する可能性があるため、理由なく切り替えないこと。
- `structured_output` / `structuredContent` を触ったら、`outputSchema` が OFF になっていることと、`content[0].text` の `results` が実際に返ることをライブ環境で確認してから完了にすること。
- `debug` は返してよいが、商品情報の代替にしないこと。LLM/host が検索結果として読む主データは `results` とする。
- 日次利用量、Yahoo 向け直列レート制御、アプリ全体のグローバルレート制限は別物として扱う。目的を混同しない。
- このプロジェクトは認証を使わない。認証やユーザー単位制御、UI 画面を再導入しないこと。
- 過剰なフォールバックや用途不明の抽象化を追加しないこと。公開面は `MCP + healthz` に限定する。

## Testing Policy

- テスト実行は `uv run pytest`
- 外部 API は必ずスタブ化する
- 最低限カバーしたい観点:
  - 入力バリデーション
  - Yahoo API エラー処理
  - 429 / 5xx リトライ
  - キャッシュ
  - 日次利用量監視
  - グローバルレート制限
  - `GET /` と `GET /healthz`
  - 削除済みルートの `404`
  - MCP ツールの公開アクセス
  - MCP tool result の `content[0].text` に `results[0].title`, `results[0].metadata.price`, `results[0].metadata.seller_name` が含まれること

## Notes For Agents

- リポジトリに formatter や linter はまだ入っていません。追加する場合は `pyproject.toml` と `Makefile` を合わせて更新してください。
- `FastMCP` を使っているため、一般的な FastAPI 専用パターンをそのまま持ち込まないでください。HTTP ルートは `custom_route`、MCP ツールは `@mcp.tool` です。
- Cloudflare 配信時は `YAHOO_SHOPPING_MCP_ALLOWED_HOSTS` を tunnel 用ホスト名に合わせて更新してください。
