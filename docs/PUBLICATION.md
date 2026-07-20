# Publication record / 公開・掲載台帳

This file records where `yahoo-shopping-mcp` has been registered or published.
It is intentionally separate from deployment instructions: a directory listing
does not mean that a shared production endpoint is available.

最終確認日: **2026-07-20**

## Current records

| Destination | Status | Record |
| --- | --- | --- |
| [Official MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.ymuichiro%2Fyahoo-shopping-mcp) | **Active** | Server `io.github.ymuichiro/yahoo-shopping-mcp`, version `0.9.0-preview.2`. Metadata is defined in [`server.json`](../server.json). |
| [GitHub Container Registry](https://github.com/ymuichiro/yahoo-shopping-mcp/pkgs/container/yahoo-shopping-mcp) | **Published** | `ghcr.io/ymuichiro/yahoo-shopping-mcp:v0.9.0-preview.2`. This is a self-hosted distribution artifact, not a shared endpoint. |
| [Glama OSS Server](https://glama.ai/mcp/servers?query=yahoo-shopping-mcp) | **Pending review** | Source submission: [`ymuichiro/yahoo-shopping-mcp`](https://github.com/ymuichiro/yahoo-shopping-mcp). Ownership metadata is in [`glama.json`](../glama.json). The repository submission is pending review and is not publicly listed yet. |
| [MCP.Directory](https://mcp.directory/submit) | **Submitted / pending review** | Submitted with the public GitHub repository URL. Publication is performed after directory review. |

## Evidence of Glama submission

On **2026-07-20**, after submitting the repository through the authenticated
Glama **OSS Server** form, the form reported:

> A submission for this repository is already pending review

This confirms that Glama accepted the repository into its review queue. It is
not approval or public listing: the server search and Glama server API did not
yet expose a public server page at the time of verification. No submission ID
or approval timestamp was provided by Glama.

## Intentionally not published

- A production remote endpoint is **not** registered. [`server.json`](../server.json)
  intentionally has no `remotes` entry.
- The maintainer-provided demo endpoint remains demonstration-only and is not a
  supported shared service. See [DEPLOYMENT.md](DEPLOYMENT.md).
- Glama Gateway hosting has not been deployed yet. After Glama approves the OSS
  listing, the intended order is private deployment, Secret configuration,
  authenticated MCP verification, and only then a limited-access release.
- No Smithery, PulseMCP, or other marketplace submission has been made as part
  of this record.

## Glama Gateway checklist

When the Glama listing becomes available, record the following in this file:

1. Glama server page URL and deployment identifier.
2. Whether the deployment is private or public.
3. The generated Gateway endpoint URL. Never record tokens or secret values.
4. Secret name configured in Glama: `YAHOO_SHOPPING_APP_ID`.
5. Verification date for `initialize`, `tools/list`, and a safe product search.

Do not promote the current unauthenticated demo endpoint in place of the Glama
Gateway. Review [SECURITY.md](../SECURITY.md), [TERMS.md](../TERMS.md), and the
current Yahoo! API terms before changing the publication state.

## Maintenance rule

Whenever a submission is accepted, rejected, or moved to a new version, update
the status, direct URL, version or image tag, and **最終確認日** in this file.
