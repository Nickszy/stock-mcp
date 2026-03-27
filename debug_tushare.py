#!/usr/bin/env uv run python
"""Debug tushare validate_ticker issue."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.server.domain.types import Exchange, AdapterCapability
from src.server.domain.adapters.tushare_adapter import TushareAdapter

# Create a minimal tushare adapter for testing
class MockTushareConn:
    def get_client(self):
        return None

class MockCache:
    async def get(self, key):
        return None

    async def set(self, key, value, ttl=None):
        pass

# Test capabilities
adapter = TushareAdapter(MockTushareConn(), MockCache())
capabilities = adapter.get_capabilities()

print("=" * 60)
print("TushareAdapter Capabilities:")
print("=" * 60)
for i, cap in enumerate(capabilities, 1):
    print(f"\n{i}. Asset Type: {cap.asset_type}")
    print(f"   Exchanges: {[e.value for e in cap.exchanges]}")

# Test validate_ticker
print("\n" + "=" * 60)
print("Testing validate_ticker:")
print("=" * 60)

test_tickers = [
    "SSE:600519",
    "SZSE:000001",
    "BSE:430047",
    "NASDAQ:AAPL",  # Should fail
]

for ticker in test_tickers:
    result = adapter.validate_ticker(ticker)
    print(f"\n{ticker}: {result}")

    if not result:
        # Debug why it failed
        exchange_str = ticker.split(":")[0]
        try:
            exchange_enum = Exchange(exchange_str)
            print(f"  - Exchange enum created: {exchange_enum}")
            print(f"  - Supports check:")
            for cap in capabilities:
                supports = cap.supports_exchange(exchange_enum)
                print(f"    - {cap.asset_type}: {supports}")
        except Exception as e:
            print(f"  - Failed to create Exchange enum: {e}")

print("\n" + "=" * 60)
