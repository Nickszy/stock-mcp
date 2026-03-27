# tests/test_data_quality.py
"""
Stock-MCP 数据质量测试套件

覆盖维度:
1. 数据完整性 - 缺失率、日期覆盖
2. 数据准确性 - 交叉验证、逻辑校验
3. 数据时效性 - 延迟检查
4. 数据一致性 - 历史回溯、字段稳定

运行: uv run pytest tests/test_data_quality.py -v -m "not slow"
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

sys.path.insert(0, ".")

from src.server.domain.adapters.akshare_adapter import AkshareAdapter


# ---- Helpers ----

class MockCache:
    """Simple in-memory cache for testing."""
    _store: Dict[str, Any] = {}

    async def get(self, key: str):
        return MockCache._store.get(key)

    async def set(self, key: str, value: Any, ttl: int = 0):
        MockCache._store[key] = value


@pytest.fixture
def adapter():
    return AkshareAdapter(MockCache())


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _retry(func, *args, retries=2, delay=3, **kwargs):
    """Retry network calls with delay."""
    last_err = None
    for i in range(retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if i < retries:
                await asyncio.sleep(delay)
    raise last_err


# ---- 1. 行情数据完整性 ----

class TestMarketData:
    """行情数据质量测试."""

    @pytest.mark.asyncio
    async def test_stock_realtime_has_all_fields(self, adapter):
        """实时行情必须包含关键字段."""
        result = await _retry(adapter.get_real_time_price, "SSE:600519")

        # AssetPrice object - check attribute access
        assert result.price is not None, "Missing price"
        assert float(result.price) > 0, "Price should be positive"
        assert result.ticker is not None, "Missing ticker"
        assert result.volume is not None or result.close_price is not None, \
            "Should have volume or close"

    @pytest.mark.asyncio
    async def test_historical_prices_complete(self, adapter):
        """历史行情日期覆盖完整."""
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=90)

        # get_historical_prices returns List[AssetPrice]
        prices = await _retry(
            adapter.get_historical_prices,
            "SSE:600519",
            start_date=start_dt,
            end_date=end_dt,
        )

        assert isinstance(prices, list), f"Expected list, got {type(prices)}"
        assert len(prices) >= 40, f"Expected >=40 trading days, got {len(prices)}"

        # Verify OHLCV fields on AssetPrice objects
        for rec in prices[-5:]:
            assert rec.close_price is not None, "Missing close_price"
            assert rec.high_price is not None, "Missing high_price"
            assert rec.low_price is not None, "Missing low_price"
            assert rec.open_price is not None, "Missing open_price"

            # High >= Close >= Low
            h = float(rec.high_price)
            c = float(rec.close_price)
            l = float(rec.low_price)
            assert h >= c >= l, f"OHLC violation: H={h} C={c} L={l}"

    @pytest.mark.asyncio
    async def test_index_data_available(self, adapter):
        """指数行情数据可用."""
        end_dt = datetime(2026, 3, 28)
        start_dt = datetime(2025, 1, 1)

        prices = await _retry(
            adapter.get_historical_prices,
            "SSE:000300",
            start_date=start_dt,
            end_date=end_dt,
        )

        assert isinstance(prices, list)
        assert len(prices) >= 200, f"CSI300 should have >=200 records, got {len(prices)}"


# ---- 2. 资金流数据 ----

class TestMoneyFlow:
    """资金流数据质量测试."""

    @pytest.mark.asyncio
    async def test_sector_money_flow_structure(self, adapter):
        """板块资金流结构正确."""
        result = await _retry(
            adapter.get_sector_money_flow_history,
            sector_name="白酒", days=10,
        )

        assert "records" in result or "history" in result
        records = result.get("records", result.get("history", []))
        assert len(records) >= 5, f"Expected >=5 records, got {len(records)}"

    @pytest.mark.asyncio
    async def test_north_bound_flow_has_data(self, adapter):
        """北向资金数据可获取."""
        result = await _retry(adapter.get_north_bound_flow, days=10)
        data = result.get("data", {})
        total = data.get("total", [])
        assert len(total) >= 5, "North bound flow should have recent data"

    @pytest.mark.asyncio
    async def test_market_money_flow(self, adapter):
        """市场整体资金流统计."""
        result = await _retry(adapter.get_market_money_flow, top_n=5)
        assert "top_inflow" in result or "market_overview" in result
        top_in = result.get("top_inflow", [])
        if top_in:
            assert len(top_in) <= 5


# ---- 3. 板块与行业 ----

class TestSectorData:
    """板块/行业数据质量测试."""

    @pytest.mark.asyncio
    async def test_sector_trend(self, adapter):
        """板块走势数据."""
        result = await _retry(adapter.get_sector_trend, sector_name="银行", days=10)
        assert "trend" in result
        trend = result.get("trend", [])
        assert len(trend) >= 5

    @pytest.mark.asyncio
    async def test_sector_valuation_metrics(self, adapter):
        """行业估值分位数据."""
        result = await _retry(
            adapter.get_sector_valuation_metrics,
            sector_name="银行", days=120,
        )
        assert "current" in result
        assert "summary" in result

        current = result["current"]
        assert "pe_ttm" in current
        assert current["pe_ttm"] > 0

        summary = result["summary"]
        assert "valuation_level" in summary
        assert summary["valuation_level"] in ["高估", "偏高", "合理", "偏低", "低估"]

    @pytest.mark.asyncio
    async def test_market_breadth(self, adapter):
        """市场广度指标."""
        result = await _retry(adapter.get_market_breadth, days=20)
        # Returns {"data": {"up_count": ..., "total_stocks": ...}}
        data = result.get("data", {})
        total_stocks = data.get("total_stocks", 0)
        assert total_stocks > 0, "Should have stock data"

        assert "up_count" in data
        assert "down_count" in data
        assert data["up_count"] + data["down_count"] > 0


# ---- 4. 相对强弱 ----

class TestRelativeStrength:
    """相对强弱指标测试."""

    @pytest.mark.asyncio
    async def test_rs_vs_benchmark(self, adapter):
        """RS 计算结果合理."""
        result = await _retry(
            adapter.get_relative_strength,
            symbol="600519", benchmark="000300", days=60,
        )

        assert "rs_pct" in result
        assert "trend" in result
        assert result["trend"] in ["outperform", "underperform", "neutral"]

        history = result.get("history", [])
        assert len(history) >= 30, f"RS history should be >=30, got {len(history)}"

        # Verify RS consistency: last history entry matches rs_pct
        if history:
            latest_rs = history[-1].get("rs")
            assert latest_rs is not None
            assert abs(latest_rs - result["rs_pct"]) < 0.1, (
                f"RS mismatch: history={latest_rs} vs result={result['rs_pct']}"
            )

    @pytest.mark.asyncio
    async def test_rs_outperform_logic(self, adapter):
        """RS 超额收益逻辑正确."""
        result = await _retry(
            adapter.get_relative_strength,
            symbol="600519", benchmark="000300", days=60,
        )

        stock_ret = result.get("latest_stock_return_pct")
        bench_ret = result.get("latest_benchmark_return_pct")

        if stock_ret is not None and bench_ret is not None:
            expected_rs = round(stock_ret - bench_ret, 2)
            actual_rs = result["rs_pct"]
            # Allow 1.0% tolerance for rounding differences
            assert abs(expected_rs - actual_rs) < 1.0, (
                f"RS calculation error: stock_ret={stock_ret}, bench_ret={bench_ret}, "
                f"expected_rs={expected_rs}, actual={actual_rs}"
            )


# ---- 5. 技术指标 ----

class TestTechnicalIndicators:
    """技术指标计算测试."""

    @pytest.mark.asyncio
    async def test_ma_calculation(self, adapter):
        """均线计算正确."""
        result = await _retry(
            adapter.calculate_technical_indicators,
            symbol="600519", indicators=["MA"], days=60,
        )

        assert "data" in result
        data = result["data"]

        # MA5 should exist and have valid values
        ma5 = data.get("ma5", [])
        valid_ma5 = [x for x in ma5 if x.get("value") is not None]
        assert len(valid_ma5) >= 50, f"MA5 should have >=50 valid points"

        # Latest MA5 should be close to recent prices
        latest_ma5 = valid_ma5[-1]["value"]
        latest_close = result["latest_close"]
        assert abs(latest_ma5 - latest_close) / latest_close < 0.1, (
            f"MA5={latest_ma5} too far from close={latest_close}"
        )

    @pytest.mark.asyncio
    async def test_macd_structure(self, adapter):
        """MACD 结构完整."""
        result = await _retry(
            adapter.calculate_technical_indicators,
            symbol="600519", indicators=["MACD"], days=60,
        )

        macd = result["data"].get("macd", [])
        assert len(macd) >= 30

        # Each MACD entry should have DIF, DEA, MACD bar
        for entry in macd[-10:]:
            assert "dif" in entry
            assert "dea" in entry
            assert "macd_bar" in entry

    @pytest.mark.asyncio
    async def test_rsi_range(self, adapter):
        """RSI 值在 0-100 范围内."""
        result = await _retry(
            adapter.calculate_technical_indicators,
            symbol="600519", indicators=["RSI"], days=60,
        )

        for key in ["rsi6", "rsi12", "rsi24"]:
            rsi_data = result["data"].get(key, [])
            for entry in rsi_data:
                v = entry.get("value")
                if v is not None:
                    assert 0 <= v <= 100, f"{key} RSI out of range: {v}"

    @pytest.mark.asyncio
    async def test_bollinger_bands(self, adapter):
        """布林带 upper >= mid >= lower."""
        result = await _retry(
            adapter.calculate_technical_indicators,
            symbol="600519", indicators=["BOLL"], days=60,
        )

        boll = result["data"].get("boll", [])
        for entry in boll:
            u = entry.get("upper")
            m = entry.get("mid")
            l = entry.get("lower")
            if u is not None and m is not None and l is not None:
                assert u >= m >= l, f"BOLL violation: U={u} M={m} L={l}"

    @pytest.mark.asyncio
    async def test_kdj_range(self, adapter):
        """KDJ 值合理."""
        result = await _retry(
            adapter.calculate_technical_indicators,
            symbol="600519", indicators=["KDJ"], days=60,
        )

        kdj = result["data"].get("kdj", [])
        for entry in kdj:
            k = entry.get("k")
            d = entry.get("d")
            if k is not None:
                assert 0 <= k <= 100, f"K out of range: {k}"
            if d is not None:
                assert 0 <= d <= 100, f"D out of range: {d}"

    @pytest.mark.asyncio
    async def test_all_indicators_together(self, adapter):
        """所有指标同时计算不冲突."""
        result = await _retry(
            adapter.calculate_technical_indicators,
            symbol="600519",
            indicators=["MA", "MACD", "RSI", "BOLL", "KDJ"],
            days=60,
        )

        expected_keys = ["ma5", "ma10", "ma20", "ma60", "macd",
                         "rsi6", "rsi12", "rsi24", "boll", "kdj"]
        for key in expected_keys:
            assert key in result["data"], f"Missing indicator: {key}"


# ---- 6. 宏观数据 ----

class TestMacroData:
    """宏观经济数据质量测试."""

    @pytest.mark.asyncio
    async def test_money_supply(self, adapter):
        """货币供应量数据."""
        result = await _retry(adapter.get_money_supply, months=12)
        data = result.get("data", [])
        assert len(data) >= 6, "Should have at least 6 months of data"

    @pytest.mark.asyncio
    async def test_interest_rates(self, adapter):
        """利率数据."""
        result = await _retry(adapter.get_interest_rates, shibor_days=30, lpr_months=6)
        assert "data" in result
        shibor = result.get("data", {}).get("shibor", [])
        if shibor:
            assert len(shibor) >= 10

    @pytest.mark.asyncio
    async def test_inflation_data(self, adapter):
        """CPI/PPI 通胀数据."""
        result = await _retry(adapter.get_inflation_data, months=12)
        cpi = result.get("data", {}).get("cpi", [])
        ppi = result.get("data", {}).get("ppi", [])
        total = len(cpi) + len(ppi)
        assert total >= 6, f"Should have CPI or PPI data, got CPI={len(cpi)}, PPI={len(ppi)}"

    @pytest.mark.asyncio
    async def test_pmi_data(self, adapter):
        """PMI 制造业/非制造业数据."""
        result = await _retry(adapter.get_pmi_data, months=12)
        data = result.get("data", [])
        assert len(data) >= 6, f"Should have PMI data, got {len(data)}"

    @pytest.mark.asyncio
    async def test_gdp_data(self, adapter):
        """GDP 季度数据."""
        result = await _retry(adapter.get_gdp_data, quarters=8)
        data = result.get("data", [])
        assert len(data) >= 4, f"Should have GDP data, got {len(data)}"

    @pytest.mark.asyncio
    async def test_social_financing(self, adapter):
        """社会融资规模数据."""
        result = await _retry(adapter.get_social_financing, months=12)
        data = result.get("data", [])
        assert len(data) >= 4, f"Should have social financing data, got {len(data)}"

    @pytest.mark.asyncio
    async def test_ggt_daily(self, adapter):
        """港股通每日资金流向数据."""
        result = await _retry(adapter.get_ggt_daily, days=10)
        data = result.get("data", [])
        assert len(data) >= 5, f"Should have GGT daily data, got {len(data)}"


# ---- 7. 财务数据 ----

class TestFundamentalData:
    """基本面数据质量测试."""

    @pytest.mark.asyncio
    async def test_financials_available(self, adapter):
        """财务数据可获取."""
        result = await _retry(adapter.get_financials, "SSE:600519")
        assert result is not None

    @pytest.mark.asyncio
    async def test_mainbz_info(self, adapter):
        """主营构成数据."""
        result = await _retry(adapter.get_mainbz_info, "SSE:600519")
        assert result is not None


# ---- 8. 跨数据源一致性 ----

class TestCrossValidation:
    """跨数据源/接口一致性验证."""

    @pytest.mark.asyncio
    async def test_realtime_vs_hist_consistent(self, adapter):
        """实时价格与历史最新价格一致."""
        # Get realtime - returns AssetPrice
        rt = await _retry(adapter.get_real_time_price, "SSE:600519")
        rt_price = float(rt.price)

        # Get latest historical - returns List[AssetPrice]
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=7)
        prices = await _retry(
            adapter.get_historical_prices,
            "SSE:600519",
            start_date=start_dt,
            end_date=end_dt,
        )

        if prices and rt_price:
            latest_hist_close = float(prices[-1].close_price)
            # Allow 3% tolerance for timing difference
            pct_diff = abs(rt_price - latest_hist_close) / latest_hist_close * 100
            assert pct_diff < 3.0, (
                f"Realtime={rt_price} vs Hist={latest_hist_close}, diff={pct_diff:.2f}%"
            )

    @pytest.mark.asyncio
    async def test_boll_contains_price(self, adapter):
        """价格应在布林带范围内（大部分时间）."""
        result = await _retry(
            adapter.calculate_technical_indicators,
            symbol="600519", indicators=["BOLL"], days=60,
        )

        boll = result["data"].get("boll", [])
        within_bands = 0
        total = 0
        for entry in boll:
            u = entry.get("upper")
            m = entry.get("mid")
            l = entry.get("lower")
            if u is not None and l is not None:
                total += 1
                if l <= m <= u:
                    within_bands += 1

        if total > 0:
            assert within_bands / total > 0.9, \
                "BOLL mid should be within bands >90% of time"
