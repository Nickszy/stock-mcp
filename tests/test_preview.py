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
    akshare.get_stock_factors = AsyncMock(return_value={"symbol": "600519", "factors": {"momentum": 1.2}})
    akshare.get_stock_correlation = AsyncMock(return_value={"symbols": ["600519", "000858"], "correlation": 0.82})
    akshare.get_factor_ranking = AsyncMock(return_value={"factor": "change_pct", "items": []})

    tushare = MagicMock()
    tushare.name = "tushare"
    tushare.get_money_flow = AsyncMock(return_value={"symbol": "600519", "flows": []})
    # tushare does NOT have get_gdp_data (not callable)
    tushare.get_gdp_data = None
    tushare.get_stock_factors = AsyncMock(return_value={"symbol": "600519", "factors": {"momentum": 1.1}})
    tushare.get_stock_correlation = AsyncMock(return_value={"symbols": ["600519", "000858"], "correlation": 0.8})
    tushare.get_factor_ranking = AsyncMock(return_value={"factor": "change_pct", "items": []})

    gateway.adapters = {"akshare": akshare, "tushare": tushare}
    gateway.get_money_flow = AsyncMock(return_value={"symbol": "600519", "flows": [], "_source": "akshare"})
    gateway.get_gdp_data = AsyncMock(return_value={"data": [], "_source": "akshare"})
    gateway.get_financials = AsyncMock(return_value={"data": {"revenue": 100}})
    gateway.get_stock_factors = AsyncMock(return_value={"symbol": "600519", "factors": {"momentum": 1.2}})
    gateway.get_stock_correlation = AsyncMock(return_value={"symbols": ["600519", "000858"], "correlation": 0.82})
    gateway.get_factor_ranking = AsyncMock(return_value={"factor": "change_pct", "items": []})

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


class TestPreviewTemplate:
    """Direct import tests for the PREVIEW_HTML template constant."""

    def test_preview_html_is_non_empty_string(self):
        from src.server.api.routes.preview_template import PREVIEW_HTML
        assert isinstance(PREVIEW_HTML, str)
        assert len(PREVIEW_HTML) > 0

    def test_preview_html_contains_doctype_and_html(self):
        from src.server.api.routes.preview_template import PREVIEW_HTML
        assert "<!DOCTYPE html>" in PREVIEW_HTML
        assert "<html" in PREVIEW_HTML
        assert "</html>" in PREVIEW_HTML

    def test_preview_html_contains_head_and_body(self):
        from src.server.api.routes.preview_template import PREVIEW_HTML
        assert "<head>" in PREVIEW_HTML
        assert "</head>" in PREVIEW_HTML
        assert "<body>" in PREVIEW_HTML
        assert "</body>" in PREVIEW_HTML

    def test_preview_html_contains_script(self):
        from src.server.api.routes.preview_template import PREVIEW_HTML
        assert "<script>" in PREVIEW_HTML
        assert "fetch(" in PREVIEW_HTML

    def test_preview_html_contains_title(self):
        from src.server.api.routes.preview_template import PREVIEW_HTML
        assert "Stock MCP" in PREVIEW_HTML


class TestPreviewCatalogParams:
    """Verify catalog exposes _METHOD_PARAMS schemas for methods that define them."""

    def test_get_stock_factors_has_params(self, client):
        r = client.get("/api/v1/preview/catalog")
        methods = _collect_methods(r.json())
        m = methods["get_stock_factors"]
        assert m["params"] is not None
        assert len(m["params"]) == 2
        param_names = [p["name"] for p in m["params"]]
        assert "symbol" in param_names
        assert "days" in param_names

    def test_get_stock_correlation_has_params(self, client):
        r = client.get("/api/v1/preview/catalog")
        methods = _collect_methods(r.json())
        m = methods["get_stock_correlation"]
        assert m["params"] is not None
        assert len(m["params"]) == 2
        param_names = [p["name"] for p in m["params"]]
        assert "symbols" in param_names
        assert "days" in param_names

    def test_get_factor_ranking_has_params(self, client):
        r = client.get("/api/v1/preview/catalog")
        methods = _collect_methods(r.json())
        m = methods["get_factor_ranking"]
        assert m["params"] is not None
        assert len(m["params"]) == 4
        param_names = [p["name"] for p in m["params"]]
        assert "factor" in param_names
        assert "direction" in param_names
        assert "limit" in param_names
        assert "exchange" in param_names

    def test_generic_methods_have_null_params(self, client):
        r = client.get("/api/v1/preview/catalog")
        methods = _collect_methods(r.json())
        # get_money_flow has no custom _METHOD_PARAMS entry
        assert methods["get_money_flow"]["params"] is None
        # get_gdp_data has no custom _METHOD_PARAMS entry
        assert methods["get_gdp_data"]["params"] is None


