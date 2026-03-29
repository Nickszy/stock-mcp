# tests/test_sector_research.py
"""Tests for the sector research REST API endpoints."""

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


def _payload(response):
    """Extract the inner data payload from rest_response envelope."""
    return response.json()["data"]["data"]


# ---------------------------------------------------------------------------
# Tests: /api/v1/sector-research/scope
# ---------------------------------------------------------------------------


class TestResolveSectorScope:
    def test_cn_sector_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/scope",
                json={"sector_name": "半导体", "market": "cn"},
            )
        assert r.status_code == 200
        data = _payload(r)
        assert data["scope"]["sector_name"] == "半导体"
        assert data["scope"]["market"] == "CN"
        assert len(data["recommended_tools"]) > 0

    def test_us_sector_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/scope",
                json={"sector_name": "Semiconductors", "market": "us"},
            )
        assert r.status_code == 200
        data = _payload(r)
        assert data["scope"]["market"] == "US"

    def test_auto_detect_from_cn_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/scope",
                json={"sector_name": "白酒", "market": "auto"},
            )
        assert r.status_code == 200
        assert _payload(r)["scope"]["market"] == "CN"


# ---------------------------------------------------------------------------
# Tests: /api/v1/sector-research/universe
# ---------------------------------------------------------------------------


class TestBuildSectorUniverse:
    def test_manual_symbols(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with patch(
            "src.server.api.routes.sector_research._resolve_symbols",
            new_callable=AsyncMock,
            return_value=["SSE:600519", "SZSE:000858"],
        ), patch(
            "src.server.api.routes.sector_research.market_use_cases.get_asset_info",
            new_callable=AsyncMock,
            side_effect=lambda t: {"name": "贵州茅台" if "600519" in t else "五粮液"},
        ), _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/universe",
                json={
                    "sector_name": "白酒",
                    "symbols": ["600519", "000858"],
                },
            )
        assert r.status_code == 200
        data = _payload(r)
        assert data["source"] == "manual"
        assert len(data["universe"]) == 2

    def test_cn_auto_universe_no_tushare(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with patch(
            "src.server.api.routes.sector_research._build_cn_universe_from_tushare",
            new_callable=AsyncMock,
            return_value={"universe": [], "source": "manual", "note": "no tushare"},
        ), _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/universe",
                json={"sector_name": "新能源", "market": "cn"},
            )
        assert r.status_code == 200
        data = _payload(r)
        assert data["source"] == "manual"


# ---------------------------------------------------------------------------
# Tests: /api/v1/sector-research/peer-benchmark
# ---------------------------------------------------------------------------


class TestBuildPeerBenchmark:
    def test_peer_benchmark(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with patch(
            "src.server.api.routes.sector_research._resolve_symbols",
            new_callable=AsyncMock,
            return_value=["SSE:600519"],
        ), patch(
            "src.server.api.routes.sector_research._build_peer_rows",
            new_callable=AsyncMock,
            return_value=[
                {
                    "ticker": "SSE:600519",
                    "company_name": "贵州茅台",
                    "pe": 30.5,
                    "market_cap": 2.1e12,
                }
            ],
        ), _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/peer-benchmark",
                json={"sector_name": "白酒", "symbols": ["600519"]},
            )
        assert r.status_code == 200
        data = _payload(r)
        assert data["sector_name"] == "白酒"
        assert len(data["rows"]) == 1

    def test_empty_symbols_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/peer-benchmark",
                json={"sector_name": "白酒", "symbols": []},
            )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests: /api/v1/sector-research/value-chain
# ---------------------------------------------------------------------------


class TestClassifyValueChain:
    def test_value_chain_classification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with patch(
            "src.server.api.routes.sector_research._resolve_symbols",
            new_callable=AsyncMock,
            return_value=["SSE:600519"],
        ), patch(
            "src.server.api.routes.sector_research.market_use_cases.get_asset_info",
            new_callable=AsyncMock,
            return_value={"name": "贵州茅台"},
        ), patch(
            "src.server.api.routes.sector_research.fundamental_use_cases.get_mainbz_info",
            new_callable=AsyncMock,
            return_value={"rows": [{"bz_item": "白酒销售"}]},
        ), _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/value-chain",
                json={"sector_name": "白酒", "symbols": ["SSE:600519"]},
            )
        assert r.status_code == 200
        data = _payload(r)
        assert "rows" in data
        assert "stage_counts" in data
        assert len(data["rows"]) == 1

    def test_empty_symbols_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/value-chain",
                json={"sector_name": "白酒", "symbols": []},
            )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests: /api/v1/sector-research/evidence-pack
