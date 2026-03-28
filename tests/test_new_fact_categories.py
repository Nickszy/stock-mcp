# tests/test_new_fact_categories.py
"""Focused tests for new fact pack categories (COL-163).

Covers data transformation logic for:
  - get_technical_signals: RSI/MACD/BOLL signal derivation
  - company_master: field mapping from stock_individual_info_em
  - peers: market cap sorting, top N, exclude self
  - fees: fee field extraction from fund detail
  - peer_comparison: exclude self + same-type ranking

Run: uv run pytest tests/test_new_fact_categories.py -v
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, ".")


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


# =====================================================================
# get_technical_signals
# =====================================================================


class TestTechnicalSignals:
    """Verify get_technical_signals deterministic signal logic."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def _mock_tech_data(self, rsi14_val=None, macd_curr=None, macd_prev=None,
                        boll=None, latest_close=None, latest_date="2026-03-28"):
        """Build mock data from calculate_technical_indicators output."""
        data = {}
        if rsi14_val is not None:
            data["rsi14"] = [{"value": rsi14_val, "date": "2026-03-28"}]
        if macd_curr is not None:
            data["macd"] = [macd_prev, macd_curr]
        if boll is not None:
            data["boll"] = [boll]
        return {
            "data": data,
            "latest_close": latest_close,
            "latest_date": latest_date,
        }

    def test_rsi_overbought(self, adapter):
        """RSI(14) > 70 should signal RSI超买区."""
        mock_result = self._mock_tech_data(rsi14_val=78.5)
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["rsi"]["signal"] == "RSI超买区"
        assert result["signals"]["rsi"]["value"] == 78.5
        assert result["signals"]["rsi"]["threshold_overbought"] == 70

    def test_rsi_oversold(self, adapter):
        """RSI(14) < 30 should signal RSI超卖区."""
        mock_result = self._mock_tech_data(rsi14_val=22.1)
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["rsi"]["signal"] == "RSI超卖区"
        assert result["signals"]["rsi"]["value"] == 22.1
        assert result["signals"]["rsi"]["threshold_oversold"] == 30

    def test_rsi_neutral(self, adapter):
        """30 <= RSI(14) <= 70 should signal RSI中性区."""
        mock_result = self._mock_tech_data(rsi14_val=52.3)
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["rsi"]["signal"] == "RSI中性区"

    def test_rsi_boundary_70(self, adapter):
        """RSI(14) exactly 70 is NOT overbought (strict >)."""
        mock_result = self._mock_tech_data(rsi14_val=70.0)
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["rsi"]["signal"] == "RSI中性区"

    def test_rsi_boundary_30(self, adapter):
        """RSI(14) exactly 30 is NOT oversold (strict <)."""
        mock_result = self._mock_tech_data(rsi14_val=30.0)
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["rsi"]["signal"] == "RSI中性区"

    def test_macd_golden_cross(self, adapter):
        """DIF crosses above DEA → MACD金叉."""
        mock_result = self._mock_tech_data(
            macd_curr={"dif": 1.5, "dea": 1.2, "macd_bar": 0.3},
            macd_prev={"dif": 0.9, "dea": 1.1, "macd_bar": -0.2},
        )
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["macd"]["signal"] == "MACD金叉"
        assert result["signals"]["macd"]["dif"] == 1.5
        assert result["signals"]["macd"]["dea"] == 1.2

    def test_macd_death_cross(self, adapter):
        """DIF crosses below DEA → MACD死叉."""
        mock_result = self._mock_tech_data(
            macd_curr={"dif": 0.8, "dea": 1.0, "macd_bar": -0.2},
            macd_prev={"dif": 1.2, "dea": 1.1, "macd_bar": 0.1},
        )
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["macd"]["signal"] == "MACD死叉"

    def test_macd_no_cross(self, adapter):
        """DIF stays above DEA → MACD无交叉."""
        mock_result = self._mock_tech_data(
            macd_curr={"dif": 2.0, "dea": 1.5, "macd_bar": 0.5},
            macd_prev={"dif": 1.8, "dea": 1.3, "macd_bar": 0.5},
        )
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["macd"]["signal"] == "MACD无交叉"

    def test_boll_above_upper(self, adapter):
        """Close > upper band → 突破上轨."""
        mock_result = self._mock_tech_data(
            boll={"upper": 100.0, "mid": 95.0, "lower": 90.0},
            latest_close=101.5,
        )
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["boll"]["signal"] == "突破上轨"
        assert result["signals"]["boll"]["close"] == 101.5
        assert result["signals"]["boll"]["upper"] == 100.0

    def test_boll_below_lower(self, adapter):
        """Close < lower band → 跌破下轨."""
        mock_result = self._mock_tech_data(
            boll={"upper": 100.0, "mid": 95.0, "lower": 90.0},
            latest_close=88.0,
        )
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["boll"]["signal"] == "跌破下轨"

    def test_boll_within_bands(self, adapter):
        """Lower < Close < Upper → 布林带内."""
        mock_result = self._mock_tech_data(
            boll={"upper": 100.0, "mid": 95.0, "lower": 90.0},
            latest_close=96.5,
        )
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(return_value=mock_result)):
            result = _run(adapter.get_technical_signals("600519"))

        assert result["signals"]["boll"]["signal"] == "布林带内"

    def test_error_returns_graceful(self, adapter):
        """Adapter error returns error dict, not exception."""
        with patch.object(adapter, "calculate_technical_indicators",
                          AsyncMock(side_effect=RuntimeError("API down"))):
            result = _run(adapter.get_technical_signals("600519"))

        assert "error" in result
        assert result["symbol"] == "600519"
        assert result["signals"] == {}


