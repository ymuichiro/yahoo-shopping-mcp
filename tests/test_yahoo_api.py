from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import time
from pathlib import Path

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from yahoo_shopping_mcp.config import Settings
from yahoo_shopping_mcp.constants import GLOBAL_RATE_LIMIT_FILENAME, STATE_DB_FILENAME, USAGE_FILENAME
from yahoo_shopping_mcp.errors import YahooShoppingError
from yahoo_shopping_mcp.global_rate_limiter import GlobalRateLimitError, GlobalRateLimiter
from yahoo_shopping_mcp.models import SearchProductsInput
from yahoo_shopping_mcp.rate_limiter import SerialRateLimiter
from yahoo_shopping_mcp.server import create_mcp_server
from yahoo_shopping_mcp.storage import CacheStore, UsageStore
from yahoo_shopping_mcp.yahoo_api import YahooShoppingClient


def build_client(
    tmp_path: Path,
    handler,
    *,
    warning_threshold: int = 45_000,
    hard_limit: int = 50_000,
    rate_seconds: float = 1.0,
) -> YahooShoppingClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return YahooShoppingClient(
        app_id="test-appid",
        http_client=http_client,
        rate_limiter=SerialRateLimiter(rate_seconds),
        usage_store=UsageStore(tmp_path / "state"),
        cache_store=CacheStore(tmp_path / "cache", ttl_seconds=300),
        warning_threshold=warning_threshold,
        hard_limit=hard_limit,
    )


def _process_context():
    for method in ("forkserver", "spawn", "fork"):
        if method in mp.get_all_start_methods():
            return mp.get_context(method)
    pytest.skip("A multiprocessing start method is required for concurrency tests.")


def _usage_increment_worker(state_dir: str, barrier, queue) -> None:
    store = UsageStore(Path(state_dir))
    barrier.wait()
    queue.put(store.increment().count)


def _global_rate_limit_worker(state_dir: str, limit: int, window_seconds: int, barrier, queue) -> None:
    limiter = GlobalRateLimiter(Path(state_dir), limit=limit, window_seconds=window_seconds)
    barrier.wait()
    try:
        limiter.consume()
    except GlobalRateLimitError:
        queue.put(False)
    else:
        queue.put(True)


@pytest.mark.anyio
async def test_maps_request_parameters(tmp_path: Path) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 1, "firstResultsPosition": 1, "hits": []},
        )

    client = build_client(tmp_path, handler)
    payload = SearchProductsInput(query="nike", price_from=1000, price_to=2000, results=10, start=11)

    try:
        await client.search(payload)
    finally:
        await client._http_client.aclose()

    assert captured["params"]["appid"] == "test-appid"
    assert captured["params"]["query"] == "nike"
    assert captured["params"]["price_from"] == "1000"
    assert captured["params"]["price_to"] == "2000"
    assert captured["params"]["results"] == "10"
    assert captured["params"]["start"] == "11"


@pytest.mark.anyio
async def test_retries_429_then_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr("yahoo_shopping_mcp.yahoo_api.random.uniform", lambda _a, _b: 0.0)

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(429, json={"message": "Too Many Requests"})
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 1, "firstResultsPosition": 1, "hits": []},
        )

    client = build_client(tmp_path, handler)
    try:
        result = await client.search(SearchProductsInput(query="nikon"))
    finally:
        await client._http_client.aclose()

    assert result["summary"]["total_results_available"] == 1
    assert calls["count"] == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.anyio
async def test_daily_limit_warning(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 0, "firstResultsPosition": 1, "hits": []},
        )

    usage_store = UsageStore(tmp_path / "state")
    usage_store.save(usage_store.load().model_copy(update={"count": 44_999}))
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = YahooShoppingClient(
        app_id="test-appid",
        http_client=http_client,
        rate_limiter=SerialRateLimiter(0.0),
        usage_store=usage_store,
        cache_store=CacheStore(tmp_path / "cache", ttl_seconds=300),
        warning_threshold=45_000,
        hard_limit=50_000,
    )

    try:
        result = await client.search(SearchProductsInput(query="sony"))
    finally:
        await http_client.aclose()

    assert result["usage"]["count"] == 45_000
    assert result["warnings"][0]["kind"] == "daily_limit_warning"


