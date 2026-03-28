# tests/test_us_fundamental_new.py
"""Tests for the 5 new US fundamental MCP tools.

Validates:
1. Adapter methods return correct structure
2. Use case layer delegates properly
3. Registry and ComponentType updates
4. Gateway method registration

Run: uv run pytest tests/test_us_fundamental_new.py -v
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, ".")


# ---- Mock Infrastructure ----


class MockCache:
    _store: Dict[str, Any] = {}

    async def get(self, key: str):
        return MockCache._store.get(key)

    async def set(self, key: str, value: Any, ttl: int = 0):
        MockCache._store[key] = value


@pytest.fixture
def mock_cache():
    MockCache._store = {}
    return MockCache()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_mock_run(ticker_obj):
    """Create a mock _run that returns ticker_obj for yf.Ticker calls
    and executes lambdas otherwise."""
    async def mock_run(func, *args, **kwargs):
        # yf.Ticker constructor: func is the class, args has ticker string
        if func.__name__ == "Ticker" if hasattr(func, "__name__") else False:
            return ticker_obj
        # lambda / callable: execute it
        if callable(func):
            return func()
        return func
    return AsyncMock(side_effect=mock_run)


# ---- Adapter Tests ----


class TestYahooAdapterNewMethods:
    """Test new adapter methods in YahooAdapter."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.yahoo_adapter import YahooAdapter
        return YahooAdapter(mock_cache)

    def test_get_us_company_profile_structure(self, adapter):
        """get_us_company_profile should return expected keys."""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "longName": "Apple Inc.",
            "shortName": "AAPL",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "country": "US",
            "city": "Cupertino",
            "fullTimeEmployees": 164000,
            "longBusinessSummary": "Apple designs smartphones, PCs, tablets...",
            "marketCap": 3500000000000,
            "enterpriseValue": 3400000000000,
            "trailingPE": 30.5,
            "forwardPE": 28.0,
            "priceToBook": 55.0,
            "dividendYield": 0.005,
            "beta": 1.2,
            "fiftyTwoWeekHigh": 260.0,
            "fiftyTwoWeekLow": 165.0,
            "currency": "USD",
            "exchange": "NMS",
            "companyOfficers": [{"name": "Tim Cook", "title": "Chief Executive Officer"}],
        }

        with patch.object(adapter, "_run", _make_mock_run(mock_ticker)):
            result = _run(adapter.get_us_company_profile("NASDAQ:AAPL"))

        assert result["ticker"] == "NASDAQ:AAPL"
        assert result["name"] == "Apple Inc."
        assert result["sector"] == "Technology"
        assert result["industry"] == "Consumer Electronics"
        assert result["employees"] == 164000
        assert result["market_cap"] == 3500000000000
        assert result["pe_ttm"] == 30.5
        assert result["ceo"] == "Tim Cook"
        assert result["description"] == "Apple designs smartphones, PCs, tablets..."

    def test_get_us_analyst_recommendations_structure(self, adapter):
        """get_us_analyst_recommendations should return expected keys."""
        import pandas as pd

        rec_df = pd.DataFrame({
            "period": ["0m", "-1m", "-2m"],
            "strongBuy": [15, 14, 13],
            "buy": [10, 11, 12],
            "hold": [8, 9, 7],
            "sell": [3, 2, 4],
            "strongSell": [2, 2, 2],
        })
        summary_df = pd.DataFrame({
            "strongBuy": [15],
            "buy": [10],
            "hold": [8],
            "sell": [3],
            "strongSell": [2],
        })
        upgrades_df = pd.DataFrame({
            "GradeDate": ["2026-03-15", "2026-03-10"],
            "Firm": ["Morgan Stanley", "Goldman Sachs"],
            "From Grade": ["Equal-Weight", "Neutral"],
            "To Grade": ["Overweight", "Buy"],
            "Action": ["up", "up"],
        })

        mock_ticker = MagicMock()
        mock_ticker.info = {
            "targetHighPrice": 250.0,
            "targetLowPrice": 150.0,
            "targetMeanPrice": 200.0,
            "targetMedianPrice": 195.0,
            "currentPrice": 180.0,
            "numberOfAnalystOpinions": 38,
        }

        def mock_fetch():
            return rec_df, summary_df, upgrades_df, mock_ticker.info

        call_count = [0]

        async def mock_run(func, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: yf.Ticker(ticker_norm)
                mock_ticker.recommendations = rec_df
                mock_ticker.recommendations_summary = summary_df
                mock_ticker.upgrades_downgrades = upgrades_df
                return mock_ticker
            if callable(func):
                return func()
            return func

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_us_analyst_recommendations("NASDAQ:AAPL"))

        assert result["ticker"] == "NASDAQ:AAPL"
        assert "target_price" in result
        assert result["target_price"]["mean"] == 200.0
        assert result["current_price"] == 180.0
        assert result["num_analysts"] == 38
        assert isinstance(result["recommendations"], list)
        assert isinstance(result["upgrade_history"], list)

    def test_get_us_revenue_segments_structure(self, adapter):
        """get_us_revenue_segments should return expected keys."""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "longName": "Apple Inc.",
            "totalRevenue": 383285000000,
            "currency": "USD",
        }

        with patch.object(adapter, "_run", _make_mock_run(mock_ticker)):
            result = _run(adapter.get_us_revenue_segments("NASDAQ:AAPL"))

        assert result["ticker"] == "NASDAQ:AAPL"
        assert result["name"] == "Apple Inc."
        assert result["total_revenue"] == 383285000000
        assert "geographic_segments" in result
        assert "business_segments" in result

    def test_get_us_insider_trading_structure(self, adapter):
        """get_us_insider_trading should return expected keys."""
        import pandas as pd

        mock_ticker = MagicMock()
        mock_ticker.insider_purchases = pd.DataFrame()
        mock_ticker.insider_transactions = pd.DataFrame()

        call_count = [0]

        async def mock_run(func, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_ticker
            if callable(func):
                return func()
            return func

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_us_insider_trading("NASDAQ:AAPL"))

        assert result["ticker"] == "NASDAQ:AAPL"
        assert "purchases" in result
        assert "transactions" in result
        assert "summary" in result
        assert "net_sentiment" in result["summary"]

    def test_get_us_share_statistics_structure(self, adapter):
        """get_us_share_statistics should return expected keys."""
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "longName": "Tesla, Inc.",
            "sharesOutstanding": 3200000000,
            "floatShares": 2900000000,
            "sharesShort": 95000000,
            "shortRatio": 1.5,
            "shortPercentOfFloat": 0.0328,
            "heldPercentInstitutions": 0.66,
            "heldPercentInsiders": 0.13,
            "averageVolume": 63000000,
        }
        mock_ticker.shares = MagicMock()
        mock_ticker.shares.empty = True

        call_count = [0]

        async def mock_run(func, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_ticker
            if callable(func):
                return func()
            return func

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_us_share_statistics("NASDAQ:TSLA"))

        assert result["ticker"] == "NASDAQ:TSLA"
        assert "short_interest" in result
        assert "ownership" in result
        assert result["short_interest"]["shares_short"] == 95000000


