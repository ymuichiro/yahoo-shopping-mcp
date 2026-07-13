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
- The server does not request chat history, precise location, payment data,
  government identifiers, passwords, or authentication codes.

## Recipients

The explicit search request is sent to the operator's MCP server and to the
Yahoo! Shopping Item Search API using the operator's configured Client ID.
Product results are returned to the MCP client. The application does not send
the data to an additional analytics or advertising service.

## Retention

The default cache lifetime is 300 seconds and can be changed with
`YAHOO_SHOPPING_MCP_CACHE_TTL_SECONDS`. Cache files and rate-limit state remain
until their configured lifecycle or until the operator deletes the data
directory. Reverse-proxy, container, and platform logs are controlled by the
operator and may have separate retention rules.

## User and operator controls

Users should not send secrets or sensitive personal data as search terms. An
operator can keep the server bound to loopback, reduce cache lifetime, protect
the data directory, configure log retention, and delete the local state and
cache. Public deployments must publish their own contact and retention details
that match the actual infrastructure.

This notice describes the default application behavior. It does not replace
the privacy notice required by a particular operator, jurisdiction, hosting
provider, or third-party API agreement.
