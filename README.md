# Yahoo! Shopping MCP

An open-source, community-maintained MCP server for the Yahoo! Shopping Item
Search API v3. It provides read-only product search through Streamable HTTP and
can be run locally or self-hosted with Docker.

This is not an official Yahoo! Shopping, LINE Yahoo, or OpenAI service. The
maintainers do not represent, endorse, operate, or guarantee Yahoo! Shopping,
the Yahoo! Developer Network, or OpenAI.

## Project status and hosted endpoints

This project is intended for self-hosting. It does not provide a guaranteed
shared or production-hosted endpoint.

If a Cloudflare Tunnel URL is shared separately by a maintainer for testing,
that URL is a temporary verification endpoint. It may be stopped, restarted,
changed, or unavailable at any time; it has no uptime, SLA, support, privacy,
or data-retention guarantee. Do not use it for production or confidential
workloads. Run this server on infrastructure you control instead.

A maintainer-operated sample deployment may be available at:

- MCP endpoint: <https://non-official-yahoo-shopping-mcp.notelligent.app/mcp>
- Health check: <https://non-official-yahoo-shopping-mcp.notelligent.app/healthz>
- Root health check: <https://non-official-yahoo-shopping-mcp.notelligent.app/>

These URLs are provided for demonstration and connectivity checks only. They
are not an official Yahoo! or OpenAI service and are not guaranteed to be
online, stable, supported, private, or available to any particular user.

This is a community implementation. Before using it, independently review the
current Yahoo! Developer Network and Yahoo! Shopping API terms, quotas,
attribution requirements, content restrictions, and any rules applicable to
your jurisdiction and deployment. The maintainers do not guarantee that the
implementation or its usage complies with a third-party policy.

## Demo

The short demo below shows a Yahoo! Shopping search from ChatGPT and the
resulting MCP Apps product carousel.

![Yahoo! Shopping MCP demo](assets/demo.gif)

The GIF is used for inline playback because GitHub does not reliably embed
repository-local MP4 files in rendered Markdown. The higher-quality MP4 is
available at [assets/demo.mp4](assets/demo.mp4).

## Features

- Read-only `search_products` tool for Yahoo! Shopping product search
- Keyword, JAN code, price, stock, condition, shipping, sorting, category,
  brand, seller, image-size, and pagination filters
- A same-process interval between Yahoo request starts (1 second by default)
- Exponential backoff for Yahoo HTTP 429 responses and a bounded 5xx retry
- Short-lived cache of safety-filtered Yahoo response data
- SQLite-backed application-wide rate limiting
- MCP Apps product carousel with Yahoo attribution
- Conservative filtering of restricted product terms and non-Yahoo URLs
- `GET /`, `GET /healthz`, and Streamable HTTP MCP at `/mcp`

The rate limiter is an application safeguard, not a Yahoo quota guarantee or an
SLA. It applies within one process; separate replicas need their own controls.

## Protocol and endpoints

The server uses the MCP Streamable HTTP transport:

- MCP endpoint: `/mcp`
- Health endpoint: `GET /healthz`
- Root health endpoint: `GET /`
- MCP authentication: none

The server is bound to loopback by default. An unauthenticated endpoint is not
automatically an internet-public endpoint; if you expose it, add network,
reverse-proxy, rate-limit, logging, and data-retention controls appropriate to
your deployment.

## Local plugin package

The repository includes metadata for local use:

- `.codex-plugin/plugin.json`: local plugin metadata, prompts, and logo
- `.mcp.json`: local MCP client configuration
- `assets/logo.svg`: product-search icon

These files do not provide a store listing or a shared hosted service. Start
your own server and configure your own Yahoo Client ID before using them.

## Quick start

Requirements: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and a Yahoo!
Shopping API `appid` obtained by the operator.

```bash
make sync-dev
YAHOO_SHOPPING_APP_ID="your-app-id" make run
```

The local MCP endpoint is `http://127.0.0.1:8000/mcp` and the health check is
`http://127.0.0.1:8000/healthz`.

To bind a different interface or port for a controlled deployment:

```bash
YAHOO_SHOPPING_APP_ID="your-app-id" make run HOST=0.0.0.0 PORT=8080
```

Keep the Yahoo Client ID in an environment variable. Never commit it or place
it in a search query.

## Docker and self-hosting

Create the local environment template and start the container:

```bash
make init-env
make up
```

The default local Compose endpoint is
`http://127.0.0.1:18000/mcp`. See [Deployment](docs/DEPLOYMENT.md) for a
production-oriented container and reverse-proxy checklist.

