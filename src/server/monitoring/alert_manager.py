"""
告警管理器
"""

from datetime import datetime, timedelta
from typing import List, Optional
from .db import MonitoringDB
from .models import Alert, AlertSeverity


class AlertManager:
    """告警管理"""

    def __init__(self, db: MonitoringDB):
        self.db = db

    def check_and_alert(self, metrics: dict):
        """
        检查质量指标并生成告警

        Args:
            metrics: 从 MetricsCalculator.calculate_all_metrics() 返回的指标
        """
        for source, data_types in metrics.items():
            for data_type, m in data_types.items():
                # 规则1: 成功率低于90%
                if m.success_rate < 0.90 and m.total_requests >= 10:
                    severity = AlertSeverity.CRITICAL if m.success_rate < 0.80 else AlertSeverity.WARNING
                    self.create_alert(
                        source=source,
                        severity=severity.value,
                        message=f"{source} {data_type} 成功率过低: {m.success_rate:.1%} (最近{m.total_requests}次请求)",
                    )

                # 规则2: 平均延迟过高
                if m.avg_latency_ms > 5000:
                    severity = (
                        AlertSeverity.CRITICAL if m.avg_latency_ms > 10000 else AlertSeverity.WARNING
                    )
                    self.create_alert(
                        source=source,
                        severity=severity.value,
                        message=f"{source} {data_type} 延迟过高: {m.avg_latency_ms:.0f}ms",
                    )

                # 规则3: 完全无数据
                if m.total_requests >= 5 and m.data_availability_rate == 0:
                    self.create_alert(
                        source=source,
                        severity=AlertSeverity.CRITICAL.value,
                        message=f"{source} {data_type} 无可用数据 (最近{m.total_requests}次请求)",
                    )

    def create_alert(
        self,
        source: str,
        severity: str,
        message: str,
    ) -> int:
        """
        创建告警

        Args:
            source: 数据源
            severity: 告警级别
            message: 告警消息

        Returns:
            告警ID
        """
        # 检查是否已有相同告警（避免重复）
        recent_alerts = self.db.get_alerts(hours=1, unresolved_only=True, limit=100)
        for alert in recent_alerts:
            if alert.source == source and alert.message == message:
                # 已存在相同告警，不重复创建
                return alert.id

        alert = Alert(
            source=source,
            severity=severity,
            message=message,
        )

        return self.db.create_alert(alert)

    def resolve_alert(self, alert_id: int):
        """解决告警"""
        self.db.resolve_alert(alert_id)

    def get_recent_alerts(self, hours: int = 24, limit: int = 100) -> List[Alert]:
        """获取最近告警"""
        return self.db.get_alerts(hours=hours, limit=limit)

    def get_alert_summary(self, hours: int = 24) -> dict:
        """
        获取告警汇总

        Returns:
            {
                "total": 10,
                "critical": 2,
                "warning": 5,
                "info": 3,
                "unresolved": 7,
            }
        """
        alerts = self.get_recent_alerts(hours=hours)

        summary = {
            "total": len(alerts),
            "critical": 0,
            "warning": 0,
            "info": 0,
            "unresolved": 0,
        }

        for alert in alerts:
            if alert.severity in summary:
                summary[alert.severity] += 1
            if not alert.resolved:
                summary["unresolved"] += 1

        return summary
