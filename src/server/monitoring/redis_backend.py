"""
Redis 监控后端

使用 Redis 作为统一监控存储，支持多容器/多服务共享。
"""

import json
import os
import time
import logging
import redis
from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, field, asdict

# 从 models.py 导入枚举，避免重复定义
from .models import RequestStatus, AlertSeverity


logger = logging.getLogger(__name__)


@dataclass
class RequestLog:
    """请求日志 - Redis 版本"""
    timestamp: str = ""
    data_type: str = ""
    instrument_id: str = ""
    source: str = ""
    status: str = RequestStatus.SUCCESS.value
    latency_ms: float = 0.0
    error_message: Optional[str] = None
    fields_count: int = 0
    has_data: bool = False
    raw_response: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class Alert:
    """告警"""
    timestamp: str = ""
    source: str = ""
    severity: str = AlertSeverity.WARNING.value
    message: str = ""
    resolved: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class RedisMonitoring:
    """
    Redis 监控后端

    数据结构：
    - logs:queue     - List, 请求日志队列（FIFO）
    - metrics:{source}:{type} - Hash, 实时指标
    - alerts         - ZSet, 告警列表（按时间排序）

    特性：
    - LPUSH 非阻塞写入 < 1ms
    - 自动过期清理
    - 多容器共享
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: Optional[str] = None,
        db: int = 0,
        max_logs: int = 100000,
        log_ttl: int = 86400 * 7,  # 7 天
        metrics_ttl: int = 86400,  # 1 天
    ):
        self.max_logs = max_logs
        self.log_ttl = log_ttl
        self.metrics_ttl = metrics_ttl

        # Redis 连接（连接池）
        self._pool = redis.ConnectionPool(
            host=host,
            port=port,
            password=password,
            db=db,
            decode_responses=True,
            max_connections=10,
        )
        self._client = redis.Redis(connection_pool=self._pool)

    def log_request(self, log: RequestLog) -> bool:
        """
        非阻塞记录请求日志

        使用 LPUSH + LTRIM 保证队列大小，< 1ms 返回
        """
        try:
            if not log.timestamp:
                log.timestamp = datetime.now().isoformat()

            pipe = self._client.pipeline()

            # 1. 写入日志队列
            pipe.lpush("logs:queue", log.to_json())
            pipe.ltrim("logs:queue", 0, self.max_logs - 1)

            # 2. 更新实时指标
            metric_key = f"metrics:{log.source}:{log.data_type}"
            pipe.hincrby(metric_key, "total_requests", 1)
            pipe.hincrby(metric_key, f"status:{log.status}", 1)
            pipe.hincrbyfloat(metric_key, "total_latency", log.latency_ms)

            if log.status == RequestStatus.SUCCESS.value and log.has_data:
                pipe.hincrby(metric_key, "data_available", 1)

            if log.error_message:
                pipe.hset(metric_key, "last_error", log.error_message[:200])

            pipe.hset(metric_key, "last_request", log.timestamp)
            pipe.expire(metric_key, self.metrics_ttl)

            pipe.execute()
            return True

        except redis.RedisError as e:
            # Redis 错误不阻塞业务，但记录日志便于调试
            logger.debug(f"Redis log_request failed: {e}")
            return False

    def create_alert(self, alert: Alert) -> bool:
        """创建告警"""
        try:
            if not alert.timestamp:
                alert.timestamp = datetime.now().isoformat()

            score = time.time()
            self._client.zadd("alerts", {alert.to_json(): score})
            self._client.expire("alerts", self.log_ttl)
            return True

        except redis.RedisError:
            return False

    def get_logs(
        self,
        source: Optional[str] = None,
        data_type: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        """获取日志列表"""
        try:
            logs = self._client.lrange("logs:queue", 0, limit - 1)
            result = []

            for log_json in logs:
                log = json.loads(log_json)

                # 过滤
                if source and log.get("source") != source:
                    continue
                if data_type and log.get("data_type") != data_type:
                    continue

                result.append(log)

            return result

        except redis.RedisError:
            return []

    def get_metrics(self, source: Optional[str] = None) -> dict:
        """获取指标汇总"""
        try:
            # 扫描所有 metrics key
            pattern = f"metrics:{source}:*" if source else "metrics:*"
            keys = self._client.keys(pattern)

            result = {}
            for key in keys:
                # 解析 key: metrics:{source}:{data_type}
                parts = key.split(":")
                if len(parts) >= 3:
                    src = parts[1]
                    dtype = parts[2]
                    data = self._client.hgetall(key)

                    if src not in result:
                        result[src] = {}

                    total = int(data.get("total_requests", 0))
                    success = int(data.get(f"status:{RequestStatus.SUCCESS.value}", 0))
                    total_latency = float(data.get("total_latency", 0))

                    result[src][dtype] = {
                        "total_requests": total,
                        "success_count": success,
                        "success_rate": success / total if total > 0 else 0,
                        "avg_latency_ms": total_latency / total if total > 0 else 0,
                        "data_available": int(data.get("data_available", 0)),
                        "last_error": data.get("last_error"),
                        "last_request": data.get("last_request"),
                    }

            return result

        except redis.RedisError:
            return {}

    def get_alerts(self, unresolved_only: bool = False, limit: int = 100) -> list[dict]:
        """获取告警列表"""
        try:
            # ZSet 按时间倒序
            alerts = self._client.zrevrange("alerts", 0, limit - 1, withscores=True)
            result = []

            for alert_json, score in alerts:
                alert = json.loads(alert_json)
                if unresolved_only and alert.get("resolved"):
                    continue
                alert["_score"] = score
                result.append(alert)

            return result

        except redis.RedisError:
            return []

    def resolve_alert(self, alert_json: str) -> bool:
        """解决告警（标记 resolved）"""
        try:
            # 从 ZSet 中删除旧的，添加标记过的
            score = self._client.zscore("alerts", alert_json)
            if score:
                self._client.zrem("alerts", alert_json)
                alert = json.loads(alert_json)
                alert["resolved"] = True
                self._client.zadd("alerts", {json.dumps(alert): score})
                return True
            return False

        except redis.RedisError:
            return False

    def get_stats(self) -> dict:
        """获取队列统计"""
        try:
            return {
                "logs_count": self._client.llen("logs:queue"),
                "alerts_count": self._client.zcard("alerts"),
                "metrics_keys": len(self._client.keys("metrics:*")),
                "connected": True,
            }
        except redis.RedisError:
            return {"connected": False}


# 全局实例
_redis_monitoring: Optional[RedisMonitoring] = None


def get_redis_monitoring(
    host: Optional[str] = None,
    port: Optional[int] = None,
    password: Optional[str] = None,
) -> RedisMonitoring:
    """获取全局 Redis 监控实例（支持环境变量配置）"""
    global _redis_monitoring
    if _redis_monitoring is None:
        # 从环境变量读取配置
        _redis_monitoring = RedisMonitoring(
            host=host or os.getenv("REDIS_HOST", "localhost"),
            port=port or int(os.getenv("REDIS_PORT", "6379")),
            password=password or os.getenv("REDIS_PASSWORD"),
        )
    return _redis_monitoring


def log_to_redis(log: RequestLog) -> bool:
    """便捷函数：记录日志到 Redis"""
    return get_redis_monitoring().log_request(log)


def alert_to_redis(alert: Alert) -> bool:
    """便捷函数：创建告警到 Redis"""
    return get_redis_monitoring().create_alert(alert)
