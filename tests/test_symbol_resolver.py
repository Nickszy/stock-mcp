# tests/test_symbol_resolver.py
"""
Comprehensive tests for the symbol resolution pipeline.

Covers:
1. SymbolResolver.resolve() with various input formats
2. Exchange detection (A-share, US, HK, BSE)
3. normalize_ticker / to_ts_code from normalize.py
4. Commodity spot/future, FX, crypto resolution
5. Auto-correction of mismatched A-share exchange prefixes
6. Security master candidate selection
7. US exchange probing
8. Error / edge cases

Run: uv run pytest tests/test_symbol_resolver.py -v
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, ".")

from src.server.domain.symbols.normalize import normalize_ticker, to_ts_code
from src.server.domain.symbols.resolver import SymbolResolver
from src.server.domain.symbols.types import (
    InstrumentRef,
    ResolutionStatus,
    SymbolCandidate,
    SymbolResolution,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine synchronously for test ergonomics."""
    return asyncio.get_event_loop().run_until_complete(coro)


class MockRepo:
    """Mock security master repository.

    Supports configure-find-by-listing / find-candidates / upsert / alias / identifier
    via simple in-memory dicts so tests stay pure unit tests.
    """

    def __init__(
        self,
        listings: Optional[Dict[str, dict]] = None,
        candidates: Optional[List[dict]] = None,
    ):
        self._listings = listings or {}
        self._candidates = candidates or []
        # Track calls for assertions
        self.upsert_asset_calls: List[dict] = []
        self.upsert_listing_calls: List[dict] = []
        self.add_alias_calls: List[dict] = []
        self.add_identifier_calls: List[dict] = []

    async def find_by_listing(self, exchange: str, ticker: str) -> Optional[dict]:
        key = f"{exchange}:{ticker}"
        return self._listings.get(key)

    async def find_candidates(self, raw: str) -> List[dict]:
        return self._candidates

    async def upsert_asset(self, **kwargs) -> str:
        self.upsert_asset_calls.append(kwargs)
        return kwargs.get("asset_id") or "mock-asset-123"

    async def upsert_listing(self, **kwargs) -> None:
        self.upsert_listing_calls.append(kwargs)

    async def add_alias(
        self, asset_id: str, alias: str, *, alias_type: str, source: str, confidence: float
    ) -> None:
        self.add_alias_calls.append(
            dict(asset_id=asset_id, alias=alias, alias_type=alias_type, source=source, confidence=confidence)
        )

    async def add_identifier(self, asset_id: str, id_type: str, value: str) -> None:
        self.add_identifier_calls.append(dict(asset_id=asset_id, id_type=id_type, value=value))


class MockAdapterManager:
    """Mock adapter manager used by SymbolResolver for US probing and asset info."""

    def __init__(
        self,
        price_responses: Optional[Dict[str, Any]] = None,
        asset_info: Optional[Any] = None,
    ):
        self._price_responses = price_responses or {}
        self._asset_info = asset_info

    async def get_real_time_price(self, symbol: str):
        return self._price_responses.get(symbol)

    async def get_asset_info(self, symbol: str):
        return self._asset_info


def _make_resolver(
    listings: Optional[Dict[str, dict]] = None,
    candidates: Optional[List[dict]] = None,
    price_responses: Optional[Dict[str, Any]] = None,
    asset_info: Optional[Any] = None,
) -> SymbolResolver:
    repo = MockRepo(listings=listings, candidates=candidates)
    adapters = MockAdapterManager(price_responses=price_responses, asset_info=asset_info)
    return SymbolResolver(repo, adapters)


# ===================================================================
# Part 1: normalize_ticker (src/server/domain/symbols/normalize.py)
# ===================================================================


