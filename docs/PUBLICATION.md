# Publication record / 公開・掲載台帳

This file records where `yahoo-shopping-mcp` has been registered or published.
It is intentionally separate from deployment instructions: a directory listing
does not mean that a shared production endpoint is available.

最終確認日: **2026-07-25**

## Current records

| Destination | Status | Record |
| --- | --- | --- |
| [Official MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.ymuichiro%2Fyahoo-shopping-mcp) | **Active** | Server `io.github.ymuichiro/yahoo-shopping-mcp`, version `0.9.0-preview.2`. Metadata is defined in [`server.json`](../server.json). |
| [GitHub Container Registry](https://github.com/ymuichiro/yahoo-shopping-mcp/pkgs/container/yahoo-shopping-mcp) | **Published** | `ghcr.io/ymuichiro/yahoo-shopping-mcp:v0.9.0-preview.2`. This is a self-hosted distribution artifact, not a shared endpoint. |
| [Glama OSS Server](https://glama.ai/mcp/servers/ymuichiro/yahoo-shopping-mcp) | **Published / publicly listed** | Public server page for [`ymuichiro/yahoo-shopping-mcp`](https://github.com/ymuichiro/yahoo-shopping-mcp). Glama server ID: `l465au1oto`. Ownership metadata is in [`glama.json`](../glama.json). At the latest check, the listing had no Glama release yet, so it is a directory listing rather than a Glama-hosted endpoint. |
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

This confirms publication of the OSS listing. It does not confirm a Glama
release, a hosted remote endpoint, or successful Yahoo API execution from
Glama. The page currently reports no Glama release and does not offer an
installable hosted server.

## Glama post-publication follow-up

On **2026-07-25**, the maintainer completed the Glama ownership handoff in a
logged-in Chrome session. The server admin pages became available and the
claim dialog disappeared, confirming that the server is claimed. No Yahoo
credentials were entered into Glama.

The following public metadata was saved in Glama:

- Category: `E-commerce & Retail`
- Existing name and read-only Yahoo! Shopping API description retained
- A related-server suggestion was submitted for `shopping-radar`

The following Glama verification work is still asynchronous and is recorded
here as pending rather than successful:

- Repository sync was started, but the admin page still showed `Sync in
  Progress`, last synced `2026-07-24 19:44`, and last commit `06f4b3c` at the
  latest check. The local repository head is `cc2e9b1`.
- This follow-up record was committed afterward as `aa250b7`; a later
  successful Glama sync is needed to include that commit in the directory
  snapshot.
- A Docker build test was submitted with ID
  `019f977d-0f1a-7e65-bee0-c9c197f3579f` and remained `pending` at the latest
  check.
- The build specification used Debian Trixie, Python 3.12,
  `uv sync --frozen --no-dev`, and
  `.venv/bin/yahoo-shopping-mcp` behind `mcp-proxy`. The required
  `YAHOO_SHOPPING_APP_ID` was declared as a sensitive environment variable;
  only the non-secret placeholder `glama-check-placeholder` was supplied for
  startup verification.

Until the sync and build test complete, Glama still reports no Glama release;
Server Coherence and Tool Definition Quality therefore remain unavailable.
The no-recent-usage indicator also remains expected until a usable Glama
release is available and a safe test call can be made.

## Intentionally not published

- A production remote endpoint is **not** registered. [`server.json`](../server.json)
  intentionally has no `remotes` entry.
- The maintainer-provided demo endpoint remains demonstration-only and is not a
  supported shared service. See [DEPLOYMENT.md](DEPLOYMENT.md).
- Glama Gateway or another Glama-hosted release has not been deployed yet. The
  OSS listing is public, but the intended next order is private deployment,
  Secret configuration, authenticated MCP verification, and only then a
  limited-access release.
- No Smithery, PulseMCP, or other marketplace submission has been made as part
  of this record.

## Glama hosted release checklist

If a Glama-hosted release is intentionally created later, record the following
in this file:

1. Glama server page URL, server ID, and deployment identifier.
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
