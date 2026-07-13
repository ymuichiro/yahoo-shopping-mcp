from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import sqlite3
import time
from pathlib import Path

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from yahoo_shopping_mcp.config import Settings
from yahoo_shopping_mcp.constants import YAHOO_ITEM_SEARCH_URL
from yahoo_shopping_mcp.models import SearchProductsInput
from yahoo_shopping_mcp.server import create_mcp_server
from yahoo_shopping_mcp.storage import CacheStore, SQLiteStateStore, StoredRateLimitExceededError
from yahoo_shopping_mcp.yahoo_api import YahooShoppingClient, YahooShoppingError


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
        min_interval_seconds=rate_seconds,
        state_store=SQLiteStateStore(tmp_path / "state"),
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
    store = SQLiteStateStore(Path(state_dir))
    barrier.wait()
    queue.put(store.increment_usage().count)


def _global_rate_limit_worker(state_dir: str, limit: int, window_seconds: int, barrier, queue) -> None:
    store = SQLiteStateStore(Path(state_dir))
    barrier.wait()
    try:
        store.consume_global_rate_limit(key="global", limit=limit, window_seconds=window_seconds, now=int(time.time()))
    except Exception:
        queue.put(False)
    else:
        queue.put(True)


def _seed_usage_count(state_dir: Path, count: int) -> None:
    store = SQLiteStateStore(state_dir)
    current_day = store.load_usage().date
    with sqlite3.connect(state_dir / "state.sqlite3") as conn:
        conn.execute("UPDATE usage_state SET date = ?, count = ? WHERE singleton = 1", (current_day, count))
        conn.commit()


def _seed_global_rate_limit_count(state_dir: Path, count: int, *, window_started_at: int) -> None:
    SQLiteStateStore(state_dir)
    with sqlite3.connect(state_dir / "state.sqlite3") as conn:
        conn.execute(
            """
            INSERT INTO global_rate_limit_windows (key, window_started_at, count)
            VALUES ('global', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                window_started_at = excluded.window_started_at,
                count = excluded.count
            """,
            (window_started_at, count),
        )
        conn.commit()


def _yahoo_item_search_response() -> dict:
    return {
        "totalResultsAvailable": 2,
        "totalResultsReturned": 2,
        "firstResultsPosition": 1,
        "hits": [
            {
                "code": "store_desk-lamp",
                "name": "Desk Lamp",
                "headLine": "Bright compact lamp",
                "url": "https://store.shopping.yahoo.co.jp/example/desk-lamp.html",
                "price": 3200,
                "priceLabel": {
                    "defaultPrice": 3980,
                    "discountedPrice": 3200,
                    "fixedPrice": None,
                    "periodStart": 1783090800,
                    "periodEnd": 1783270800,
                },
                "inStock": True,
                "condition": "new",
                "image": {"small": "https://item-shopping.c.yimg.jp/i/g/example_s", "medium": "https://item-shopping.c.yimg.jp/i/g/example_m"},
                "exImage": {"url": "https://item-shopping.c.yimg.jp/i/g/example_ex", "width": 600, "height": 600},
                "genreCategory": {"id": 2506, "name": "Furniture", "depth": 2},
                "parentGenreCategories": [{"id": 1, "name": "Shopping", "depth": 0}],
                "brand": {"id": 123, "name": "Lamp Brand"},
                "parentBrands": [{"id": 100, "name": "Lighting"}],
                "janCode": "4900000000000",
                "delivery": {"area": "13", "deadline": 13, "day": 1},
                "review": {"rate": 4.5, "count": 12, "url": "https://store.shopping.yahoo.co.jp/example/review"},
                "seller": {"name": "Store", "url": "https://store.shopping.yahoo.co.jp/example/", "isBestSeller": True},
                "description": "compact lamp",
            },
            {
                "name": "Floor Lamp",
                "url": "https://store.shopping.yahoo.co.jp/example/floor-lamp.html",
                "price": 4980,
                "inStock": False,
                "image": {"small": "https://item-shopping.c.yimg.jp/i/g/example_floor"},
                "seller": {"name": "Interior Store"},
            },
        ],
    }