class TestNormalizeTicker:
    """Tests for normalize_ticker helper."""

    # -- Already normalized EXCHANGE:SYMBOL inputs --

    @pytest.mark.parametrize(
        "input_sym, expected",
        [
            ("SSE:600519", "SSE:600519"),
            ("SZSE:000001", "SZSE:000001"),
            ("NASDAQ:AAPL", "NASDAQ:AAPL"),
            ("NYSE:TSLA", "NYSE:TSLA"),
            ("HKEX:00700", "HKEX:00700"),
        ],
    )
    def test_already_normalized(self, input_sym, expected):
        assert normalize_ticker(input_sym) == expected

    # -- Suffix forms (600519.SH, AAPL.US, etc.) --

    @pytest.mark.parametrize(
        "input_sym, expected",
        [
            ("600519.SH", "SSE:600519"),
            ("600519.SS", "SSE:600519"),
            ("000001.SZ", "SZSE:000001"),
            ("430047.BJ", "BSE:430047"),
            ("00700.HK", "HKEX:00700"),
            ("AAPL.US", "NASDAQ:AAPL"),
        ],
    )
    def test_suffix_forms(self, input_sym, expected):
        assert normalize_ticker(input_sym) == expected

    # -- Bare numeric A-share codes --

    @pytest.mark.parametrize(
        "input_sym, expected",
        [
            ("600519", "SSE:600519"),
            ("601398", "SSE:601398"),
            ("000001", "SZSE:000001"),
            ("300750", "SZSE:300750"),
            ("830946", "BSE:830946"),
        ],
    )
    def test_bare_a_share(self, input_sym, expected):
        assert normalize_ticker(input_sym) == expected

    # -- 5-digit numeric treated as HK --

    def test_5digit_as_hk(self):
        assert normalize_ticker("00700") == "HKEX:00700"
        assert normalize_ticker("03988") == "HKEX:03988"

    # -- Bare alpha treated as US stock by default --

    def test_bare_alpha_default_us(self):
        assert normalize_ticker("AAPL") == "NASDAQ:AAPL"
        assert normalize_ticker("TSLA") == "NASDAQ:TSLA"

    def test_bare_alpha_custom_default_exchange(self):
        assert normalize_ticker("AAPL", default_us_exchange="NYSE") == "NYSE:AAPL"

    def test_bare_alpha_no_default(self):
        assert normalize_ticker("AAPL", default_us_exchange=None) == "AAPL"

    # -- Edge cases --

    def test_empty_string(self):
        assert normalize_ticker("") == ""

    def test_none_input(self):
        assert normalize_ticker(None) == ""

    def test_whitespace_input(self):
        assert normalize_ticker("  600519  ") == "SSE:600519"

    def test_case_insensitive(self):
        assert normalize_ticker("sse:600519") == "SSE:600519"
        assert normalize_ticker("nasdaq:aapl") == "NASDAQ:AAPL"
        assert normalize_ticker("szse:000001") == "SZSE:000001"

    # -- Exchange alias normalization --

    @pytest.mark.parametrize(
        "input_sym, expected",
        [
            ("SH:600519", "SSE:600519"),
            ("SHSE:600519", "SSE:600519"),
            ("SS:600519", "SSE:600519"),
            ("SZ:000001", "SZSE:000001"),
            ("BJ:430047", "BSE:430047"),
            ("HK:00700", "HKEX:00700"),
            ("US:AAPL", "NASDAQ:AAPL"),
        ],
    )
    def test_exchange_aliases(self, input_sym, expected):
        assert normalize_ticker(input_sym) == expected

    # -- Auto-correct A-share exchange mismatches --

    @pytest.mark.parametrize(
        "input_sym, expected",
        [
            ("SZSE:600519", "SSE:600519"),   # 6xxxx should be SSE, not SZSE
            ("SSE:000001", "SZSE:000001"),    # 0xxxx should be SZSE, not SSE
            ("SSE:300750", "SZSE:300750"),    # 3xxxx should be SZSE, not SSE
        ],
    )
    def test_autocorrect_a_share_exchange(self, input_sym, expected):
        assert normalize_ticker(input_sym) == expected


# ===================================================================
# Part 2: to_ts_code (src/server/domain/symbols/normalize.py)
# ===================================================================


class TestToTsCode:
    """Tests for to_ts_code helper."""

    @pytest.mark.parametrize(
        "input_sym, expected",
        [
            ("SSE:600519", "600519.SH"),
            ("SZSE:000001", "000001.SZ"),
            ("BSE:430047", "430047.BJ"),
            ("600519.SH", "600519.SH"),
        ],
    )
    def test_exchange_to_suffix(self, input_sym, expected):
        assert to_ts_code(input_sym) == expected

    def test_already_has_dot(self):
        assert to_ts_code("600519.SH") == "600519.SH"

    def test_plain_with_fallback(self):
        assert to_ts_code("600519", fallback_exchange="SSE") == "600519.SH"
        assert to_ts_code("000001", fallback_exchange="SZSE") == "000001.SZ"
        assert to_ts_code("430047", fallback_exchange="BSE") == "430047.BJ"

    def test_plain_without_fallback(self):
        assert to_ts_code("600519") == "600519"

    def test_empty(self):
        assert to_ts_code("") == ""

    def test_none(self):
        assert to_ts_code(None) == ""

    def test_non_ts_exchange_passthrough(self):
        # For non-SSE/SZSE/BSE exchanges, to_ts_code returns just the symbol part
        assert to_ts_code("NASDAQ:AAPL") == "AAPL"


# ===================================================================
# Part 3: SymbolResolver - basic resolve() paths
# ===================================================================