# ---- Use Case Layer Tests ----


class TestUseCaseDelegates:
    """Verify use case delegates exist and are callable."""

    def test_company_profile_usecase_exists(self):
        from src.server.core.use_cases import fundamental as fu
        assert hasattr(fu, "get_us_company_profile")
        assert callable(fu.get_us_company_profile)

    def test_analyst_recommendations_usecase_exists(self):
        from src.server.core.use_cases import fundamental as fu
        assert hasattr(fu, "get_us_analyst_recommendations")
        assert callable(fu.get_us_analyst_recommendations)

    def test_revenue_segments_usecase_exists(self):
        from src.server.core.use_cases import fundamental as fu
        assert hasattr(fu, "get_us_revenue_segments")
        assert callable(fu.get_us_revenue_segments)

    def test_insider_trading_usecase_exists(self):
        from src.server.core.use_cases import fundamental as fu
        assert hasattr(fu, "get_us_insider_trading")
        assert callable(fu.get_us_insider_trading)

    def test_share_statistics_usecase_exists(self):
        from src.server.core.use_cases import fundamental as fu
        assert hasattr(fu, "get_us_share_statistics")
        assert callable(fu.get_us_share_statistics)

    def test_financial_health_usecase_exists(self):
        from src.server.core.use_cases import fundamental as fu
        assert hasattr(fu, "get_us_financial_health")
        assert callable(fu.get_us_financial_health)


