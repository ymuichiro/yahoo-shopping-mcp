from pydantic import ValidationError

from yahoo_shopping_mcp.models import SearchProductsInput


def test_requires_query_or_jan_code() -> None:
    try:
        SearchProductsInput()
    except ValidationError as exc:
        assert "Either query or jan_code is required." in str(exc)
    else:
        raise AssertionError("ValidationError was not raised")


def test_validates_price_range() -> None:
    try:
        SearchProductsInput(query="camera", price_from=1000, price_to=500)
    except ValidationError as exc:
        assert "price_from must be less than or equal to price_to." in str(exc)
    else:
        raise AssertionError("ValidationError was not raised")


def test_validates_start_results_limit() -> None:
    try:
        SearchProductsInput(query="camera", start=980, results=21)
    except ValidationError as exc:
        assert "start + results must be less than or equal to 1000." in str(exc)
    else:
        raise AssertionError("ValidationError was not raised")
