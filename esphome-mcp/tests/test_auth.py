"""Tests for the bearer-token middleware."""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from server.auth import BearerAuthMiddleware


def _ok(_):
    return PlainTextResponse("ok")


@pytest.fixture
def client():
    app = Starlette(routes=[Route("/health", _ok), Route("/mcp", _ok)])
    app.add_middleware(BearerAuthMiddleware)
    return TestClient(app)


def test_valid_token(client, monkeypatch):
    monkeypatch.setenv("ESPHOME_MCP_AUTH_TOKEN", "secret-token")
    r = client.get("/mcp", headers={"Authorization": "Bearer secret-token"})
    assert r.status_code == 200


def test_wrong_or_missing_token(client, monkeypatch):
    monkeypatch.setenv("ESPHOME_MCP_AUTH_TOKEN", "secret-token")
    assert client.get("/mcp", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert client.get("/mcp").status_code == 401


def test_empty_token_fails_closed(client, monkeypatch):
    monkeypatch.setenv("ESPHOME_MCP_AUTH_TOKEN", "")
    assert client.get("/mcp").status_code == 503


def test_health_is_unauthenticated(client, monkeypatch):
    monkeypatch.setenv("ESPHOME_MCP_AUTH_TOKEN", "")
    assert client.get("/health").status_code == 200
