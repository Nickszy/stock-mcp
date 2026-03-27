"""Data types and structures for the Stock MCP platform.

This module defines the core data structures for representing financial assets,
aligned with ValueCell's architecture.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator


class AssetType(str, Enum):
    """Enumeration of supported asset types."""

    STOCK = "stock"
    CRYPTO = "crypto"
    CCXT = "ccxt"
    ETF = "etf"
    INDEX = "index"
    FUND = "fund"
    COMMODITY_SPOT = "commodity_spot"
    COMMODITY_FUTURE = "commodity_future"
    FX = "fx"


class Exchange(str, Enum):
    """Enumeration of supported exchanges."""

    NASDAQ = "NASDAQ"
    NYSE = "NYSE"
    AMEX = "AMEX"
    SSE = "SSE"  # Shanghai Stock Exchange
    SZSE = "SZSE"  # Shenzhen Stock Exchange
    BSE = "BSE"  # Beijing Stock Exchange
    HKEX = "HKEX"  # Hong Kong Stock Exchange
    CRYPTO = "CRYPTO"
    COMEX = "COMEX"  # Metals futures
    NYMEX = "NYMEX"  # Energy futures
    CME = "CME"
    ICE = "ICE"
    FOREX = "FOREX"
    OTC = "OTC"


class MarketStatus(str, Enum):
    """Market status enumeration."""

    OPEN = "open"
    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    AFTER_HOURS = "after_hours"
    HALTED = "halted"
    UNKNOWN = "unknown"


class DataSource(str, Enum):
    """Supported data source providers."""

    YAHOO = "yahoo"
    AKSHARE = "akshare"
    FINNHUB = "finnhub"
    TUSHARE = "tushare"
    BAOSTOCK = "baostock"
    CRYPTO = "crypto"
    EDGAR = "edgar"
    ALPHA_VANTAGE = "alpha_vantage"
    FUTURES = "futures"
    TWELVE_DATA = "twelve_data"
    CCXT = "ccxt"
    FRED = "fred"


@dataclass
class AdapterCapability:
    """Describes the asset types and exchanges supported by an adapter."""

    asset_type: AssetType
    exchanges: Set[Exchange]

    def supports_exchange(self, exchange: Exchange) -> bool:
        """Check if this capability supports the given exchange."""
        return exchange in self.exchanges


@dataclass
class MarketInfo:
    """Market information for an asset."""

    exchange: str
    country: str
    currency: str
    timezone: str
    trading_hours: Optional[Dict[str, str]] = None
    market_status: MarketStatus = MarketStatus.UNKNOWN


class Asset(BaseModel):
    """Core asset data structure."""

    # Core identification
    ticker: str = Field(..., description="Standardized ticker format: EXCHANGE:SYMBOL")
    asset_type: AssetType = Field(..., description="Type of financial asset")

    # Names
    name: str = Field(..., description="Asset name")

    # Market information
    market_info: MarketInfo = Field(..., description="Market and exchange information")

    # Data source mappings
    source_mappings: Dict[DataSource, str] = Field(
        default_factory=dict,
        description="Mapping of data sources to their specific ticker formats",
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(
        default=True, description="Whether asset is currently tradable"
    )

    # Additional properties
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Additional asset properties"
    )

    @field_validator("ticker")
    @classmethod
    def validate_ticker_format(cls, v):
        """Validate ticker format: EXCHANGE:SYMBOL"""
        if ":" not in v:
            raise ValueError("Ticker must be in format 'EXCHANGE:SYMBOL'")
        parts = v.split(":")
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise ValueError("Invalid ticker format. Expected 'EXCHANGE:SYMBOL'")
        return v.upper()

    def get_exchange(self) -> str:
        """Extract exchange from ticker."""
        return self.ticker.split(":")[0]

    def get_symbol(self) -> str:
        """Extract symbol from ticker."""
        return self.ticker.split(":")[1]

    def get_source_ticker(self, source: DataSource) -> Optional[str]:
        """Get ticker format for specific data source."""
        return self.source_mappings.get(source)

    def set_source_ticker(self, source: DataSource, ticker: str) -> None:
        """Set ticker format for specific data source."""
        self.source_mappings[source] = ticker
        self.updated_at = datetime.utcnow()

    model_config = {"arbitrary_types_allowed": True}


@dataclass
class AssetPrice:
    """Real-time or historical price data for an asset."""

    ticker: str
    price: Decimal
    currency: str
    timestamp: datetime
    volume: Optional[Decimal] = None
    open_price: Optional[Decimal] = None
    high_price: Optional[Decimal] = None
    low_price: Optional[Decimal] = None
    close_price: Optional[Decimal] = None
    change: Optional[Decimal] = None
    change_percent: Optional[Decimal] = None
    market_cap: Optional[Decimal] = None
    source: Optional[DataSource] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation with intelligent rounding."""
        def _round_price(val):
            """Round price fields to 2 decimal places."""
            if val is None:
                return None
            f = float(val)
            return round(f, 2)

        def _round_large(val):
            """Round large numbers (volume, market_cap) intelligently."""
            if val is None:
                return None
            f = float(val)
            if abs(f) >= 1_000_000:
                return int(round(f))  # Large numbers as integers
            return round(f, 2)

        return {
            "ticker": self.ticker,
            "price": _round_price(self.price),
            "currency": self.currency,
            "timestamp": (
                self.timestamp.isoformat()
                if isinstance(self.timestamp, datetime)
                else self.timestamp
            ),
            "volume": _round_large(self.volume),
            "open_price": _round_price(self.open_price),
            "high_price": _round_price(self.high_price),
            "low_price": _round_price(self.low_price),
            "close_price": _round_price(self.close_price),
            "change": _round_price(self.change),
            "change_percent": (
                round(float(self.change_percent), 2) if self.change_percent else None
            ),
            "market_cap": _round_large(self.market_cap),
            "source": self.source.value if self.source else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssetPrice":
        """Create AssetPrice from dictionary (for cache deserialization)."""
        # Parse timestamp if it's a string
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        # Parse source enum if it's a string
        source = data.get("source")
        if isinstance(source, str):
            source = DataSource(source)

        # Convert numeric fields back to Decimal
        return cls(
            ticker=data["ticker"],
            price=(
                Decimal(str(data["price"])) if data.get("price") is not None else None
            ),
            currency=data["currency"],
            timestamp=timestamp,
            volume=(
                Decimal(str(data["volume"])) if data.get("volume") is not None else None
            ),
            open_price=(
                Decimal(str(data["open_price"]))
                if data.get("open_price") is not None
                else None
            ),
            high_price=(
                Decimal(str(data["high_price"]))
                if data.get("high_price") is not None
                else None
            ),
            low_price=(
                Decimal(str(data["low_price"]))
                if data.get("low_price") is not None
                else None
            ),
            close_price=(
                Decimal(str(data["close_price"]))
                if data.get("close_price") is not None
                else None
            ),
            change=(
                Decimal(str(data["change"])) if data.get("change") is not None else None
            ),
            change_percent=(
                Decimal(str(data["change_percent"]))
                if data.get("change_percent") is not None
                else None
            ),
            market_cap=(
                Decimal(str(data["market_cap"]))
                if data.get("market_cap") is not None
                else None
            ),
            source=source,
        )



# Fallback search provider type (for LLM-based search)
class FallbackSearchProvider(BaseModel):
    """Configuration for LLM-based fallback search."""

    enabled: bool = True
    model_name: str = "gpt-4"
    max_retries: int = 3
