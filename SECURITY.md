# Security policy

## Scope

This project is an unauthenticated, read-only MCP server. It calls the Yahoo! Shopping Item Search API and returns filtered product information. It does not execute purchases, orders, account changes, or arbitrary URLs.

## Self-hosting guidance

- Keep the default loopback bind for local use.
- If exposing the server publicly, set `YAHOO_SHOPPING_MCP_ALLOWED_HOSTS` and `YAHOO_SHOPPING_MCP_ALLOWED_ORIGINS` to the exact values used by your deployment.
- Keep the Yahoo Client ID in an environment variable; never commit it.
- Protect the data directory and reverse-proxy logs.
- Review the global rate-limit and cache settings before sharing an endpoint.
- Do not put credentials, payment data, or sensitive personal data in search queries.

Cloudflare Tunnel is an optional developer deployment path. Other tunnels, reverse proxies, and cloud platforms are supported as long as they preserve the `/mcp` route and the configured Host/Origin policy.

## Reporting

Please report suspected vulnerabilities privately through GitHub's private
vulnerability reporting page:

<https://github.com/ymuichiro/yahoo-shopping-mcp/security/advisories/new>

If private reporting is unavailable, contact the repository maintainer through
the repository hosting provider before opening a public issue. Include a
minimal reproduction and avoid posting credentials or personal data.