@pytest.mark.anyio
async def test_daily_limit_stop(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    usage_store = UsageStore(tmp_path / "state")
    usage_store.save(usage_store.load().model_copy(update={"count": 50_000}))
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = YahooShoppingClient(
        app_id="test-appid",
        http_client=http_client,
        rate_limiter=SerialRateLimiter(0.0),
        usage_store=usage_store,
        cache_store=CacheStore(tmp_path / "cache", ttl_seconds=300),
        warning_threshold=45_000,
        hard_limit=50_000,
    )

    try:
        with pytest.raises(YahooShoppingError) as exc_info:
            await client.search(SearchProductsInput(query="sony"))
    finally:
        await http_client.aclose()

    assert exc_info.value.kind == "daily_limit_exceeded"


@pytest.mark.anyio
async def test_cache_hit_skips_upstream_and_marks_usage(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "totalResultsAvailable": 1,
                "totalResultsReturned": 1,
                "firstResultsPosition": 1,
                "hits": [{"name": "A", "url": "https://example.com", "price": 100}],
            },
        )

    client = build_client(tmp_path, handler, rate_seconds=0.0)
    payload = SearchProductsInput(query="ipad")

    try:
        first = await client.search(payload)
        second = await client.search(payload)
    finally:
        await client._http_client.aclose()

    assert calls["count"] == 1
    assert first["usage"]["from_cache"] is False
    assert second["usage"]["from_cache"] is True
    assert second["usage"]["count"] == 1


@pytest.mark.anyio
async def test_cache_persists_only_yahoo_response_payload(tmp_path: Path) -> None:
    secret_query = "private@example.com"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "totalResultsAvailable": 1,
                "totalResultsReturned": 1,
                "firstResultsPosition": 1,
                "hits": [{"name": "A", "url": "https://example.com", "price": 100}],
            },
        )

    client = build_client(tmp_path, handler, rate_seconds=0.0)
    try:
        result = await client.search(SearchProductsInput(query=secret_query))
    finally:
        await client._http_client.aclose()

    cache_files = list((tmp_path / "cache").glob("*.json"))
    assert len(cache_files) == 1
    cache_text = cache_files[0].read_text(encoding="utf-8")
    cache_payload = json.loads(cache_text)["payload"]

    assert result["applied_filters"]["query"] == secret_query
    assert secret_query not in cache_text
    assert "applied_filters" not in cache_text
    assert '"usage"' not in cache_text
    assert cache_payload["totalResultsAvailable"] == 1


@pytest.mark.anyio
async def test_cache_expiry_triggers_refetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 1, "firstResultsPosition": 1, "hits": []},
        )

    client = YahooShoppingClient(
        app_id="test-appid",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        rate_limiter=SerialRateLimiter(0.0),
        usage_store=UsageStore(tmp_path / "state"),
        cache_store=CacheStore(tmp_path / "cache", ttl_seconds=1),
        warning_threshold=45_000,
        hard_limit=50_000,
    )
    payload = SearchProductsInput(query="macbook")

    try:
        await client.search(payload)
        monkeypatch.setattr(time, "time", lambda: 9_999_999_999.0)
        await client.search(payload)
    finally:
        await client._http_client.aclose()

    assert calls["count"] == 2


@pytest.mark.anyio
async def test_rate_limiter_serializes_parallel_calls(tmp_path: Path) -> None:
    call_times: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        call_times.append(time.monotonic())
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 1, "firstResultsPosition": 1, "hits": []},
        )

    client = build_client(tmp_path, handler, rate_seconds=0.05)

    try:
        await asyncio.gather(
            client.search(SearchProductsInput(query="a")),
            client.search(SearchProductsInput(query="b")),
        )
    finally:
        await client._http_client.aclose()

    assert len(call_times) == 2
    assert call_times[1] - call_times[0] >= 0.045


@pytest.mark.anyio
async def test_parallel_identical_queries_share_single_upstream_call(tmp_path: Path) -> None:
    calls = {"count": 0}

    async def fake_get(_url, *, params):
        calls["count"] += 1
        await asyncio.sleep(0.05)
        return httpx.Response(
            200,
            json={
                "totalResultsAvailable": 1,
                "totalResultsReturned": 1,
                "firstResultsPosition": 1,
                "hits": [{"name": params["query"], "url": "https://example.com", "price": 100}],
            },
        )

    http_client = httpx.AsyncClient()
    http_client.get = fake_get  # type: ignore[method-assign]
    client = YahooShoppingClient(
        app_id="test-appid",
        http_client=http_client,
        rate_limiter=SerialRateLimiter(0.0),
        usage_store=UsageStore(tmp_path / "state"),
        cache_store=CacheStore(tmp_path / "cache", ttl_seconds=300),
        warning_threshold=45_000,
        hard_limit=50_000,
    )

    try:
        payload = SearchProductsInput(query="ipad")
        first, second = await asyncio.gather(client.search(payload), client.search(payload))
    finally:
        await http_client.aclose()

    assert calls["count"] == 1
    assert UsageStore(tmp_path / "state").load().count == 1
    assert sorted([first["usage"]["from_cache"], second["usage"]["from_cache"]]) == [False, True]


