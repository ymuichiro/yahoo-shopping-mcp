# Deployment

This project is self-hosted. Choose an infrastructure and domain that you
control; no maintainer-hosted endpoint is part of the supported deployment.

## Direct process

Install the dependencies and run the Streamable HTTP server:

```bash
make sync
YAHOO_SHOPPING_APP_ID="your-app-id" make run HOST=0.0.0.0 PORT=8000
```

Use a process supervisor and a reverse proxy for a long-running deployment.
Keep the application port private and expose only the proxy. The proxy must
forward `/mcp`, preserve the HTTP method and streaming response, and expose
`/healthz` for health checks.

## Docker Compose

```bash
make init-env
make up
```

The default Compose mapping binds the application to loopback at
`127.0.0.1:18000`. Put a reverse proxy or tunnel in front of that local
endpoint if it must be reachable from another network. Do not commit `.env`.

## GitHub Container Registry preview image

Pushes of version tags (`v*`) publish a container image to GitHub Container
Registry. The image tag matches the Git tag, for example:

```bash
docker pull ghcr.io/ymuichiro/yahoo-shopping-mcp:v0.9.0-preview.1
```

The workflow also supports manually rebuilding an existing tag when the
workflow was added after that tag was created. Treat preview images as
pre-release artifacts and verify the source tag, configuration, Yahoo
requirements, and deployment environment before using them.

## Host and Origin policy

For direct startup, configure the exact values used by the deployment:

```env
YAHOO_SHOPPING_MCP_ALLOWED_HOSTS=mcp.example.com
YAHOO_SHOPPING_MCP_ALLOWED_ORIGINS=https://mcp.example.com
```

For Compose, set the equivalent convenience variables:

```env
ALLOWED_HOSTS=mcp.example.com
ALLOWED_ORIGINS=https://mcp.example.com
```

Do not use a wildcard unless it is an intentional, reviewed deployment
choice. These settings are host/origin protections, not user authentication.
The server does not implement MCP login, OAuth, JWT, or per-user accounts.

## Optional Cloudflare Tunnel

The optional `cloudflared` Compose profile uses a token and a tunnel configured
outside this repository:

```bash
make up-tunnel
```

Set `CLOUDFLARE_TUNNEL_TOKEN` only for this profile. Configure the published
hostname and service in Cloudflare, then put that exact hostname in
`ALLOWED_HOSTS` and its HTTPS origin in `ALLOWED_ORIGINS`. A tunnel URL shared
by a maintainer for testing may be offline or removed and is not a production
service or SLA.

The maintainer's sample deployment, when online, is:

- MCP: <https://non-official-yahoo-shopping-mcp.notelligent.app/mcp>
- Health: <https://non-official-yahoo-shopping-mcp.notelligent.app/healthz>

It is a demonstration endpoint only and may be offline, changed, or removed.
It is not a supported production service. Use your own hostname and
infrastructure for any real deployment.

## Operational checklist

- Use your own Yahoo Client ID and verify the current Yahoo terms, quotas, and
  attribution requirements.
- Keep the MCP endpoint behind a network or proxy policy appropriate to the
  users of the deployment; it has no built-in authentication.
- Review global and Yahoo request-rate settings before sharing the endpoint.
- Protect `/data`, cache files, database state, and proxy/container logs.
- Publish deployment-specific privacy, retention, support, and incident
  contact information.
- Check `GET /healthz`, MCP `initialize`, `tools/list`, and a safe
  `search_products` call after every deployment.

For protocol and UI verification, see [VERIFICATION.md](VERIFICATION.md).
