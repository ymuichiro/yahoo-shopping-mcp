from __future__ import annotations

import json

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from yahoo_shopping_mcp.config import Settings
from yahoo_shopping_mcp.constants import YAHOO_ITEM_SEARCH_URL
from yahoo_shopping_mcp.server import create_mcp_server


def yahoo_handler(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"totalResultsAvailable": 1, "totalResultsReturned": 0, "firstResultsPosition": 1, "hits": []},
    )


@pytest.mark.anyio
async def test_root_matches_healthz(tmp_path) -> None:
    settings = Settings(
        app_id="test-appid",
        host="127.0.0.1",
        port=8000,
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
    )
    app = create_mcp_server(
        settings,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(yahoo_handler)),
    ).streamable_http_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            root = await client.get("/")
            healthz = await client.get("/healthz")

    assert root.status_code == 200
    assert healthz.status_code == 200
    assert root.json() == {"ok": True}
    assert healthz.json() == root.json()


@pytest.mark.anyio
async def test_removed_routes_return_not_found(tmp_path) -> None:
    settings = Settings(
        app_id="test-appid",
        host="127.0.0.1",
        port=8000,
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
    )
    app = create_mcp_server(
        settings,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(yahoo_handler)),
    ).streamable_http_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            dashboard = await client.get("/dashboard")
            terms = await client.get("/terms")
            privacy = await client.get("/privacy")

    assert dashboard.status_code == 404
    assert terms.status_code == 404
    assert privacy.status_code == 404


@pytest.mark.anyio
async def test_streamable_http_tool_call_is_public(tmp_path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 0, "firstResultsPosition": 1, "hits": []},
        )

    settings = Settings(
        app_id="test-appid",
        host="127.0.0.1",
        port=8000,
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
    )
    app = create_mcp_server(
        settings,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ).streamable_http_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            async with streamable_http_client("http://127.0.0.1:8000/mcp", http_client=client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    result = await session.call_tool("search_products", {"query": "lamp"})

    assert result.isError is False
    content_payload = json.loads(result.content[0].text)
    assert tools.tools[0].outputSchema is not None
    assert tools.tools[0].outputSchema["properties"]["results"]["type"] == "array"
    assert result.structuredContent is not None
    assert result.structuredContent["results"] == content_payload["results"]
    assert content_payload["summary"]["total_results_available"] == 1
    assert content_payload["no_items_reason"] == "upstream_hits_empty"


@pytest.mark.anyio
async def test_streamable_http_allows_configured_cors_origin(tmp_path) -> None:
    settings = Settings(
        app_id="test-appid",
        host="127.0.0.1",
        port=8000,
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        allowed_hosts=["127.0.0.1:*"],
        allowed_origins=["https://chatgpt.com"],
    )
    app = create_mcp_server(
        settings,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(yahoo_handler)),
    ).streamable_http_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            preflight = await client.options(
                "/mcp",
                headers={
                    "Origin": "https://chatgpt.com",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,accept,mcp-session-id",
                },
            )
            initialize = await client.post(
                "/mcp",
                headers={
                    "Origin": "https://chatgpt.com",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "cors-test", "version": "0.0.0"},
                    },
                },
            )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://chatgpt.com"
    assert "POST" in preflight.headers["access-control-allow-methods"]
    assert initialize.status_code == 200
    assert initialize.headers["access-control-allow-origin"] == "https://chatgpt.com"
    assert initialize.headers["access-control-expose-headers"] == "mcp-session-id"


@pytest.mark.anyio
async def test_streamable_http_tool_call_works_with_internal_http_client(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_get = httpx.AsyncClient.get

    async def patched_get(self, url, *args, **kwargs):
        if str(url).startswith(YAHOO_ITEM_SEARCH_URL):
            return httpx.Response(
                200,
                json={
                    "totalResultsAvailable": 1,
                    "totalResultsReturned": 1,
                    "firstResultsPosition": 1,
                    "hits": [{"name": "Desk Lamp", "url": "https://example.com/desk-lamp", "price": 3200}],
                },
            )
        return await original_get(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", patched_get)

    settings = Settings(
        app_id="test-appid",
        host="127.0.0.1",
        port=8000,
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
    )
    app = create_mcp_server(settings).streamable_http_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            async with streamable_http_client("http://127.0.0.1:8000/mcp", http_client=client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    result = await session.call_tool("search_products", {"query": "lamp"})

    assert result.isError is False
    content_payload = json.loads(result.content[0].text)
    assert tools.tools[0].outputSchema is not None
    assert result.structuredContent is not None
    assert result.structuredContent["results"][0]["title"] == "Desk Lamp"
    assert content_payload["results"][0]["title"] == "Desk Lamp"
    assert content_payload["results"][0]["metadata"]["price"] == 3200


@pytest.mark.anyio
async def test_global_rate_limit_blocks_second_request(tmp_path) -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return yahoo_handler(_request)

    settings = Settings(
        app_id="test-appid",
        host="127.0.0.1",
        port=8000,
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        global_rate_limit=1,
        global_window_seconds=60,
    )
    app = create_mcp_server(
        settings,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ).streamable_http_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            async with streamable_http_client("http://127.0.0.1:8000/mcp", http_client=client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    first = await session.call_tool("search_products", {"query": "lamp"})
                    second = await session.call_tool("search_products", {"query": "chair"})

    assert first.isError is False
    assert second.isError is True
    assert "global rate limit exceeded" in second.content[0].text.lower()
    assert calls["count"] == 1
