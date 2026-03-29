from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


def _build_client(monkeypatch: pytest.MonkeyPatch):
    import src.server.app as stock_app

    async def fake_init_adapters() -> None:
        return None

    def fake_create_mcp_server():
        raise RuntimeError("disable MCP in tests")

    monkeypatch.setattr(stock_app, "init_adapters", fake_init_adapters)
    monkeypatch.setattr(stock_app, "create_mcp_server", fake_create_mcp_server)

    test_app = stock_app.create_app()
    from fastapi.testclient import TestClient
    return TestClient(test_app)


def test_root_serves_user_portal_html(monkeypatch: pytest.MonkeyPatch) -> None:
    with _build_client(monkeypatch) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Stock MCP" in response.text


def test_api_meta_exposes_service_information(monkeypatch: pytest.MonkeyPatch) -> None:
    with _build_client(monkeypatch) as client:
        response = client.get("/api/meta")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "Stock Tool Server"
    assert payload["protocols"]["restful_api"]["base_url"] == "/api/v1"


def test_preview_catalog_returns_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.server.core.dependencies import Container

    fake_gateway = MagicMock()
    fake_gateway.adapters = {}

    monkeypatch.setattr(Container, "market_gateway", lambda: fake_gateway)

    with _build_client(monkeypatch) as client:
        response = client.get("/api/v1/preview/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert "total_methods" in payload
    assert "categories" in payload
    assert payload["total_methods"] > 0
    for cat in payload["categories"]:
        assert "name" in cat
        assert "methods" in cat
        for m in cat["methods"]:
            assert "name" in m
            assert "type" in m
            assert "sources" in m


def test_preview_query_dispatches_to_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.server.core.dependencies import Container

    adapter = MagicMock()
    adapter.name = "akshare"
    adapter.get_money_flow = AsyncMock(return_value={"symbol": "000001", "flows": [{"amount": 100}]})

    fake_gateway = MagicMock()
    fake_gateway.adapters = {"akshare": adapter}
    fake_gateway.get_money_flow = AsyncMock(
        return_value={"symbol": "000001", "flows": [{"amount": 100}]}
    )

    monkeypatch.setattr(Container, "market_gateway", lambda: fake_gateway)

    with _build_client(monkeypatch) as client:
        response = client.post(
            "/api/v1/preview/query",
            json={
                "method": "get_money_flow",
                "params": {"symbol": "000001"},
                "sources": ["akshare"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "get_money_flow"
    assert "akshare" in payload["results"]
    assert payload["results"]["akshare"]["error"] is None
    assert payload["results"]["akshare"]["elapsed_ms"] >= 0
