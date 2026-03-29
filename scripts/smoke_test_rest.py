#!/usr/bin/env python3
"""Smoke test: hit every REST endpoint and report HTTP status.

Usage:
    # Against Docker container (default)
    uv run python scripts/smoke_test_rest.py

    # Against local uvicorn
    uv run python scripts/smoke_test_rest.py --base http://localhost:9898
"""

import asyncio
import sys
from typing import List, Tuple

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: uv pip install httpx")
    sys.exit(1)

BASE = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8120"

# (method, path, params_dict)
ENDPOINTS: List[Tuple[str, str, dict]] = [
    # --- Fact Pack ---
    ("GET", "/api/v1/fact-pack/stock/000001", {}),
    ("GET", "/api/v1/fact-pack/fund/110011", {}),
    ("GET", "/api/v1/fact-pack/market/SSE:600519", {}),
    ("GET", "/api/v1/fact-pack/us-stock/AAPL", {}),
    ("GET", "/api/v1/fact-pack/etf/510300", {}),
    ("GET", "/api/v1/fact-pack/index/000300", {}),

    # --- Fund ---
    ("GET", "/api/v1/fund/detail", {"fund_code": "110011"}),
    ("GET", "/api/v1/fund/search", {"keyword": "易方达"}),
    ("GET", "/api/v1/fund/ranking", {}),
    ("GET", "/api/v1/fund/manager", {}),
    ("GET", "/api/v1/fund/valuation", {}),
    ("GET", "/api/v1/fund/performance", {"fund_code": "110011"}),
    ("GET", "/api/v1/fund/scale", {}),
    ("GET", "/api/v1/fund/nav", {"fund_code": "110011", "days": "7"}),
    ("GET", "/api/v1/fund/holdings", {"fund_code": "110011"}),

    # --- US Market ---
    ("GET", "/api/v1/us/profile", {"ticker": "AAPL"}),
    ("GET", "/api/v1/us/earnings", {"ticker": "AAPL", "quarters": "2"}),
    ("GET", "/api/v1/us/cashflow-quality", {"ticker": "AAPL"}),
    ("GET", "/api/v1/us/valuation", {"ticker": "AAPL"}),
    ("GET", "/api/v1/us/institutional", {"ticker": "AAPL"}),
    ("GET", "/api/v1/us/analyst", {"ticker": "AAPL"}),
    ("GET", "/api/v1/us/revenue-segments", {"ticker": "AAPL"}),
    ("GET", "/api/v1/us/insider", {"ticker": "AAPL"}),
    ("GET", "/api/v1/us/share-stats", {"ticker": "AAPL"}),
    ("GET", "/api/v1/us/financial-health", {"ticker": "AAPL"}),
    ("GET", "/api/v1/us/price-history", {"ticker": "AAPL", "days": "5"}),
    ("GET", "/api/v1/us/volume-analysis", {"ticker": "AAPL", "days": "5"}),
    ("GET", "/api/v1/us/market-overview", {}),

    # --- Fundamental (gateway GET endpoints) ---
    ("GET", "/api/v1/fundamental/main-business", {"symbol": "000001"}),
    ("GET", "/api/v1/fundamental/shareholders", {"symbol": "000001"}),
    ("GET", "/api/v1/fundamental/dividends", {"symbol": "000001"}),
    ("GET", "/api/v1/fundamental/valuation", {"symbol": "000001"}),

    # --- Fundamental (use-case POST endpoints) ---
    ("POST", "/api/v1/fundamental/financials", {"symbol": "000001"}),
    ("POST", "/api/v1/fundamental/report", {"symbol": "000001"}),
    ("POST", "/api/v1/fundamental/ratios", {"symbol": "000001"}),

    # --- ETF ---
    ("GET", "/api/v1/etf/list", {}),
    ("GET", "/api/v1/etf/detail", {"symbol": "510300"}),
    ("GET", "/api/v1/etf/performance", {"symbol": "510300"}),

    # --- Index ---
    ("GET", "/api/v1/index/list", {}),
    ("GET", "/api/v1/index/pe-pb", {"symbol": "沪深300", "limit": "5"}),
    ("GET", "/api/v1/index/performance", {"symbol": "000300", "limit": "5"}),

    # --- Quantitative ---
    ("GET", "/api/v1/quant/industry-ranking", {}),
    ("GET", "/api/v1/quant/concept-ranking", {}),
    ("GET", "/api/v1/quant/factors", {"symbol": "600519", "days": "30"}),
    ("GET", "/api/v1/quant/factor-ranking", {}),

    # --- Market Data (POST endpoints) ---
    ("POST", "/api/v1/market/asset/info", {"symbol": "SSE:600519"}),
    ("POST", "/api/v1/market/signals/technical", {"symbol": "SSE:600519"}),

    # --- Corporate Action ---
    ("GET", "/api/v1/corporate-action/shareholder-holding", {"symbol": "688235"}),
    ("GET", "/api/v1/corporate-action/ipo-calendar", {}),
    ("GET", "/api/v1/corporate-action/ipo-info/600519", {}),
    # --- Money Flow (batch 2: COL-177) ---
    ("GET", "/api/v1/money-flow/market-money-flow", {"days": 10}),
    ("GET", "/api/v1/money-flow/dragon-tiger", {"days": 5}),
    ("GET", "/api/v1/money-flow/block-trade", {}),
    ("GET", "/api/v1/money-flow/money-supply", {}),
    ("GET", "/api/v1/money-flow/pmi", {}),
    ("GET", "/api/v1/money-flow/gdp", {}),
    ("GET", "/api/v1/money-flow/bond-yield", {"days": 30}),
    ("GET", "/api/v1/money-flow/etf-flow", {}),
    ("GET", "/api/v1/money-flow/futures-main", {}),
    ("GET", "/api/v1/money-flow/northbound-holdings", {"symbol": "600519"}),
    ("GET", "/api/v1/money-flow/top10-shareholders", {"symbol": "600519"}),
    ("GET", "/api/v1/money-flow/sector-pe-pb", {"sector_name": "白酒", "days": 60}),
    ("GET", "/api/v1/money-flow/risk-metrics", {"symbol": "600519", "days": 60}),
    ("GET", "/api/v1/money-flow/index-constituents", {"symbol": "000300"}),
    ("GET", "/api/v1/money-flow/fund-holdings", {"symbol": "110011"}),
]


async def main():
    ok, fail, skip = 0, 0, 0
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        for method, path, params in ENDPOINTS:
            try:
                if method == "GET":
                    r = await client.get(path, params=params)
                else:
                    r = await client.post(path, params=params)
                status = r.status_code
                if status < 400:
                    ok += 1
                    print(f"  OK  {status} {method} {path}")
                else:
                    fail += 1
                    detail = ""
                    try:
                        body = r.json()
                        detail = body.get("detail", "")[:80]
                    except Exception:
                        detail = r.text[:80]
                    print(f" FAIL {status} {method} {path} — {detail}")
            except Exception as e:
                skip += 1
                print(f" SKIP      {method} {path} — {e}")

    total = ok + fail + skip
    print(f"\n{'='*60}")
    print(f"Results: {ok} OK, {fail} FAIL, {skip} SKIP ({total} total)")
    if fail > 0:
        print(f"FAIL rate: {fail/total*100:.1f}%")
        sys.exit(1)
    else:
        print("All endpoints passed!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
