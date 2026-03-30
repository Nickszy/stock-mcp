# src/server/domain/structured_data/normalize/engine.py
"""Normalization engine — transform raw source data into canonical schema.

Each data dimension provides a Normalizer that maps source-specific field names
and value formats to the unified canonical schema. The engine provides the
base class and shared utilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.server.utils.logger import logger


# ---------------------------------------------------------------------------
# Field mapping helper
# ---------------------------------------------------------------------------

class FieldMapping:
    """Declarative field mapping from source schema to canonical schema.

    Usage:
        mapping = FieldMapping([
            ("source_field", "canonical_field", str, None),   # required
            ("src_opt", "canonical_opt", float, 0.0),         # optional with default
        ])
        result = mapping.apply(raw_data)
    """

    def __init__(self,
        mappings: List[Tuple[str, str, type, Any]],
        # (source_key, canonical_key, value_type, default_or_MISSING)
    ):
        self.mappings = mappings

    def apply(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Apply mappings to raw data, producing canonical dict."""
        result: Dict[str, Any] = {}
        for src_key, canon_key, vtype, default in self.mappings:
            if src_key not in raw or raw[src_key] is None:
                # Check if default is the MISSING sentinel
                if default is MISSING or isinstance(default, type) and issubclass(default, MISSING):
                    continue
                result[canon_key] = default
                continue
            result[canon_key] = self._coerce(raw[src_key], vtype)
        return result

    @staticmethod
    def _coerce(value: Any, vtype: type) -> Any:
        """Coerce a value to the target type, returning original on failure."""
        if isinstance(value, vtype):
            return value
        try:
            if vtype is float:
                return float(value)
            if vtype is int:
                return int(float(value))  # handle "123.0" strings
            if vtype is str:
                return str(value).strip()
            return vtype(value)
        except (ValueError, TypeError):
            return value  # Return as-is if coercion fails


class MISSING:
    """Sentinel for required fields with no default."""
    pass


# ---------------------------------------------------------------------------
# Normalizer base class
# ---------------------------------------------------------------------------

class Normalizer(ABC):
    """Base class for data dimension normalizers.

    Subclasses must implement `normalize()` to transform raw source data
    into the canonical schema for their dimension.
    """

    @property
    @abstractmethod
    def dataset_key(self) -> str:
        """The dataset this normalizer handles."""
        ...

    @abstractmethod
    async def normalize(
        self,
        raw_data: Dict[str, Any],
        source: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Transform raw data to canonical schema.

        Args:
            raw_data: Raw data from a source adapter
            source: Source name (akshare, tushare, etc.)

        Returns:
            Normalized data dict with at minimum:
            - business_key: str (canonical primary key components)
            - canonical fields per dimension schema
        """
        ...

    async def normalize_batch(
        self,
        raw_items: List[Dict[str, Any]],
        source: str = "",
    ) -> List[Dict[str, Any]]:
        """Normalize a batch of raw items."""
        results = []
        for item in raw_items:
            try:
                normalized = await self.normalize(item, source=source)
                results.append(normalized)
            except Exception as e:
                logger.warning(
                    "Normalization failed for item",
                    dataset_key=self.dataset_key,
                    source=source,
                    error=str(e),
                )
                results.append({
                    "_normalization_error": str(e),
                    "_raw_data": item,
                })
        return results

    def build_business_key(self, **kwargs) -> str:
        """Build a canonical business key from components.

        Default implementation joins with ':'. Subclasses can override.
        """
        parts = [str(v) for v in kwargs.values() if v is not None]
        return ":".join(parts)


# ---------------------------------------------------------------------------
# Identity normalizer (passthrough — for testing or already-normalized data)
# ---------------------------------------------------------------------------

class IdentityNormalizer(Normalizer):
    """Pass-through normalizer that adds business_key and metadata."""

    def __init__(self, dataset_key: str = "identity"):
        self._dataset_key = dataset_key

    @property
    def dataset_key(self) -> str:
        return self._dataset_key

    async def normalize(
        self,
        raw_data: Dict[str, Any],
        source: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        result = dict(raw_data)
        if "business_key" not in result:
            result["business_key"] = result.get("symbol", "unknown")
        result["_source"] = source
        result["_normalized_at"] = datetime.now(timezone.utc).isoformat()
        return result
