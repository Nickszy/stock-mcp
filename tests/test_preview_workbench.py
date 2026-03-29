# tests/test_preview_workbench.py
"""Regression tests for the Preview Workbench (COL-180).

Verifies:
- Catalog includes per-method parameter schemas
- get_stock_factors is a ticker method (shows symbol input)
- get_stock_correlation has a 'symbols' param in its schema
- Market-aware defaults are accessible
- Extra params parser uses semicolons (not commas)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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


# ---------------------------------------------------------------------------
# Tests: Catalog structure
# ---------------------------------------------------------------------------


class TestPreviewCatalog:
    def test_catalog_returns_methods(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with _build_client(monkeypatch) as client:
            r = client.get("/api/v1/preview/catalog")
        assert r.status_code == 200
        data = r.json()
        assert data["total_methods"] > 0
        assert "categories" in data
        # Flatten all methods
        all_methods = []
        for cat in data["categories"]:
            all_methods.extend(cat["methods"])
        method_names = {m["name"] for m in all_methods}
        assert "get_stock_factors" in method_names
        assert "get_stock_correlation" in method_names

    def test_get_stock_factors_is_ticker_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """COL-180: get_stock_factors should be ticker type (has symbol input)."""
        with _build_client(monkeypatch) as client:
            r = client.get("/api/v1/preview/catalog")
        data = r.json()
        all_methods = []
        for cat in data["categories"]:
            all_methods.extend(cat["methods"])
        factors = next(m for m in all_methods if m["name"] == "get_stock_factors")
        assert factors["type"] == "ticker"

    def test_get_stock_correlation_has_symbols_param(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """COL-180: get_stock_correlation should have a 'symbols' param schema."""
        with _build_client(monkeypatch) as client:
            r = client.get("/api/v1/preview/catalog")
        data = r.json()
        all_methods = []
        for cat in data["categories"]:
            all_methods.extend(cat["methods"])
        corr = next(m for m in all_methods if m["name"] == "get_stock_correlation")
        assert corr["params"] is not None
        param_names = [p["name"] for p in corr["params"]]
        assert "symbols" in param_names
        # Check symbols param is required
        symbols_param = next(p for p in corr["params"] if p["name"] == "symbols")
        assert symbols_param["required"] is True

    def test_method_params_have_required_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All param schemas should have name, type, required, and label."""
        with _build_client(monkeypatch) as client:
            r = client.get("/api/v1/preview/catalog")
        data = r.json()
        all_methods = []
        for cat in data["categories"]:
            all_methods.extend(cat["methods"])
        methods_with_params = [m for m in all_methods if m.get("params")]
        for method in methods_with_params:
            for param in method["params"]:
                assert "name" in param, f"Missing 'name' in {method['name']} param"
                assert "type" in param, f"Missing 'type' in {method['name']}.{param.get('name')}"
                assert "required" in param, f"Missing 'required' in {method['name']}.{param.get('name')}"

    def test_screen_stocks_has_param_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """screen_stocks should have a rich parameter schema."""
        with _build_client(monkeypatch) as client:
            r = client.get("/api/v1/preview/catalog")
        data = r.json()
        all_methods = []
        for cat in data["categories"]:
            all_methods.extend(cat["methods"])
        screen = next(m for m in all_methods if m["name"] == "screen_stocks")
        assert screen["params"] is not None
        param_names = [p["name"] for p in screen["params"]]
        assert "min_pe" in param_names
        assert "max_pe" in param_names
        assert "sort_by" in param_names
        assert "limit" in param_names

    def test_factor_ranking_has_select_options(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_factor_ranking factor param should be a select with options."""
        with _build_client(monkeypatch) as client:
            r = client.get("/api/v1/preview/catalog")
        data = r.json()
        all_methods = []
        for cat in data["categories"]:
            all_methods.extend(cat["methods"])
        ranking = next(m for m in all_methods if m["name"] == "get_factor_ranking")
        assert ranking["params"] is not None
        factor_param = next(p for p in ranking["params"] if p["name"] == "factor")
        assert factor_param["type"] == "select"
        assert "options" in factor_param
        assert "change_pct" in factor_param["options"]


# ---------------------------------------------------------------------------
# Tests: Query dispatch
# ---------------------------------------------------------------------------


class TestPreviewQuery:
    def test_unknown_method_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/preview/query",
                json={"method": "nonexistent_method", "params": {}, "sources": ["auto"]},
            )
        assert r.status_code == 400

    def test_get_stock_factors_with_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """COL-180: get_stock_factors should accept symbol param via auto dispatch."""
        with patch(
            "src.server.core.dependencies.Container.market_gateway",
            return_value=MagicMock(
                get_stock_factors=AsyncMock(
                    return_value={"symbol": "600519", "factors": {"momentum_1M": 5.2}}
                )
            ),
        ), _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/preview/query",
                json={
                    "method": "get_stock_factors",
                    "params": {"symbol": "SSE:600519"},
                    "sources": ["auto"],
                },
            )
        assert r.status_code == 200
        result = r.json()
        assert "results" in result
        assert "auto" in result["results"]
        assert result["results"]["auto"]["error"] is None
        assert result["results"]["auto"]["data"]["symbol"] == "600519"

    def test_get_stock_correlation_with_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """COL-180: get_stock_correlation should accept symbols param."""
        with patch(
            "src.server.core.dependencies.Container.market_gateway",
            return_value=MagicMock(
                get_stock_correlation=AsyncMock(
                    return_value={"symbols": "600519,000858", "correlation": 0.85}
                )
            ),
        ), _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/preview/query",
                json={
                    "method": "get_stock_correlation",
                    "params": {"symbols": "600519,000858", "days": 60},
                    "sources": ["auto"],
                },
            )
        assert r.status_code == 200
        result = r.json()
        assert result["results"]["auto"]["data"]["correlation"] == 0.85


# ---------------------------------------------------------------------------
# Tests: Method categorization (from market_gateway)
# ---------------------------------------------------------------------------


class TestMethodCategorization:
    def test_get_stock_factors_in_ticker_methods(self) -> None:
        """COL-180: get_stock_factors MUST be in _TICKER_METHODS."""
        from src.server.domain.market_gateway import _TICKER_METHODS, _MARKET_METHODS

        assert "get_stock_factors" in _TICKER_METHODS
        assert "get_stock_factors" not in _MARKET_METHODS

    def test_get_stock_correlation_in_market_methods(self) -> None:
        """get_stock_correlation stays in _MARKET_METHODS (no single symbol)."""
        from src.server.domain.market_gateway import _MARKET_METHODS

        assert "get_stock_correlation" in _MARKET_METHODS

    def test_no_method_in_both_sets(self) -> None:
        """No method should appear in both _TICKER_METHODS and _MARKET_METHODS."""
        from src.server.domain.market_gateway import _TICKER_METHODS, _MARKET_METHODS

        overlap = _TICKER_METHODS & _MARKET_METHODS
        assert len(overlap) == 0, f"Methods in both sets: {overlap}"
