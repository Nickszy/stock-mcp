"""
质量指标计算器
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any
from collections import defaultdict
import statistics

from .db import MonitoringDB
from .models import QualityMetrics, RequestLog


class MetricsCalculator:
    """计算数据源质量指标"""

    def __init__(self, db: MonitoringDB):
        self.db = db

    def calculate_source_metrics(
        self,
        source: str,
        data_type: str,
        hours: int = 24,
    ) -> QualityMetrics:
        """
        计算某个数据源的质量指标

        Args:
            source: 数据源名称
            data_type: 数据类型
            hours: 统计最近N小时

        Returns:
            QualityMetrics 对象
        """
        # 获取原始日志
        logs = self.db.get_logs(source=source, data_type=data_type, hours=hours, limit=10000)

        if not logs:
            return QualityMetrics(
                date=datetime.now().strftime("%Y-%m-%d"),
                source=source,
                data_type=data_type,
            )

        # 统计指标
        total_requests = len(logs)
        success_count = sum(1 for log in logs if log.status == "success")
        failed_count = total_requests - success_count

        success_rate = success_count / total_requests if total_requests > 0 else 0.0

        # 平均延迟（只计算成功的请求）
        latency_values = [log.latency_ms for log in logs if log.latency_ms > 0]
        avg_latency_ms = statistics.mean(latency_values) if latency_values else 0.0

        # 平均字段数
        fields_values = [log.fields_count for log in logs if log.fields_count > 0]
        avg_fields_count = statistics.mean(fields_values) if fields_values else 0.0

        # 数据可用率
        data_available_count = sum(1 for log in logs if log.has_data)
        data_availability_rate = data_available_count / total_requests if total_requests > 0 else 0.0

        return QualityMetrics(
            date=datetime.now().strftime("%Y-%m-%d"),
            source=source,
            data_type=data_type,
            success_rate=success_rate,
            avg_latency_ms=avg_latency_ms,
            total_requests=total_requests,
            success_count=success_count,
            failed_count=failed_count,
            avg_fields_count=avg_fields_count,
            data_availability_rate=data_availability_rate,
        )

    def calculate_all_metrics(self, hours: int = 24) -> Dict[str, Dict[str, QualityMetrics]]:
        """
        计算所有数据源的质量指标

        Args:
            hours: 统计最近N小时

        Returns:
            {
                "tushare": {
                    "price": QualityMetrics,
                    "financials": QualityMetrics,
                },
                "akshare": {...},
            }
        """
        # 定义数据源和数据类型组合
        source_data_types = {
            "tushare": ["price", "financials", "news"],
            "akshare": ["price", "financials", "news"],
            "baostock": ["price"],
            "yahoo": ["price", "financials"],
            "finnhub": ["price", "news"],
            "fred": ["macro"],
        }

        result = defaultdict(dict)

        for source, data_types in source_data_types.items():
            for data_type in data_types:
                metrics = self.calculate_source_metrics(source, data_type, hours)
                result[source][data_type] = metrics

        return dict(result)

    def get_source_summary(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        获取数据源汇总（按数据源聚合）

        Args:
            hours: 统计最近N小时

        Returns:
            [
                {
                    "source": "tushare",
                    "success_rate": 0.985,
                    "avg_latency_ms": 1200,
                    "total_requests": 1234,
                },
                ...
            ]
        """
        all_metrics = self.calculate_all_metrics(hours)

        summaries = []
        for source, data_types in all_metrics.items():
            # 聚合所有数据类型
            total_requests = sum(m.total_requests for m in data_types.values())
            if total_requests == 0:
                continue

            # 加权平均成功率
            success_rates = [
                m.success_rate * m.total_requests for m in data_types.values() if m.total_requests > 0
            ]
            total_weight = sum(m.total_requests for m in data_types.values() if m.total_requests > 0)
            avg_success_rate = sum(success_rates) / total_weight if total_weight > 0 else 0.0

            # 加权平均延迟
            latencies = [
                m.avg_latency_ms * m.total_requests for m in data_types.values() if m.total_requests > 0
            ]
            avg_latency = sum(latencies) / total_weight if total_weight > 0 else 0.0

            summaries.append(
                {
                    "source": source,
                    "success_rate": avg_success_rate,
                    "avg_latency_ms": avg_latency,
                    "total_requests": total_requests,
                }
            )

        # 按成功率排序
        summaries.sort(key=lambda x: x["success_rate"], reverse=True)

        return summaries

    def get_data_type_summary(self, hours: int = 24) -> Dict[str, Dict[str, Any]]:
        """
        获取数据类型汇总（按数据类型聚合）

        Args:
            hours: 统计最近N小时

        Returns:
            {
                "price": {
                    "best_source": "tushare",
                    "avg_success_rate": 0.95,
                    "avg_latency_ms": 1100,
                },
                ...
            }
        """
        all_metrics = self.calculate_all_metrics(hours)

        # 按数据类型分组
        data_type_metrics = defaultdict(list)
        for source_metrics in all_metrics.values():
            for data_type, metrics in source_metrics.items():
                data_type_metrics[data_type].append((metrics.source, metrics))

        # 计算每个数据类型的汇总
        result = {}
        for data_type, source_metrics_list in data_type_metrics.items():
            if not source_metrics_list:
                continue

            # 找到最佳数据源（成功率最高）
            best_source, best_metrics = max(
                source_metrics_list, key=lambda x: x[1].success_rate
            )

            # 计算平均指标
            total_requests = sum(m.total_requests for _, m in source_metrics_list)
            if total_requests == 0:
                continue

            avg_success_rate = sum(m.success_rate for _, m in source_metrics_list) / len(
                source_metrics_list
            )
            avg_latency = sum(m.avg_latency_ms for _, m in source_metrics_list) / len(
                source_metrics_list
            )

            result[data_type] = {
                "best_source": best_source,
                "best_success_rate": best_metrics.success_rate,
                "avg_success_rate": avg_success_rate,
                "avg_latency_ms": avg_latency,
                "total_requests": total_requests,
                "sources": [source for source, _ in source_metrics_list],
            }

        return result

    def get_source_trend(
        self,
        source: str,
        data_type: str,
        hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """
        获取数据源质量趋势（按小时聚合）

        Args:
            source: 数据源
            data_type: 数据类型
            hours: 统计最近N小时

        Returns:
            [
                {
                    "hour": "2024-01-01 10:00",
                    "success_rate": 0.95,
                    "avg_latency_ms": 1200,
                    "total_requests": 50,
                },
                ...
            ]
        """
        logs = self.db.get_logs(source=source, data_type=data_type, hours=hours, limit=10000)

        if not logs:
            return []

        # 按小时分组
        hourly_data = defaultdict(list)
        for log in logs:
            hour_key = log.timestamp.replace(minute=0, second=0, microsecond=0)
            hourly_data[hour_key].append(log)

        # 计算每小时指标
        trend = []
        for hour, hour_logs in sorted(hourly_data.items()):
            total = len(hour_logs)
            success = sum(1 for log in hour_logs if log.status == "success")
            avg_latency = sum(log.latency_ms for log in hour_logs) / total if total > 0 else 0

            trend.append(
                {
                    "hour": hour.strftime("%Y-%m-%d %H:%M"),
                    "success_rate": success / total if total > 0 else 0,
                    "avg_latency_ms": avg_latency,
                    "total_requests": total,
                }
            )

        return trend
