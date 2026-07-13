from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


Condition = Literal["new", "used"]
Shipping = Literal["free", "conditional_free", "free,conditional_free"]
Sort = Literal["-score", "+price", "-price", "-review_count"]


class SearchProductsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str | None = Field(default=None, min_length=1, max_length=200)
    jan_code: str | None = Field(default=None, min_length=8, max_length=13, pattern=r"^\d+$")
    price_from: int | None = Field(default=None, ge=0)
    price_to: int | None = Field(default=None, ge=0)
    in_stock: bool | None = None
    condition: Condition | None = None
    shipping: Shipping | None = None
    sort: Sort | None = None
    genre_category_ids: list[PositiveInt] | None = Field(default=None, min_length=1, max_length=20)
    brand_ids: list[PositiveInt] | None = Field(default=None, min_length=1, max_length=20)
    seller_id: str | None = Field(default=None, min_length=1, max_length=100)
    image_size: Literal[76, 106, 132, 146, 300, 600] | None = None
    is_discounted: bool | None = None
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


class UsageState(BaseModel):
    date: str
    count: int = 0


class CachedResponse(BaseModel):
    expires_at: float
    payload: dict


class SummaryPayload(BaseModel):
    total_results_available: int
    total_results_returned: int
    first_results_position: int


class ItemPayload(BaseModel):
    code: str | None = None
    name: str | None = None
    headline: str | None = None
    url: str | None = None
    price: int | float | None = None
    price_label: dict[str, object] | None = None
    in_stock: bool | None = None
    condition: str | None = None
    image: dict[str, object | None]
    ex_image: dict[str, object | None] | None = None
    genre_category: dict[str, object] | None = None
    parent_genre_categories: list[dict[str, object]] = Field(default_factory=list)
    brand: dict[str, object] | None = None
    parent_brands: list[dict[str, object]] = Field(default_factory=list)
    jan_code: str | None = None
    delivery: dict[str, object] | None = None
    review: dict[str, object | None]
    seller: dict[str, object | None]
    description: str | None = None


class SearchResultPayload(BaseModel):
    id: str
    title: str
    url: str
    text: str
    metadata: dict[str, object] = Field(default_factory=dict)


class ProductCardPayload(BaseModel):
    id: str
    title: str
    url: str
    imageUrl: str | None = None
    price: int | float = 0
    priceText: str = ""
    sellerName: str | None = None
    inStock: bool = False
    description: str | None = None


class ProductCarouselResponse(BaseModel):
    products: list[ProductCardPayload]


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


class SearchProductsResponse(BaseModel):
    results: list[SearchResultPayload]
    products: list[ProductCardPayload]
    display_summary: str
    no_items_reason: str | None = None
    summary: SummaryPayload
    items: list[ItemPayload]
    pagination: PaginationPayload
    applied_filters: dict[str, object]
    usage: UsagePayload
    warnings: list[WarningPayload]
    attribution: AttributionPayload