# ---------------------------------------------------------------------------


class TestBuildEvidencePack:
    def test_evidence_pack_with_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with patch(
            "src.server.api.routes.sector_research._resolve_symbols",
            new_callable=AsyncMock,
            return_value=["SSE:600519"],
        ), patch(
            "src.server.api.routes.sector_research._build_peer_rows",
            new_callable=AsyncMock,
            return_value=[{"ticker": "SSE:600519", "pe": 30}],
        ), patch(
            "src.server.api.routes.sector_research.money_flow_use_cases.get_sector_trend",
            new_callable=AsyncMock,
            return_value={"total_pct_chg": 5.2},
        ), patch(
            "src.server.api.routes.sector_research.money_flow_use_cases.get_sector_valuation_metrics",
            new_callable=AsyncMock,
            return_value={"summary": {"valuation_level": "偏低"}},
        ), patch(
            "src.server.api.routes.sector_research.filings_use_cases.fetch_ashare_filings",
            new_callable=AsyncMock,
            return_value=[{"filing_date": "2025-01-01"}],
        ), _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/evidence-pack",
                json={
                    "sector_name": "白酒",
                    "symbols": ["SSE:600519"],
                    "market": "cn",
                },
            )
        assert r.status_code == 200
        data = _payload(r)
        assert "sector_snapshot" in data
        assert "peer_benchmark" in data
        assert "filings_digest" in data
        assert data["scope"]["market"] == "CN"


# ---------------------------------------------------------------------------
# Tests: /api/v1/sector-research/structure-snapshot
# ---------------------------------------------------------------------------


class TestBuildStructureSnapshot:
    def test_cn_structure_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with patch(
            "src.server.api.routes.sector_research.money_flow_use_cases.get_sector_trend",
            new_callable=AsyncMock,
            return_value={"total_pct_chg": 3.5},
        ), patch(
            "src.server.api.routes.sector_research.money_flow_use_cases.get_sector_money_flow_history",
            new_callable=AsyncMock,
            return_value={"summary": {"trend": "净流入"}},
        ), patch(
            "src.server.api.routes.sector_research.money_flow_use_cases.get_sector_valuation_metrics",
            new_callable=AsyncMock,
            return_value={"summary": {"valuation_level": "偏低"}},
        ), _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/structure-snapshot",
                json={"sector_name": "半导体", "market": "cn", "days": 60},
            )
        assert r.status_code == 200
        snap = _payload(r)["snapshot"]
        assert snap["sector_name"] == "半导体"
        assert snap["market"] == "CN"
        assert snap["structure_score"] == 3  # +1 momentum +1 flow +1 valuation

    def test_us_structure_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with patch(
            "src.server.api.routes.sector_research.technical_use_cases.get_us_sector_etf_analysis",
            new_callable=AsyncMock,
            return_value={"total_change_pct": -2.1},
        ), _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/structure-snapshot",
                json={"sector_name": "Technology", "market": "us"},
            )
        assert r.status_code == 200
        snap = _payload(r)["snapshot"]
        assert snap["market"] == "US"
        assert snap["structure_score"] == -1


# ---------------------------------------------------------------------------
# Tests: /api/v1/sector-research/quality-gate
# ---------------------------------------------------------------------------


class TestQualityGate:
    def test_passing_report(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/quality-gate",
                json={
                    "report_markdown": (
                        "## 执行摘要\n半导体行业增长 15.2% , 市场规模达 450 亿.\n\n"
                        "## 风险与失效条件\nPE为 28.5 x, 注意回调风险.\n\n"
                        "## 结论与下一步\n是否继续加仓？"
                    ),
                    "evidence_pack": {
                        "peer_benchmark": [1, 2, 3],
                        "filings_digest": [{"ticker": "TEST"}],
                        "universe": ["SSE:600519"],
                    },
                    "min_numeric_facts": 3,
                },
            )
        assert r.status_code == 200
        data = _payload(r)
        assert data["pass"] is True
        assert data["failed_checks"] == []

    def test_failing_report(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with _build_client(monkeypatch) as client:
            r = client.post(
                "/api/v1/sector-research/quality-gate",
                json={
                    "report_markdown": "This is a minimal report.",
                    "evidence_pack": None,
                },
            )
        assert r.status_code == 200
        data = _payload(r)
        assert data["pass"] is False
        assert len(data["failed_checks"]) > 0
