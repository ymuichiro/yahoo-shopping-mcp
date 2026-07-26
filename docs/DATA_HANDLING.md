# Data handling

The operator-facing privacy notice is [PRIVACY.md](../PRIVACY.md). This page
records the implementation-specific storage and data-flow details.

## Data flow

1. The MCP client sends the search parameters to this server.
2. The server validates the parameters and applies the safety policy.
3. A valid request is sent to the Yahoo! Shopping Item Search API with the configured Client ID.
4. The server filters and formats the response before returning it to the MCP client.

Search terms are sent to both the MCP server and Yahoo. Do not use this server for secrets, payment data, passwords, government identifiers, or sensitive personal data.

Agentic Memory is a separate opt-in flow. In `single_user` mode, the client
first performs bounded Space, Claim, and neighborhood reads. A proposed change
is normalized and stored as an expiring Preview mutation. Only a matching,
unexpired preview with explicit confirmation can be applied to the active
Neo4j graph. Memory is never inferred and committed automatically from one
`search_products` call.

## Storage

- The cache stores only the safety-filtered Yahoo response payload.
- Cache keys are hashes and do not contain the raw search query or JAN code.
- SQLite stores the global rate-limit window.
- The default cache lifetime is short and configurable with `YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS`.
- The server does not persist full chat history or client authentication data.

The operator of a public deployment is responsible for protecting the data directory and for checking reverse-proxy, container, and platform logs. The default server does not implement authentication or per-user accounts.

## Optional memory storage

Memory is disabled by default and creates no Neo4j records in that mode. A
dedicated single-user deployment can store fixed-ontology `MemorySpace`,
`Claim`, `Concept`, `Context`, `PreferenceRule`, minimized `Evidence` and
`Source`, short-lived `Observation`, and staged `MemoryMutation` records.
Every record is isolated to the server-configured subject and carries revision
and timestamp metadata.

The graph must not contain API keys, passwords, credentials, payment or
financial data, government identifiers, precise addresses, health, political,
religious, or sexual information, unrelated sensitive attributes, full
transcripts, or complete Yahoo product responses. Evidence and Source fields
store only the minimum summary and locator needed for provenance. Memory
bodies must not be written to application logs.

Observation TTL defaults to 86,400 seconds; pending mutation TTL defaults to
3,600 seconds. Both are positive operator settings. Long-term Claims remain
until retired, superseded, or deleted. Bounded export and delete tools provide
subject-wide or narrower control, including source-scoped deletion where
applicable.

Neo4j is the source of truth for preference memory. Existing SQLite state and
the Yahoo response cache are not graph stores. Keep Neo4j credentials secret
and its Bolt and HTTP interfaces private.
