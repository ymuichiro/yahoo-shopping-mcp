# Data handling

The operator-facing privacy notice is [PRIVACY.md](../PRIVACY.md). This page
records the implementation-specific storage and data-flow details.

## Data flow

1. The MCP client sends the search parameters to this server.
2. The server validates the parameters and applies the safety policy.
3. A valid request is sent to the Yahoo! Shopping Item Search API with the configured Client ID.
4. The server filters and formats the response before returning it to the MCP client.

Search terms are sent to both the MCP server and Yahoo. Do not use this server for secrets, payment data, passwords, government identifiers, or sensitive personal data.

## Storage

- The cache stores only the safety-filtered Yahoo response payload.
- Cache keys are hashes and do not contain the raw search query or JAN code.
- SQLite stores the global rate-limit window.
- The default cache lifetime is short and configurable with `YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS`.
- The server does not persist full chat history or client authentication data.

The operator of a public deployment is responsible for protecting the data directory and for checking reverse-proxy, container, and platform logs. The default server does not implement authentication or per-user accounts.
