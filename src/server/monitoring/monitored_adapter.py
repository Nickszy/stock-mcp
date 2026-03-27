"""
Adapter 监控包装器

包装现有 Adapter，自动记录请求日志
"""

import time
import json
from typing import Any, Optional
from datetime import datetime

from .db import MonitoringDB
from .models import RequestLog, RequestStatus


class MonitoredAdapter:
    """
    监控 Adapter 包装器

    自动记录每次请求的结果、延迟等信息
    """

    def __init__(self, adapter: Any, db: MonitoringDB, adapter_name: Optional[str] = None):
        """
        初始化监控包装器

        Args:
            adapter: 原始 Adapter 实例
            db: 监控数据库实例
            adapter_name: Adapter 名称（可选，默认从 adapter 获取）
        """
        self.adapter = adapter
        self.db = db
        self.adapter_name = adapter_name or getattr(adapter, "name", adapter.__class__.__name__)

    async def fetch_with_monitoring(
        self,
        data_type: str,
        instrument_id: str,
        fetch_func: callable,
        *args,
        **kwargs,
    ) -> tuple[Any, RequestLog]:
        """
        带监控的 fetch 操作

        Args:
            data_type: 数据类型（price, financials, news等）
            instrument_id: 标的ID（如 SSE:600519）
            fetch_func: 实际执行的 fetch 函数
            *args, **kwargs: 传递给 fetch_func 的参数

        Returns:
            (原始结果, 请求日志)
        """
        start_time = time.time()
        status = RequestStatus.SUCCESS
        error_message = None
        raw_response = None
        parsed_result = None
        fields_count = 0
        has_data = False

        try:
            # 执行实际请求
            result = await fetch_func(*args, **kwargs)

            # 尝试提取数据信息
            if result:
                has_data = True
                if isinstance(result, dict):
                    fields_count = len(result)
                    raw_response = json.dumps(result, ensure_ascii=False, default=str)[:5000]  # 限制长度
                    parsed_result = raw_response
                elif hasattr(result, "__dict__"):
                    fields_count = len(vars(result))
                    parsed_result = json.dumps(
                        vars(result), ensure_ascii=False, default=str
                    )[:5000]
                else:
                    raw_response = str(result)[:5000]

            return result, None  # 先返回结果，日志稍后记录

        except TimeoutError:
            status = RequestStatus.TIMEOUT
            error_message = "请求超时"
            raise

        except Exception as e:
            status = RequestStatus.FAILED
            error_message = f"{type(e).__name__}: {str(e)}"
            raise

        finally:
            # 记录请求日志
            latency_ms = (time.time() - start_time) * 1000

            log = RequestLog(
                timestamp=datetime.now(),
                data_type=data_type,
                instrument_id=instrument_id,
                source=self.adapter_name,
                status=status.value,
                latency_ms=latency_ms,
                error_message=error_message,
                fields_count=fields_count,
                has_data=has_data,
                raw_response=raw_response,
                parsed_result=parsed_result,
            )

            self.db.log_request(log)

    def __getattr__(self, name):
        """代理所有其他属性到原始 adapter"""
        return getattr(self.adapter, name)


def wrap_adapter(adapter: Any, db: MonitoringDB, name: Optional[str] = None) -> MonitoredAdapter:
    """
    便捷函数：包装 Adapter

    Args:
        adapter: 原始 Adapter
        db: 监控数据库
        name: Adapter 名称

    Returns:
        MonitoredAdapter 实例
    """
    return MonitoredAdapter(adapter, db, name)
