"""Black-box release-candidate smoke tests for LocalLife Copilot.

Run from the repository root after the Compose stack is healthy:

    python -m pytest docs/测试用例文档/test_code/test_release_candidate_smoke.py -q

Authenticated cases require LOCAL_LIFE_TEST_USERNAME and
LOCAL_LIFE_TEST_PASSWORD. The tests use only the public Nginx/API contract.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import pytest


BASE_URL = os.getenv("LOCAL_LIFE_BASE_URL", "http://127.0.0.1:3000").rstrip("/") + "/"
USERNAME = os.getenv("LOCAL_LIFE_TEST_USERNAME")
PASSWORD = os.getenv("LOCAL_LIFE_TEST_PASSWORD")
KNOWLEDGE_BASE_ID = os.getenv("LOCAL_LIFE_TEST_KB_ID")


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    data: Any


def request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 15.0,
) -> Response:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(urljoin(BASE_URL, path.lstrip("/")), data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read()
            data = json.loads(raw.decode("utf-8")) if raw else None
            return Response(response.status, dict(response.headers.items()), data)
    except HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else None
        except json.JSONDecodeError:
            data = raw.decode("utf-8", errors="replace")
        return Response(exc.code, dict(exc.headers.items()), data)
    except URLError as exc:
        pytest.fail(f"LocalLife Copilot is not reachable at {BASE_URL}: {exc.reason}")


def response_code(response: Response) -> str | None:
    if not isinstance(response.data, dict):
        return None
    error = response.data.get("error")
    if isinstance(error, dict):
        return error.get("code")
    return response.data.get("code")


@pytest.fixture(scope="module")
def login_pair() -> dict[str, str]:
    if not USERNAME or not PASSWORD:
        pytest.skip("Set LOCAL_LIFE_TEST_USERNAME and LOCAL_LIFE_TEST_PASSWORD")
    response = request_json(
        "POST",
        "/api/v1/auth/login",
        payload={"username": USERNAME, "password": PASSWORD},
    )
    assert response.status == 200, response.data
    payload = response.data.get("data", response.data)
    assert payload["access_token"]
    assert payload["refresh_token"]
    return payload


def test_live_health_reports_process_alive() -> None:
    response = request_json("GET", "/health/live")
    assert response.status == 200
    assert isinstance(response.data, dict)
    assert response.data.get("status") in {"alive", "ok"}


def test_ready_health_reports_dependency_map() -> None:
    response = request_json("GET", "/health/ready")
    assert response.status == 200, response.data
    assert response.data.get("status") == "ready"
    assert set(response.data.get("checks", {})) >= {
        "mysql",
        "redis",
        "opensearch",
        "model_gateway",
    }


def test_nginx_exposes_openapi_contract() -> None:
    response = request_json("GET", "/openapi.json")
    assert response.status == 200
    assert response.data.get("info", {}).get("title")
    assert "/api/v1/auth/login" in response.data.get("paths", {})


def test_invalid_credentials_are_rejected_without_secret_echo() -> None:
    secret = "not-the-real-password-acceptance-probe"
    response = request_json(
        "POST",
        "/api/v1/auth/login",
        payload={"username": "missing-acceptance-user", "password": secret},
    )
    assert response.status == 401
    assert secret not in json.dumps(response.data, ensure_ascii=False)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/users/me",
        "/api/v1/knowledge-bases",
        "/api/v1/users",
        "/api/v1/models",
    ],
)
def test_protected_resources_reject_anonymous_access(path: str) -> None:
    response = request_json("GET", path)
    assert response.status == 401, (path, response.data)


def test_authenticated_user_contract(login_pair: dict[str, str]) -> None:
    response = request_json("GET", "/api/v1/users/me", token=login_pair["access_token"])
    assert response.status == 200, response.data
    payload = response.data.get("data", response.data)
    assert payload.get("id")
    assert isinstance(payload.get("roles"), list)


def test_refresh_token_rotates_and_replay_is_rejected(login_pair: dict[str, str]) -> None:
    old_refresh = login_pair["refresh_token"]
    first = request_json("POST", "/api/v1/auth/refresh", payload={"refresh_token": old_refresh})
    assert first.status == 200, first.data
    payload = first.data.get("data", first.data)
    assert payload["refresh_token"] != old_refresh

    replay = request_json("POST", "/api/v1/auth/refresh", payload={"refresh_token": old_refresh})
    assert replay.status == 401


def test_search_contract_returns_ranked_items(login_pair: dict[str, str]) -> None:
    if not KNOWLEDGE_BASE_ID:
        pytest.skip("Set LOCAL_LIFE_TEST_KB_ID to an authorized knowledge base UUID")
    response = request_json(
        "POST",
        "/api/v1/search",
        token=login_pair["access_token"],
        payload={
            "query": "适合两个人的本地餐厅",
            "knowledge_base_ids": [KNOWLEDGE_BASE_ID],
            "top_k": 5,
        },
        timeout=30,
    )
    assert response.status == 200, response.data
    payload = response.data.get("data", response.data)
    assert isinstance(payload.get("items", payload.get("hits", [])), list)