REQUEST_CASES = [
    (
        "query_only",
        {"query": "nike"},
        {"appid": "test-appid", "query": "nike", "results": "20", "start": "1"},
    ),
    (
        "jan_code_only",
        {"jan_code": "4900000000000"},
        {"appid": "test-appid", "jan_code": "4900000000000", "results": "20", "start": "1"},
    ),
    (
        "price_from_only",
        {"query": "nike", "price_from": 1000},
        {"appid": "test-appid", "query": "nike", "price_from": "1000", "results": "20", "start": "1"},
    ),
    (
        "price_to_only",
        {"query": "nike", "price_to": 2000},
        {"appid": "test-appid", "query": "nike", "price_to": "2000", "results": "20", "start": "1"},
    ),
    (
        "price_range",
        {"query": "nike", "price_from": 1000, "price_to": 2000},
        {
            "appid": "test-appid",
            "query": "nike",
            "price_from": "1000",
            "price_to": "2000",
            "results": "20",
            "start": "1",
        },
    ),
    (
        "stock_true",
        {"query": "nike", "in_stock": True},
        {"appid": "test-appid", "query": "nike", "in_stock": "true", "results": "20", "start": "1"},
    ),
    (
        "stock_false",
        {"query": "nike", "in_stock": False},
        {"appid": "test-appid", "query": "nike", "in_stock": "false", "results": "20", "start": "1"},
    ),
    (
        "condition_new",
        {"query": "nike", "condition": "new"},
        {"appid": "test-appid", "query": "nike", "condition": "new", "results": "20", "start": "1"},
    ),
    (
        "condition_used",
        {"query": "nike", "condition": "used"},
        {"appid": "test-appid", "query": "nike", "condition": "used", "results": "20", "start": "1"},
    ),
    (
        "shipping_free",
        {"query": "nike", "shipping": "free"},
        {"appid": "test-appid", "query": "nike", "shipping": "free", "results": "20", "start": "1"},
    ),
    (
        "shipping_conditional_free",
        {"query": "nike", "shipping": "conditional_free"},
        {
            "appid": "test-appid",
            "query": "nike",
            "shipping": "conditional_free",
            "results": "20",
            "start": "1",
        },
    ),
    (
        "shipping_both",
        {"query": "nike", "shipping": "free,conditional_free"},
        {
            "appid": "test-appid",
            "query": "nike",
            "shipping": "free,conditional_free",
            "results": "20",
            "start": "1",
        },
    ),
    (
        "sort_score",
        {"query": "nike", "sort": "-score"},
        {"appid": "test-appid", "query": "nike", "sort": "-score", "results": "20", "start": "1"},
    ),
    (
        "sort_price_asc",
        {"query": "nike", "sort": "+price"},
        {"appid": "test-appid", "query": "nike", "sort": "+price", "results": "20", "start": "1"},
    ),
    (
        "sort_price_desc",
        {"query": "nike", "sort": "-price"},
        {"appid": "test-appid", "query": "nike", "sort": "-price", "results": "20", "start": "1"},
    ),
    (
        "sort_review_count",
        {"query": "nike", "sort": "-review_count"},
        {"appid": "test-appid", "query": "nike", "sort": "-review_count", "results": "20", "start": "1"},
    ),
    (
        "new_filters",
        {
            "query": "nike",
            "genre_category_ids": [2498, 4744],
            "brand_ids": [123, 456],
            "seller_id": "store-id",
            "image_size": 600,
            "is_discounted": True,
        },
        {
            "appid": "test-appid",
            "query": "nike",
            "genre_category_id": "2498,4744",
            "brand_id": "123,456",
            "seller_id": "store-id",
            "image_size": "600",
            "is_discounted": "true",
            "results": "20",
            "start": "1",
        },
    ),
    (
        "mixed_all",
        {
            "query": "ゲーミングデスク",
            "jan_code": "4900000000000",
            "price_from": 1000,
            "price_to": 2000,
            "in_stock": False,
            "condition": "used",
            "shipping": "free",
            "sort": "-review_count",
            "results": 5,
            "start": 11,
        },
        {
            "appid": "test-appid",
            "query": "ゲーミングデスク",
            "jan_code": "4900000000000",
            "price_from": "1000",
            "price_to": "2000",
            "in_stock": "false",
            "condition": "used",
            "shipping": "free",
            "sort": "-review_count",
            "results": "5",
            "start": "11",
        },
    ),
]


