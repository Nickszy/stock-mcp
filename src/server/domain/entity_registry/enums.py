# src/server/domain/entity_registry/enums.py
"""Enums for the entity registry module."""

from enum import Enum


class EntityStatus(str, Enum):
    """Lifecycle status for a registered entity."""

    ACTIVE = "active"              # Normal trading
    SUSPENDED = "suspended"        # Temporarily halted
    DELISTED = "delisted"          # Permanently removed from exchange
    PENDING = "pending"            # Awaiting verification / enrichment
    MERGED = "merged"              # Absorbed by another entity


class ClassificationScheme(str, Enum):
    """Industry classification system.

    Primary usage per market:
    - A 股: SW_INDUSTRY (申万) 一级最佳 + CITIC (中信) 细分最佳
    - 港股: HSICS (恒生行业分类) 港交所官方标准
    - 美股/国际: GICS (MSCI/标普)
    - A+H 对比: 统一用中信或申万
    """

    # ── A 股 ──
    SW_INDUSTRY = "sw_industry"    # 申万行业分类 (A股一级行业最优，公认标准)
    CITIC = "citic"                # 中信行业分类 (A股细分行业最优，二三级更精细)
    CSRC = "csrc"                  # 证监会行业分类

    # ── 港股 ──
    HSICS = "hsics"                # 恒生行业分类 (Hang Seng Industry Classification System, 港交所官方)

    # ── 美股/国际 ──
    GICS = "gics"                  # Global Industry Classification Standard (MSCI/标普)

    # ── 跨市场/通用 ──
    WIND = "wind"                  # Wind 行业分类 (覆盖 A/港/美)
    CONCEPT = "concept"            # 概念板块
    REGION = "region"              # 地域板块
    CUSTOM = "custom"              # User-defined


class RelationType(str, Enum):
    """Type of relationship between two entities."""

    SUBSIDIARY = "subsidiary"              # Parent owns child
    CROSS_LISTED = "cross_listed"          # Same company listed on multiple exchanges (e.g. A+H)
    SAME_ENTITY = "same_entity"            # Aliases for the same underlying company
    SPUN_OFF_FROM = "spun_off_from"        # Child was carved out from parent
    MERGED_INTO = "merged_into"            # Source entity merged into target
    PEER = "peer"                          # Same-industry peer (loose relationship)
    SUPPLY_CHAIN_UP = "supply_chain_up"    # Upstream supplier
    SUPPLY_CHAIN_DOWN = "supply_chain_down"  # Downstream customer


class EntityEventType(str, Enum):
    """Type of corporate event affecting an entity."""

    NAME_CHANGE = "name_change"
    TICKER_CHANGE = "ticker_change"
    IPO = "ipo"
    DELISTING = "delisting"
    MERGER = "merger"
    SPINOFF = "spinoff"
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    STATUS_CHANGE = "status_change"        # e.g. ST → normal


class MarketCapTier(str, Enum):
    """Market capitalization tier."""

    MEGA = "mega"        # > 1000 亿
    LARGE = "large"      # 200-1000 亿
    MID = "mid"          # 50-200 亿
    SMALL = "small"      # 10-50 亿
    MICRO = "micro"      # < 10 亿
