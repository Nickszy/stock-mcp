# src/server/infrastructure/cache/redis_cache.py
"""Async cache wrapper using aiocache with Redis backend.
All services can use `cache.get/set` without worrying about client details.
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import aiocache
from aiocache import Cache
from aiocache.serializers import BaseSerializer
from src.server.infrastructure.connections.redis_connection import RedisConnection

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))  # A-stock market timezone (UTC+8)


def market_aware_ttl(trading_ttl: int = 300, max_ttl: int = 72 * 3600) -> int:
    """Calculate smart TTL based on A-stock market hours (CST/UTC+8).

    - Trading hours (weekday 9:30-15:00 CST, excluding 15:00): use ``trading_ttl``
    - After market close on weekday: cache until next 9:15 CST
    - Weekend: cache until Monday 9:15 CST
    - Chinese public holidays are NOT handled (data stays short-TTL)

    Returns:
        TTL in seconds, capped at ``max_ttl`` for freshness-oriented windows while
        allowing closed-market carryover TTLs to span the full closed period.
    """
    now = datetime.now(_CST)
    weekday = now.weekday()  # 0=Mon .. 6=Sun

    def _seconds_until(target_hour: int, target_min: int, days_ahead: int = 0) -> int:
        target = (now + timedelta(days=days_ahead)).replace(
            hour=target_hour, minute=target_min, second=0, microsecond=0
        )
        return max(int((target - now).total_seconds()), 0)

    # Weekend → cache until Monday 9:15
    if weekday >= 5:
        days_to_mon = 7 - weekday
        ttl = _seconds_until(9, 15, days_to_mon)
        return max(ttl, 3600)

    # Before market open → cache until 9:30
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        ttl = _seconds_until(9, 30)
        return min(max(ttl, 300), max_ttl)

    # During trading hours (9:30-14:59) → short TTL
    if now.hour < 15:
        return min(trading_ttl, max_ttl)

    # After market close on weekday
    if weekday == 4:  # Friday → cache until Monday 9:15
        ttl = _seconds_until(9, 15, 3)
    else:
        ttl = _seconds_until(9, 15, 1)

    return max(ttl, 3600)


class DateAwareJsonSerializer(BaseSerializer):
    """JSON serializer that handles date and datetime objects."""
    
    DEFAULT_ENCODING = "utf-8"
    
    def _default(self, obj):
        if isinstance(obj, datetime):
            return {"__datetime__": obj.isoformat()}
        elif isinstance(obj, date):
            return {"__date__": obj.isoformat()}
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
    
    def _object_hook(self, dct):
        if "__datetime__" in dct:
            return datetime.fromisoformat(dct["__datetime__"])
        if "__date__" in dct:
            return date.fromisoformat(dct["__date__"])
        return dct
    
    def dumps(self, value: Any) -> str:
        return json.dumps(value, default=self._default)
    
    def loads(self, value: Optional[str]) -> Any:
        if value is None:
            return None
        return json.loads(value, object_hook=self._object_hook)


class AsyncRedisCache:
    def __init__(self, redis_client: RedisConnection, ttl_default: int = 300):
        # Ensure the underlying Redis connection is established
        self._redis_conn = redis_client
        self._ttl_default = ttl_default
        # aiocache will use the same Redis URL with custom serializer
        self._cache = Cache(
            Cache.REDIS,
            endpoint=redis_client.config.get("host", "localhost"),
            port=redis_client.config.get("port", 6379),
            db=redis_client.config.get("db", 0),
            password=redis_client.config.get("password"),
            ttl=self._ttl_default,
            serializer=DateAwareJsonSerializer(),
        )

    async def get(self, key: str) -> Optional[Any]:
        try:
            return await self._cache.get(key)
        except Exception as e:
            logger.error(f"❌ Cache get error for {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        try:
            cache_ttl = ttl if ttl is not None else self._ttl_default
            await self._cache.set(key, value, ttl=cache_ttl)
            return True
        except Exception as e:
            logger.error(f"❌ Cache set error for {key}: {e}")
            return False

    async def delete(self, key: str) -> bool:
        try:
            await self._cache.delete(key)
            return True
        except Exception as e:
            logger.error(f"❌ Cache delete error for {key}: {e}")
            return False
