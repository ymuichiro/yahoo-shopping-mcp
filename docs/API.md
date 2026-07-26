# API contract

## MCP endpoint

The server exposes Streamable HTTP at `/mcp` and read-only health routes at `/` and `/healthz`.

## `search_products`

`query` or `jan_code` is required. When both `price_from` and `price_to` are
provided, `price_from <= price_to` is required. The result window must satisfy
`start + results <= 1000`. The first condition is represented in the public
JSON Schema with `allOf`/`anyOf`; the numeric comparisons are enforced during
runtime validation and documented in the schema description because standard
JSON Schema cannot compare or add two instance values.

| Field | Type | Constraint |
|---|---|---|
| `query` | string | 1–200 characters |
| `jan_code` | string | 8–13 digits |
| `price_from`, `price_to` | integer | 0 or greater |
| `in_stock`, `is_discounted` | boolean | optional |
| `condition` | string | `new` or `used` |
| `shipping` | string | `free`, `conditional_free`, or both |
| `sort` | string | `-score`, `+price`, `-price`, or `-review_count` |
| `genre_category_ids` | integer array | 1–20 positive IDs |
| `brand_ids` | integer array | 1–20 positive IDs |
| `seller_id` | string | 1–100 characters |
| `image_size` | integer | `76`, `106`, `132`, `146`, `300`, or `600` |
| `results` | integer | 1–50; `start + results <= 1000` |
| `start` | integer | 1 or greater |

The tool only searches products. It does not purchase items, place orders, or modify accounts.

## Result contract

- `content[0].text` contains the model-readable JSON payload whose primary field is `results`.
- `structuredContent.products` contains the carousel view model.
- `outputSchema` describes the carousel view model.
- The response does not expose the internal normalized `items` list.
- Product URLs and image URLs are limited to approved Yahoo domains.
- Diagnostic data, upstream response bodies, credentials, and request identifiers are not returned.

Searches and products that match the safety policy are rejected or filtered before they are returned.

## Optional Agentic Memory

Memory mode defaults to `disabled`. Disabled mode registers no memory tools or
resources and leaves the `search_products` contract above unchanged. The only
enabled mode is `single_user`, which uses the operator-configured
`YAHOO_SHOPPING_MCP_MEMORY_SUBJECT_ID`; callers cannot choose a subject.
`multi_user` is not supported.

Single-user mode exposes these resources:

- `memory://yahoo-shopping/schema/v1`: fixed ontology, enums, relation
  domain/range, and constraints
- `memory://yahoo-shopping/instructions/v1`: staged read and
  preview/confirmation/apply workflow
- `memory://yahoo-shopping/profile/current/summary`: bounded current-profile
  summary, not a full graph dump

It exposes the following bounded MCP tools:

| Tool | Effect |
|---|---|
| `get_preference_memory_schema` | Read the fixed ontology |
| `route_memory_spaces` | Find relevant Memory Spaces |
| `search_claim_candidates` | Find existing Claim, Rule, or Context candidates |
| `get_claim_neighborhood` | Read a bounded local graph with a snapshot |
| `get_preference_graph` | Read an explicitly bounded partial graph |
| `preview_preference_memory_update` | Validate and stage a mutation without changing the active graph |
| `apply_preference_memory_update` | Apply a non-expired preview after explicit confirmation |
| `export_preference_memory` | Export the fixed subject's memory |
| `delete_preference_memory` | Delete or retire an explicitly selected scope |

Tool schemas expose the fixed node, relation, kind, operation, and status
enums. Inputs do not accept Cypher, arbitrary labels or relations, a subject
ID, server-generated IDs for new nodes, or unbounded graph reads.

All mutations follow Route → Search → Neighborhood → Preview → confirmation →
Apply. Preview performs domain/range, self-loop, cycle, duplicate, conflicting
rule, evidence/source, subject-isolation, revision/snapshot, limit, and privacy
checks. Apply requires `confirmation=true`, a matching preview hash, an
unexpired mutation, and the current profile revision. Preview never changes
the active graph, returns a bounded text-free SVG summary for supporting hosts,
and repeated Apply calls are idempotent.

Memory errors use stable `memory_*` kinds, including validation, schema,
relation, domain/range, cycle, duplicate, ambiguous target, revision,
snapshot, expiry, preview hash, confirmation, limit, not-found, and privacy
errors. Error payloads are bounded and do not expose credentials, Cypher,
database internals, full evidence text, or transcripts.

The memory read path does not automatically rewrite `search_products`
arguments. Product searches do not automatically create long-term Claims.
