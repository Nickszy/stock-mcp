# tests/test_attention_sentiment_tools.py
"""Tests for attention and sentiment MCP tools."""

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


class TestBaiduHotSearchAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_baidu_hot_search(self, adapter):
        mock_df = pd.DataFrame([
            ["贵州茅台", "+3", 324461],
        ])

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_baidu_hot_search(symbol="A股", date="20260331", time_period="今日"))

        assert result["source"] == "akshare"
        assert result["symbol"] == "A股"
        assert result["date"] == "20260331"
        assert result["total"] == 1
        assert result["data"][0]["keyword"] == "贵州茅台"
        assert result["data"][0]["heat"] == 324461


class TestXueqiuHotnessAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_tweet_hotness(self, adapter):
        mock_df = pd.DataFrame([
            ["SH600519", "贵州茅台", 3578798, 1420.0],
        ])

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_xueqiu_tweet_hotness())

        assert result["source"] == "akshare"
        assert result["total"] == 1
        assert result["data"][0]["stock_code"] == "SH600519"
        assert result["data"][0]["heat"] == 3578798


class TestAttentionSentimentToolRegistration:
    def test_registers_four_tools(self):
        from src.server.mcp.tools.attention_sentiment_tools import register_attention_sentiment_tools

        mcp = MagicMock()
        registered = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_attention_sentiment_tools(mcp)

        expected = [
            "get_baidu_hot_search",
            "get_xueqiu_tweet_hotness",
            "get_xueqiu_follow_hotness",
            "get_xueqiu_deal_hotness",
        ]
        for name in expected:
            assert name in registered


class TestAttentionSentimentRegistry:
    def test_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "attention-sentiment"]
        assert len(groups) == 1
        assert groups[0].enabled is True
        assert groups[0].count == 4

    def test_total_tool_count_updated(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total == 195, f"Expected 195, got {total}"