@pytest.mark.anyio
@pytest.mark.parametrize("payload_kwargs, expected_params", [(case[1], case[2]) for case in REQUEST_CASES], ids=[case[0] for case in REQUEST_CASES])
async def test_maps_request_parameters_across_query_patterns(tmp_path: Path, payload_kwargs: dict, expected_params: dict) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 1, "firstResultsPosition": 1, "hits": []},
        )

    client = build_client(tmp_path, handler, rate_seconds=0.0)

    try:
        await client.search(SearchProductsInput(**payload_kwargs))
    finally:
        await client._http_client.aclose()

    assert captured["params"] == expected_params


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
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=["not", "an", "object"]),
    ],
    ids=["invalid-json", "invalid-shape"],
)
async def test_invalid_success_response_is_sanitized(tmp_path: Path, response: httpx.Response) -> None:
    client = build_client(tmp_path, lambda _request: response, rate_seconds=0.0)
    try:
        with pytest.raises(YahooShoppingError) as exc_info:
            await client.search(SearchProductsInput(query="lamp"))
    finally:
        await client._http_client.aclose()

    assert exc_info.value.kind == "provider_invalid_response"
    assert exc_info.value.message == "Yahoo Shopping API returned an invalid response."
    assert exc_info.value.details is None


@pytest.mark.anyio
async def test_malformed_provider_error_is_sanitized(tmp_path: Path) -> None:
    client = build_client(
        tmp_path,
        lambda _request: httpx.Response(
            400,
            json={"Error": "not-an-object", "message": "secret-provider-message"},
        ),
        rate_seconds=0.0,
    )
    try:
        with pytest.raises(YahooShoppingError) as exc_info:
            await client.search(SearchProductsInput(query="lamp"))
    finally:
        await client._http_client.aclose()

    assert exc_info.value.kind == "provider_error"
    assert exc_info.value.provider_code is None
    assert exc_info.value.message == "Yahoo Shopping API request failed."
    assert "secret-provider-message" not in str(exc_info.value)


