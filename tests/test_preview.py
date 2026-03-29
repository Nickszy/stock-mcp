# tests/test_preview.py
"""Tests for the data preview workbench endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gateway_mock():
    """Create a mock MarketGateway with realistic adapter structure."""
    gateway = MagicMock()

    # Mock adapters dict: DataSource -> adapter
    akshare = MagicMock()
    akshare.name = "akshare"
    akshare.get_money_flow = AsyncMock(return_value={"symbol": "600519", "flows": []})
    akshare.get_gdp_data = AsyncMock(return_value={"data": []})
    akshare.get_financials = AsyncMock(return_value={"data": {"revenue": 100}})

    tushare = MagicMock()
    tushare.name = "tushare"
    tushare.get_money_flow = AsyncMock(return_value={"symbol": "600519", "flows": []})
    # tushare does NOT have get_gdp_data (not callable)
    tushare.get_gdp_data = None

    gateway.adapters = {"akshare": akshare, "tushare": tushare}
    gateway.get_money_flow = AsyncMock(return_value={"symbol": "600519", "flows": [], "_source": "akshare"})
    gateway.get_gdp_data = AsyncMock(return_value={"data": [], "_source": "akshare"})
    gateway.get_financials = AsyncMock(return_value={"data": {"revenue": 100}})

    return gateway


@pytest.fixture(autouse=True)
def _patch_container():
    """Patch Container.market_gateway for all tests."""
    gateway = _make_gateway_mock()
    with patch("src.server.api.routes.preview.Container") as mock_container:
        mock_container.market_gateway.return_value = gateway
        yield mock_container


@pytest.fixture(autouse=True)
def _patch_init_adapters():
    """Prevent real adapter init during test client creation."""
    with patch("src.server.core.bootstrap.init_adapters", new_callable=AsyncMock):
        yield


@pytest.fixture(autouse=True)
def _patch_mcp():
    """Prevent MCP server creation in tests."""
    with patch("src.server.mcp.server.create_mcp_server", return_value=None):
        yield


@pytest.fixture
def client():
    from src.server.app import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestApiMeta:
    def test_returns_service_info(self, client):
        r = client.get("/api/meta")
        assert r.status_code == 200
        data = r.json()
        assert data["service"] == "Stock Tool Server"
        assert "version" in data
        assert "protocols" in data
        assert "restful_api" in data["protocols"]
        assert "mcp" in data["protocols"]

    def test_includes_supported_markets(self, client):
        r = client.get("/api/meta")
        data = r.json()
        assert "US Stocks" in data["supported_markets"]


class TestPreviewCatalog:
    def test_returns_methods(self, client):
        r = client.get("/api/v1/preview/catalog")
        assert r.status_code == 200
        data = r.json()
        assert "total_methods" in data
        assert data["total_methods"] > 0
        assert "categories" in data
        assert len(data["categories"]) > 0

    def test_method_has_required_fields(self, client):
        r = client.get("/api/v1/preview/catalog")
        data = r.json()
        for cat in data["categories"]:
            for m in cat["methods"]:
                assert "name" in m
                assert "type" in m
                assert m["type"] in ("ticker", "market")
                assert "sources" in m
                assert isinstance(m["sources"], list)

    def test_ticker_market_counts(self, client):
        r = client.get("/api/v1/preview/catalog")
        data = r.json()
        assert data["ticker_methods"] > 0
        assert data["market_methods"] > 0
        assert data["total_methods"] == data["ticker_methods"] + data["market_methods"]


class TestPreviewQuery:
    def test_auto_source(self, client):
        r = client.post("/api/v1/preview/query", json={
            "method": "get_money_flow",
            "params": {"symbol": "600519"},
            "sources": ["auto"],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["method"] == "get_money_flow"
        assert "auto" in data["results"]
        auto = data["results"]["auto"]
        assert auto["error"] is None
        assert auto["elapsed_ms"] >= 0

    def test_multi_source(self, client):
        r = client.post("/api/v1/preview/query", json={
            "method": "get_money_flow",
            "params": {"symbol": "600519"},
            "sources": ["auto", "akshare", "tushare"],
        })
        assert r.status_code == 200
        data = r.json()
        assert "auto" in data["results"]
        assert "akshare" in data["results"]
        assert "tushare" in data["results"]
        # Each result should have elapsed_ms
        for name, res in data["results"].items():
            assert "elapsed_ms" in res
            assert "error" in res

    def test_unknown_method_rejected(self, client):
        r = client.post("/api/v1/preview/query", json={
            "method": "nonexistent_method",
            "params": {},
            "sources": ["auto"],
        })
        assert r.status_code == 400
        assert "Unknown method" in r.json()["detail"]

    def test_source_error_captured(self, client, _patch_container):
        """When an adapter throws, error is captured not raised."""
        gateway = _patch_container.market_gateway.return_value
        # Make akshare throw for this test
        gateway.adapters["akshare"].get_money_flow = AsyncMock(side_effect=RuntimeError("API timeout"))

        r = client.post("/api/v1/preview/query", json={
            "method": "get_money_flow",
            "params": {"symbol": "600519"},
            "sources": ["akshare"],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["results"]["akshare"]["error"] is not None
        assert "API timeout" in data["results"]["akshare"]["error"]

    def test_unsupported_source_method(self, client):
        """Source that doesn't support the method returns error."""
        r = client.post("/api/v1/preview/query", json={
            "method": "get_gdp_data",
            "params": {},
            "sources": ["tushare"],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["results"]["tushare"]["error"] is not None


class TestRootPage:
    def test_root_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Stock MCP" in r.text

    def test_preview_alt_path(self, client):
        r = client.get("/preview")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_html_contains_js(self, client):
        r = client.get("/")
        assert "<script>" in r.text
        assert "fetch" in r.text  # JS makes API calls
