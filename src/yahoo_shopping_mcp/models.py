from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


Condition = Literal["new", "used"]
Shipping = Literal["free", "conditional_free", "free,conditional_free"]
Sort = Literal["-score", "+price", "-price", "-review_count"]


class SearchProductsInput(BaseModel):
    query: str | None = Field(default=None, min_length=1)
    jan_code: str | int | None = Field(default=None, min_length=1)
    price_from: int | None = Field(default=None, ge=0)
    price_to: int | None = Field(default=None, ge=0)
    in_stock: bool | None = None
    condition: Condition | None = None
    shipping: Shipping | None = None
    sort: Sort | None = None
    results: int = Field(default=20, ge=1, le=50)
    start: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_payload(self) -> "SearchProductsInput":
        if not (self.query or self.jan_code):
            raise ValueError("Either query or jan_code is required.")
        if self.price_from is not None and self.price_to is not None and self.price_from > self.price_to:
            raise ValueError("price_from must be less than or equal to price_to.")
        if self.start + self.results > 1000:
            raise ValueError("start + results must be less than or equal to 1000.")
        return self

    @field_validator("jan_code", mode="before")
    @classmethod
    def normalize_jan_code(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, int):
            return str(value)
        return value


class UsageState(BaseModel):
    date: str
    count: int = 0


class CachedResponse(BaseModel):
    expires_at: float
    payload: dict


class RateLimitWindow(BaseModel):
    window_started_at: int
    count: int


class RateLimitStoreData(BaseModel):
    counters: dict[str, RateLimitWindow] = Field(default_factory=dict)


class SummaryPayload(BaseModel):
    total_results_available: int
    total_results_returned: int
    first_results_position: int


class ImagePayload(BaseModel):
    small: str | None = None
    medium: str | None = None


class ExImagePayload(BaseModel):
    url: str | None = None
    width: int | None = None
    height: int | None = None


class PriceLabelPayload(BaseModel):
    default_price: int | float | None = None
    discounted_price: int | float | None = None
    fixed_price: int | float | None = None
    period_start: int | str | None = None
    period_end: int | str | None = None


class GenreCategoryPayload(BaseModel):
    id: int | str | None = None
    name: str | None = None
    depth: int | None = None


class BrandPayload(BaseModel):
    id: int | str | None = None
    name: str | None = None


class DeliveryPayload(BaseModel):
    area: str | None = None
    deadline: int | str | None = None
    day: int | str | None = None


class ReviewPayload(BaseModel):
    rate: float | None = None
    count: int | None = None
    url: str | None = None


class SellerPayload(BaseModel):
    name: str | None = None
    url: str | None = None
    is_best_seller: bool | None = None


class ItemPayload(BaseModel):
    code: str | None = None
    name: str | None = None
    headline: str | None = None
    url: str | None = None
    price: int | float | None = None
    price_label: PriceLabelPayload | None = None
    in_stock: bool | None = None
    condition: str | None = None
    image: ImagePayload
    ex_image: ExImagePayload | None = None
    genre_category: GenreCategoryPayload | None = None
    parent_genre_categories: list[GenreCategoryPayload] = Field(default_factory=list)
    brand: BrandPayload | None = None
    parent_brands: list[BrandPayload] = Field(default_factory=list)
    jan_code: str | None = None
    delivery: DeliveryPayload | None = None
    review: ReviewPayload
    seller: SellerPayload
    description: str | None = None


class SearchResultPayload(BaseModel):
    id: str
    title: str
    url: str
    text: str
    metadata: dict[str, object] = Field(default_factory=dict)


class PaginationPayload(BaseModel):
    start: int
    results: int
    total_results_available: int
    total_results_returned: int


class UsagePayload(BaseModel):
    date: str
    count: int
    from_cache: bool
    global_rate_limit: "GlobalRateLimitPayload | None" = None


class WarningPayload(BaseModel):
    kind: str
    message: str


class AttributionPayload(BaseModel):
    text: str
    url: str
    required_display: bool


class GlobalRateLimitPayload(BaseModel):
    limit: int
    remaining: int
    window_seconds: int
    reset_at: int


class DebugPayload(BaseModel):
    upstream_url: str
    upstream_status: int | None = None
    upstream_keys: list[str]
    upstream_hits_count: int
    formatted_items_count: int
    cache_hit: bool


class SearchProductsResponse(BaseModel):
    results: list[SearchResultPayload]
    display_summary: str
    no_items_reason: str | None = None
    debug: DebugPayload
    summary: SummaryPayload
    items: list[ItemPayload]
    pagination: PaginationPayload
    applied_filters: dict[str, object]
    usage: UsagePayload
    warnings: list[WarningPayload]
    attribution: AttributionPayload
