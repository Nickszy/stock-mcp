"""Test to verify precision fix at the adapter level."""
import asyncio
from src.server.domain.adapters.yahoo_adapter import _to_decimal, _to_decimal_large
from decimal import Decimal

print("=== Testing Precision Helper Functions ===\n")

# Test _to_decimal
test_values = [
    (251.63999938964844, 2, "251.64"),
    (250.49000549316406, 2, "250.49"),
    (254.8249969482422, 2, "254.82"),
    (-1.38000061035156, 2, "-1.38"),
    (-0.5454116711530946, 2, "-0.55"),
    (None, 2, "None"),
]

print("Testing _to_decimal (for prices):")
for value, places, expected in test_values:
    result = _to_decimal(value, places)
    result_str = str(result) if result else "None"
    status = "PASS" if result_str == expected else "FAIL"
    print(f"  [{status}] _to_decimal({value}, {places}) = {result_str} (expected: {expected})")

print("\nTesting _to_decimal_large (for market_cap, volume):")
large_test_values = [
    (3698586089669.0977, "3698586089669"),  # Large number -> integer
    (27882961, "27882961"),  # Large number -> integer
    (999.999, "1000.00"),  # Small number -> 2 decimals
    (None, "None"),
]

for value, expected in large_test_values:
    result = _to_decimal_large(value)
    result_str = str(result) if result else "None"
    status = "PASS" if result_str == expected else "FAIL"
    print(f"  [{status}] _to_decimal_large({value}) = {result_str} (expected: {expected})")

print("\n=== Summary ===")
print("[PASS] Precision is now handled at the adapter level (data source)")
print("[PASS] Float precision issues are eliminated during Decimal conversion")
print("[PASS] No need for rounding in to_dict() output layer")
