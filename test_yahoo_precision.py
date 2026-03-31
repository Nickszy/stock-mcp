"""Test to check raw data precision from Yahoo Finance."""
import yfinance as yf
from decimal import Decimal

# Get AAPL data
ticker = yf.Ticker("AAPL")

# Check fast_info
print("=== Raw data from Yahoo Finance API ===\n")

try:
    fast_info = ticker.fast_info
    if fast_info:
        price = getattr(fast_info, "last_price", None)
        print(f"Raw price type: {type(price)}")
        print(f"Raw price value: {price}")
        print(f"Raw price repr: {repr(price)}")
        print()

        # Show the problem
        print("=== Current (Wrong) Conversion ===")
        print(f"Decimal(str(price)): {Decimal(str(price))}")
        print()

        # Show correct conversion methods
        print("=== Better Conversion Methods ===")

        # Method 1: Direct Decimal then quantize
        from decimal import ROUND_HALF_UP
        precise = Decimal(str(price))
        rounded = precise.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        print(f"Method 1 - Quantize to 2 decimals: {rounded}")

        # Method 2: Round float first
        rounded_float = round(price, 2)
        decimal_from_rounded = Decimal(str(rounded_float))
        print(f"Method 2 - Round float first: {decimal_from_rounded}")

        print()

        # Check other fields
        for attr in ['open', 'day_high', 'day_low', 'previous_close', 'market_cap']:
            val = getattr(fast_info, attr, None)
            if val is not None:
                print(f"{attr}: {val} (type: {type(val).__name__})")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
