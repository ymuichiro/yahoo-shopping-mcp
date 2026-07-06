from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
import json
import logging
import time
from typing import Annotated

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from yahoo_shopping_mcp.config import Settings, load_settings
from yahoo_shopping_mcp.models import SearchProductsInput, SearchProductsResponse
from yahoo_shopping_mcp.storage import CacheStore, SQLiteStateStore, StoredRateLimitExceededError, ensure_dir
from yahoo_shopping_mcp.yahoo_api import YahooShoppingClient, YahooShoppingError


def _tool_error_json(*, kind: str, message: str, retryable: bool, http_status: int | None = None, provider_code: str | None = None, details: dict | None = None) -> str:
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

def create_mcp_server(
    settings: Settings | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> FastMCP:
    resolved_settings = settings or load_settings()
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    structured_output_enabled = resolved_settings.tool_response_mode != "chatgpt"
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
        ensure_dir(resolved_settings.state_dir)
        ensure_dir(resolved_settings.cache_dir)
        request_http_client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        try:
            state_store = SQLiteStateStore(resolved_settings.state_dir)
            yield {
                "settings": resolved_settings,
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

    @mcp.tool(structured_output=structured_output_enabled)
    async def search_products(
        query: str | None = None,
        jan_code: str | int | None = None,
        price_from: int | None = None,
        price_to: int | None = None,
        in_stock: bool | None = None,
        condition: str | None = None,
        shipping: str | None = None,
        sort: str | None = None,
        results: int = 20,
        start: int = 1,
    ) -> Annotated[CallToolResult, SearchProductsResponse]:
        """Search Yahoo! Shopping products with global rate limiting, retry, caching, and attribution metadata."""

        try:
            lifespan_context = mcp.get_context().request_context.lifespan_context
            state_store: SQLiteStateStore = lifespan_context["state_store"]
            rate_limit = state_store.consume_global_rate_limit(
                key="global",
                limit=resolved_settings.global_rate_limit,
                window_seconds=resolved_settings.global_window_seconds,
                now=int(time.time()),
            )
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
            result = CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "results": content_payload["results"],
                                "display_summary": content_payload["display_summary"],
                                "items": content_payload["items"],
                                "no_items_reason": content_payload["no_items_reason"],
                                "summary": content_payload["summary"],
                                "debug": content_payload["debug"],
                                "attribution": content_payload["attribution"],
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                ],
                structuredContent=content_payload,
            )
            if resolved_settings.tool_response_mode == "chatgpt":
                return CallToolResult(content=result.content)
            return result
        except ValidationError as exc:
            first_error = exc.errors()[0]
            raise ToolError(_tool_error_json(kind="validation_error", message=first_error["msg"], retryable=False, details={"errors": exc.errors()})) from exc
        except StoredRateLimitExceededError as exc:
            raise ToolError(
                _tool_error_json(
                    kind="global_rate_limited",
                    message=f"Global rate limit exceeded. Retry after {exc.retry_after} seconds.",
                    retryable=True,
                    http_status=429,
                )
            ) from exc
        except YahooShoppingError as exc:
            raise ToolError(json.dumps(asdict(exc), ensure_ascii=False)) from exc

    return mcp


def main() -> None:
    create_mcp_server().run(transport="streamable-http")


if __name__ == "__main__":
    main()
