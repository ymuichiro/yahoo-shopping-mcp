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
docker pull ghcr.io/ymuichiro/yahoo-shopping-mcp:v0.9.0-preview.2
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

## Optional single-user memory

Memory defaults to `disabled`, which requires no Neo4j service and preserves
the existing product-search deployment. Enable `single_user` only for one
trusted subject on a dedicated, access-controlled instance:

```env
YAHOO_SHOPPING_MCP_MEMORY_MODE=single_user
YAHOO_SHOPPING_MCP_MEMORY_SUBJECT_ID=local-default
YAHOO_SHOPPING_MCP_MEMORY_REQUIRE_PREVIEW=true
YAHOO_SHOPPING_MCP_MEMORY_OBSERVATION_TTL_SECONDS=86400
YAHOO_SHOPPING_MCP_MEMORY_MUTATION_TTL_SECONDS=3600
YAHOO_SHOPPING_MCP_MEMORY_MAX_SPACES_PER_QUERY=5
YAHOO_SHOPPING_MCP_MEMORY_MAX_CLAIM_CANDIDATES=30
YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_NODES=100
YAHOO_SHOPPING_MCP_MEMORY_MAX_SUBGRAPH_EDGES=250
YAHOO_SHOPPING_MCP_MEMORY_MAX_DEPTH=3
NEO4J_URI=neo4j://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=replace-with-secret
NEO4J_DATABASE=neo4j
```

All TTL and query-bound settings must be positive. The hard safety ceilings are
50 spaces, 100 claim candidates, 100 subgraph nodes, 250 subgraph edges, and
depth 3.
`YAHOO_SHOPPING_MCP_MEMORY_REQUIRE_PREVIEW` must remain `true`; startup
configuration fails when single-user identity or Neo4j credentials are
missing. The subject ID is fixed by the server and must not come from MCP tool
arguments.

Operate Neo4j on a private network. Do not expose Bolt `7687` or Neo4j HTTP
`7474` to MCP clients or the public internet. Store credentials in the
deployment platform's secret facility, use persistent encrypted storage and
backups appropriate to the data, set resource limits and health probes, and
test export/deletion and restoration procedures. The repository's default
Compose stack does not provision Neo4j or enable memory.

This implementation does not add a production or local-k3s deployment. Any
future cluster rollout requires a separate review of authentication, network
policy, Secrets, persistence, backup, retention, and subject isolation.

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
- If memory is enabled, keep the instance single-user and private; protect
  Neo4j credentials and storage, verify Preview/Apply confirmation, and test
  bounded export and deletion.
- Publish deployment-specific privacy, retention, support, and incident
  contact information.
- Check `GET /healthz`, MCP `initialize`, `tools/list`, and a safe
  `search_products` call after every deployment.

For protocol and UI verification, see [VERIFICATION.md](VERIFICATION.md).
