"""
SQLite 数据库操作
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from contextlib import contextmanager

from .models import RequestLog, QualityMetrics, Alert


class MonitoringDB:
    """监控数据库"""

    def __init__(self, db_path: str = "monitoring.db"):
        """
        初始化数据库

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 请求日志表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    data_type TEXT NOT NULL,
                    instrument_id TEXT,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms REAL,
                    error_message TEXT,
                    fields_count INTEGER DEFAULT 0,
                    has_data INTEGER DEFAULT 0,
                    raw_response TEXT,
                    parsed_result TEXT,
                    metadata TEXT
                )
            """)

            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_request_logs_timestamp
                ON request_logs(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_request_logs_source
                ON request_logs(source, data_type)
            """)

            # 质量指标表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quality_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    source TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    success_rate REAL,
                    avg_latency_ms REAL,
                    total_requests INTEGER,
                    success_count INTEGER,
                    failed_count INTEGER,
                    avg_fields_count REAL,
                    data_availability_rate REAL,
                    UNIQUE(date, source, data_type)
                )
            """)

            # 告警表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    source TEXT,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    resolved INTEGER DEFAULT 0,
                    resolved_at DATETIME
                )
            """)

            conn.commit()

    @contextmanager
    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ========== 请求日志 ==========

    def log_request(self, log: RequestLog) -> int:
        """
        记录请求日志

        Args:
            log: 请求日志对象

        Returns:
            插入的记录ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO request_logs (
                    timestamp, data_type, instrument_id, source,
                    status, latency_ms, error_message,
                    fields_count, has_data, raw_response, parsed_result, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log.timestamp.isoformat() if log.timestamp else datetime.now().isoformat(),
                log.data_type,
                log.instrument_id,
                log.source,
                log.status,
                log.latency_ms,
                log.error_message,
                log.fields_count,
                1 if log.has_data else 0,
                log.raw_response,
                log.parsed_result,
                json.dumps(log.metadata) if log.metadata else None,
            ))
            conn.commit()
            return cursor.lastrowid

    def get_logs(
        self,
        source: Optional[str] = None,
        data_type: Optional[str] = None,
        hours: int = 24,
        limit: int = 1000,
    ) -> List[RequestLog]:
        """
        查询请求日志

        Args:
            source: 数据源（可选）
            data_type: 数据类型（可选）
            hours: 查询最近N小时
            limit: 最大返回数量

        Returns:
            请求日志列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT * FROM request_logs
                WHERE timestamp >= datetime('now', '-{} hours')
            """.format(hours)

            params = []
            if source:
                query += " AND source = ?"
                params.append(source)
            if data_type:
                query += " AND data_type = ?"
                params.append(data_type)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_log(row) for row in rows]

    def _row_to_log(self, row: sqlite3.Row) -> RequestLog:
        """将数据库行转换为 RequestLog 对象"""
        return RequestLog(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            data_type=row["data_type"],
            instrument_id=row["instrument_id"],
            source=row["source"],
            status=row["status"],
            latency_ms=row["latency_ms"] or 0.0,
            error_message=row["error_message"],
            fields_count=row["fields_count"] or 0,
            has_data=bool(row["has_data"]),
            raw_response=row["raw_response"],
            parsed_result=row["parsed_result"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def create_alert(self, alert: Alert) -> int:
        """创建告警"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alerts (timestamp, source, severity, message, resolved, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                alert.timestamp.isoformat() if alert.timestamp else datetime.now().isoformat(),
                alert.source,
                alert.severity,
                alert.message,
                1 if alert.resolved else 0,
                alert.resolved_at.isoformat() if alert.resolved_at else None,
            ))
            conn.commit()
            return cursor.lastrowid

    def get_alerts(
        self,
        hours: int = 24,
        unresolved_only: bool = False,
        limit: int = 100,
    ) -> List[Alert]:
        """查询告警"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT * FROM alerts
                WHERE timestamp >= datetime('now', '-{} hours')
            """.format(hours)

            if unresolved_only:
                query += " AND resolved = 0"

            query += " ORDER BY timestamp DESC LIMIT ?"

            cursor.execute(query, (limit,))
            rows = cursor.fetchall()

            return [
                Alert(
                    id=row["id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    source=row["source"],
                    severity=row["severity"],
                    message=row["message"],
                    resolved=bool(row["resolved"]),
                    resolved_at=datetime.fromisoformat(row["resolved_at"])
                    if row["resolved_at"]
                    else None,
                )
                for row in rows
            ]

    def resolve_alert(self, alert_id: int):
        """解决告警"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE alerts
                SET resolved = 1, resolved_at = ?
                WHERE id = ?
            """,
                (datetime.now().isoformat(), alert_id),
            )
            conn.commit()

    # ========== 质量指标 ==========

    def save_metrics(self, metrics: QualityMetrics):
        """保存质量指标"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO quality_metrics (
                    date, source, data_type,
                    success_rate, avg_latency_ms, total_requests,
                    success_count, failed_count,
                    avg_fields_count, data_availability_rate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics.date,
                metrics.source,
                metrics.data_type,
                metrics.success_rate,
                metrics.avg_latency_ms,
                metrics.total_requests,
                metrics.success_count,
                metrics.failed_count,
                metrics.avg_fields_count,
                metrics.data_availability_rate,
            ))
            conn.commit()

    def get_metrics(
        self,
        source: Optional[str] = None,
        days: int = 7,
    ) -> List[QualityMetrics]:
        """
        查询质量指标

        Args:
            source: 数据源（可选）
            days: 查询最近N天

        Returns:
            质量指标列表
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT * FROM quality_metrics
                WHERE date >= date('now', '-{} days')
            """.format(days)

            params = []
            if source:
                query += " AND source = ?"
                params.append(source)

            query += " ORDER BY date DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [
                QualityMetrics(
                    id=row["id"],
                    date=row["date"],
                    source=row["source"],
                    data_type=row["data_type"],
                    success_rate=row["success_rate"] or 0.0,
                    avg_latency_ms=row["avg_latency_ms"] or 0.0,
                    total_requests=row["total_requests"] or 0,
                    success_count=row["success_count"] or 0,
                    failed_count=row["failed_count"] or 0,
                    avg_fields_count=row["avg_fields_count"] or 0.0,
                    data_availability_rate=row["data_availability_rate"] or 0.0,
                )
                for row in rows
            ]

    # ========== 告警 ==========

    def create_alert(self, alert: Alert) -> int:
        """创建告警"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alerts (timestamp, source, severity, message, resolved, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                alert.timestamp.isoformat() if alert.timestamp else datetime.now().isoformat(),
                alert.source,
                alert.severity,
                alert.message,
                1 if alert.resolved else 0,
                alert.resolved_at.isoformat() if alert.resolved_at else None,
            ))
            conn.commit()
            return cursor.lastrowid

    def get_alerts(
        self,
        hours: int = 24,
        unresolved_only: bool = False,
        limit: int = 100,
    ) -> List[Alert]:
        """查询告警"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = """
                SELECT * FROM alerts
                WHERE timestamp >= datetime('now', '-{} hours')
            """.format(hours)

            if unresolved_only:
                query += " AND resolved = 0"

            query += " ORDER BY timestamp DESC LIMIT ?"

            cursor.execute(query, (limit,))
            rows = cursor.fetchall()

            return [
                Alert(
                    id=row["id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    source=row["source"],
                    severity=row["severity"],
                    message=row["message"],
                    resolved=bool(row["resolved"]),
                    resolved_at=datetime.fromisoformat(row["resolved_at"])
                    if row["resolved_at"]
                    else None,
                )
                for row in rows
            ]

    def resolve_alert(self, alert_id: int):
        """解决告警"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE alerts
                SET resolved = 1, resolved_at = ?
                WHERE id = ?
            """,
                (datetime.now().isoformat(), alert_id),
            )
            conn.commit()
