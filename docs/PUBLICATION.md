# Publication record / 公開・掲載台帳

This file records where `yahoo-shopping-mcp` has been registered or published.
It is intentionally separate from deployment instructions: a directory listing
does not mean that a shared production endpoint is available.

最終確認日: **2026-08-01**

## Current records

| Destination | Status | Record |
| --- | --- | --- |
| [Official MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.ymuichiro%2Fyahoo-shopping-mcp) | **Active** | Server `io.github.ymuichiro/yahoo-shopping-mcp`, version `0.9.0-preview.2`. Metadata is defined in [`server.json`](../server.json). |
| [GitHub Container Registry](https://github.com/ymuichiro/yahoo-shopping-mcp/pkgs/container/yahoo-shopping-mcp) | **Published** | `ghcr.io/ymuichiro/yahoo-shopping-mcp:v0.9.0-preview.2`. This is a self-hosted distribution artifact, not a shared endpoint. |
| [Glama OSS Server](https://glama.ai/mcp/servers/ymuichiro/yahoo-shopping-mcp) | **Published / publicly listed** | Public server page for [`ymuichiro/yahoo-shopping-mcp`](https://github.com/ymuichiro/yahoo-shopping-mcp). Glama server ID: `l465au1oto`. Ownership metadata is in [`glama.json`](../glama.json). |
| [Glama Managed Release](https://glama.ai/mcp/servers/ymuichiro/yahoo-shopping-mcp/admin/dockerfile/releases#release-0.9.0-preview.3) | **Published / latest** | Release `0.9.0-preview.3`, image `registry.glama.ai/mcp-l465au1oto:nxe0spah8z`. It was created and published on 2026-08-01 from commit `0eeca0eed70aff73c893ae0c4ea3d90af0b188cd`; the successful Build Test is [`019fbb14-4206-70ab-ba81-2270aa13894d`](https://glama.ai/mcp/servers/ymuichiro/yahoo-shopping-mcp/admin/dockerfile/tests/019fbb14-4206-70ab-ba81-2270aa13894d). |
| [MCP.Directory](https://mcp.directory/submit) | **Submitted / pending review** | Submitted with the public GitHub repository URL. Publication is performed after directory review. |

## Evidence of Glama submission

On **2026-07-20**, after submitting the repository through the authenticated
Glama **OSS Server** form, the form reported:

> A submission for this repository is already pending review

This confirms that Glama accepted the repository into its review queue. It is
not approval or public listing: the server search and Glama server API did not
yet expose a public server page at the time of verification. No submission ID
or approval timestamp was provided by Glama.

## Evidence of public listing

On **2026-07-22**, the approval notification was verified against the public
[Glama server page](https://glama.ai/mcp/servers/ymuichiro/yahoo-shopping-mcp).
The page is publicly accessible as **Yahoo! Shopping MCP** by `ymuichiro` and
is linked to this GitHub repository. The public record exposes Glama server ID
`l465au1oto`.

This confirms publication of the OSS listing. A Glama managed release was
created later; this listing and the managed release are recorded separately
because a directory listing alone does not prove a hosted endpoint.

## Glama post-publication follow-up

On **2026-07-25**, the maintainer completed the Glama ownership handoff in a
logged-in Chrome session. The server admin pages became available and the
claim dialog disappeared, confirming that the server is claimed. No Yahoo
credentials were entered into Glama.

The following public metadata was saved in Glama:

- Category: `E-commerce & Retail`
- Existing name and read-only Yahoo! Shopping API description retained
- A related-server suggestion was submitted for `shopping-radar`

On **2026-08-01**, the repository sync completed and Glama reported head
commit `0eeca0e`. The managed build specification used:

- Base image: `debian:trixie-slim`
- Build step: `uv sync`
- CMD arguments: `['uv', 'run', 'yahoo-shopping-mcp-stdio']`
- Effective Glama command: `mcp-proxy -- uv run yahoo-shopping-mcp-stdio`
- Pinned commit: `0eeca0eed70aff73c893ae0c4ea3d90af0b188cd`

The first test with this specification failed because Glama's Docker builder
timed out while resolving `debian:trixie-slim` metadata. A retry succeeded:

- Successful Build Test: [`019fbb14-4206-70ab-ba81-2270aa13894d`](https://glama.ai/mcp/servers/ymuichiro/yahoo-shopping-mcp/admin/dockerfile/tests/019fbb14-4206-70ab-ba81-2270aa13894d)
- Result: `success`
- Observed checks: MCP `initialize`, `tools/list`, `prompts/list`, and
  `resources/list` completed through the stdio process and Glama's proxy.
- Published release: `0.9.0-preview.3`, image
  `registry.glama.ai/mcp-l465au1oto:nxe0spah8z`

No real Yahoo application ID was entered into Glama, so a real Yahoo API
product search was intentionally not performed. The build and MCP protocol
startup checks are confirmed; Gateway endpoint deployment and a production
credential-backed tool call remain separate follow-up work.

## Intentionally not published

- A production remote endpoint is **not** registered. [`server.json`](../server.json)
  intentionally has no `remotes` entry.
- The maintainer-provided demo endpoint remains demonstration-only and is not a
  supported shared service. See [DEPLOYMENT.md](DEPLOYMENT.md).
- The Glama managed release is published, but no separate public Gateway
  endpoint URL or production secret deployment is recorded yet. The release
  image must not be treated as evidence of a credential-backed Yahoo API call.
- No Smithery, PulseMCP, or other marketplace submission has been made as part
  of this record.

## Glama managed transport split

The intended Glama managed transport split is now implemented:

- Self-hosted local/Docker distribution: `yahoo-shopping-mcp` with Streamable HTTP.
- Glama managed build: `yahoo-shopping-mcp-stdio`, configured in Glama as
  `['uv', 'run', 'yahoo-shopping-mcp-stdio']`. Glama's build wrapper turns this
  into the effective `mcp-proxy -- uv run yahoo-shopping-mcp-stdio` command.

The stdio entrypoint is part of the repository and is the command used by the
published Glama managed release. Self-hosted local and Docker deployments
continue to use the Streamable HTTP entrypoint.

## Glama hosted release checklist

For the published Glama managed release, this file records:

1. Glama server page URL, server ID, release version, image, and Build Test ID.
2. The release is published as the latest managed release; no separate
   Gateway deployment visibility has been confirmed.
3. No Gateway endpoint URL is recorded because one has not been configured or
   verified. Never record tokens or secret values.
4. Secret name configured in Glama: `YAHOO_SHOPPING_APP_ID`.
5. Verification date and results for `initialize`, `tools/list`, `prompts/list`,
   and `resources/list`; a real product search remains unverified without a
   production credential.

Do not promote the current unauthenticated demo endpoint in place of the Glama
Gateway. Review [SECURITY.md](../SECURITY.md), [TERMS.md](../TERMS.md), and the
current Yahoo! API terms before changing the publication state.

## Maintenance rule

Whenever a submission is accepted, rejected, or moved to a new version, update
the status, direct URL, version or image tag, and **最終確認日** in this file.
