from __future__ import annotations

from pathlib import Path

YAHOO_ITEM_SEARCH_URL = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch"
YAHOO_ATTRIBUTION_TEXT = "Web Services by Yahoo! JAPAN"
YAHOO_ATTRIBUTION_URL = "https://developer.yahoo.co.jp/sitemap/"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_BASE_RATE_SECONDS = 1.0
DEFAULT_WARNING_THRESHOLD = 45_000
DEFAULT_HARD_LIMIT = 50_000
DEFAULT_GLOBAL_RATE_LIMIT = 60
DEFAULT_GLOBAL_WINDOW_SECONDS = 60

STATE_DIRNAME = "state"
CACHE_DIRNAME = "cache"
USAGE_FILENAME = "usage.json"
GLOBAL_RATE_LIMIT_FILENAME = "global_rate_limits.json"
STATE_DB_FILENAME = "state.sqlite3"

PACKAGE_ROOT = Path(__file__).resolve().parent
