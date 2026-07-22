"""Stable statistic names shared by the Locust workload and gate evaluator."""

from typing import Final

API_STAT_NAME: Final = "API GET /api/v1/users/me"
SEARCH_STAT_NAME: Final = "SEARCH POST /api/v1/search"
TTFB_STAT_NAME: Final = "TTFB POST /v1/chat/completions"