class TestMethodParamDefaults:
    """Verify default values from _METHOD_PARAMS are present in catalog responses."""

    def test_stock_factors_defaults(self, client):
        r = client.get("/api/v1/preview/catalog")
        methods = _collect_methods(r.json())
        params = {p["name"]: p for p in methods["get_stock_factors"]["params"]}
        assert params["symbol"]["default"] == "600519"
        assert params["days"]["default"] == 250

    def test_stock_correlation_defaults(self, client):
        r = client.get("/api/v1/preview/catalog")
        methods = _collect_methods(r.json())
        params = {p["name"]: p for p in methods["get_stock_correlation"]["params"]}
        assert params["symbols"]["default"] == "600519,000858,000333"
        assert params["days"]["default"] == 60

    def test_factor_ranking_defaults(self, client):
        r = client.get("/api/v1/preview/catalog")
        methods = _collect_methods(r.json())
        params = {p["name"]: p for p in methods["get_factor_ranking"]["params"]}
        assert params["factor"]["default"] == "change_pct"
        assert params["direction"]["default"] == "desc"
        assert params["limit"]["default"] == 30
        assert params["exchange"]["default"] == ""

    def test_param_schema_fields(self, client):
        """Each param entry has required structural fields."""
        r = client.get("/api/v1/preview/catalog")
        methods = _collect_methods(r.json())
        for param in methods["get_stock_factors"]["params"]:
            assert "name" in param
            assert "type" in param
            assert "required" in param
            assert "label" in param


class TestPreviewQuantitativeQuery:
    """Verify quantitative methods work through /api/v1/preview/query."""

    def test_get_stock_factors_query(self, client):
        r = client.post("/api/v1/preview/query", json={
            "method": "get_stock_factors",
            "params": {"symbol": "600519"},
            "sources": ["auto"],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["method"] == "get_stock_factors"
        auto = data["results"]["auto"]
        assert auto["error"] is None
        assert auto["data"]["symbol"] == "600519"
        assert "factors" in auto["data"]

    def test_get_stock_factors_source_adapter(self, client):
        r = client.post("/api/v1/preview/query", json={
            "method": "get_stock_factors",
            "params": {"symbol": "600519"},
            "sources": ["akshare"],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["results"]["akshare"]["error"] is None
        assert data["results"]["akshare"]["data"]["symbol"] == "600519"

    def test_get_stock_correlation_query(self, client):
        r = client.post("/api/v1/preview/query", json={
            "method": "get_stock_correlation",
            "params": {"symbols": "600519,000858"},
            "sources": ["auto"],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["method"] == "get_stock_correlation"
        auto = data["results"]["auto"]
        assert auto["error"] is None
        assert "correlation" in auto["data"]

    def test_get_factor_ranking_query(self, client):
        r = client.post("/api/v1/preview/query", json={
            "method": "get_factor_ranking",
            "params": {"factor": "change_pct", "direction": "desc"},
            "sources": ["auto"],
        })
        assert r.status_code == 200
        data = r.json()
        auto = data["results"]["auto"]
        assert auto["error"] is None
        assert auto["data"]["factor"] == "change_pct"

    def test_get_stock_factors_symbol_remap(self, client, _patch_container):
        """Ticker methods remap 'symbol' -> 'raw_symbol' in auto dispatch."""
        gateway = _patch_container.market_gateway.return_value
        gateway.get_stock_factors = AsyncMock(return_value={"ok": True})

        r = client.post("/api/v1/preview/query", json={
            "method": "get_stock_factors",
            "params": {"symbol": "600519", "days": 120},
            "sources": ["auto"],
        })
        assert r.status_code == 200
        # Verify gateway was called with raw_symbol, not symbol
        call_kwargs = gateway.get_stock_factors.call_args[1]
        assert "raw_symbol" in call_kwargs
        assert call_kwargs["raw_symbol"] == "600519"
        assert "symbol" not in call_kwargs
        assert call_kwargs["days"] == 120


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_methods(catalog_json: dict) -> dict:
    """Flatten catalog categories into {method_name: method_info} dict."""
    result = {}
    for cat in catalog_json["categories"]:
        for m in cat["methods"]:
            result[m["name"]] = m
    return result
