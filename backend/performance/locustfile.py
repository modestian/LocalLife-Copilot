"""Locust workloads for the TK-703-03 release performance gate.

Required environment variables:

* ``PERF_USERNAME``: a seeded account with access to ``PERF_KNOWLEDGE_BASE_ID``;
* ``PERF_PASSWORD``: that account's password.

The deterministic ST-702 knowledge-base identifier is used by default. Secrets
are read only from the process environment and are never written to Locust
reports.
"""

from __future__ import annotations

import os
import time
from typing import Final

from locust import HttpUser, between, tag, task
from locust.exception import StopUser

from performance.contracts import API_STAT_NAME, SEARCH_STAT_NAME, TTFB_STAT_NAME

DEFAULT_KNOWLEDGE_BASE_ID: Final = "70200000-0000-4000-8000-000000000010"


class LocalLifePerformanceUser(HttpUser):
    """Exercise authenticated API, hybrid retrieval, and SSE first-byte paths."""

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        username = os.getenv("PERF_USERNAME", "").strip()
        password = os.getenv("PERF_PASSWORD", "")
        if not username or not password:
            raise RuntimeError("PERF_USERNAME and PERF_PASSWORD must be set")

        with self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
            name="SETUP POST /api/v1/auth/login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login returned HTTP {response.status_code}")
                raise StopUser
            try:
                token = response.json()["data"]["access_token"]
            except (KeyError, TypeError, ValueError):
                response.failure("login response did not contain an access token")
                raise StopUser from None

        self.client.headers.update({"Authorization": f"Bearer {token}"})
        self.knowledge_base_id = os.getenv(
            "PERF_KNOWLEDGE_BASE_ID", DEFAULT_KNOWLEDGE_BASE_ID
        ).strip()

    @tag("api")
    @task
    def authenticated_api(self) -> None:
        with self.client.get(
            "/api/v1/users/me",
            name=API_STAT_NAME,
            catch_response=True,
        ) as response:
            self._require_status(response, 200)

    @tag("search")
    @task
    def hybrid_search(self) -> None:
        payload = {
            "query": os.getenv("PERF_SEARCH_QUERY", "安静适合周末办公的咖啡馆"),
            "knowledge_base_ids": [self.knowledge_base_id],
            "top_k": 10,
            "vector_weight": 0.6,
            "keyword_weight": 0.4,
            "rerank": True,
            "filters": {"open_now": True},
        }
        with self.client.post(
            "/api/v1/search",
            json=payload,
            name=SEARCH_STAT_NAME,
            catch_response=True,
        ) as response:
            self._require_status(response, 200)

    @tag("ttfb")
    @task
    def streaming_first_byte(self) -> None:
        payload = {
            "model": "local-life-assistant",
            "messages": [
                {
                    "role": "user",
                    "content": os.getenv("PERF_CHAT_QUERY", "推荐一家适合安静办公的咖啡馆"),
                }
            ],
            "stream": True,
            "knowledge_base_ids": [self.knowledge_base_id],
        }
        started = time.perf_counter()
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            name=TTFB_STAT_NAME,
            catch_response=True,
            stream=True,
        ) as response:
            if not self._require_status(response, 200):
                return
            first_frame = next(
                (line for line in response.iter_lines(chunk_size=1) if line.startswith(b"data: ")),
                None,
            )
            # Locust normally records time to response headers for streamed requests.
            # Override it with the wall time through the first non-empty SSE data frame.
            response.request_meta["response_time"] = (time.perf_counter() - started) * 1000
            if first_frame is None:
                response.failure("stream ended before the first SSE data frame")
            response.close()

    @staticmethod
    def _require_status(response, expected: int) -> bool:
        if response.status_code == expected:
            return True
        response.failure(f"expected HTTP {expected}, got {response.status_code}")
        return False
