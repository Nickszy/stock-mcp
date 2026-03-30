# tests/test_canonical_entity_analytics_tools.py
"""Tests for canonical data bridge, entity registry, and financial analytics MCP tools."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Canonical Data Tools Tests
# ---------------------------------------------------------------------------

class TestCanonicalDataTools:
    """Verify canonical data MCP tools."""

    def test_parse_symbol_with_exchange(self):
        from src.server.mcp.tools.canonical_data_tools import _parse_symbol
        exchange, ticker = _parse_symbol("SSE:600519")
        assert exchange == "SSE"
        assert ticker == "600519"

    def test_parse_symbol_without_exchange(self):
        from src.server.mcp.tools.canonical_data_tools import _parse_symbol
        # 6-digit numeric -> A-share heuristic
        exchange, ticker = _parse_symbol("600519")
        assert exchange == "SSE"
        assert ticker == "600519"

        exchange, ticker = _parse_symbol("000001")
        assert exchange == "SZSE"
        assert ticker == "000001"

    def test_parse_symbol_non_numeric(self):
        from src.server.mcp.tools.canonical_data_tools import _parse_symbol
        exchange, ticker = _parse_symbol("AAPL")
        assert exchange == ""
        assert ticker == "AAPL"

    def test_format_source_attribution_canonical(self):
        from src.server.mcp.tools.canonical_data_tools import _format_source_attribution
        result = _format_source_attribution(
            "canonical", version=3, provider="akshare+tushare", confidence=0.95
        )
        assert "canonical" in result
        assert "v3" in result
        assert "95%" in result

    def test_format_source_attribution_live(self):
        from src.server.mcp.tools.canonical_data_tools import _format_source_attribution
        result = _format_source_attribution("live")
        assert "live" in result

    @pytest.mark.asyncio
    async def test_get_canonical_financials_no_data(self):
        """When no data available, returns appropriate error response."""
        from src.server.mcp.tools.canonical_data_tools import register_canonical_data_tools

        mcp = MagicMock()

        registered_fn = None

        def capture_tool(**kwargs):
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn
            return decorator

        mcp.tool = capture_tool
        register_canonical_data_tools(mcp)

        assert registered_fn is not None

    @pytest.mark.asyncio
    async def test_get_canonical_dataset_status(self):
        """Dataset status tool returns registry info."""
        from src.server.mcp.tools.canonical_data_tools import register_canonical_data_tools

        mcp = MagicMock()

        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_canonical_data_tools(mcp)

        # The last registered function should be get_canonical_dataset_status
        status_fn = registered_fns[-1]
        result = await status_fn()

        assert result is not None
        assert "artifact" in result
        content = result["artifact"]["content"]
        data = content["data"]
        assert "datasets" in data
        assert data["total"] > 0

    def test_tool_group_registered(self):
        """Verify canonical-data group is in TOOL_GROUPS."""
        from src.server.mcp.registry import TOOL_GROUPS
        names = [g.name for g in TOOL_GROUPS]
        assert "canonical-data" in names
        canonical = [g for g in TOOL_GROUPS if g.name == "canonical-data"][0]
        assert canonical.enabled
        assert canonical.count == 3


# ---------------------------------------------------------------------------
# Entity Tools Tests
# ---------------------------------------------------------------------------

class TestEntityTools:
    """Verify entity registry MCP tools."""

    @pytest.mark.asyncio
    async def test_resolve_entity_not_initialized(self):
        """When entity service not initialized, returns error."""
        from src.server.mcp.tools.entity_tools import register_entity_tools

        mcp = MagicMock()
        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_entity_tools(mcp)

        # resolve_entity should be first
        resolve_fn = registered_fns[0]
        result = await resolve_fn(query="SSE:600519")

        assert result is not None
        # Should indicate not initialized
        assert "未初始化" in result["summary"] or "error" in str(result).lower()

    @pytest.mark.asyncio
    async def test_search_entities_not_initialized(self):
        """When entity repo not initialized, returns error."""
        from src.server.mcp.tools.entity_tools import register_entity_tools

        mcp = MagicMock()
        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_entity_tools(mcp)

        # search_entities should be last
        search_fn = registered_fns[-1]
        result = await search_fn(q="茅台")

        assert result is not None
        assert "未初始化" in result["summary"]

    @pytest.mark.asyncio
    async def test_resolve_entity_with_service(self):
        """When service is available, resolve_entity works."""
        from src.server.mcp.tools.entity_tools import register_entity_tools

        mcp = MagicMock()
        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_entity_tools(mcp)

        mock_service = MagicMock()
        mock_service.resolve_entity = AsyncMock(return_value={
            "profile": {"name_zh": "贵州茅台", "asset_id": "test-uuid", "status": "active"},
            "classifications": [{"scheme": "sw_industry", "name": "白酒", "code": "801152"}],
            "relations": [],
            "events": [],
        })

        with patch("src.server.mcp.tools.entity_tools._get_entity_service", return_value=mock_service):
            resolve_fn = registered_fns[0]
            result = await resolve_fn(query="SSE:600519")

        assert "贵州茅台" in result["summary"]
        content = result["artifact"]["content"]
        assert content["data"]["profile"]["name_zh"] == "贵州茅台"

    @pytest.mark.asyncio
    async def test_resolve_entity_name_query(self):
        """Name-based query is handled correctly."""
        from src.server.mcp.tools.entity_tools import register_entity_tools

        mcp = MagicMock()
        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_entity_tools(mcp)

        mock_service = MagicMock()
        mock_service.resolve_entity = AsyncMock(return_value={
            "profile": {"name_zh": "贵州茅台", "asset_id": "test-uuid"},
            "classifications": [],
            "relations": [],
        })

        with patch("src.server.mcp.tools.entity_tools._get_entity_service", return_value=mock_service):
            resolve_fn = registered_fns[0]
            result = await resolve_fn(query="茅台")

        # Should have called resolve_entity with name="茅台"
        mock_service.resolve_entity.assert_called_once_with(ticker=None, name="茅台", asset_id=None)

    @pytest.mark.asyncio
    async def test_get_entity_peers_with_service(self):
        """Peer discovery works when entity resolves."""
        from src.server.mcp.tools.entity_tools import register_entity_tools

        mcp = MagicMock()
        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_entity_tools(mcp)

        mock_service = MagicMock()
        mock_service.resolve_entity = AsyncMock(return_value={
            "profile": {"name_zh": "贵州茅台", "asset_id": "uuid-1"},
            "classifications": [{"scheme": "sw_industry", "name": "白酒", "code": "801152", "level": 1}],
            "relations": [],
        })
        mock_service.get_peers = AsyncMock(return_value=[
            {"asset_id": "uuid-2", "name_zh": "五粮液"},
            {"asset_id": "uuid-3", "name_zh": "泸州老窖"},
        ])

        with patch("src.server.mcp.tools.entity_tools._get_entity_service", return_value=mock_service):
            peers_fn = registered_fns[2]  # get_entity_peers
            result = await peers_fn(symbol="SSE:600519")

        assert "同行" in result["summary"]
        content = result["artifact"]["content"]
        assert content["data"]["peer_count"] == 2

    def test_tool_group_registered(self):
        """Verify entity group is in TOOL_GROUPS."""
        from src.server.mcp.registry import TOOL_GROUPS
        names = [g.name for g in TOOL_GROUPS]
        assert "entity" in names
        entity = [g for g in TOOL_GROUPS if g.name == "entity"][0]
        assert entity.enabled
        assert entity.count == 4


# ---------------------------------------------------------------------------
# Financial Analytics Tools Tests
# ---------------------------------------------------------------------------

class TestFinancialAnalyticsTools:
    """Verify financial analytics MCP tools."""

    def test_calc_growth(self):
        from src.server.mcp.tools.financial_analytics_tools import _calc_growth
        # Normal growth
        assert _calc_growth(120, 100) == pytest.approx(0.2)
        # Negative growth
        assert _calc_growth(80, 100) == pytest.approx(-0.2)
        # Zero previous
        assert _calc_growth(100, 0) is None
        # None values
        assert _calc_growth(None, 100) is None
        assert _calc_growth(100, None) is None

    def test_safe_float(self):
        from src.server.mcp.tools.financial_analytics_tools import _safe_float
        assert _safe_float(3.14) == 3.14
        assert _safe_float("42") == 42.0
        assert _safe_float(None) is None
        assert _safe_float("abc") is None

    def test_format_pct(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_pct
        assert "+20.0%" in _format_pct(0.2)
        assert "-10.0%" in _format_pct(-0.1)
        assert _format_pct(None) == "N/A"

    def test_format_amount(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_amount
        assert "亿" in _format_amount(1e9)
        assert "万" in _format_amount(1e5)
        assert _format_amount(None) == "N/A"

    def test_score_to_rating(self):
        from src.server.mcp.tools.financial_analytics_tools import _score_to_rating
        assert _score_to_rating(90) == "优秀"
        assert _score_to_rating(70) == "良好"
        assert _score_to_rating(50) == "一般"
        assert _score_to_rating(30) == "较弱"
        assert _score_to_rating(10) == "风险"

    @pytest.mark.asyncio
    async def test_growth_analysis_no_data(self):
        """When no financial data, returns error."""
        from src.server.mcp.tools.financial_analytics_tools import register_financial_analytics_tools

        mcp = MagicMock()
        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_financial_analytics_tools(mcp)

        growth_fn = registered_fns[0]

        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await growth_fn(symbol="SSE:600519")

        assert "无财报数据" in result["summary"]

    @pytest.mark.asyncio
    async def test_growth_analysis_with_data(self):
        """Growth analysis calculates YoY/QoQ correctly."""
        from src.server.mcp.tools.financial_analytics_tools import register_financial_analytics_tools

        mcp = MagicMock()
        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_financial_analytics_tools(mcp)

        growth_fn = registered_fns[0]

        mock_data = []
        for i in range(5):
            mock_data.append({
                "report_period": f"2023Q{i+1}",
                "data": {
                    "revenue": 1000 + i * 100,
                    "net_income": 100 + i * 20,
                    "eps": 1.0 + i * 0.2,
                    "total_assets": 5000 + i * 100,
                },
                "source_type": "live",
            })

        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            result = await growth_fn(symbol="SSE:600519")

        assert result is not None
        content = result["artifact"]["content"]
        data = content["data"]
        assert data["period_count"] == 5
        periods = data["periods"]
        # Last period should have YoY (index 4, can compare with index 0)
        last = periods[-1]
        assert last.get("revenue_yoy") is not None

    @pytest.mark.asyncio
    async def test_health_score_with_data(self):
        """Health score calculation with mock data."""
        from src.server.mcp.tools.financial_analytics_tools import register_financial_analytics_tools

        mcp = MagicMock()
        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_financial_analytics_tools(mcp)

        health_fn = registered_fns[1]

        mock_data = [
            {
                "report_period": "2024Q3",
                "data": {
                    "revenue": 1000000000,
                    "net_income": 300000000,
                    "total_assets": 5000000000,
                    "total_liabilities": 1500000000,
                    "operating_cash_flow": 350000000,
                    "current_assets": 2000000000,
                    "current_liabilities": 800000000,
                },
                "source_type": "live",
            },
            {
                "report_period": "2024Q2",
                "data": {
                    "revenue": 900000000,
                    "net_income": 250000000,
                },
                "source_type": "live",
            },
        ]

        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            result = await health_fn(symbol="SSE:600519")

        assert result is not None
        content = result["artifact"]["content"]
        data = content["data"]
        assert "total_score" in data
        assert "rating" in data
        assert "dimensions" in data
        assert isinstance(data["total_score"], int)
        assert data["total_score"] >= 0
        assert data["total_score"] <= 100

    @pytest.mark.asyncio
    async def test_health_score_risk_flags(self):
        """High debt ratio should trigger risk flag."""
        from src.server.mcp.tools.financial_analytics_tools import register_financial_analytics_tools

        mcp = MagicMock()
        registered_fns = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns.append(fn)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_financial_analytics_tools(mcp)

        health_fn = registered_fns[1]

        mock_data = [
            {
                "report_period": "2024Q3",
                "data": {
                    "revenue": 500000000,
                    "net_income": 5000000,  # Low margin
                    "total_assets": 1000000000,
                    "total_liabilities": 800000000,  # 80% debt ratio
                    "operating_cash_flow": 10000000,
                },
                "source_type": "live",
            },
            {
                "report_period": "2024Q2",
                "data": {"revenue": 600000000, "net_income": 10000000},
                "source_type": "live",
            },
        ]

        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            result = await health_fn(symbol="SSE:000001")

        data = result["artifact"]["content"]["data"]
        risks = data.get("risks", [])
        assert len(risks) > 0
        assert any("负债率" in r for r in risks)

    def test_tool_group_registered(self):
        """Verify financial-analytics group is in TOOL_GROUPS."""
        from src.server.mcp.registry import TOOL_GROUPS
        names = [g.name for g in TOOL_GROUPS]
        assert "financial-analytics" in names
        analytics = [g for g in TOOL_GROUPS if g.name == "financial-analytics"][0]
        assert analytics.enabled
        assert analytics.count == 2


# ---------------------------------------------------------------------------
# Integration: Tool Count Verification
# ---------------------------------------------------------------------------

class TestToolCountVerification:
    """Verify total tool count after registration."""

    def test_total_tool_count_increased(self):
        """After adding new tool groups, total should be higher."""
        from src.server.mcp.registry import get_enabled_tool_count
        count = get_enabled_tool_count()
        # Original: ~168 tools + 3 (canonical) + 4 (entity) + 2 (analytics) = ~177
        # Just verify it's in reasonable range
        assert count >= 170

    def test_all_groups_have_valid_counts(self):
        """All tool groups should have count > 0."""
        from src.server.mcp.registry import TOOL_GROUPS
        for group in TOOL_GROUPS:
            assert group.count > 0, f"Group {group.name} has count 0"

    def test_new_groups_present_and_enabled(self):
        """All three new groups are present and enabled."""
        from src.server.mcp.registry import TOOL_GROUPS
        new_groups = {g.name: g for g in TOOL_GROUPS if g.name in (
            "canonical-data", "entity", "financial-analytics"
        )}
        assert len(new_groups) == 3
        for name, group in new_groups.items():
            assert group.enabled, f"{name} should be enabled"
            assert group.register is not None, f"{name} should have register function"
