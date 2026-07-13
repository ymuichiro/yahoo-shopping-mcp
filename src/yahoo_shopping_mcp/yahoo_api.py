from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from yahoo_shopping_mcp.constants import (
    RESTRICTED_SEARCH_TERMS,
    YAHOO_ATTRIBUTION_TEXT,
    YAHOO_ATTRIBUTION_URL,
    YAHOO_IMAGE_HOSTS,
    YAHOO_ITEM_SEARCH_URL,
    YAHOO_PRODUCT_HOSTS,
)
from yahoo_shopping_mcp.models import SearchProductsInput
from yahoo_shopping_mcp.storage import CacheStore


@dataclass(slots=True)
class YahooShoppingError(Exception):
    kind: str
    message: str
    retryable: bool = False
    http_status: int | None = None
    provider_code: str | None = None
    details: dict[str, Any] | None = None


def is_restricted_query(query: str | None) -> bool:
    normalized = (query or "").casefold()
    return any(term in normalized for term in RESTRICTED_SEARCH_TERMS)


def _safe_https_url(value: Any, hosts: frozenset[str]) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password:
        return None
    return value


def _contains_restricted_product_term(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.casefold()
        return any(term in normalized for term in RESTRICTED_SEARCH_TERMS)
    if isinstance(value, dict):
        return any(_contains_restricted_product_term(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_restricted_product_term(item) for item in value)
    return False


class YahooRateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval_seconds = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_started_at = 0.0

    async def wait_for_slot(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            elapsed = now - self._last_started_at
            if self._last_started_at and elapsed < self._min_interval_seconds:
                await asyncio.sleep(self._min_interval_seconds - elapsed)
            self._last_started_at = asyncio.get_running_loop().time()


class YahooShoppingClient:
    def __init__(
        self,
        app_id: str,
        http_client: httpx.AsyncClient,
        min_interval_seconds: float,
        cache_store: CacheStore,
        rate_limiter: YahooRateLimiter | None = None,
    ) -> None:
        self._app_id = app_id
        self._http_client = http_client
        self._cache_store = cache_store
        self._rate_limiter = rate_limiter or YahooRateLimiter(min_interval_seconds)

    async def search(self, request: SearchProductsInput) -> dict[str, Any]:
        if is_restricted_query(request.query):
            raise YahooShoppingError(
                kind="policy_restricted",
                message="This search request is not supported.",
                retryable=False,
            )
        cache_key_payload = request.model_dump(exclude_none=True)
        cached_response = self._cache_store.get(cache_key_payload)
        if cached_response is not None:
            return self._format_response(
                request,
                self._filter_response(cached_response, request),
            )

        await self._rate_limiter.wait_for_slot()
        response_json = await self._fetch_with_retry(request)
        response_json = self._filter_response(response_json, request)
        self._cache_store.set(cache_key_payload, response_json)
        return self._format_response(request, response_json)

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

            try:
                payload = response.json()
            except ValueError as exc:
                raise YahooShoppingError(
                    kind="provider_invalid_response",
                    message="Yahoo Shopping API returned an invalid response.",
                    retryable=False,
                    http_status=response.status_code,
                ) from exc
            if not isinstance(payload, dict):
                raise YahooShoppingError(
                    kind="provider_invalid_response",
                    message="Yahoo Shopping API returned an invalid response.",
                    retryable=False,
                    http_status=response.status_code,
                )
            return payload

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
        for input_name, yahoo_name in (("genre_category_ids", "genre_category_id"), ("brand_ids", "brand_id")):
            if values := optional_params.pop(input_name, None):
                optional_params[yahoo_name] = ",".join(map(str, values))
        params.update(optional_params)
        return params

    def _format_response(
        self,
        request: SearchProductsInput,
        response_json: dict[str, Any],
    ) -> dict[str, Any]:
        hits = response_json.get("hits", [])
        if not isinstance(hits, list):
            hits = []
        items = [self._format_item(hit) for hit in hits if isinstance(hit, dict)]
        results = [
            self._format_search_result(item, request, index)
            for index, item in enumerate(items, start=1)
        ]
        products = [self._format_product_card(item, index) for index, item in enumerate(items, start=1)]
        no_items_reason = (
            "policy_filtered"
            if response_json.get("_policy_filtered") and not items
            else self._build_no_items_reason(hits, items)
        )
        return {
            "results": results,
            "products": products,
            "display_summary": self._build_display_summary(request, items),
            "no_items_reason": no_items_reason,
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
            "attribution": {
                "text": YAHOO_ATTRIBUTION_TEXT,
                "url": YAHOO_ATTRIBUTION_URL,
                "required_display": True,
            },
        }

    @staticmethod
    def _filter_response(response_json: dict[str, Any], request: SearchProductsInput) -> dict[str, Any]:
        raw_hits = response_json.get("hits", [])
        if not isinstance(raw_hits, list):
            raw_hits = []
        safe_hits = [
            hit
            for hit in raw_hits
            if isinstance(hit, dict)
            and _safe_https_url(hit.get("url"), YAHOO_PRODUCT_HOSTS)
            and not _contains_restricted_product_term(hit)
        ]
        filtered = dict(response_json)
        filtered["hits"] = safe_hits
        if len(safe_hits) != len(raw_hits):
            filtered["_policy_filtered"] = True
            filtered["totalResultsAvailable"] = len(safe_hits)
            filtered["totalResultsReturned"] = len(safe_hits)
            filtered["firstResultsPosition"] = request.start
        return filtered

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
            "url": _safe_https_url(hit.get("url"), YAHOO_PRODUCT_HOSTS),
            "price": hit.get("price"),
            "price_label": YahooShoppingClient._format_price_label(price_label),
            "in_stock": hit.get("inStock"),
            "condition": hit.get("condition"),
            "image": {
                "small": _safe_https_url(image.get("small"), YAHOO_IMAGE_HOSTS),
                "medium": _safe_https_url(image.get("medium"), YAHOO_IMAGE_HOSTS),
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
                "url": _safe_https_url(review.get("url"), YAHOO_PRODUCT_HOSTS),
            },
            "seller": {
                "name": seller.get("name"),
                "url": _safe_https_url(seller.get("url"), YAHOO_PRODUCT_HOSTS),
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
            "url": _safe_https_url(ex_image.get("url"), YAHOO_IMAGE_HOSTS),
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
        ex_image = item.get("ex_image") or {}
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
                "image_url": ex_image.get("url") or image.get("medium") or image.get("small"),
                "badges": badges,
            },
        }

    @staticmethod
    def _format_product_card(item: dict[str, Any], index: int) -> dict[str, Any]:
        image = item.get("image") or {}
        ex_image = item.get("ex_image") or {}
        seller = item.get("seller") or {}
        price = item.get("price")
        return {
            "id": item.get("url") or f"product-{index}",
            "title": str(item.get("name") or f"Product {index}"),
            "url": str(item.get("url") or ""),
            "imageUrl": ex_image.get("url") or image.get("medium") or image.get("small"),
            "price": price if isinstance(price, (int, float)) else 0,
            "priceText": YahooShoppingClient._format_price_text(price) or "",
            "sellerName": seller.get("name"),
            "inStock": item.get("in_stock") is True,
            "description": item.get("description"),
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

        try:
            payload = response.json()
            if isinstance(payload, dict):
                error_payload = payload.get("Error")
                if isinstance(error_payload, dict):
                    provider_code = str(error_payload.get("Code") or "")
                provider_code = provider_code or str(payload.get("code") or "")
        except ValueError:
            pass

        return YahooShoppingError(
            kind="provider_error" if response.status_code < 500 else "provider_unavailable",
            message=message,
            retryable=response.status_code in {429} or response.status_code >= 500,
            http_status=response.status_code,
            provider_code=provider_code or None,
        )
