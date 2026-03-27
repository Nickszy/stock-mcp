"""
数据质量监控系统

提供数据源质量监控、测试台、告警管理等功能

核心设计：
1. 异步队列：Redis LPUSH，延迟 < 1ms
2. 统一存储：多服务共享（stock-mcp + news-mcp + dashboard）
3. 自动过期：7 天 TTL，无需手动清理
"""

from .models import (
    DataSourceType,
    DataType,
    RequestStatus,
    AlertSeverity,
    RequestLog,
    QualityMetrics,
    Alert,
)
from .db import MonitoringDB
from .monitored_adapter import MonitoredAdapter
from .metrics_calculator import MetricsCalculator
from .alert_manager import AlertManager
from .redis_backend import (
    RedisMonitoring,
    get_redis_monitoring,
    log_to_redis,
    alert_to_redis,
)
from .middleware import (
    monitored,
    MonitoringContext,
    quick_log,
)

__all__ = [
    # 模型
    "DataSourceType",
    "DataType",
    "RequestStatus",
    "AlertSeverity",
    "RequestLog",
    "QualityMetrics",
    "Alert",
    # 数据库（兼容旧代码）
    "MonitoringDB",
    "MonitoredAdapter",
    "MetricsCalculator",
    "AlertManager",
    # Redis 监控（新）
    "RedisMonitoring",
    "get_redis_monitoring",
    "log_to_redis",
    "alert_to_redis",
    # 中间件
    "monitored",
    "MonitoringContext",
    "quick_log",
]