# =====================================================================
# company_master (within get_stock_fact_pack)
# =====================================================================


class TestCompanyMaster:
    """Verify company_master field mapping from stock_individual_info_em."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def _company_info_df(self):
        return pd.DataFrame({
            "item": ["公司名称", "股票简称", "成立日期", "上市日期", "法人代表",
                     "董事长", "总经理", "董秘", "行业", "员工总数",
                     "注册资本", "主营业务", "公司网址", "注册地址", "办公地址",
                     "经营范围", "电话", "邮箱", "公司简介"],
            "value": ["贵州茅台酒股份有限公司", "贵州茅台", "1951-01-01",
                      "2001-08-27", "丁雄军", "丁雄军", "李静仁", "饶蔓",
                      "白酒", "28000", "12.56亿", "茅台酒及系列酒",
                      "www.moutaichina.com", "贵州省仁怀市", "贵州省仁怀市茅台镇",
                      "茅台酒生产销售", "0851-2238666", "ir@moutai.com",
                      "白酒行业龙头"],
        })

    def test_field_mapping(self, adapter):
        """company_master maps CN field names to EN keys correctly."""
        info_df = self._company_info_df()

        async def mock_run(func, *args, **kwargs):
            if func.__name__ == "stock_individual_info_em":
                return info_df
            return pd.DataFrame()

        # Mock all sub-methods to return empty/None
        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            with patch.object(adapter, "get_asset_info", AsyncMock(return_value=None)):
                with patch.object(adapter, "get_financials", AsyncMock(return_value={"error": 1})):
                    with patch.object(adapter, "_get_valuation_raw", AsyncMock(return_value=None)):
                        with patch.object(adapter, "get_money_flow", AsyncMock(return_value={"error": 1})):
                            with patch.object(adapter, "get_stock_top10_shareholders", AsyncMock(return_value={"error": 1})):
                                with patch.object(adapter, "get_stock_shareholder_changes", AsyncMock(return_value={"error": 1})):
                                    with patch.object(adapter, "get_dividend_info", AsyncMock(return_value={"error": 1})):
                                        with patch.object(adapter, "get_repurchase_info", AsyncMock(return_value={"error": 1})):
                                            with patch.object(adapter, "get_restricted_release", AsyncMock(return_value={"error": 1})):
                                                with patch.object(adapter, "get_mainbz_info", AsyncMock(return_value={"error": 1})):
                                                    result = _run(adapter.get_stock_fact_pack("600519"))

        cm = result["facts"]["company_master"]
        assert cm["company_name"] == "贵州茅台酒股份有限公司"
        assert cm["short_name"] == "贵州茅台"
        assert cm["ipo_date"] == "2001-08-27"
        assert cm["industry"] == "白酒"
        assert cm["legal_representative"] == "丁雄军"
        assert cm["employees"] == "28000"
        assert cm["main_business"] == "茅台酒及系列酒"
        assert cm["website"] == "www.moutaichina.com"
        assert result["coverage"]["company_master"] == "complete"

    def test_empty_df_marks_missing(self, adapter):
        """Empty stock_individual_info_em marks company_master as missing."""
        async def mock_run(func, *args, **kwargs):
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            with patch.object(adapter, "get_asset_info", AsyncMock(return_value=None)):
                with patch.object(adapter, "get_financials", AsyncMock(return_value={"error": 1})):
                    with patch.object(adapter, "_get_valuation_raw", AsyncMock(return_value=None)):
                        with patch.object(adapter, "get_money_flow", AsyncMock(return_value={"error": 1})):
                            with patch.object(adapter, "get_stock_top10_shareholders", AsyncMock(return_value={"error": 1})):
                                with patch.object(adapter, "get_stock_shareholder_changes", AsyncMock(return_value={"error": 1})):
                                    with patch.object(adapter, "get_dividend_info", AsyncMock(return_value={"error": 1})):
                                        with patch.object(adapter, "get_repurchase_info", AsyncMock(return_value={"error": 1})):
                                            with patch.object(adapter, "get_restricted_release", AsyncMock(return_value={"error": 1})):
                                                with patch.object(adapter, "get_mainbz_info", AsyncMock(return_value={"error": 1})):
                                                    result = _run(adapter.get_stock_fact_pack("600519"))

        assert "company_master" not in result["facts"]
        assert "company_master" in result["missing_fields"]


# =====================================================================
# peers (within get_stock_fact_pack)
# =====================================================================


class TestPeers:
    """Verify peers sorting, top-N, and self-exclusion."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def _peers_df(self):
        """5 industry peers with varying market caps."""
        return pd.DataFrame({
            "代码": ["600519", "000858", "000568", "603369", "002304"],
            "名称": ["贵州茅台", "五粮液", "泸州老窖", "今世缘", "洋河股份"],
            "总市值": [2.1e12, 6000e8, 3000e8, 500e8, 1500e8],
            "市盈率-动态": [35.2, 22.1, 18.5, 25.0, 20.3],
            "市净率": [12.1, 6.5, 8.2, 5.0, 4.8],
        })

    def test_sorted_by_market_cap_desc(self, adapter):
        """Peers sorted by market cap descending."""
        peers_df = self._peers_df()
        info_df = pd.DataFrame({"item": ["行业"], "value": ["白酒"]})

        async def mock_run(func, *args, **kwargs):
            if func.__name__ == "stock_individual_info_em":
                return info_df
            if func.__name__ == "stock_board_industry_cons_em":
                return peers_df
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            with patch.object(adapter, "get_asset_info", AsyncMock(return_value=None)):
                with patch.object(adapter, "get_financials", AsyncMock(return_value={"error": 1})):
                    with patch.object(adapter, "_get_valuation_raw", AsyncMock(return_value=None)):
                        with patch.object(adapter, "get_money_flow", AsyncMock(return_value={"error": 1})):
                            with patch.object(adapter, "get_stock_top10_shareholders", AsyncMock(return_value={"error": 1})):
                                with patch.object(adapter, "get_stock_shareholder_changes", AsyncMock(return_value={"error": 1})):
                                    with patch.object(adapter, "get_dividend_info", AsyncMock(return_value={"error": 1})):
                                        with patch.object(adapter, "get_repurchase_info", AsyncMock(return_value={"error": 1})):
                                            with patch.object(adapter, "get_restricted_release", AsyncMock(return_value={"error": 1})):
                                                with patch.object(adapter, "get_mainbz_info", AsyncMock(return_value={"error": 1})):
                                                    result = _run(adapter.get_stock_fact_pack("600519"))

        peers = result["facts"]["peers"]
        assert peers["industry"] == "白酒"
        # Self (600519) excluded → 4 peers
        assert peers["count"] == 4
        # Sorted by market cap desc: 五粮液 > 泸州老窖 > 洋河股份 > 今世缘
        assert peers["peers"][0]["code"] == "000858"  # 五粮液, 6000亿
        assert peers["peers"][1]["code"] == "000568"  # 泸州老窖, 3000亿
        assert peers["peers"][2]["code"] == "002304"  # 洋河股份, 1500亿
        assert peers["peers"][3]["code"] == "603369"  # 今世缘, 500亿

    def test_self_excluded(self, adapter):
        """Target stock (600519) must not appear in peers list."""
        peers_df = self._peers_df()
        info_df = pd.DataFrame({"item": ["行业"], "value": ["白酒"]})

        async def mock_run(func, *args, **kwargs):
            if func.__name__ == "stock_individual_info_em":
                return info_df
            if func.__name__ == "stock_board_industry_cons_em":
                return peers_df
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            with patch.object(adapter, "get_asset_info", AsyncMock(return_value=None)):
                with patch.object(adapter, "get_financials", AsyncMock(return_value={"error": 1})):
                    with patch.object(adapter, "_get_valuation_raw", AsyncMock(return_value=None)):
                        with patch.object(adapter, "get_money_flow", AsyncMock(return_value={"error": 1})):
                            with patch.object(adapter, "get_stock_top10_shareholders", AsyncMock(return_value={"error": 1})):
                                with patch.object(adapter, "get_stock_shareholder_changes", AsyncMock(return_value={"error": 1})):
                                    with patch.object(adapter, "get_dividend_info", AsyncMock(return_value={"error": 1})):
                                        with patch.object(adapter, "get_repurchase_info", AsyncMock(return_value={"error": 1})):
                                            with patch.object(adapter, "get_restricted_release", AsyncMock(return_value={"error": 1})):
                                                with patch.object(adapter, "get_mainbz_info", AsyncMock(return_value={"error": 1})):
                                                    result = _run(adapter.get_stock_fact_pack("600519"))

        peer_codes = [p["code"] for p in result["facts"]["peers"]["peers"]]
        assert "600519" not in peer_codes

    def test_no_industry_marks_missing(self, adapter):
        """No industry info → peers missing."""
        info_df = pd.DataFrame({"item": ["公司名称"], "value": ["Test"]})

        async def mock_run(func, *args, **kwargs):
            if func.__name__ == "stock_individual_info_em":
                return info_df
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            with patch.object(adapter, "get_asset_info", AsyncMock(return_value=None)):
                with patch.object(adapter, "get_financials", AsyncMock(return_value={"error": 1})):
                    with patch.object(adapter, "_get_valuation_raw", AsyncMock(return_value=None)):
                        with patch.object(adapter, "get_money_flow", AsyncMock(return_value={"error": 1})):
                            with patch.object(adapter, "get_stock_top10_shareholders", AsyncMock(return_value={"error": 1})):
                                with patch.object(adapter, "get_stock_shareholder_changes", AsyncMock(return_value={"error": 1})):
                                    with patch.object(adapter, "get_dividend_info", AsyncMock(return_value={"error": 1})):
                                        with patch.object(adapter, "get_repurchase_info", AsyncMock(return_value={"error": 1})):
                                            with patch.object(adapter, "get_restricted_release", AsyncMock(return_value={"error": 1})):
                                                with patch.object(adapter, "get_mainbz_info", AsyncMock(return_value={"error": 1})):
                                                    result = _run(adapter.get_stock_fact_pack("600519"))

        assert "peers" in result["missing_fields"]