class TestYahooAdapterFinancialHealth:
    """Test the get_us_financial_health method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.yahoo_adapter import YahooAdapter
        return YahooAdapter(mock_cache)

    def test_health_score_computation(self, adapter):
        """get_us_financial_health should return score with all sections."""
        mock_info = {
            "longName": "Apple Inc.",
            "shortName": "AAPL",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "marketCap": 3500000000000,
            "grossMargins": 0.46,
            "operatingMargins": 0.32,
            "profitMargins": 0.26,
            "returnOnEquity": 1.60,
            "returnOnAssets": 0.28,
            "currentRatio": 0.87,
            "quickRatio": 0.80,
            "debtToEquity": 1.87,
            "trailingPE": 33.5,
            "forwardPE": 28.0,
            "priceToBook": 55.0,
            "priceToSalesTrailing12Months": 9.0,
            "enterpriseToEbitda": 24.0,
            "pegRatio": 2.8,
            "revenueGrowth": 0.05,
            "earningsGrowth": 0.10,
            "revenuePerShare": 24.5,
            "trailingEps": 6.5,
            "dividendYield": 0.005,
            "payoutRatio": 0.15,
            "dividendRate": 0.96,
        }

        mock_ticker = MagicMock()
        mock_ticker.info = mock_info

        with patch.object(adapter, "_run", _make_mock_run(mock_ticker)):
            result = _run(adapter.get_us_financial_health("NASDAQ:AAPL"))

        assert result["ticker"] == "NASDAQ:AAPL"
        assert result["name"] == "Apple Inc."
        assert "health_score" in result
        assert 0 <= result["health_score"] <= 100
        assert "grade" in result
        assert "grade_label" in result
        assert "profitability" in result
        assert "liquidity" in result
        assert "solvency" in result
        assert "valuation" in result
        assert "growth" in result
        assert "dividend" in result
        assert "score_breakdown" in result
        assert "key_findings" in result
        # Check specific values
        assert result["profitability"]["net_margin"] == 26.0
        assert result["profitability"]["roe"] == 160.0
        assert result["liquidity"]["current_ratio"] == 0.87


class TestRegistryFinancialHealth:
    """Verify registry includes health tool."""

    def test_us_fundamental_count_with_health(self):
        from src.server.mcp.registry import TOOL_GROUPS
        us_fund = [g for g in TOOL_GROUPS if g.name == "us-fundamental"]
        assert len(us_fund) == 1
        assert us_fund[0].count == 10

    def test_financial_health_usecase_exists(self):
        from src.server.core.use_cases import fundamental as fu
        assert hasattr(fu, "get_us_financial_health")
        assert callable(fu.get_us_financial_health)


# ---- Registry Tests ----


class TestRegistryUpdated:
    """Verify registry reflects new tool counts."""

    def test_us_fundamental_tool_count(self):
        from src.server.mcp.registry import TOOL_GROUPS
        us_fund = [g for g in TOOL_GROUPS if g.name == "us-fundamental"]
        assert len(us_fund) == 1
        assert us_fund[0].count == 10
        assert us_fund[0].enabled is True

    def test_total_enabled_tool_count_increased(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # Should be at least 84 (original 78 + 6 new: 5 + health score)
        assert total >= 84, f"Expected >= 84, got {total}"


# ---- ComponentType Tests ----


class TestComponentTypes:
    """Verify new ComponentType enums exist."""

    def test_new_component_types_exist(self):
        from src.server.mcp.tools.artifact_utils import ComponentType
        assert ComponentType.US_COMPANY_PROFILE.value == "us_company_profile"
        assert ComponentType.US_ANALYST_RECOMMENDATIONS.value == "us_analyst_recommendations"
        assert ComponentType.US_REVENUE_SEGMENTS.value == "us_revenue_segments"
        assert ComponentType.US_INSIDER_TRADING.value == "us_insider_trading"
        assert ComponentType.US_SHARE_STATISTICS.value == "us_share_statistics"


# ---- Gateway Method Registration Tests ----


class TestGatewayRegistration:
    """Verify new methods are registered in MarketGateway."""

    def test_new_methods_in_ticker_methods(self):
        from src.server.domain.market_gateway import _TICKER_METHODS
        assert "get_us_company_profile" in _TICKER_METHODS
        assert "get_us_analyst_recommendations" in _TICKER_METHODS
        assert "get_us_revenue_segments" in _TICKER_METHODS
        assert "get_us_insider_trading" in _TICKER_METHODS
        assert "get_us_share_statistics" in _TICKER_METHODS
