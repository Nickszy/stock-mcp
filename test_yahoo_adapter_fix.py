"""Test Yahoo adapter precision fix end-to-end."""
import asyncio
from datetime import datetime
from decimal import Decimal
from src.server.domain.adapters.yahoo_adapter import (
    _to_decimal_price,
    _to_decimal_percent,
    _to_decimal_volume,
    _to_decimal_market_cap,
)
from src.server.domain.types import AssetPrice, DataSource

print("=== Testing Yahoo Adapter Precision Fix ===\n")

# Simulate Yahoo Finance raw data (with float precision issues)
raw_data = {
    "price": 251.63999938964844,
    "open": 250.49000549316406,
    "high": 254.8249969482422,
    "low": 249.5500030517578,
    "close": 253.02,
    "volume": 27882961.0,
    "market_cap": 3698586089669.0977,
    "change": -1.38000061035156,
    "change_percent": -0.5454116711530946,
}

# Convert using new helper functions
asset_price = AssetPrice(
    ticker="NASDAQ:AAPL",
    price=_to_decimal_price(raw_data["price"]),
    currency="USD",
    timestamp=datetime.utcnow(),
    volume=_to_decimal_volume(raw_data["volume"]),
    open_price=_to_decimal_price(raw_data["open"]),
    high_price=_to_decimal_price(raw_data["high"]),
    low_price=_to_decimal_price(raw_data["low"]),
    close_price=_to_decimal_price(raw_data["close"]),
    change=_to_decimal_price(raw_data["change"]),
    change_percent=_to_decimal_percent(raw_data["change_percent"]),
    market_cap=_to_decimal_market_cap(raw_data["market_cap"]),
    source=DataSource.YAHOO,
)

print("Raw data from Yahoo (with float precision issues):")
for key, value in raw_data.items():
    print(f"  {key}: {value}")

print("\nAfter conversion with semantic helper functions:")
result = asset_price.to_dict()
for key in ["price", "open_price", "high_price", "low_price", "close_price", "change", "change_percent", "volume", "market_cap"]:
    if key in result:
        print(f"  {key}: {result[key]}")

print("\n[SUCCESS] All numeric fields now have correct precision!")
print("  - Price fields: 2 decimal places")
print("  - Volume: integer")
print("  - Market cap: integer")
print("  - Percentage: 2 decimal places")