class TestResolveAlreadyNormalized:
    """resolve() when input already contains EXCHANGE:SYMBOL."""

    def test_sse_stock(self):
        r = _make_resolver(listings={"SSE:600519": {"asset_id": "a1", "asset_type": "stock"}})
        res = _run(r.resolve("SSE:600519"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "SSE:600519"
        assert res.exchange == "SSE"
        assert res.asset_id == "a1"

    def test_nasdaq_stock(self):
        r = _make_resolver(listings={"NASDAQ:AAPL": {"asset_id": "a2", "asset_type": "stock"}})
        res = _run(r.resolve("NASDAQ:AAPL"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "NASDAQ:AAPL"

    def test_exchange_alias_sh_to_sse(self):
        r = _make_resolver()
        res = _run(r.resolve("SH:600519"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "SSE:600519"

    def test_colon_but_empty_parts(self):
        r = _make_resolver()
        res = _run(r.resolve(":"))
        assert res.status == ResolutionStatus.INVALID
        assert res.reason == "invalid_format"

    def test_colon_only_exchange(self):
        r = _make_resolver()
        res = _run(r.resolve("SSE:"))
        assert res.status == ResolutionStatus.INVALID

    def test_colon_only_symbol(self):
        r = _make_resolver()
        res = _run(r.resolve(":600519"))
        assert res.status == ResolutionStatus.INVALID


class TestResolveSuffixForms:
    """resolve() with suffix-style inputs like 600519.SH."""

    @pytest.mark.parametrize(
        "input_sym, expected_normalized, expected_exchange",
        [
            ("600519.SH", "SSE:600519", "SSE"),
            ("600519.SS", "SSE:600519", "SSE"),
            ("000001.SZ", "SZSE:000001", "SZSE"),
            ("430047.BJ", "BSE:430047", "BSE"),
            ("00700.HK", "HKEX:00700", "HKEX"),
            ("AAPL.US", "NASDAQ:AAPL", "NASDAQ"),
        ],
    )
    def test_common_suffixes(self, input_sym, expected_normalized, expected_exchange):
        r = _make_resolver()
        res = _run(r.resolve(input_sym))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == expected_normalized
        assert res.exchange == expected_exchange


class TestResolveNumeric:
    """resolve() with bare numeric codes."""

    @pytest.mark.parametrize(
        "input_sym, expected_normalized, expected_exchange",
        [
            ("600519", "SSE:600519", "SSE"),
            ("601398", "SSE:601398", "SSE"),
            ("000001", "SZSE:000001", "SZSE"),
            ("300750", "SZSE:300750", "SZSE"),
            ("830946", "BSE:830946", "BSE"),
        ],
    )
    def test_a_share_numeric(self, input_sym, expected_normalized, expected_exchange):
        r = _make_resolver()
        res = _run(r.resolve(input_sym))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == expected_normalized
        assert res.exchange == expected_exchange

    def test_5digit_hk(self):
        r = _make_resolver()
        res = _run(r.resolve("00700"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "HKEX:00700"
        assert res.exchange == "HKEX"

    def test_4digit_numeric_not_recognized(self):
        # 4-digit numbers are not matched by any heuristic
        r = _make_resolver()
        res = _run(r.resolve("1234"))
        # Should fall through to not_found (no repo candidates, not alpha for US probe)
        assert res.status == ResolutionStatus.NOT_FOUND


# ===================================================================
# Part 4: Auto-correction of A-share exchange
# ===================================================================


class TestAutoCorrectAShareExchange:
    """_autocorrect_a_share_exchange should fix mismatched exchange prefixes."""

    def test_6xxx_wrong_szse_to_sse(self):
        r = _make_resolver()
        ex, sym = r._autocorrect_a_share_exchange("SZSE", "600519", "SZSE:600519")
        assert ex == "SSE"
        assert sym == "600519"

    def test_0xxx_wrong_sse_to_szse(self):
        r = _make_resolver()
        ex, sym = r._autocorrect_a_share_exchange("SSE", "000001", "SSE:000001")
        assert ex == "SZSE"
        assert sym == "000001"

    def test_3xxx_wrong_sse_to_szse(self):
        r = _make_resolver()
        ex, sym = r._autocorrect_a_share_exchange("SSE", "300750", "SSE:300750")
        assert ex == "SZSE"
        assert sym == "300750"

    def test_correct_exchange_unchanged(self):
        r = _make_resolver()
        ex, sym = r._autocorrect_a_share_exchange("SSE", "600519", "SSE:600519")
        assert ex == "SSE"
        assert sym == "600519"

    def test_non_a_share_exchange_unchanged(self):
        r = _make_resolver()
        ex, sym = r._autocorrect_a_share_exchange("NASDAQ", "AAPL", "NASDAQ:AAPL")
        assert ex == "NASDAQ"
        assert sym == "AAPL"

    def test_non_digit_symbol_unchanged(self):
        r = _make_resolver()
        ex, sym = r._autocorrect_a_share_exchange("SSE", "AAPL", "SSE:AAPL")
        assert ex == "SSE"
        assert sym == "AAPL"

    def test_empty_inputs(self):
        r = _make_resolver()
        assert r._autocorrect_a_share_exchange("", "600519", "") == ("", "600519")
        assert r._autocorrect_a_share_exchange("SSE", "", "") == ("SSE", "")

    # Integration: auto-correct flows through resolve()

    def test_resolve_autocorrects_suffix(self):
        r = _make_resolver()
        # 600519 is 6xxx but .SZ maps to SZSE - should auto-correct to SSE
        res = _run(r.resolve("600519.SZ"))
        assert res.normalized == "SSE:600519"

    def test_resolve_autocorrects_colon_form(self):
        r = _make_resolver()
        # 000001 is 0xxx but prefixed with SSE - should auto-correct to SZSE
        res = _run(r.resolve("SSE:000001"))
        assert res.normalized == "SZSE:000001"


# ===================================================================
# Part 5: Exchange normalization via _normalize_exchange
# ===================================================================


class TestNormalizeExchange:
    """_normalize_exchange maps common aliases to canonical exchange names."""

    @pytest.mark.parametrize(
        "alias, expected",
        [
            ("SH", "SSE"),
            ("SHSE", "SSE"),
            ("SS", "SSE"),
            ("SZ", "SZSE"),
            ("BJ", "BSE"),
            ("HK", "HKEX"),
        ],
    )
    def test_aliases(self, alias, expected):
        r = _make_resolver()
        assert r._normalize_exchange(alias) == expected

    def test_unknown_passthrough(self):
        r = _make_resolver()
        assert r._normalize_exchange("NASDAQ") == "NASDAQ"
        assert r._normalize_exchange("NYSE") == "NYSE"

    def test_lowercase_not_mapped(self):
        # The resolver's _normalize_exchange does not uppercase input before lookup.
        # Lowercase aliases are handled by callers (e.g. _split_exchange uppercases first).
        r = _make_resolver()
        assert r._normalize_exchange("sh") == "sh"
        assert r._normalize_exchange("sz") == "sz"


# ===================================================================
# Part 6: _split_exchange
# ===================================================================


class TestSplitExchange:
    def test_normal(self):
        r = _make_resolver()
        ex, sym = r._split_exchange("SSE:600519")
        assert ex == "SSE"
        assert sym == "600519"

    def test_no_colon(self):
        r = _make_resolver()
        ex, sym = r._split_exchange("600519")
        assert ex is None
        assert sym is None

    def test_alias_normalization(self):
        r = _make_resolver()
        ex, sym = r._split_exchange("SH:600519")
        assert ex == "SSE"
        assert sym == "600519"

    def test_whitespace_handling(self):
        r = _make_resolver()
        ex, sym = r._split_exchange("  SSE : 600519 ")
        assert ex == "SSE"
        assert sym == "600519"

    def test_empty_exchange(self):
        r = _make_resolver()
        ex, sym = r._split_exchange(":600519")
        assert ex is None
        assert sym == "600519"

    def test_empty_symbol(self):
        r = _make_resolver()
        ex, sym = r._split_exchange("SSE:")
        assert ex == "SSE"
        assert sym is None


# ===================================================================
# Part 7: _resolve_suffix
# ===================================================================


class TestResolveSuffix:
    def test_sh_suffix(self):
        r = _make_resolver()
        result = r._resolve_suffix("600519.SH")
        assert result == ("SSE", "600519")

    def test_sz_suffix(self):
        r = _make_resolver()
        result = r._resolve_suffix("000001.SZ")
        assert result == ("SZSE", "000001")

    def test_hk_suffix(self):
        r = _make_resolver()
        result = r._resolve_suffix("00700.HK")
        assert result == ("HKEX", "00700")

    def test_bj_suffix(self):
        r = _make_resolver()
        result = r._resolve_suffix("430047.BJ")
        assert result == ("BSE", "430047")

    def test_us_suffix(self):
        r = _make_resolver()
        result = r._resolve_suffix("AAPL.US")
        assert result == ("NASDAQ", "AAPL")

    def test_ss_suffix(self):
        r = _make_resolver()
        result = r._resolve_suffix("600519.SS")
        assert result == ("SSE", "600519")

    def test_unknown_suffix_returns_none(self):
        r = _make_resolver()
        assert r._resolve_suffix("600519.XX") is None

    def test_no_dot_returns_none(self):
        r = _make_resolver()
        assert r._resolve_suffix("600519") is None


# ===================================================================
# Part 8: _resolve_numeric
# ===================================================================


class TestResolveNumeric:
    def test_6xxx_sse(self):
        r = _make_resolver()
        assert r._resolve_numeric("600519") == ("SSE", "600519")

    def test_0xxx_szse(self):
        r = _make_resolver()
        assert r._resolve_numeric("000001") == ("SZSE", "000001")

    def test_3xxx_szse(self):
        r = _make_resolver()
        assert r._resolve_numeric("300750") == ("SZSE", "300750")

    def test_8xxx_bse(self):
        r = _make_resolver()
        assert r._resolve_numeric("830946") == ("BSE", "830946")

    def test_5digit_hkex(self):
        r = _make_resolver()
        assert r._resolve_numeric("00700") == ("HKEX", "00700")

    def test_alpha_returns_none(self):
        r = _make_resolver()
        assert r._resolve_numeric("AAPL") is None

    def test_4digit_returns_none(self):
        r = _make_resolver()
        assert r._resolve_numeric("1234") is None

    def test_7digit_returns_none(self):
        r = _make_resolver()
        assert r._resolve_numeric("1234567") is None


# ===================================================================
# Part 9: Crypto resolution
# ===================================================================


class TestResolveCrypto:
    def test_btc(self):
        r = _make_resolver()
        result = r._resolve_crypto("BTC")
        assert result is not None
        normalized, asset_type, exchange, base, quote, contract = result
        assert normalized == "CRYPTO:BTC"
        assert asset_type == "crypto"
        assert exchange == "CRYPTO"
        assert base == "BTC"

    def test_eth(self):
        r = _make_resolver()
        result = r._resolve_crypto("ETH")
        assert result is not None
        assert result[0] == "CRYPTO:ETH"

    def test_crypto_with_slash(self):
        r = _make_resolver()
        result = r._resolve_crypto("BTC/USDT")
        assert result is not None
        normalized, asset_type, exchange, base, quote, contract = result
        assert normalized == "CRYPTO:BTC"
        assert base == "BTC"
        assert quote == "USDT"

    def test_crypto_with_dash(self):
        r = _make_resolver()
        result = r._resolve_crypto("ETH-USDC")
        assert result is not None
        assert result[3] == "ETH"  # base
        assert result[4] == "USDC"  # quote

    def test_all_known_cryptos(self):
        r = _make_resolver()
        known = {"BTC", "ETH", "USDT", "BNB", "USDC", "XRP", "ADA", "DOGE", "SOL", "DOT"}
        for sym in known:
            result = r._resolve_crypto(sym)
            assert result is not None, f"{sym} should be recognized as crypto"
            assert result[0] == f"CRYPTO:{sym}"

    def test_unknown_alpha_not_crypto(self):
        r = _make_resolver()
        assert r._resolve_crypto("UNKNOWNCOIN") is None

    def test_resolve_crypto_via_resolve(self):
        r = _make_resolver()
        res = _run(r.resolve("BTC"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "CRYPTO:BTC"
        assert res.asset_type == "crypto"


# ===================================================================
# Part 10: Commodity spot resolution
# ===================================================================


class TestResolveCommoditySpot:
    def test_xauusd(self):
        r = _make_resolver()
        result = r._resolve_commodity_spot("XAUUSD")
        assert result is not None
        normalized, asset_type, exchange, base, quote, contract = result
        assert normalized == "OTC:XAUUSD"
        assert asset_type == "commodity_spot"
        assert exchange == "OTC"
        assert base == "XAU"
        assert quote == "USD"

    def test_xagusd(self):
        r = _make_resolver()
        result = r._resolve_commodity_spot("XAGUSD")
        assert result is not None
        assert result[0] == "OTC:XAGUSD"

    def test_chinese_alias_gold(self):
        r = _make_resolver()
        result = r._resolve_commodity_spot("黄金")
        assert result is not None
        assert result[0] == "OTC:XAUUSD"

    def test_chinese_alias_single_char(self):
        r = _make_resolver()
        result = r._resolve_commodity_spot("金")
        assert result is not None
        assert result[0] == "OTC:XAUUSD"

    def test_chinese_alias_silver(self):
        r = _make_resolver()
        result = r._resolve_commodity_spot("白银")
        assert result is not None
        assert result[0] == "OTC:XAGUSD"

    def test_english_alias_gold(self):
        r = _make_resolver()
        result = r._resolve_commodity_spot("GOLD")
        assert result is not None
        assert result[0] == "OTC:XAUUSD"

    def test_english_alias_silver(self):
        r = _make_resolver()
        result = r._resolve_commodity_spot("SILVER")
        assert result is not None
        assert result[0] == "OTC:XAGUSD"

    def test_yahoo_style_xauusd_x(self):
        r = _make_resolver()
        result = r._resolve_commodity_spot("XAUUSD=X")
        assert result is not None
        assert result[0] == "OTC:XAUUSD"

    def test_unknown_returns_none(self):
        r = _make_resolver()
        assert r._resolve_commodity_spot("NOTASPOT") is None

    def test_resolve_spot_via_resolve(self):
        r = _make_resolver()
        res = _run(r.resolve("XAUUSD"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "OTC:XAUUSD"
        assert res.asset_type == "commodity_spot"


# ===================================================================
# Part 11: Commodity future resolution
# ===================================================================


class TestResolveCommodityFuture:
    def test_gc_gold(self):
        r = _make_resolver()
        result = r._resolve_commodity_future("GC")
        assert result is not None
        normalized, asset_type, exchange, base, quote, contract = result
        assert normalized == "COMEX:GC"
        assert asset_type == "commodity_future"
        assert exchange == "COMEX"
        assert contract == "CONTINUOUS"

    def test_cl_crude(self):
        r = _make_resolver()
        result = r._resolve_commodity_future("CL")
        assert result is not None
        assert result[0] == "NYMEX:CL"

    def test_chinese_alias_crude_future(self):
        r = _make_resolver()
        result = r._resolve_commodity_future("原油期货")
        assert result is not None
        assert result[0] == "NYMEX:CL"

    def test_chinese_alias_brent(self):
        r = _make_resolver()
        result = r._resolve_commodity_future("布油")
        assert result is not None
        assert result[0] == "ICE:BRN"

    def test_english_alias_brent(self):
        r = _make_resolver()
        result = r._resolve_commodity_future("BRENT")
        assert result is not None
        assert result[0] == "ICE:BRN"

    def test_yahoo_style_gc_f(self):
        r = _make_resolver()
        result = r._resolve_commodity_future("GC=F")
        assert result is not None
        assert result[0] == "COMEX:GC"

    def test_unknown_returns_none(self):
        r = _make_resolver()
        assert r._resolve_commodity_future("NOTAFUTURE") is None

    def test_resolve_future_via_resolve(self):
        r = _make_resolver()
        res = _run(r.resolve("GC"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "COMEX:GC"
        assert res.asset_type == "commodity_future"


# ===================================================================
# Part 12: FX resolution
# ===================================================================


class TestResolveFx:
    def test_eurusd(self):
        r = _make_resolver()
        result = r._resolve_fx("EURUSD")
        assert result is not None
        normalized, asset_type, exchange, base, quote, contract = result
        assert normalized == "FOREX:EURUSD"
        assert asset_type == "fx"
        assert exchange == "FOREX"
        assert base == "EUR"
        assert quote == "USD"

    def test_usdjpy(self):
        r = _make_resolver()
        result = r._resolve_fx("USDJPY")
        assert result is not None
        assert result[0] == "FOREX:USDJPY"
        assert result[3] == "USD"
        assert result[4] == "JPY"

    def test_eur_slash_usd(self):
        r = _make_resolver()
        result = r._resolve_fx("EUR/USD")
        assert result is not None
        assert result[0] == "FOREX:EURUSD"

    def test_eur_dash_usd(self):
        r = _make_resolver()
        result = r._resolve_fx("EUR-USD")
        assert result is not None
        assert result[0] == "FOREX:EURUSD"

    def test_yahoo_style_fx(self):
        r = _make_resolver()
        result = r._resolve_fx("EURUSD=X")
        assert result is not None
        assert result[0] == "FOREX:EURUSD"

    def test_non_fx_pair_returns_none(self):
        r = _make_resolver()
        assert r._resolve_fx("ZZZYYY") is None

    def test_too_short_returns_none(self):
        r = _make_resolver()
        assert r._resolve_fx("EUR") is None

    def test_resolve_fx_via_resolve(self):
        r = _make_resolver()
        res = _run(r.resolve("EURUSD"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "FOREX:EURUSD"
        assert res.asset_type == "fx"


# ===================================================================
# Part 13: _build_canonical_id
# ===================================================================


class TestBuildCanonicalId:
    def test_stock(self):
        r = _make_resolver()
        cid = r._build_canonical_id("stock", "SSE", "600519")
        assert cid == "stock|SSE|600519"

    def test_commodity_spot(self):
        r = _make_resolver()
        cid = r._build_canonical_id("commodity_spot", "OTC", "XAUUSD", base="XAU", quote="USD")
        assert cid == "spot|OTC|XAU|USD"

    def test_commodity_future(self):
        r = _make_resolver()
        cid = r._build_canonical_id("commodity_future", "COMEX", "GC", contract="CONTINUOUS")
        assert cid == "future|COMEX|GC|CONTINUOUS"

    def test_fx(self):
        r = _make_resolver()
        cid = r._build_canonical_id("fx", "FOREX", "EURUSD", base="EUR", quote="USD")
        assert cid == "fx|FOREX|EUR|USD"

    def test_crypto(self):
        r = _make_resolver()
        cid = r._build_canonical_id("crypto", "CRYPTO", "BTC", base="BTC", quote="USD")
        assert cid == "crypto|CRYPTO|BTC|USD"

    def test_crypto_no_quote_defaults_usd(self):
        r = _make_resolver()
        cid = r._build_canonical_id("crypto", "CRYPTO", "BTC", base="BTC")
        assert cid == "crypto|CRYPTO|BTC|USD"

    def test_default_asset_type_is_stock(self):
        r = _make_resolver()
        cid = r._build_canonical_id(None, "NASDAQ", "AAPL")
        assert cid == "stock|NASDAQ|AAPL"


# ===================================================================
# Part 14: _build_instrument
# ===================================================================


class TestBuildInstrument:
    def test_basic_stock(self):
        r = _make_resolver()
        inst = r._build_instrument(
            raw_symbol="600519",
            normalized="SSE:600519",
            asset_type="stock",
            exchange="SSE",
        )
        assert isinstance(inst, InstrumentRef)
        assert inst.normalized == "SSE:600519"
        assert inst.asset_type == "stock"
        assert inst.exchange == "SSE"
        assert inst.raw_input == "600519"

    def test_with_base_quote(self):
        r = _make_resolver()
        inst = r._build_instrument(
            raw_symbol="XAUUSD",
            normalized="OTC:XAUUSD",
            asset_type="commodity_spot",
            exchange="OTC",
            base="XAU",
            quote="USD",
        )
        assert inst.base == "XAU"
        assert inst.quote == "USD"


# ===================================================================
# Part 15: _select_candidate
# ===================================================================


class TestSelectCandidate:
    def test_prefers_primary(self):
        r = _make_resolver()
        candidates = [
            {"exchange": "NASDAQ", "ticker": "AAPL", "is_primary": False, "asset_id": "1"},
            {"exchange": "NYSE", "ticker": "AAPL", "is_primary": True, "asset_id": "2"},
        ]
        result = r._select_candidate(candidates)
        assert result == "NYSE:AAPL"

    def test_first_if_no_primary(self):
        r = _make_resolver()
        candidates = [
            {"exchange": "NASDAQ", "ticker": "AAPL", "is_primary": False, "asset_id": "1"},
            {"exchange": "NYSE", "ticker": "AAPL", "is_primary": False, "asset_id": "2"},
        ]
        result = r._select_candidate(candidates)
        assert result == "NASDAQ:AAPL"

    def test_empty_candidates(self):
        r = _make_resolver()
        assert r._select_candidate([]) is None

    def test_candidate_missing_exchange(self):
        r = _make_resolver()
        candidates = [{"ticker": "AAPL", "is_primary": True, "asset_id": "1"}]
        assert r._select_candidate(candidates) is None

    def test_candidate_missing_ticker(self):
        r = _make_resolver()
        candidates = [{"exchange": "NASDAQ", "is_primary": True, "asset_id": "1"}]
        assert r._select_candidate(candidates) is None


# ===================================================================
# Part 16: Security master candidate lookup via resolve()
# ===================================================================


class TestResolveSecurityMasterCandidates:
    """When heuristics fail, resolver falls back to repo.find_candidates."""

    def test_single_candidate_resolved(self):
        r = _make_resolver(
            candidates=[{"exchange": "NASDAQ", "ticker": "AAPL", "is_primary": True, "asset_id": "a1"}]
        )
        res = _run(r.resolve("AAPL"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "NASDAQ:AAPL"

    def test_multiple_candidates_ambiguous(self):
        r = _make_resolver(
            candidates=[
                {"exchange": "NASDAQ", "ticker": "ABC", "is_primary": True, "asset_id": "1", "name": "ABC Nasdaq"},
                {"exchange": "NYSE", "ticker": "ABC", "is_primary": True, "asset_id": "2", "name": "ABC Nyse"},
            ]
        )
        res = _run(r.resolve("ABC"))
        # Multiple primaries -- first one wins via _select_candidate,
        # so this will resolve to the first candidate
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "NASDAQ:ABC"

    def test_no_candidates_returns_not_found(self):
        # Empty repo, no candidates. A single alpha token also probes US exchanges.
        r = _make_resolver(price_responses={})
        res = _run(r.resolve("ZZZZZZ"))
        assert res.status == ResolutionStatus.NOT_FOUND


# ===================================================================
# Part 17: US exchange probing
# ===================================================================


class TestProbeUsExchanges:
    """_probe_us_exchanges tries NASDAQ -> NYSE -> AMEX."""

    def test_found_on_nasdaq(self):
        r = _make_resolver(price_responses={"NASDAQ:AAPL": {"price": 150.0}})
        result = _run(r._probe_us_exchanges("AAPL"))
        assert result == "NASDAQ:AAPL"

    def test_found_on_nyse(self):
        r = _make_resolver(price_responses={"NYSE:TSLA": {"price": 200.0}})
        result = _run(r._probe_us_exchanges("TSLA"))
        assert result == "NYSE:TSLA"

    def test_found_on_amex(self):
        r = _make_resolver(price_responses={"AMEX:SPY": {"price": 450.0}})
        result = _run(r._probe_us_exchanges("SPY"))
        assert result == "AMEX:SPY"

    def test_not_found_on_any(self):
        r = _make_resolver(price_responses={})
        result = _run(r._probe_us_exchanges("NONEXISTENT"))
        assert result is None

    def test_probe_order_nasdaq_first(self):
        # If found on multiple, NASDAQ wins
        r = _make_resolver(price_responses={
            "NASDAQ:AAPL": {"price": 150},
            "NYSE:AAPL": {"price": 150},
        })
        result = _run(r._probe_us_exchanges("AAPL"))
        assert result == "NASDAQ:AAPL"


# ===================================================================
# Part 18: Persist resolution
# ===================================================================


class TestPersistResolution:
    """_persist_resolution creates/updates assets and listings in the repo."""

    def test_existing_listing_reuses_asset_id(self):
        r = _make_resolver(listings={"SSE:600519": {"asset_id": "existing-id", "asset_type": "stock"}})
        asset_id, resolved_type, canonical_id = _run(
            r._persist_resolution("600519", "SSE:600519")
        )
        assert asset_id == "existing-id"
        assert resolved_type == "stock"
        assert canonical_id == "stock|SSE|600519"

    def test_new_listing_creates_asset(self):
        r = _make_resolver()
        asset_id, resolved_type, canonical_id = _run(
            r._persist_resolution("600519", "SSE:600519", asset_type="stock")
        )
        # MockRepo.upsert_asset returns "mock-asset-123" by default
        assert asset_id == "mock-asset-123"
        assert resolved_type == "stock"
        assert canonical_id == "stock|SSE|600519"

    def test_invalid_normalized_returns_none(self):
        r = _make_resolver()
        asset_id, resolved_type, canonical_id = _run(
            r._persist_resolution("bad", "NOEXCHANGE")
        )
        assert asset_id is None
        assert resolved_type is None
        assert canonical_id is None

    def test_alias_added_when_raw_differs_from_symbol(self):
        r = _make_resolver(listings={"SSE:600519": {"asset_id": "a1", "asset_type": "stock"}})
        _run(r._persist_resolution("茅台上证", "SSE:600519"))
        repo = r._repo
        assert len(repo.add_alias_calls) == 1
        assert repo.add_alias_calls[0]["alias"] == "茅台上证"

    def test_no_alias_when_raw_equals_symbol(self):
        r = _make_resolver(listings={"SSE:600519": {"asset_id": "a1", "asset_type": "stock"}})
        _run(r._persist_resolution("600519", "SSE:600519"))
        repo = r._repo
        assert len(repo.add_alias_calls) == 0

    def test_canonical_id_stored_as_identifier(self):
        r = _make_resolver(listings={"SSE:600519": {"asset_id": "a1", "asset_type": "stock"}})
        _run(r._persist_resolution("600519", "SSE:600519"))
        repo = r._repo
        assert len(repo.add_identifier_calls) == 1
        assert repo.add_identifier_calls[0]["id_type"] == "canonical_id"
        assert repo.add_identifier_calls[0]["value"] == "stock|SSE|600519"


# ===================================================================
# Part 19: Error and edge cases
# ===================================================================


class TestResolveEdgeCases:
    def test_empty_string(self):
        r = _make_resolver()
        res = _run(r.resolve(""))
        assert res.status == ResolutionStatus.INVALID
        assert res.reason == "empty"

    def test_none_input(self):
        r = _make_resolver()
        res = _run(r.resolve(None))
        assert res.status == ResolutionStatus.INVALID
        assert res.reason == "empty"

    def test_whitespace_only(self):
        r = _make_resolver()
        res = _run(r.resolve("   "))
        assert res.status == ResolutionStatus.INVALID
        assert res.reason == "empty"

    def test_case_insensitive_input(self):
        r = _make_resolver()
        res = _run(r.resolve("sse:600519"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "SSE:600519"

    def test_whitespace_trimmed(self):
        r = _make_resolver()
        res = _run(r.resolve("  600519  "))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "SSE:600519"

    def test_long_numeric_not_matched(self):
        r = _make_resolver()
        res = _run(r.resolve("1234567890"))
        assert res.status == ResolutionStatus.NOT_FOUND

    def test_special_characters(self):
        r = _make_resolver()
        res = _run(r.resolve("@#$%"))
        assert res.status in (ResolutionStatus.NOT_FOUND, ResolutionStatus.INVALID)


# ===================================================================
# Part 20: End-to-end integration via resolve()
# ===================================================================


class TestResolveEndToEnd:
    """Full resolve() path exercising the complete pipeline."""

    @pytest.mark.parametrize(
        "input_sym, expected_normalized, expected_exchange, expected_asset_type",
        [
            ("SSE:600519", "SSE:600519", "SSE", "stock"),
            ("600519", "SSE:600519", "SSE", "stock"),
            ("600519.SH", "SSE:600519", "SSE", "stock"),
            ("000001", "SZSE:000001", "SZSE", "stock"),
            ("000001.SZ", "SZSE:000001", "SZSE", "stock"),
            ("300750", "SZSE:300750", "SZSE", "stock"),
            ("830946", "BSE:830946", "BSE", "stock"),
            ("00700", "HKEX:00700", "HKEX", "stock"),
            ("00700.HK", "HKEX:00700", "HKEX", "stock"),
            ("BTC", "CRYPTO:BTC", "CRYPTO", "crypto"),
            ("XAUUSD", "OTC:XAUUSD", "OTC", "commodity_spot"),
            ("GC", "COMEX:GC", "COMEX", "commodity_future"),
            ("EURUSD", "FOREX:EURUSD", "FOREX", "fx"),
        ],
    )
    def test_various_inputs(self, input_sym, expected_normalized, expected_exchange, expected_asset_type):
        r = _make_resolver()
        res = _run(r.resolve(input_sym))
        assert res.status == ResolutionStatus.RESOLVED, f"Failed for {input_sym}: {res.reason}"
        assert res.normalized == expected_normalized
        assert res.exchange == expected_exchange
        assert res.asset_type == expected_asset_type

    def test_instrument_ref_populated(self):
        r = _make_resolver()
        res = _run(r.resolve("SSE:600519"))
        assert res.instrument is not None
        assert isinstance(res.instrument, InstrumentRef)
        assert res.instrument.normalized == "SSE:600519"
        assert res.instrument.raw_input == "SSE:600519"

    def test_fx_with_slash(self):
        r = _make_resolver()
        res = _run(r.resolve("EUR/USD"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "FOREX:EURUSD"
        assert res.instrument.base == "EUR"
        assert res.instrument.quote == "USD"

    def test_commodity_spot_with_yahoo_suffix(self):
        r = _make_resolver()
        res = _run(r.resolve("XAUUSD=X"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "OTC:XAUUSD"

    def test_commodity_future_with_yahoo_suffix(self):
        r = _make_resolver()
        res = _run(r.resolve("GC=F"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "COMEX:GC"

    def test_chinese_commodity_name(self):
        r = _make_resolver()
        res = _run(r.resolve("黄金"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "OTC:XAUUSD"

    def test_us_stock_probed_and_found(self):
        r = _make_resolver(price_responses={"NASDAQ:AAPL": {"price": 150}})
        # AAPL is 4 chars -> matches [A-Z]{1,6} -> probes US exchanges
        # First need no repo candidates so it falls through to probe
        res = _run(r.resolve("AAPL"))
        assert res.status == ResolutionStatus.RESOLVED
        assert res.normalized == "NASDAQ:AAPL"

    def test_raw_preserved_in_result(self):
        r = _make_resolver()
        res = _run(r.resolve("600519"))
        assert res.raw == "600519"

    def test_raw_case_preserved(self):
        r = _make_resolver()
        res = _run(r.resolve("sse:600519"))
        assert res.raw == "sse:600519"
        assert res.normalized == "SSE:600519"
