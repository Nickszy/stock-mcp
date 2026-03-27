"""
监控数据模型
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class DataSourceType(str, Enum):
    """数据源类型"""
    TUSHARE = "tushare"
    AKSHARE = "akshare"
    BAOSTOCK = "baostock"
    YAHOO = "yahoo"
    FINNHUB = "finnhub"
    FRED = "fred"
    CCXT = "ccxt"


class DataType(str, Enum):
    """数据类型"""
    PRICE = "price"  # 行情
    FINANCIALS = "financials"  # 财报
    NEWS = "news"  # 新闻
    EVENT = "event"  # 事件
    MACRO = "macro"  # 宏观


class RequestStatus(str, Enum):
    """请求状态"""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class AlertSeverity(str, Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class RequestLog:
    """请求日志"""
    id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    # 请求标识
    data_type: str = ""
    instrument_id: str = ""
    source: str = ""

    # 请求结果
    status: str = RequestStatus.SUCCESS.value
    latency_ms: float = 0.0
    error_message: Optional[str] = None

    # 数据质量
    fields_count: int = 0
    has_data: bool = False

    # 原始数据（用于调试）
    raw_response: Optional[str] = None
    parsed_result: Optional[str] = None

    # 额外元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "data_type": self.data_type,
            "instrument_id": self.instrument_id,
            "source": self.source,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error_message": self.error_message,
            "fields_count": self.fields_count,
            "has_data": self.has_data,
            "raw_response": self.raw_response,
            "parsed_result": self.parsed_result,
            "metadata": self.metadata,
        }


@dataclass
class QualityMetrics:
    """质量指标"""
    id: Optional[int] = None
    date: str = ""  # YYYY-MM-DD
    source: str = ""
    data_type: str = ""

    # 核心指标
    success_rate: float = 0.0  # 成功率 0-1
    avg_latency_ms: float = 0.0  # 平均延迟（毫秒）
    total_requests: int = 0  # 总请求数
    success_count: int = 0  # 成功次数
    failed_count: int = 0  # 失败次数

    # 数据质量
    avg_fields_count: float = 0.0  # 平均字段数
    data_availability_rate: float = 0.0  # 数据可用率

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "date": self.date,
            "source": self.source,
            "data_type": self.data_type,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "avg_fields_count": self.avg_fields_count,
            "data_availability_rate": self.data_availability_rate,
        }


@dataclass
class Alert:
    """告警"""
    id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""
    severity: str = AlertSeverity.WARNING.value
    message: str = ""
    resolved: bool = False
    resolved_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "source": self.source,
            "severity": self.severity,
            "message": self.message,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }
