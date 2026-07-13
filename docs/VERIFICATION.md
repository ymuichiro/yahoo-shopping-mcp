# MCP verification

These checks are environment-independent. They do not require a particular cloud platform or tunnel provider.

For deployment and reverse-proxy requirements, see [DEPLOYMENT.md](DEPLOYMENT.md).

## Local smoke test

```bash
YAHOO_SHOPPING_APP_ID="your-app-id" make run
curl -fsS http://127.0.0.1:8000/healthz
```

The response should be `{"ok":true}`.

## MCP Inspector

Run the server first, then point MCP Inspector at:

```text
http://127.0.0.1:8000/mcp
```

The Inspector can also be started from a shell:

```bash
npx --yes @modelcontextprotocol/inspector --transport http --server-url http://127.0.0.1:8000/mcp
```

For a remote self-hosted endpoint, replace the URL with the endpoint you control. Select Streamable HTTP and use Direct mode when the Inspector offers both Direct and Proxy modes.

Verify:

1. `initialize` succeeds.
2. `tools/list` exposes `search_products` with the documented constraints and annotations.
3. `resources/read` returns `text/html;profile=mcp-app`.
4. The resource contains the Yahoo credit and the UI bridge initialization.
5. A safe search returns JSON in `content[0].text` and carousel data in `structuredContent.products`.
6. A restricted search is rejected without an upstream Yahoo request.
7. Provider errors do not expose the upstream response body.
8. The browser console has no errors and product links are limited to approved Yahoo hosts.

## Automated checks

```bash
make test
```

Tests use `httpx.MockTransport`; they do not call Yahoo in CI.
