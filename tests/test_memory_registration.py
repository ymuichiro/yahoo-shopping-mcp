from __future__ import annotations

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from yahoo_shopping_mcp.config import Settings
from yahoo_shopping_mcp.server import create_mcp_server


class RepositoryInitializationGuard:
    def __init__(self) -> None:
        self.initialize_calls = 0

    async def initialize(self) -> None:
        self.initialize_calls += 1
        raise AssertionError("disabled memory must not initialize a repository")

    async def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_disabled_mode_registers_no_memory_surface_or_repository(tmp_path) -> None:
    repository = RepositoryInitializationGuard()
    settings = Settings(
        app_id="test-appid",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
    )
    upstream_transport = httpx.MockTransport(lambda _request: httpx.Response(500))
    async with httpx.AsyncClient(transport=upstream_transport) as http_client:
        app = create_mcp_server(
            settings,
            http_client=http_client,
            memory_repository=repository,
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
                        resources = await session.list_resources()

    assert repository.initialize_calls == 0
    assert [tool.name for tool in tools.tools] == ["search_products"]
    assert all(not str(resource.uri).startswith("memory://") for resource in resources.resources)
