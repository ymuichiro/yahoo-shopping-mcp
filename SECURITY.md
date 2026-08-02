# Security policy

## Scope

This project is an unauthenticated MCP server. Product search is read-only: it
calls the Yahoo! Shopping Item Search API and returns filtered product
information without purchases, orders, account changes, or arbitrary URLs.
Optional single-user Agentic Memory adds bounded graph reads and
preview-confirmed preference-memory writes. Memory is disabled by default.

## Self-hosting guidance

- Keep the default loopback bind for local use.
- If exposing the server publicly, set `YAHOO_SHOPPING_MCP_ALLOWED_HOSTS` and `YAHOO_SHOPPING_MCP_ALLOWED_ORIGINS` to the exact values used by your deployment.
- Keep the Yahoo Client ID in an environment variable; never commit it.
- Protect the data directory and reverse-proxy logs.
- Review the global rate-limit and cache settings before sharing an endpoint.
- Do not put credentials, payment data, or sensitive personal data in search queries.
- Do not enable `single_user` memory on a shared or public endpoint. It uses one
  fixed server-side subject and is not a multi-user security boundary.
- Keep `YAHOO_SHOPPING_MCP_MEMORY_REQUIRE_PREVIEW=true`; configuration rejects
  attempts to disable confirmation.
- Keep Neo4j Bolt and HTTP interfaces private, protect `NEO4J_PASSWORD`, and
  grant the application only the database access it needs.
- Do not log memory bodies, full transcripts, Preview patches, credentials, or
  sensitive evidence.

Cloudflare Tunnel is an optional developer deployment path. Other tunnels, reverse proxies, and cloud platforms are supported as long as they preserve the `/mcp` route and the configured Host/Origin policy.

Memory tools never accept client Cypher, arbitrary labels or relation types,
client-selected subjects, or unbounded graph reads. Fixed ontology validation,
subject isolation, graph-integrity checks, mutation expiry, revision checks,
preview hashes, and explicit confirmation are security boundaries and must not
be bypassed.

## Reporting

Please report suspected vulnerabilities privately through GitHub's private
vulnerability reporting page:

<https://github.com/ymuichiro/yahoo-shopping-mcp/security/advisories/new>

If private reporting is unavailable, contact the repository maintainer through
the repository hosting provider before opening a public issue. Include a
minimal reproduction and avoid posting credentials or personal data.
