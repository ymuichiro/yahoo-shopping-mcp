# Contributing

## Development

```bash
make sync-dev
uv run pytest -q
```

Tests must use `httpx.MockTransport` and must not send requests to Yahoo. Keep MCP response compatibility tests in `tests/test_http_routes.py` when changing tool metadata, output structure, or the UI Resource.

When changing the UI Resource, update its versioned URI and test the Inspector workflow described in [MCP verification](docs/VERIFICATION.md).

## Scope

Keep the server read-only and limited to Yahoo! Shopping product search. Do not add authentication screens, user accounts, arbitrary proxying, scraping, or unrelated routes.