For direct application startup, use the `YAHOO_SHOPPING_MCP_*` environment
variables. Compose maps its convenience variables `ALLOWED_HOSTS` and
`ALLOWED_ORIGINS` to the application settings.

## Optional Cloudflare Tunnel

Cloudflare Tunnel is an optional developer deployment path, not a requirement.
It is only enabled by:

```bash
make up-tunnel
```

Set `CLOUDFLARE_TUNNEL_TOKEN` only when using that Compose profile. The tunnel
hostname and published application are configured in Cloudflare, outside this
repository. Replace the local values in `.env` with the exact external
hostname and origin used by your deployment:

```env
YAHOO_SHOPPING_APP_ID=replace-with-your-yahoo-app-id
CLOUDFLARE_TUNNEL_TOKEN=replace-with-your-cloudflare-tunnel-token
ALLOWED_HOSTS=mcp.example.com
ALLOWED_ORIGINS=https://mcp.example.com
```

The tunnel does not add MCP authentication. Do not treat a tunnel URL shared
by the maintainer as a supported hosted service; use a hostname and
infrastructure that you control.

## Using the tool

Use the endpoint you started from ChatGPT Developer Mode or another MCP
client. No MCP authentication header is expected.

`search_products` requires at least one of `query` and `jan_code`. Important
constraints include:

- `query`: 1–200 characters
- `jan_code`: an 8–13 digit string
- `genre_category_ids` and `brand_ids`: arrays of 1–20 positive integers
- `results`: 1–50
- `start`: 1 or greater
- `start + results <= 1000`
- `price_from <= price_to` when both are supplied

See the complete contract in [docs/API.md](docs/API.md).

Example:

```json
{
  "query": "desk lamp",
  "in_stock": true,
  "sort": "-score",
  "results": 10,
  "start": 1
}
```

The tool returns model-readable JSON in `content[0].text`, with product data
under `results`. Carousel data is returned in `structuredContent.products`.
The UI Resource is versioned as
`ui://yahoo-shopping/product-carousel-v4.html` and displays Yahoo attribution.

The server does not place orders, process payments, modify accounts, or
guarantee product availability, prices, sellers, shipping, or legal compliance.

## Privacy and safety

Search fields are sent to the operator's MCP server and to Yahoo! Shopping.
The server stores only safety-filtered Yahoo response data in a short-lived
cache and global rate-limit state in local storage. It does not provide user
accounts or persist full chat history.

Do not send secrets, payment data, passwords, government identifiers, or
sensitive personal data as search terms. Public operators must publish privacy,
support, and retention details that match their actual infrastructure.

The safety filter is conservative and does not guarantee complete product
classification. It is not a substitute for Yahoo's policies, legal advice, or
operator review.

See [PRIVACY.md](PRIVACY.md), [TERMS.md](TERMS.md),
[SECURITY.md](SECURITY.md), and [docs/DATA_HANDLING.md](docs/DATA_HANDLING.md).

## Yahoo! Developer Network references

The following official pages define the external requirements that apply to the
operator's own Yahoo! application. They are not part of this repository's
license or a substitute for reading the current versions:

- [Yahoo! Developer Network guidelines](https://developer.yahoo.co.jp/guideline/)
- [Yahoo! Shopping API portal](https://developer.yahoo.co.jp/webapi/shopping/)
- [Yahoo! Shopping product search v3](https://developer.yahoo.co.jp/webapi/shopping/v3/itemsearch.html)
- [Credit and attribution rules](https://developer.yahoo.co.jp/attribution/)
- [Usage limits](https://developer.yahoo.co.jp/appendix/rate.html)
- [Developer guide and Client ID registration](https://developer.yahoo.co.jp/start/)

Each operator must obtain and protect their own Client ID and independently
confirm the applicable terms, usage limits, attribution, and legal requirements
before operating this server.

## Development and verification

```bash
make test
```

Tests use `httpx.MockTransport` and do not call Yahoo! from CI. For MCP
Inspector and UI checks, see [docs/VERIFICATION.md](docs/VERIFICATION.md).
Reviewable positive and negative cases are in
[docs/SUBMISSION_TEST_CASES.md](docs/SUBMISSION_TEST_CASES.md).

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before
opening a change. For support, use [SUPPORT.md](SUPPORT.md); report security
issues using the private process in [SECURITY.md](SECURITY.md).

## Japanese documentation

日本語の概要・導入手順は [docs/README.ja.md](docs/README.ja.md) を参照してください。

## License

[MIT](LICENSE)
