# Privacy notice

This repository is a self-hosted open-source MCP server. It does not provide a
central hosted service, and the repository maintainer does not receive requests
from installations that users run themselves.

## Data categories and purposes

- The MCP client sends only the explicit search fields supplied to
  `search_products`, such as a keyword, JAN code, price range, or filter IDs.
- The server uses those fields to validate the request, apply the safety policy,
  query Yahoo! Shopping, and return relevant product information.
- The server stores safety-filtered Yahoo response data in a short-lived local
  cache and stores global rate-limit counters in a local SQLite file.
- Agentic Memory is disabled by default. A dedicated operator can explicitly
  enable single-user memory to store concise, typed purchasing preferences,
  intentions, contexts, evidence summaries, sources, and revision history in
  Neo4j for the operator-configured fixed subject.
- The server does not request chat history, precise location, payment data,
  government identifiers, passwords, or authentication codes.
- Memory rejects full transcripts, credentials, payment or financial data,
  government identifiers, precise addresses, health, political, religious, or
  sexual information, and unrelated sensitive attributes.

## Recipients

The explicit search request is sent to the operator's MCP server and to the
Yahoo! Shopping Item Search API using the operator's configured Client ID.
Product results are returned to the MCP client. The application does not send
the data to an additional analytics or advertising service.

When single-user memory is enabled, the configured Neo4j service is also a
recipient and processor of the typed memory records. It must be operated or
selected by the same self-hosting operator and must not be exposed directly to
MCP clients.

## Retention

The default cache lifetime is 300 seconds and can be changed with
`YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS`. Cache files and rate-limit state remain
until their configured lifecycle or until the operator deletes the data
directory. Reverse-proxy, container, and platform logs are controlled by the
operator and may have separate retention rules.

Memory observations expire after 86,400 seconds by default, and unapplied
preview mutations expire after 3,600 seconds by default. Operators may choose
shorter or longer positive TTLs. Confirmed Claims and their minimized evidence
remain until retired, superseded, or deleted by the fixed subject's operator or
user. The application does not retain full conversation transcripts.

## User and operator controls

Users should not send secrets or sensitive personal data as search terms. An
operator can keep the server bound to loopback, reduce cache lifetime, protect
the data directory, configure log retention, and delete the local state and
cache. Public deployments must publish their own contact and retention details
that match the actual infrastructure.

Single-user memory provides bounded export and delete operations, including
source-scoped deletion and node retirement. Operators must protect Neo4j
credentials, keep Bolt/HTTP interfaces private, avoid logging memory bodies,
and provide a way for the fixed subject to request export or deletion. Because
the MCP server has no authentication, memory must not be enabled on a shared or
public endpoint.

This notice describes the default application behavior. It does not replace
the privacy notice required by a particular operator, jurisdiction, hosting
provider, or third-party API agreement.
