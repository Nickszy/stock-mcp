"""Test script to verify price rounding fix."""
from decimal import Decimal
from datetime import datetime
from src.server.domain.types import AssetPrice, DataSource

# Test data similar to the user's example
test_price = AssetPrice(
    ticker="NASDAQ:AAPL",
    price=Decimal("251.63999938964844"),
    currency="USD",
    timestamp=datetime.now(),
    volume=Decimal("27882961"),
    open_price=Decimal("250.49000549316406"),
    high_price=Decimal("254.8249969482422"),
    low_price=Decimal("249.5500030517578"),
    close_price=Decimal("253.02"),
    change=Decimal("-1.38000061035156"),
    change_percent=Decimal("-0.5454116711530946"),
    market_cap=Decimal("3698586089669.0977"),
    source=DataSource.YAHOO
)

# Convert to dict
result = test_price.to_dict()

print("=== Before Rounding (Original Issue) ===")
print(f"price: 251.63999938964844")
print(f"market_cap: 3698586089669.0977")
print()

print("=== After Rounding (Fixed) ===")
print(f"price: {result['price']}")
print(f"market_cap: {result['market_cap']}")
print(f"volume: {result['volume']}")
print(f"open_price: {result['open_price']}")
print(f"high_price: {result['high_price']}")
print(f"low_price: {result['low_price']}")
print(f"change: {result['change']}")
print(f"change_percent: {result['change_percent']}")
print()

print("=== Full Output ===")
import json
print(json.dumps(result, indent=2, default=str))