@pytest.mark.anyio
async def test_parallel_calls_respect_daily_limit(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 1, "firstResultsPosition": 1, "hits": []},
        )

    usage_store = UsageStore(tmp_path / "state")
    usage_store.save(usage_store.load().model_copy(update={"count": 49_999}))
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = YahooShoppingClient(
        app_id="test-appid",
        http_client=http_client,
        rate_limiter=SerialRateLimiter(0.0),
        usage_store=usage_store,
        cache_store=CacheStore(tmp_path / "cache", ttl_seconds=300),
        warning_threshold=45_000,
        hard_limit=50_000,
    )

    try:
        first, second = await asyncio.gather(
            client.search(SearchProductsInput(query="a")),
            client.search(SearchProductsInput(query="b")),
            return_exceptions=True,
        )
    finally:
        await http_client.aclose()

    assert calls["count"] == 1
    assert sum(isinstance(result, YahooShoppingError) for result in (first, second)) == 1
    assert sum(isinstance(result, dict) for result in (first, second)) == 1
    assert UsageStore(tmp_path / "state").load().count == 50_000


def test_usage_store_migrates_legacy_json_and_preserves_parallel_increments(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    (state_dir / USAGE_FILENAME).write_text(
        json.dumps({"date": UsageStore.current_jst_date(), "count": 3}),
        encoding="utf-8",
    )

    assert UsageStore(state_dir).load().count == 3
    assert (state_dir / STATE_DB_FILENAME).exists()

    ctx = _process_context()
    worker_count = 10
    barrier = ctx.Barrier(worker_count)
    queue = ctx.Queue()
    workers = [
        ctx.Process(target=_usage_increment_worker, args=(str(state_dir), barrier, queue))
        for _ in range(worker_count)
    ]
    for worker in workers:
        worker.start()
    values = [queue.get(timeout=10) for _ in workers]
    for worker in workers:
        worker.join(timeout=10)
        assert worker.exitcode == 0

    assert sorted(values) == list(range(4, 14))
    assert UsageStore(state_dir).load().count == 13


def test_global_rate_limiter_migrates_legacy_json_and_enforces_limit_under_concurrency(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    (state_dir / GLOBAL_RATE_LIMIT_FILENAME).write_text(
        json.dumps({"counters": {"global": {"window_started_at": int(time.time()), "count": 0}}}),
        encoding="utf-8",
    )

    assert (state_dir / STATE_DB_FILENAME).exists() is False
    limiter = GlobalRateLimiter(state_dir, limit=5, window_seconds=60)
    assert (state_dir / STATE_DB_FILENAME).exists() is True
    assert limiter.consume().remaining == 4

    ctx = _process_context()
    worker_count = 10
    barrier = ctx.Barrier(worker_count)
    queue = ctx.Queue()
    workers = [
        ctx.Process(target=_global_rate_limit_worker, args=(str(state_dir), 5, 60, barrier, queue))
        for _ in range(worker_count)
    ]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=10) for _ in workers]
    for worker in workers:
        worker.join(timeout=10)
        assert worker.exitcode == 0

    assert results.count(True) == 4
    assert results.count(False) == 6
    with pytest.raises(GlobalRateLimitError):
        limiter.consume()


@pytest.mark.anyio
async def test_streamable_http_tool_call_returns_structured_payload(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "totalResultsAvailable": 1,
                "totalResultsReturned": 1,
                "firstResultsPosition": 1,
                "hits": [
                    {
                        "name": "Desk Lamp",
                        "url": "https://example.com/desk-lamp",
                        "price": 3200,
                        "inStock": True,
                        "condition": "new",
                        "image": {"small": "https://example.com/s.jpg", "medium": "https://example.com/m.jpg"},
                        "review": {"rate": 4.5, "count": 12, "url": "https://example.com/review"},
                        "seller": {"name": "Store", "url": "https://example.com/store", "isBestSeller": True},
                        "description": "compact lamp",
                    }
                ],
            },
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
                    result = await session.call_tool("search_products", {"query": "lamp"})

    structured = result.structuredContent
    assert structured["summary"]["total_results_available"] == 1
    assert structured["items"][0]["name"] == "Desk Lamp"
    assert structured["attribution"]["required_display"] is True
    assert structured["usage"]["global_rate_limit"]["limit"] == settings.global_rate_limit
