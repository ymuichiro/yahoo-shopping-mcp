# API contract

## MCP endpoint

The server exposes Streamable HTTP at `/mcp` and read-only health routes at `/` and `/healthz`.

## `search_products`

`query` or `jan_code` is required.

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
