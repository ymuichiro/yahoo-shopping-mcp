from __future__ import annotations

from contextlib import asynccontextmanager
import json
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from yahoo_shopping_mcp.config import Settings, load_settings
from yahoo_shopping_mcp.errors import YahooShoppingError
from yahoo_shopping_mcp.global_rate_limiter import GlobalRateLimitError, GlobalRateLimiter
from yahoo_shopping_mcp.models import SearchProductsInput, SearchProductsResponse
from yahoo_shopping_mcp.rate_limiter import SerialRateLimiter
from yahoo_shopping_mcp.storage import CacheStore, UsageStore, ensure_dir
from yahoo_shopping_mcp.yahoo_api import RequestCoalescer, YahooShoppingClient


def _error_payload(
    *,
    kind: str,
    message: str,
    retryable: bool,
    http_status: int | None = None,
    provider_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    return json.dumps(
        {
            "kind": kind,
            "message": message,
            "retryable": retryable,
            "http_status": http_status,
            "provider_code": provider_code,
            "details": details or {},
        },
        ensure_ascii=False,
    )


def _build_client(mcp: FastMCP) -> YahooShoppingClient:
    context = mcp.get_context()
    settings: Settings = context.request_context.lifespan_context["settings"]
    http_client: httpx.AsyncClient = context.request_context.lifespan_context["http_client"]
    rate_limiter: SerialRateLimiter = context.request_context.lifespan_context["rate_limiter"]
    usage_store: UsageStore = context.request_context.lifespan_context["usage_store"]
    cache_store: CacheStore = context.request_context.lifespan_context["cache_store"]
    request_coalescer: RequestCoalescer = context.request_context.lifespan_context["request_coalescer"]
    return YahooShoppingClient(
        app_id=settings.app_id,
        http_client=http_client,
        rate_limiter=rate_limiter,
        usage_store=usage_store,
        cache_store=cache_store,
        warning_threshold=settings.warning_threshold,
        hard_limit=settings.hard_limit,
        request_coalescer=request_coalescer,
    )


def _build_transport_security(settings: Settings) -> TransportSecuritySettings | None:
    if not settings.allowed_hosts and not settings.allowed_origins:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.allowed_hosts or [],
        allowed_origins=settings.allowed_origins or [],
    )


def _build_product_result_text(payload: dict[str, Any]) -> str:
    model_visible_payload = {
        "results": payload.get("results") or [],
        "display_summary": payload.get("display_summary"),
        "no_items_reason": payload.get("no_items_reason"),
        "summary": payload.get("summary"),
        "debug": payload.get("debug"),
        "attribution": payload.get("attribution"),
    }
    return json.dumps(model_visible_payload, ensure_ascii=False, indent=2)


def _build_tool_result(payload: dict[str, Any]) -> CallToolResult:
    validated = SearchProductsResponse.model_validate(payload)
    content_payload = validated.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=_build_product_result_text(content_payload))],
    )


class YahooShoppingMCP(FastMCP):
    def __init__(self, *args: Any, cors_allowed_origins: list[str] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cors_allowed_origins = cors_allowed_origins or []

    def streamable_http_app(self):
        app = super().streamable_http_app()
        if not self._cors_allowed_origins:
            return app

        from starlette.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=self._cors_allowed_origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["mcp-session-id"],
        )
        return app


def create_mcp_server(
    settings: Settings | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> FastMCP:
    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(_: FastMCP):
        ensure_dir(resolved_settings.state_dir)
        ensure_dir(resolved_settings.cache_dir)
        request_http_client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        try:
            global_rate_limiter = GlobalRateLimiter(
                resolved_settings.state_dir,
                limit=resolved_settings.global_rate_limit,
                window_seconds=resolved_settings.global_window_seconds,
            )
            yield {
                "settings": resolved_settings,
                "http_client": request_http_client,
                "rate_limiter": SerialRateLimiter(resolved_settings.base_rate_seconds),
                "usage_store": UsageStore(resolved_settings.state_dir),
                "cache_store": CacheStore(resolved_settings.cache_dir, resolved_settings.cache_ttl_seconds),
                "request_coalescer": RequestCoalescer(),
                "global_rate_limiter": global_rate_limiter,
            }
        finally:
            if http_client is None:
                await request_http_client.aclose()

    mcp = YahooShoppingMCP(
        "Yahoo Shopping MCP",
        json_response=True,
        host=resolved_settings.host,
        port=resolved_settings.port,
        streamable_http_path="/mcp",
        lifespan=lifespan,
        transport_security=_build_transport_security(resolved_settings),
        cors_allowed_origins=resolved_settings.allowed_origins,
    )

    @mcp.custom_route("/", methods=["GET"])
    async def root(_request: Request):
        return JSONResponse({"ok": True})

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request):
        return JSONResponse({"ok": True})

    @mcp.tool(structured_output=False)
    async def search_products(
        query: str | None = None,
        jan_code: str | None = None,
        price_from: int | None = None,
        price_to: int | None = None,
        in_stock: bool | None = None,
        condition: str | None = None,
        shipping: str | None = None,
        sort: str | None = None,
        results: int = 20,
        start: int = 1,
    ) -> CallToolResult:
        """Search Yahoo! Shopping products with global rate limiting, retry, caching, and attribution metadata."""

        try:
            global_rate_limiter: GlobalRateLimiter = mcp.get_context().request_context.lifespan_context[
                "global_rate_limiter"
            ]
            rate_limit = global_rate_limiter.consume()
            payload = SearchProductsInput(
                query=query,
                jan_code=jan_code,
                price_from=price_from,
                price_to=price_to,
                in_stock=in_stock,
                condition=condition,
                shipping=shipping,
                sort=sort,
                results=results,
                start=start,
            )
            response_payload = await _build_client(mcp).search(payload)
            response_payload["usage"]["global_rate_limit"] = rate_limit.model_dump()
            return _build_tool_result(response_payload)
        except ValidationError as exc:
            first_error = exc.errors()[0]
            raise ToolError(
                _error_payload(
                    kind="validation_error",
                    message=first_error["msg"],
                    retryable=False,
                    details={"errors": exc.errors()},
                )
            ) from exc
        except GlobalRateLimitError as exc:
            raise ToolError(
                _error_payload(
                    kind="global_rate_limited",
                    message=str(exc),
                    retryable=True,
                    http_status=429,
                )
            ) from exc
        except YahooShoppingError as exc:
            raise ToolError(_error_payload(**exc.to_response())) from exc

    return mcp


def main() -> None:
    create_mcp_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
