from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import time
from typing import Annotated, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from yahoo_shopping_mcp.config import Settings, load_settings
from yahoo_shopping_mcp.models import ProductCarouselResponse, SearchProductsInput, SearchProductsResponse
from yahoo_shopping_mcp.product_carousel import PRODUCT_CAROUSEL_HTML, PRODUCT_UI_META, PRODUCT_UI_URI
from yahoo_shopping_mcp.storage import CacheStore, SQLiteStateStore, StoredRateLimitExceededError
from yahoo_shopping_mcp.yahoo_api import YahooShoppingClient, YahooShoppingError, is_restricted_query


def _tool_error(
    kind: str,
    message: str,
    *,
    retryable: bool,
    http_status: int | None,
    provider_code: str | None,
    details: dict[str, object],
) -> ToolError:
    return ToolError(
        json.dumps(
            {
                "kind": kind,
                "message": message,
                "retryable": retryable,
                "http_status": http_status,
                "provider_code": provider_code,
                "details": details,
            },
            ensure_ascii=False,
        )
    )


def create_mcp_server(
    settings: Settings | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> FastMCP:
    resolved_settings = settings or load_settings()
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    transport_security = (
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=resolved_settings.allowed_hosts or [],
            allowed_origins=resolved_settings.allowed_origins or [],
        )
        if resolved_settings.allowed_hosts or resolved_settings.allowed_origins
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastMCP):
        resolved_settings.state_dir.mkdir(parents=True, exist_ok=True)
        resolved_settings.cache_dir.mkdir(parents=True, exist_ok=True)
        request_http_client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        try:
            state_store = SQLiteStateStore(resolved_settings.state_dir)
            yield {
                "http_client": request_http_client,
                "state_store": state_store,
                "cache_store": CacheStore(resolved_settings.cache_dir, resolved_settings.cache_ttl_seconds),
            }
        finally:
            if http_client is None:
                await request_http_client.aclose()

    mcp = FastMCP(
        "Yahoo Shopping MCP",
        json_response=True,
        host=resolved_settings.host,
        port=resolved_settings.port,
        streamable_http_path="/mcp",
        lifespan=lifespan,
        transport_security=transport_security,
    )

    if resolved_settings.allowed_origins:
        original_streamable_http_app = mcp.streamable_http_app

        def streamable_http_app():
            app = original_streamable_http_app()
            from starlette.middleware.cors import CORSMiddleware

            app.add_middleware(
                CORSMiddleware,
                allow_origins=resolved_settings.allowed_origins or [],
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=["mcp-session-id"],
            )
            return app

        mcp.streamable_http_app = streamable_http_app  # type: ignore[assignment]

    @mcp.custom_route("/", methods=["GET"])
    async def root(_request: Request):
        return JSONResponse({"ok": True})

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request):
        return JSONResponse({"ok": True})

    @mcp.resource(
        PRODUCT_UI_URI,
        name="yahoo-product-carousel",
        title="Yahoo!ショッピング商品カルーセル",
        mime_type="text/html;profile=mcp-app",
        meta=PRODUCT_UI_META,
    )
    def product_carousel() -> str:
        return PRODUCT_CAROUSEL_HTML

    @mcp.tool(
        title="Yahoo!ショッピング商品検索",
        description=(
            "読み取り専用でYahoo!ショッピングの商品を検索します。購入、注文、アカウント変更は行いません。"
            "queryまたはjan_codeのいずれかを指定してください。"
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
        meta={
            "ui": {"resourceUri": PRODUCT_UI_URI, "visibility": ["model"]},
            "openai/toolInvocation/invoking": "Yahoo!ショッピングを検索しています…",
            "openai/toolInvocation/invoked": "商品を表示しました。",
        },
        structured_output=True,
    )
    async def search_products(
        query: Annotated[str | None, Field(min_length=1, max_length=200, description="商品名やキーワード")] = None,
        jan_code: Annotated[str | None, Field(min_length=8, max_length=13, pattern=r"^\d+$", description="JANコード")]
        = None,
        price_from: Annotated[int | None, Field(ge=0, description="価格下限（円）")] = None,
        price_to: Annotated[int | None, Field(ge=0, description="価格上限（円）")] = None,
        in_stock: Annotated[bool | None, Field(description="在庫ありに限定するか")] = None,
        condition: Annotated[Literal["new", "used"] | None, Field(description="新品または中古")] = None,
        shipping: Annotated[
            Literal["free", "conditional_free", "free,conditional_free"] | None,
            Field(description="送料条件"),
        ] = None,
        sort: Annotated[Literal["-score", "+price", "-price", "-review_count"] | None, Field(description="並び順")]
        = None,
        genre_category_ids: Annotated[
            list[int] | None, Field(min_length=1, max_length=20, description="YahooジャンルカテゴリID")
        ] = None,
        brand_ids: Annotated[list[int] | None, Field(min_length=1, max_length=20, description="YahooブランドID")]
        = None,
        seller_id: Annotated[str | None, Field(min_length=1, max_length=100, description="YahooストアID")] = None,
        image_size: Annotated[Literal[76, 106, 132, 146, 300, 600] | None, Field(description="画像サイズ")]
        = None,
        is_discounted: Annotated[bool | None, Field(description="セール対象に限定するか")] = None,
        results: Annotated[int, Field(ge=1, le=50, description="返却件数")] = 20,
        start: Annotated[int, Field(ge=1, description="取得開始位置")] = 1,
    ) -> Annotated[CallToolResult, ProductCarouselResponse]:
        """Search Yahoo! Shopping products with global rate limiting, retry, caching, and attribution metadata."""

        try:
            payload = SearchProductsInput(
                query=query,
                jan_code=jan_code,
                price_from=price_from,
                price_to=price_to,
                in_stock=in_stock,
                condition=condition,
                shipping=shipping,
                sort=sort,
                genre_category_ids=genre_category_ids,
                brand_ids=brand_ids,
                seller_id=seller_id,
                image_size=image_size,
                is_discounted=is_discounted,
                results=results,
                start=start,
            )
            if is_restricted_query(payload.query):
                raise _tool_error(
                    "policy_restricted",
                    "This search request is not supported.",
                    retryable=False,
                    http_status=None,
                    provider_code=None,
                    details={},
                )
            lifespan_context = mcp.get_context().request_context.lifespan_context
            state_store: SQLiteStateStore = lifespan_context["state_store"]
            rate_limit = state_store.consume_global_rate_limit(
                key="global",
                limit=resolved_settings.global_rate_limit,
                window_seconds=resolved_settings.global_window_seconds,
                now=int(time.time()),
            )
            client = YahooShoppingClient(
                app_id=resolved_settings.app_id,
                http_client=lifespan_context["http_client"],
                min_interval_seconds=resolved_settings.base_rate_seconds,
                state_store=state_store,
                cache_store=lifespan_context["cache_store"],
                warning_threshold=resolved_settings.warning_threshold,
                hard_limit=resolved_settings.hard_limit,
            )
            response_payload = await client.search(payload)
            response_payload["usage"]["global_rate_limit"] = rate_limit.model_dump()
            validated = SearchProductsResponse.model_validate(response_payload)
            content_payload = validated.model_dump(mode="json")
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "results": content_payload["results"],
                                "display_summary": content_payload["display_summary"],
                                "no_items_reason": content_payload["no_items_reason"],
                                "summary": content_payload["summary"],
                                "attribution": content_payload["attribution"],
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                ],
                structuredContent={"products": content_payload["products"]},
            )
        except ValidationError as exc:
            first_error = exc.errors()[0]
            raise _tool_error(
                "validation_error",
                first_error["msg"],
                retryable=False,
                http_status=None,
                provider_code=None,
                details={
                    "field": ".".join(str(part) for part in first_error.get("loc", ())) or None,
                    "error_type": first_error.get("type"),
                },
            ) from exc
        except StoredRateLimitExceededError as exc:
            raise _tool_error(
                "global_rate_limited",
                f"Global rate limit exceeded. Retry after {exc.retry_after} seconds.",
                retryable=True,
                http_status=429,
                provider_code=None,
                details={},
            ) from exc
        except YahooShoppingError as exc:
            raise _tool_error(
                exc.kind,
                exc.message,
                retryable=exc.retryable,
                http_status=exc.http_status,
                provider_code=exc.provider_code,
                details=exc.details or {},
            ) from exc

    return mcp


def main() -> None:
    create_mcp_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
