# Review test cases

These cases are written so a reviewer can reproduce the tool contract without
internal implementation knowledge. Automated tests use Yahoo API fixtures and
never call Yahoo from CI.

## Positive cases

| # | User request | Expected behavior | Expected result |
|---|---|---|---|
| 1 | Search for `desk lamp`. | Call `search_products` with `query`. | `content[0].text` is JSON whose first field is `results`; each result has `id`, `title`, `url`, `text`, and `metadata`. |
| 2 | Search by JAN `4900000000000`. | Call `search_products` with `jan_code` as a string. | The request succeeds without losing leading zeroes and returns the normal result contract. |
| 3 | Search `lamp` with `results=10`, `sort=-price`, and a category ID. | Validate and forward only the documented filters. | The request succeeds; `structuredContent.products` contains the carousel view model and `outputSchema` remains `{products}`. |
| 4 | Search for a term with no matches. | Complete the read-only search normally. | The request succeeds with an empty `results` array and a non-secret `no_items_reason`. |
| 5 | Search for a normal product while opening the MCP Apps UI. | Read the versioned UI Resource and render the returned products. | The Resource is `text/html;profile=mcp-app`, uses the `ui/*` bridge, limits image CSP to Yahoo's image host, and displays the Yahoo attribution. |

## Negative cases

| # | User request or scenario | Expected safe behavior | Why it must not complete normally |
|---|---|---|---|
| 1 | Search for a prohibited product category, such as a firearm or illegal drug. | Return a generic `policy_restricted` error and make no Yahoo request. | The app must not facilitate prohibited or high-risk goods. |
| 2 | Send an invalid condition, an overlong query, a non-digit JAN, or more than 50 results. | Reject the request with validation feedback and do not call Yahoo. | The public schema and runtime must enforce bounded, documented inputs. |
| 3 | Yahoo returns an error body containing secrets or user-specific text. | Return the status, retryability, and safe provider code only; omit the body and message. | Provider payloads, credentials, and internal diagnostics must not leak through MCP responses. |