# =====================================================================
# fees (within get_fund_fact_pack)
# =====================================================================


class TestFees:
    """Verify fee field extraction from fund detail."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_extracts_fee_fields(self, adapter):
        """Fee fields mapped from CN to EN keys."""
        detail_raw = {
            "基金代码": "110011",
            "基金名称": "易方达中小盘",
            "管理费率": "1.5",
            "托管费率": "0.25",
            "申购费率": "0.15",
            "赎回费率": "0.5",
            "销售服务费率": "0.0",
        }

        async def mock_run(func, *args, **kwargs):
            return pd.DataFrame()  # Empty for fund_purchase_fee

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            with patch.object(adapter, "get_fund_detail", AsyncMock(return_value=detail_raw)):
                with patch.object(adapter, "get_fund_nav", AsyncMock(return_value={"error": 1})):
                    with patch.object(adapter, "get_fund_holdings", AsyncMock(return_value={"error": 1})):
                        with patch.object(adapter, "get_fund_manager", AsyncMock(return_value={"error": 1})):
                            with patch.object(adapter, "get_fund_scale", AsyncMock(return_value={"error": 1})):
                                with patch.object(adapter, "get_fund_ranking", AsyncMock(return_value={"error": 1})):
                                    result = _run(adapter.get_fund_fact_pack("110011"))

        fees = result["facts"].get("fees", {})
        # _safe_float("1.5%") extracts the float
        assert fees.get("management_fee") is not None
        assert fees.get("custody_fee") is not None
        assert result["coverage"]["fees"] == "complete"

    def test_no_fee_fields_marks_missing(self, adapter):
        """Detail without fee fields → fees missing."""
        detail_raw = {"基金代码": "110011", "基金名称": "Test"}

        async def mock_run(func, *args, **kwargs):
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            with patch.object(adapter, "get_fund_detail", AsyncMock(return_value=detail_raw)):
                with patch.object(adapter, "get_fund_nav", AsyncMock(return_value={"error": 1})):
                    with patch.object(adapter, "get_fund_holdings", AsyncMock(return_value={"error": 1})):
                        with patch.object(adapter, "get_fund_manager", AsyncMock(return_value={"error": 1})):
                            with patch.object(adapter, "get_fund_scale", AsyncMock(return_value={"error": 1})):
                                with patch.object(adapter, "get_fund_ranking", AsyncMock(return_value={"error": 1})):
                                    result = _run(adapter.get_fund_fact_pack("110011"))

        assert "fees" in result["missing_fields"]


# =====================================================================
# peer_comparison (within get_fund_fact_pack)
# =====================================================================


class TestPeerComparison:
    """Verify fund peer comparison: self-exclusion + same-type ranking."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_excludes_self_and_builds_peers(self, adapter):
        """Target fund excluded from peer list."""
        detail_raw = {
            "基金代码": "110011",
            "基金名称": "易方达中小盘",
            "基金类型": "混合型",
        }
        ranking_data = {
            "results": [
                {"fund_code": "110011", "fund_name": "易方达中小盘", "nav": 5.0, "return_1y": 15.0, "return_ytd": 5.0},
                {"fund_code": "110022", "fund_name": "易方达消费", "nav": 3.0, "return_1y": 12.0, "return_ytd": 3.0},
                {"fund_code": "110033", "fund_name": "易方达蓝筹", "nav": 2.5, "return_1y": 10.0, "return_ytd": 2.0},
            ]
        }

        async def mock_run(func, *args, **kwargs):
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            with patch.object(adapter, "get_fund_detail", AsyncMock(return_value=detail_raw)):
                with patch.object(adapter, "get_fund_nav", AsyncMock(return_value={"error": 1})):
                    with patch.object(adapter, "get_fund_holdings", AsyncMock(return_value={"error": 1})):
                        with patch.object(adapter, "get_fund_manager", AsyncMock(return_value={"error": 1})):
                            with patch.object(adapter, "get_fund_scale", AsyncMock(return_value={"error": 1})):
                                with patch.object(adapter, "get_fund_ranking", AsyncMock(return_value=ranking_data)):
                                    result = _run(adapter.get_fund_fact_pack("110011"))

        peer = result["facts"].get("peer", {})
        assert peer.get("fund_type") == "混合型"
        peer_codes = [p["fund_code"] for p in peer.get("peers", [])]
        assert "110011" not in peer_codes  # Self excluded
        assert len(peer["peers"]) == 2

    def test_no_fund_type_marks_missing(self, adapter):
        """No fund type in master → peer missing."""
        detail_raw = {"基金代码": "110011", "基金名称": "Test"}

        async def mock_run(func, *args, **kwargs):
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            with patch.object(adapter, "get_fund_detail", AsyncMock(return_value=detail_raw)):
                with patch.object(adapter, "get_fund_nav", AsyncMock(return_value={"error": 1})):
                    with patch.object(adapter, "get_fund_holdings", AsyncMock(return_value={"error": 1})):
                        with patch.object(adapter, "get_fund_manager", AsyncMock(return_value={"error": 1})):
                            with patch.object(adapter, "get_fund_scale", AsyncMock(return_value={"error": 1})):
                                with patch.object(adapter, "get_fund_ranking", AsyncMock(return_value={"error": 1})):
                                    result = _run(adapter.get_fund_fact_pack("110011"))

        assert "peer" in result["missing_fields"]
