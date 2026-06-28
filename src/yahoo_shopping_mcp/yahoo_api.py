from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from yahoo_shopping_mcp.constants import (
    YAHOO_ATTRIBUTION_TEXT,
    YAHOO_ATTRIBUTION_URL,
    YAHOO_ITEM_SEARCH_URL,
)
from yahoo_shopping_mcp.errors import YahooShoppingError
from yahoo_shopping_mcp.models import SearchProductsInput, UsageState
from yahoo_shopping_mcp.rate_limiter import SerialRateLimiter
from yahoo_shopping_mcp.storage import CacheStore, UsageStore


class RequestCoalescer:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def run(self, key: str, operation: Callable[[], Awaitable[None]]) -> bool:
        async with self._lock:
            task = self._tasks.get(key)
            if task is None:
                task = asyncio.create_task(operation())
                self._tasks[key] = task
                is_leader = True
            else:
                is_leader = False

        try:
            await task
            return is_leader
        finally:
            if is_leader:
                async with self._lock:
                    self._tasks.pop(key, None)


class YahooShoppingClient:
    def __init__(
        self,
        app_id: str,
        http_client: httpx.AsyncClient,
        rate_limiter: SerialRateLimiter,
        usage_store: UsageStore,
        cache_store: CacheStore,
        warning_threshold: int,
        hard_limit: int,
        request_coalescer: RequestCoalescer | None = None,
    ) -> None:
        self._app_id = app_id
        self._http_client = http_client
        self._rate_limiter = rate_limiter
        self._usage_store = usage_store
        self._cache_store = cache_store
        self._warning_threshold = warning_threshold
        self._hard_limit = hard_limit
        self._request_coalescer = request_coalescer or RequestCoalescer()

    async def search(self, request: SearchProductsInput) -> dict[str, Any]:
        cache_key_payload = request.normalized_cache_key_payload()
        cached_response = self._cache_store.get(cache_key_payload)
        if cached_response is not None:
            return self._build_cached_response(request, cached_response)

        cache_key = self._cache_store.make_key(cache_key_payload)
        leader_payload: dict[str, Any] | None = None

        async def populate_cache() -> None:
            nonlocal leader_payload
            leader_payload = await self._fetch_uncached(request, cache_key_payload)

        is_leader = await self._request_coalescer.run(cache_key, populate_cache)
        if is_leader:
            if leader_payload is None:
                raise RuntimeError("Singleflight leader completed without a response payload.")
            return leader_payload

        cached_response = self._cache_store.get(cache_key_payload)
        if cached_response is None:
            raise RuntimeError("Cache entry missing after coalesced request completed.")
        return self._build_cached_response(request, cached_response)

    def _build_cached_response(self, request: SearchProductsInput, response_json: dict[str, Any]) -> dict[str, Any]:
        return self._format_response(request, response_json, self._usage_store.load(), from_cache=True)

    async def _fetch_uncached(self, request: SearchProductsInput, cache_key_payload: dict[str, object]) -> dict[str, Any]:
        response_json, usage_state = await self._rate_limiter.run(lambda: self._fetch_with_usage_accounting(request))
        self._cache_store.set(cache_key_payload, response_json)
        return self._format_response(request, response_json, usage_state, from_cache=False)

    async def _fetch_with_usage_accounting(
        self,
        request: SearchProductsInput,
    ) -> tuple[dict[str, Any], UsageState]:
        usage_state = self._usage_store.load()
        if usage_state.count >= self._hard_limit:
            raise YahooShoppingError(
                kind="daily_limit_exceeded",
                message="Daily request limit reached. Requests are blocked until the next JST day.",
                retryable=False,
            )
        response_json = await self._fetch_with_retry(request)
        usage_state = self._usage_store.increment()
        return response_json, usage_state

    async def _fetch_with_retry(self, request: SearchProductsInput) -> dict[str, Any]:
        params = self._build_request_params(request)
        retries_for_rate_limit = 3
        server_retry_budget = 1

        for attempt in range(retries_for_rate_limit + 1):
            try:
                response = await self._http_client.get(YAHOO_ITEM_SEARCH_URL, params=params)
            except httpx.HTTPError as exc:
                raise YahooShoppingError(
                    kind="transport_error",
                    message="Failed to reach Yahoo Shopping API.",
                    retryable=True,
                    details={"reason": str(exc)},
                ) from exc

            if response.status_code == 429 and attempt < retries_for_rate_limit:
                await asyncio.sleep((2**attempt) + random.uniform(0.0, 0.25))
                continue

            if 500 <= response.status_code <= 599 and server_retry_budget > 0:
                server_retry_budget -= 1
                await asyncio.sleep(1.0)
                continue

            if response.status_code >= 400:
                raise self._build_http_error(response)

            return response.json()

        raise YahooShoppingError(
            kind="rate_limited",
            message="Yahoo Shopping API rate limit persisted after retries.",
            retryable=True,
            http_status=429,
        )

    def _build_request_params(self, request: SearchProductsInput) -> dict[str, Any]:
        params: dict[str, Any] = {
            "appid": self._app_id,
            "results": request.results,
            "start": request.start,
        }
        optional_params = request.model_dump(exclude_none=True, exclude={"results", "start"})
        params.update(optional_params)
        return params

    def _format_response(
        self,
        request: SearchProductsInput,
        response_json: dict[str, Any],
        usage_state: UsageState,
        *,
        from_cache: bool,
    ) -> dict[str, Any]:
        hits = response_json.get("hits", [])
        if not isinstance(hits, list):
            hits = []
        items = [self._format_item(hit) for hit in hits if isinstance(hit, dict)]
        display_items = [self._format_display_item(item, request) for item in items]
        results = [
            self._format_search_result(item, display_item, index)
            for index, (item, display_item) in enumerate(zip(items, display_items, strict=False), start=1)
        ]
        no_items_reason = self._build_no_items_reason(hits, items)
        warnings: list[dict[str, Any]] = []
        if usage_state.count >= self._warning_threshold:
            warnings.append(
                {
                    "kind": "daily_limit_warning",
                    "message": f"Daily request count is {usage_state.count} and approaching the 50000 request cap.",
                }
            )

        return {
            "results": results,
            "display_summary": self._build_display_summary(request, display_items),
            "display_items": display_items,
            "no_items_reason": no_items_reason,
            "debug": {
                "upstream_url": YAHOO_ITEM_SEARCH_URL,
                "upstream_status": 200,
                "upstream_keys": list(response_json.keys()),
                "upstream_hits_count": len(hits),
                "formatted_items_count": len(items),
                "cache_hit": from_cache,
            },
            "summary": {
                "total_results_available": response_json.get("totalResultsAvailable", 0),
                "total_results_returned": response_json.get("totalResultsReturned", len(hits)),
                "first_results_position": response_json.get("firstResultsPosition", request.start),
            },
            "items": items,
            "pagination": {
                "start": request.start,
                "results": request.results,
                "total_results_available": response_json.get("totalResultsAvailable", 0),
                "total_results_returned": response_json.get("totalResultsReturned", len(hits)),
            },
            "applied_filters": request.model_dump(exclude_none=True),
            "usage": self._build_usage_payload(usage_state, from_cache=from_cache),
            "warnings": warnings,
            "attribution": {
                "text": YAHOO_ATTRIBUTION_TEXT,
                "url": YAHOO_ATTRIBUTION_URL,
                "required_display": True,
            },
        }

    @staticmethod
    def _format_item(hit: dict[str, Any]) -> dict[str, Any]:
        review = hit.get("review") or {}
        seller = hit.get("seller") or {}
        image = hit.get("image") or {}
        return {
            "name": hit.get("name"),
            "url": hit.get("url"),
            "price": hit.get("price"),
            "in_stock": hit.get("inStock"),
            "condition": hit.get("condition"),
            "image": {
                "small": image.get("small"),
                "medium": image.get("medium"),
            },
            "review": {
                "rate": review.get("rate"),
                "count": review.get("count"),
                "url": review.get("url"),
            },
            "seller": {
                "name": seller.get("name"),
                "url": seller.get("url"),
                "is_best_seller": seller.get("isBestSeller"),
            },
            "description": hit.get("description"),
        }

    @staticmethod
    def _format_search_result(
        item: dict[str, Any],
        display_item: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        title = display_item.get("title") or item.get("name") or f"Product {index}"
        url = display_item.get("product_url") or item.get("url") or ""
        price_text = display_item.get("price_text") or str(display_item.get("price") or "")
        seller_name = display_item.get("seller_name") or ""
        text_parts = [
            f"price: {price_text}" if price_text else None,
            f"seller: {seller_name}" if seller_name else None,
            "in stock" if item.get("in_stock") is True else None,
            item.get("description"),
        ]
        text = " | ".join(str(part) for part in text_parts if part)

        return {
            "id": url or f"product-{index}",
            "title": str(title),
            "url": str(url),
            "text": text,
            "metadata": {
                "price": display_item.get("price"),
                "price_text": display_item.get("price_text"),
                "seller_name": display_item.get("seller_name"),
                "image_url": display_item.get("image_url"),
                "badges": display_item.get("badges") or [],
            },
        }

    @staticmethod
    def _format_display_item(item: dict[str, Any], request: SearchProductsInput) -> dict[str, Any]:
        image = item.get("image") or {}
        seller = item.get("seller") or {}
        badges = []
        if item.get("in_stock") is True:
            badges.append("In stock")
        if request.shipping and "free" in request.shipping:
            badges.append("Free shipping")

        return {
            "title": item.get("name"),
            "price": item.get("price"),
            "price_text": YahooShoppingClient._format_price_text(item.get("price")),
            "seller_name": seller.get("name"),
            "product_url": item.get("url"),
            "image_url": image.get("medium") or image.get("small"),
            "badges": badges,
        }

    @staticmethod
    def _format_price_text(price: Any) -> str | None:
        if price is None:
            return None
        if isinstance(price, int):
            return f"JPY {price:,}"
        if isinstance(price, float):
            if price.is_integer():
                return f"JPY {int(price):,}"
            return f"JPY {price:,.2f}"
        return str(price)

    @staticmethod
    def _build_display_summary(request: SearchProductsInput, display_items: list[dict[str, Any]]) -> str:
        search_term = request.query or request.jan_code or "search"
        count = len(display_items)
        if count == 0:
            return f"{search_term}: no items returned"
        return f"{search_term}: {count} item{'s' if count != 1 else ''} returned"

    @staticmethod
    def _build_no_items_reason(hits: list[Any], items: list[dict[str, Any]]) -> str | None:
        if not hits:
            return "upstream_hits_empty"
        if not items:
            return "formatted_items_empty"
        return None

    def _build_http_error(self, response: httpx.Response) -> YahooShoppingError:
        provider_code = None
        message = "Yahoo Shopping API request failed."
        details: dict[str, Any] = {}

        try:
            payload = response.json()
            if isinstance(payload, dict):
                details["provider_payload"] = payload
                provider_code = str(payload.get("Error", {}).get("Code") or payload.get("code") or "")
                message = payload.get("Error", {}).get("Message") or payload.get("message") or message
        except ValueError:
            details["provider_payload"] = response.text

        return YahooShoppingError(
            kind="provider_error" if response.status_code < 500 else "provider_unavailable",
            message=message,
            retryable=response.status_code in {429} or response.status_code >= 500,
            http_status=response.status_code,
            provider_code=provider_code or None,
            details=details,
        )

    @staticmethod
    def _build_usage_payload(state: UsageState, *, from_cache: bool) -> dict[str, Any]:
        return {
            "date": state.date,
            "count": state.count,
            "from_cache": from_cache,
        }