@pytest.mark.anyio
async def test_daily_limit_warning(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 0, "firstResultsPosition": 1, "hits": []},
        )

    state_dir = tmp_path / "state"
    _seed_usage_count(state_dir, 44_999)
    state_store = SQLiteStateStore(state_dir)
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = YahooShoppingClient(
        app_id="test-appid",
        http_client=http_client,
        min_interval_seconds=0.0,
        state_store=state_store,
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

    state_dir = tmp_path / "state"
    _seed_usage_count(state_dir, 50_000)
    state_store = SQLiteStateStore(state_dir)
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = YahooShoppingClient(
        app_id="test-appid",
        http_client=http_client,
        min_interval_seconds=0.0,
        state_store=state_store,
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
                "hits": [{"name": "A", "url": "https://store.shopping.yahoo.co.jp/example/a.html", "price": 100}],
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
    assert len(second["items"]) == 1
    assert len(second["results"]) == 1


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
                "hits": [{"name": "A", "url": "https://store.shopping.yahoo.co.jp/example/a.html", "price": 100}],
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
async def test_formats_results_and_public_metadata(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_yahoo_item_search_response())

    client = build_client(tmp_path, handler, rate_seconds=0.0)
    try:
        result = await client.search(SearchProductsInput(query="lamp", shipping="free"))
    finally:
        await client._http_client.aclose()

    assert result["display_summary"] == "lamp: 2 items returned"
    assert result["results"][0]["title"] == "Desk Lamp"
    assert result["results"][0]["metadata"]["price"] == 3200
    assert result["results"][0]["metadata"]["price_text"] == "JPY 3,200"
    assert result["results"][0]["metadata"]["seller_name"] == "Store"
    assert result["results"][0]["metadata"]["image_url"] == "https://item-shopping.c.yimg.jp/i/g/example_ex"
    assert result["results"][0]["metadata"]["badges"] == ["In stock", "Free shipping"]
    assert result["products"][0]["imageUrl"] == "https://item-shopping.c.yimg.jp/i/g/example_ex"
    assert result["products"][0]["sellerName"] == "Store"
    assert result["products"][0]["inStock"] is True
    assert result["items"][0]["code"] == "store_desk-lamp"
    assert result["items"][0]["headline"] == "Bright compact lamp"
    assert result["items"][0]["price_label"]["default_price"] == 3980
    assert result["items"][0]["price_label"]["discounted_price"] == 3200
    assert result["items"][0]["price_label"]["fixed_price"] is None
    assert result["items"][0]["price_label"]["period_start"] == 1783090800
    assert result["items"][0]["price_label"]["period_end"] == 1783270800
    assert result["items"][0]["ex_image"] == {"url": "https://item-shopping.c.yimg.jp/i/g/example_ex", "width": 600, "height": 600}
    assert result["items"][0]["genre_category"] == {"id": 2506, "name": "Furniture", "depth": 2}
    assert result["items"][0]["parent_genre_categories"] == [{"id": 1, "name": "Shopping", "depth": 0}]
    assert result["items"][0]["brand"] == {"id": 123, "name": "Lamp Brand"}
    assert result["items"][0]["parent_brands"] == [{"id": 100, "name": "Lighting"}]
    assert result["items"][0]["jan_code"] == "4900000000000"
    assert result["items"][0]["delivery"] == {"area": "13", "deadline": 13, "day": 1}
    assert result["items"][1]["price_label"] is None
    assert result["items"][1]["parent_genre_categories"] == []
    assert result["no_items_reason"] is None


@pytest.mark.anyio
async def test_empty_hits_explain_no_items_reason(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 0, "totalResultsReturned": 0, "firstResultsPosition": 1, "hits": []},
        )

    client = build_client(tmp_path, handler, rate_seconds=0.0)
    try:
        result = await client.search(SearchProductsInput(query="missing"))
    finally:
        await client._http_client.aclose()

    assert result["results"] == []
    assert result["items"] == []
    assert result["display_summary"] == "missing: no items returned"
    assert result["no_items_reason"] == "upstream_hits_empty"


@pytest.mark.anyio
async def test_filters_restricted_products_and_external_urls(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "totalResultsAvailable": 2,
                "totalResultsReturned": 2,
                "firstResultsPosition": 1,
                "hits": [
                    {
                        "name": "Allowed lamp",
                        "url": "https://store.shopping.yahoo.co.jp/example/lamp.html",
                        "image": {"medium": "https://evil.example/image.jpg"},
                        "seller": {"name": "Store", "url": "https://evil.example/store"},
                    },
                    {
                        "name": "adult product",
                        "url": "https://store.shopping.yahoo.co.jp/example/adult.html",
                    },
                ],
            },
        )

    client = build_client(tmp_path, handler, rate_seconds=0.0)
    try:
        result = await client.search(SearchProductsInput(query="lamp"))
    finally:
        await client._http_client.aclose()

    assert len(result["items"]) == 1
    assert result["items"][0]["image"]["medium"] is None
    assert result["items"][0]["seller"]["url"] is None
    assert result["summary"]["total_results_returned"] == 1
    cache_text = next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8")
    assert "adult product" not in cache_text


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
        min_interval_seconds=0.0,
        state_store=SQLiteStateStore(tmp_path / "state"),
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
async def test_parallel_calls_respect_daily_limit(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={"totalResultsAvailable": 1, "totalResultsReturned": 1, "firstResultsPosition": 1, "hits": []},
        )

    state_dir = tmp_path / "state"
    _seed_usage_count(state_dir, 49_999)
    state_store = SQLiteStateStore(state_dir)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = YahooShoppingClient(
        app_id="test-appid",
        http_client=http_client,
        min_interval_seconds=0.0,
        state_store=state_store,
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
    assert SQLiteStateStore(tmp_path / "state").load_usage().count == 50_000


def test_usage_state_preserves_parallel_increments(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    _seed_usage_count(state_dir, 3)
    assert SQLiteStateStore(state_dir).load_usage().count == 3
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
    assert SQLiteStateStore(state_dir).load_usage().count == 13


def test_global_rate_limit_enforces_limit_under_concurrency(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    window_started_at = int(time.time())
    _seed_global_rate_limit_count(state_dir, 0, window_started_at=window_started_at)
    store = SQLiteStateStore(state_dir)
    assert store.consume_global_rate_limit(key="global", limit=5, window_seconds=60, now=window_started_at).remaining == 4

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
    with pytest.raises(StoredRateLimitExceededError):
        store.consume_global_rate_limit(key="global", limit=5, window_seconds=60, now=int(time.time()))


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
                        "code": "store_desk-lamp",
                        "name": "Desk Lamp",
                        "headLine": "Bright compact lamp",
                        "url": "https://store.shopping.yahoo.co.jp/example/desk-lamp.html",
                        "price": 3200,
                        "priceLabel": {"defaultPrice": 3980, "discountedPrice": 3200},
                        "inStock": True,
                        "condition": "new",
                        "image": {"small": "https://item-shopping.c.yimg.jp/i/g/example_s", "medium": "https://item-shopping.c.yimg.jp/i/g/example_m"},
                        "exImage": {"url": "https://item-shopping.c.yimg.jp/i/g/example_ex", "width": 600, "height": 600},
                        "genreCategory": {"id": 2506, "name": "Furniture", "depth": 2},
                        "parentGenreCategories": [{"id": 1, "name": "Shopping", "depth": 0}],
                        "brand": {"id": 123, "name": "Lamp Brand"},
                        "parentBrands": [{"id": 100, "name": "Lighting"}],
                        "janCode": "4900000000000",
                        "delivery": {"area": "13", "deadline": 13, "day": 1},
                        "review": {"rate": 4.5, "count": 12, "url": "https://store.shopping.yahoo.co.jp/example/review"},
                        "seller": {"name": "Store", "url": "https://store.shopping.yahoo.co.jp/example/", "isBestSeller": True},
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
                    tools = await session.list_tools()
                    result = await session.call_tool("search_products", {"query": "lamp"})

    content_payload = json.loads(result.content[0].text)
    content_text = result.content[0].text
    assert tools.tools[0].outputSchema is not None
    assert list(tools.tools[0].outputSchema["properties"]) == ["products"]
    assert result.structuredContent is not None
    assert result.structuredContent["products"][0]["imageUrl"] == "https://item-shopping.c.yimg.jp/i/g/example_ex"
    assert content_text.lstrip().startswith('{\n  "results"')
    assert content_payload["summary"]["total_results_available"] == 1
    assert content_payload["results"][0]["title"] == "Desk Lamp"
    assert content_payload["results"][0]["metadata"]["price"] == 3200
    assert content_payload["results"][0]["metadata"]["seller_name"] == "Store"
    assert content_payload["results"][0]["url"] == "https://store.shopping.yahoo.co.jp/example/desk-lamp.html"
    assert "items" not in content_payload
    assert "debug" not in content_payload
    assert content_payload["attribution"]["required_display"] is True
