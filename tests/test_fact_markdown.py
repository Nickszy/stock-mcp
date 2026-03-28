# tests/test_fact_markdown.py
"""Tests for COL-149: Stock fact Markdown view builder.

Verify build_stock_fact_markdown produces correct fact-only Markdown output
from a stock fact pack data structure.

Run: uv run pytest tests/test_fact_markdown.py -v
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

import pytest

from src.server.domain.fact_markdown import (
    build_stock_fact_markdown,
    _fmt_num,
    _fmt_pct,
    _fmt_date,
    _table,
)


# =====================================================================
# Number formatting tests
# =====================================================================


class TestFmtNum:
    def test_none(self):
        assert _fmt_num(None) == "-"

    def test_billions(self):
        assert _fmt_num(1.5e8) == "1.50亿"

    def test_tens_of_thousands(self):
        assert _fmt_num(25000) == "2.50万"

    def test_regular(self):
        assert _fmt_num(3.14) == "3.14"

    def test_tiny(self):
        assert _fmt_num(0.001) == "0.001000"

    def test_string_passthrough(self):
        assert _fmt_num("hello") == "hello"

    def test_zero(self):
        assert _fmt_num(0) == "0.00"


class TestFmtPct:
    def test_none(self):
        assert _fmt_pct(None) == "-"

    def test_positive(self):
        assert _fmt_pct(3.14) == "3.14%"

    def test_negative(self):
        assert _fmt_pct(-5.2) == "-5.20%"


class TestFmtDate:
    def test_none(self):
        assert _fmt_date(None) == "-"

    def test_timestamp(self):
        assert _fmt_date("2025-01-15 00:00:00") == "2025-01-15"

    def test_date_only(self):
        assert _fmt_date("2025-03-28") == "2025-03-28"


# =====================================================================
# Table builder tests
# =====================================================================


class TestTable:
    def test_basic(self):
        result = _table(["A", "B"], [["1", "2"], ["3", "4"]])
        assert "| A | B |" in result
        assert "| --- | --- |" in result
        assert "| 1 | 2 |" in result

    def test_empty(self):
        assert _table(["A"], []) == ""


# =====================================================================
# Full Markdown builder tests
# =====================================================================


def _sample_fact_pack():
    """Build a sample stock fact pack for testing."""
    return {
        "source": "akshare",
        "entity": {"symbol": "600519", "type": "stock"},
        "facts": {
            "security_master": {
                "code": "600519",
                "name": "贵州茅台",
                "exchange": "SSE",
                "asset_type": "stock",
            },
            "financial": {
                "income": {
                    "total_revenue": 150000000000,
                    "net_profit": 75000000000,
                    "revenue_yoy": 0.165,
                },
            },
            "market": {
                "valuation": {
                    "pe_ttm": 25.3,
                    "pb": 8.1,
                    "total_mv": 2.1e12,
                    "turnover_rate": 0.35,
                },
            },
            "governance": {
                "top10_shareholders": [
                    {"name": "茅台集团", "ratio": 0.548, "change": "不变"},
                    {"name": "香港中央结算", "ratio": 0.058, "change": "+0.2%"},
                ],
            },
            "events": {
                "dividends": {
                    "data": [
                        {"year": 2024, "per_share": 30.876, "yield_pct": 2.1},
                        {"year": 2023, "per_share": 25.91, "yield_pct": 1.8},
                    ]
                },
            },
            "business_structure": {
                "data": [
                    {"segment": "茅台酒", "revenue": 1.26e11, "ratio": 0.84},
                    {"segment": "系列酒", "revenue": 2.0e10, "ratio": 0.13},
                ]
            },
        },
        "coverage": {
            "security_master": "complete",
            "financial": "complete",
            "market": "complete",
            "governance": "partial",
            "events": "partial",
            "business_structure": "complete",
            "company_master": "not_implemented",
            "peers": "not_implemented",
        },
        "missing_fields": ["company_master", "peers"],
        "categories_fetched": 6,
        "categories_total": 8,
        "elapsed_seconds": 1.23,
    }


class TestBuildStockFactMarkdown:
    def test_basic_structure(self):
        md = build_stock_fact_markdown(_sample_fact_pack())
        # Header
        assert "# 贵州茅台 (600519) 事实数据" in md
        assert "覆盖: 6/8" in md
        # Coverage section
        assert "## 覆盖状态" in md
        assert "✅ security_master: complete" in md
        assert "⏳ company_master: not_implemented" in md
        # Fact categories present
        assert "## 证券主档" in md
        assert "## 财务事实" in md
        assert "## 市场事实" in md
        assert "## 治理与股权" in md
        assert "## 事件事实" in md
        assert "## 业务结构" in md
        # Missing fields
        assert "## 缺失类别" in md
        assert "company_master" in md

    def test_fact_only_no_analysis(self):
        """Verify output contains facts, not analysis."""
        md = build_stock_fact_markdown(_sample_fact_pack())
        # Should NOT contain analysis words
        forbidden = ["增速放缓", "估值偏高", "表现优异", "风险偏高", "走弱", "过热"]
        for word in forbidden:
            assert word not in md, f"Found analysis word '{word}' in Markdown output"
        # Should contain factual data
        assert "600519" in md
        assert "贵州茅台" in md

    def test_empty_facts(self):
        """Handle fact pack with no facts."""
        pack = {
            "entity": {"symbol": "000001", "type": "stock"},
            "facts": {},
            "coverage": {},
            "missing_fields": [],
            "categories_fetched": 0,
            "categories_total": 8,
            "elapsed_seconds": 0.1,
        }
        md = build_stock_fact_markdown(pack)
        assert "#  (000001) 事实数据" in md
        assert "覆盖: 0/8" in md

    def test_financial_section(self):
        md = build_stock_fact_markdown(_sample_fact_pack())
        assert "income" in md
        assert "1500.00亿" in md  # total_revenue formatted

    def test_market_section(self):
        md = build_stock_fact_markdown(_sample_fact_pack())
        assert "valuation" in md
        assert "21000.00亿" in md  # total_mv formatted (2.1e12 / 1e8)

    def test_governance_section(self):
        md = build_stock_fact_markdown(_sample_fact_pack())
        assert "茅台集团" in md
        assert "top10_shareholders" in md

    def test_events_section(self):
        md = build_stock_fact_markdown(_sample_fact_pack())
        assert "dividends" in md

    def test_business_structure(self):
        md = build_stock_fact_markdown(_sample_fact_pack())
        assert "茅台酒" in md
        assert "系列酒" in md

    def test_number_formatting_in_output(self):
        md = build_stock_fact_markdown(_sample_fact_pack())
        # Billions should be formatted as 亿
        assert "亿" in md
        # Percentages should have %
        assert "%" in md


class TestAdapterIntegration:
    """Verify adapter returns fact_markdown field."""

    def test_fact_markdown_in_result(self):
        """Build a fact pack result and check fact_markdown is generated."""
        pack = _sample_fact_pack()
        md = build_stock_fact_markdown(pack)
        assert isinstance(md, str)
        assert len(md) > 100  # Should have substantial content
