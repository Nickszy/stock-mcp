# tests/test_response_contract.py
"""Tests for the unified response contract (COL-139)."""

import pytest
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# create_data_response
# ---------------------------------------------------------------------------

def test_minimal_response():
    """Only data is required; source gets a sensible default."""
    from src.server.domain.response_contract import create_data_response

    resp = create_data_response([1, 2, 3])

    assert resp["data"] == [1, 2, 3]
    assert "source" in resp
    assert resp["source"]["provider"] == "unknown"
    assert "fetched_at" in resp["source"]


def test_period_based_response():
    """Period-based data includes period and limit."""
    from src.server.domain.response_contract import create_data_response

    resp = create_data_response(
        {"income": []},
        symbol="SSE:600519",
        source="akshare",
        period="quarterly",
        limit=8,
    )

    assert resp["symbol"] == "SSE:600519"
    assert resp["period"] == "quarterly"
    assert resp["limit"] == 8
    assert resp["source"]["provider"] == "akshare"


def test_time_series_response():
    """Time-series data includes start_date / end_date / interval."""
    from src.server.domain.response_contract import create_data_response

    resp = create_data_response(
        [{"close": 100}],
        symbol="AAPL",
        source="yahoo",
        start_date="2025-01-01",
        end_date="2025-03-01",
        interval="1d",
    )

    assert resp["start_date"] == "2025-01-01"
    assert resp["end_date"] == "2025-03-01"
    assert resp["interval"] == "1d"
    assert resp["source"]["provider"] == "yahoo"


def test_snapshot_response():
    """Snapshot data includes date."""
    from src.server.domain.response_contract import create_data_response

    resp = create_data_response(
        {"pe": 15.2},
        symbol="600519",
        source="akshare",
        date="2025-12-31",
    )

    assert resp["date"] == "2025-12-31"


def test_extra_metadata():
    """Extra kwargs are merged as top-level keys."""
    from src.server.domain.response_contract import create_data_response

    resp = create_data_response(
        data="ok",
        currency="CNY",
        exchange="SSE",
    )

    assert resp["currency"] == "CNY"
    assert resp["exchange"] == "SSE"


def test_fetched_at_is_iso():
    """fetched_at must be a valid ISO datetime string."""
    from src.server.domain.response_contract import create_data_response

    resp = create_data_response(data=None, source="akshare")
    dt = datetime.fromisoformat(resp["source"]["fetched_at"])
    assert dt.tzinfo is not None  # timezone-aware


def test_limit_string_converted_to_int():
    """limit passed as string should be converted to int."""
    from src.server.domain.response_contract import create_data_response

    resp = create_data_response(data=[], limit="10")
    assert resp["limit"] == 10
    assert isinstance(resp["limit"], int)


def test_none_fields_omitted():
    """None-valued optional fields should not appear in the response."""
    from src.server.domain.response_contract import create_data_response

    resp = create_data_response(data=[], symbol=None, period=None)
    assert "symbol" not in resp
    assert "period" not in resp


# ---------------------------------------------------------------------------
# rest_response
# ---------------------------------------------------------------------------

def test_rest_response_wrapper():
    """rest_response wraps contract in {code, message, data} envelope."""
    from src.server.domain.response_contract import rest_response

    resp = rest_response(
        data=[1, 2, 3],
        symbol="600519",
        source="akshare",
    )

    assert resp["code"] == 0
    assert resp["message"] == "success"
    assert "data" in resp
    assert resp["data"]["data"] == [1, 2, 3]
    assert resp["data"]["symbol"] == "600519"
    assert resp["data"]["source"]["provider"] == "akshare"


def test_rest_response_backward_compat():
    """REST envelope matches existing money_flow pattern."""
    from src.server.domain.response_contract import rest_response

    resp = rest_response(data={"flow": []})

    # Must have the same top-level keys as the old manual wrapper
    assert set(resp.keys()) == {"code", "message", "data"}
    assert resp["code"] == 0


# ---------------------------------------------------------------------------
# MCP artifact adapter (create_standard_artifact_response)
# ---------------------------------------------------------------------------

def test_standard_artifact_response_structure():
    """Standard artifact response has summary + artifact.content with contract."""
    from src.server.mcp.tools.artifact_utils import create_standard_artifact_response

    resp = create_standard_artifact_response(
        summary="Test summary",
        component_type="table",
        name="Test Artifact",
        data=[{"a": 1}],
        symbol="600519",
        source="akshare",
        period="quarterly",
    )

    assert resp["summary"] == "Test summary"
    assert "artifact" in resp
    artifact = resp["artifact"]
    assert artifact["name"] == "Test Artifact"
    assert artifact["component_type"] == "table"

    # content should be the data contract
    content = artifact["content"]
    assert content["data"] == [{"a": 1}]
    assert content["symbol"] == "600519"
    assert content["source"]["provider"] == "akshare"
    assert content["period"] == "quarterly"


def test_standard_artifact_response_minimal():
    """Minimal call still produces valid artifact + contract."""
    from src.server.mcp.tools.artifact_utils import create_standard_artifact_response

    resp = create_standard_artifact_response(
        summary="ok",
        component_type="other",
        name="X",
        data="hello",
    )

    assert resp["summary"] == "ok"
    assert resp["artifact"]["content"]["data"] == "hello"
    assert resp["artifact"]["content"]["source"]["provider"] == "unknown"


# ---------------------------------------------------------------------------
# Use case: get_stock_financial_statements returns contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unified_financial_statements_contract():
    """The unified use case should return a data-response contract."""
    from unittest.mock import AsyncMock, patch

    with patch("src.server.core.use_cases.fundamental.Container") as mock_container:
        mock_gw = AsyncMock()
        mock_gw.get_financial_statements.return_value = {
            "income_statement": {"quarterly": [{"revenue": 100}], "annual": []},
            "balance_sheet": {"quarterly": [], "annual": []},
            "cash_flow": {"quarterly": [], "annual": []},
            "source": "akshare",
            "ts_code": "600519.SH",
        }
        mock_container.market_gateway.return_value = mock_gw

        from src.server.core.use_cases import fundamental as uc

        result = await uc.get_stock_financial_statements("600519", period="quarterly", periods=4)

        # Verify contract shape
        assert "data" in result
        assert "source" in result
        assert result["source"]["provider"] == "akshare"
        assert "fetched_at" in result["source"]
        assert result["symbol"] == "600519.SH"
        assert result["period"] == "quarterly"
        assert result["limit"] == 4

        # Verify payload
        assert result["data"]["income_statement"]["quarterly"] == [{"revenue": 100}]


# ---------------------------------------------------------------------------
# Backward compatibility: old use case names still work
# ---------------------------------------------------------------------------

def test_old_use_case_aliases_exist():
    """get_financials and get_financial_statements should still be callable."""
    from src.server.core.use_cases import fundamental as uc

    assert callable(uc.get_financials)
    assert callable(uc.get_financial_statements)
