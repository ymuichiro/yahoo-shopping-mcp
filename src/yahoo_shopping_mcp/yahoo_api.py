from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from yahoo_shopping_mcp.constants import (
    YAHOO_ATTRIBUTION_TEXT,
    YAHOO_ATTRIBUTION_URL,
    YAHOO_ITEM_SEARCH_URL,
)
from yahoo_shopping_mcp.models import SearchProductsInput, UsageState
from yahoo_shopping_mcp.storage import CacheStore, SQLiteStateStore

logger = logging.getLogger(__name__)
REDACTED_VALUE = "[REDACTED]"
SENSITIVE_REQUEST_KEYS = {"appid", "api_key", "access_token", "authorization", "token"}
T = TypeVar("T")


@dataclass(slots=True)
class YahooShoppingError(Exception):
    kind: str
    message: str
    retryable: bool = False
    http_status: int | None = None
    provider_code: str | None = None
    details: dict[str, Any] | None = None


class YahooShoppingClient:
    def __init__(
        self,
        app_id: str,
        http_client: httpx.AsyncClient,
        min_interval_seconds: float,
        state_store: SQLiteStateStore,
        cache_store: CacheStore,
        warning_threshold: int,
        hard_limit: int,
    ) -> None:
        self._app_id = app_id
        self._http_client = http_client
        self._min_interval_seconds = min_interval_seconds
        self._rate_lock = asyncio.Lock()
        self._last_started_at = 0.0
        self._state_store = state_store
        self._cache_store = cache_store
        self._warning_threshold = warning_threshold
        self._hard_limit = hard_limit

    async def search(self, request: SearchProductsInput) -> dict[str, Any]:
        cache_key_payload = request.model_dump(exclude_none=True)
        cached_response = self._cache_store.get(cache_key_payload)
        if cached_response is not None:
            return self._build_cached_response(request, cached_response)
        return await self._fetch_uncached(request, cache_key_payload)

    def _build_cached_response(self, request: SearchProductsInput, response_json: dict[str, Any]) -> dict[str, Any]:
        return self._format_response(request, response_json, self._state_store.load_usage(), from_cache=True)

    async def _fetch_uncached(self, request: SearchProductsInput, cache_key_payload: dict[str, object]) -> dict[str, Any]:
        response_json, usage_state = await self._run_with_rate_limit(lambda: self._fetch_with_usage_accounting(request))
        self._cache_store.set(cache_key_payload, response_json)
        return self._format_response(request, response_json, usage_state, from_cache=False)

    async def _run_with_rate_limit(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._rate_lock:
            now = asyncio.get_running_loop().time()
            elapsed = now - self._last_started_at
            if self._last_started_at and elapsed < self._min_interval_seconds:
                await asyncio.sleep(self._min_interval_seconds - elapsed)
            self._last_started_at = asyncio.get_running_loop().time()
            return await operation()

    async def _fetch_with_usage_accounting(
        self,
        request: SearchProductsInput,
    ) -> tuple[dict[str, Any], UsageState]:
        usage_state = self._state_store.load_usage()
        if usage_state.count >= self._hard_limit:
            raise YahooShoppingError(
                kind="daily_limit_exceeded",
                message="Daily request limit reached. Requests are blocked until the next JST day.",
                retryable=False,
            )
        response_json = await self._fetch_with_retry(request)
        usage_state = self._state_store.increment_usage()
        return response_json, usage_state

    async def _fetch_with_retry(self, request: SearchProductsInput) -> dict[str, Any]:
        params = self._build_request_params(request)
        retries_for_rate_limit = 3
        server_retry_budget = 1

        for attempt in range(retries_for_rate_limit + 1):
            self._log_upstream_request(params, attempt)
            try:
                response = await self._http_client.get(YAHOO_ITEM_SEARCH_URL, params=params)
            except httpx.HTTPError as exc:
                raise YahooShoppingError(
                    kind="transport_error",
                    message="Failed to reach Yahoo Shopping API.",
                    retryable=True,
                    details={"reason": str(exc)},
                ) from exc

            self._log_upstream_response(response.status_code, attempt)
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

    @staticmethod
    def _redact_request_params(params: dict[str, Any]) -> dict[str, Any]:
        return {
            key: REDACTED_VALUE if key.lower() in SENSITIVE_REQUEST_KEYS else value
            for key, value in params.items()
        }

    def _log_upstream_request(self, params: dict[str, Any], attempt: int) -> None:
        redacted_params = self._redact_request_params(params)
        logger.info(
            "Yahoo Shopping API request attempt=%s method=GET url=%s params=%s body=None",
            attempt + 1,
            YAHOO_ITEM_SEARCH_URL,
            json.dumps(redacted_params, ensure_ascii=False, sort_keys=True),
        )

    def _log_upstream_response(self, status_code: int, attempt: int) -> None:
        logger.info(
            "Yahoo Shopping API response attempt=%s method=GET url=%s status=%s",
            attempt + 1,
            YAHOO_ITEM_SEARCH_URL,
            status_code,
        )

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
        results = [
            self._format_search_result(item, request, index)
            for index, item in enumerate(items, start=1)
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
            "display_summary": self._build_display_summary(request, items),
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
        review = YahooShoppingClient._as_dict(hit.get("review"))
        seller = YahooShoppingClient._as_dict(hit.get("seller"))
        image = YahooShoppingClient._as_dict(hit.get("image"))
        price_label = YahooShoppingClient._as_dict(hit.get("priceLabel"))
        ex_image = YahooShoppingClient._as_dict(hit.get("exImage"))
        genre_category = YahooShoppingClient._as_dict(hit.get("genreCategory"))
        brand = YahooShoppingClient._as_dict(hit.get("brand"))
        delivery = YahooShoppingClient._as_dict(hit.get("delivery"))
        return {
            "code": hit.get("code"),
            "name": hit.get("name"),
            "headline": hit.get("headLine"),
            "url": hit.get("url"),
            "price": hit.get("price"),
            "price_label": YahooShoppingClient._format_price_label(price_label),
            "in_stock": hit.get("inStock"),
            "condition": hit.get("condition"),
            "image": {
                "small": image.get("small"),
                "medium": image.get("medium"),
            },
            "ex_image": YahooShoppingClient._format_ex_image(ex_image),
            "genre_category": YahooShoppingClient._format_genre_category(genre_category),
            "parent_genre_categories": YahooShoppingClient._format_list(
                hit.get("parentGenreCategories"),
                YahooShoppingClient._format_genre_category,
            ),
            "brand": YahooShoppingClient._format_brand(brand),
            "parent_brands": YahooShoppingClient._format_list(hit.get("parentBrands"), YahooShoppingClient._format_brand),
            "jan_code": hit.get("janCode"),
            "delivery": YahooShoppingClient._format_delivery(delivery),
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
    def _as_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}

    @staticmethod
    def _format_price_label(price_label: dict[str, Any]) -> dict[str, Any] | None:
        if not price_label:
            return None
        return {
            "default_price": price_label.get("defaultPrice"),
            "discounted_price": price_label.get("discountedPrice"),
            "fixed_price": price_label.get("fixedPrice"),
            "period_start": price_label.get("periodStart"),
            "period_end": price_label.get("periodEnd"),
        }

    @staticmethod
    def _format_ex_image(ex_image: dict[str, Any]) -> dict[str, Any] | None:
        if not ex_image:
            return None
        return {
            "url": ex_image.get("url"),
            "width": ex_image.get("width"),
            "height": ex_image.get("height"),
        }

    @staticmethod
    def _format_genre_category(category: dict[str, Any]) -> dict[str, Any] | None:
        if not category:
            return None
        return {
            "id": category.get("id"),
            "name": category.get("name"),
            "depth": category.get("depth"),
        }

    @staticmethod
    def _format_brand(brand: dict[str, Any]) -> dict[str, Any] | None:
        if not brand:
            return None
        return {
            "id": brand.get("id"),
            "name": brand.get("name"),
        }

    @staticmethod
    def _format_delivery(delivery: dict[str, Any]) -> dict[str, Any] | None:
        if not delivery:
            return None
        return {
            "area": delivery.get("area"),
            "deadline": delivery.get("deadline"),
            "day": delivery.get("day"),
        }

    @staticmethod
    def _format_list(value: Any, formatter: Callable[[dict[str, Any]], dict[str, Any] | None]) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        formatted_items = []
        for item in value:
            if not isinstance(item, dict):
                continue
            formatted = formatter(item)
            if formatted is not None:
                formatted_items.append(formatted)
        return formatted_items

    @staticmethod
    def _format_search_result(item: dict[str, Any], request: SearchProductsInput, index: int) -> dict[str, Any]:
        image = item.get("image") or {}
        seller = item.get("seller") or {}
        title = item.get("name") or f"Product {index}"
        url = item.get("url") or ""
        price_text = YahooShoppingClient._format_price_text(item.get("price")) or ""
        seller_name = seller.get("name") or ""
        badges = []
        if item.get("in_stock") is True:
            badges.append("In stock")
        if request.shipping and "free" in request.shipping:
            badges.append("Free shipping")
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
                "price": item.get("price"),
                "price_text": price_text or None,
                "seller_name": seller_name,
                "image_url": image.get("medium") or image.get("small"),
                "badges": badges,
            },
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
    def _build_display_summary(request: SearchProductsInput, items: list[dict[str, Any]]) -> str:
        search_term = request.query or request.jan_code or "search"
        count = len(items)
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
