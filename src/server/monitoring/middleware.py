"""
监控中间件

提供统一的监控装饰器和工具函数，用于 MCP 工具和 REST API。

核心设计：
1. 非侵入式：不修改现有业务代码
2. 异步记录：Redis LPUSH，延迟 < 1ms
3. 统一接口：source, data_type, instrument_id
"""

import time
import json
import functools
from datetime import datetime
from typing import Any, Callable, Optional

from .models import RequestStatus, AlertSeverity
from .redis_backend import log_to_redis, alert_to_redis


def monitored(
    data_type: str,
    source: str = "unknown",
    instrument_id_param: str = "symbol",
    extract_fields: Optional[Callable[[Any], int]] = None,
    extract_has_data: Optional[Callable[[Any], bool]] = None,
):
    """
    监控装饰器 - 用于 MCP 工具和 REST API

    自动记录：
    - 请求时间、延迟
    - 成功/失败状态
    - 返回字段数、是否有数据

    Args:
        data_type: 数据类型（price, financials, news 等）
        source: 数据源名称
        instrument_id_param: 标的ID参数名
        extract_fields: 自定义提取字段数的函数
        extract_has_data: 自定义判断是否有数据的函数

    Usage:
        @monitored("price", source="tushare")
        async def get_price(symbol: str, ...):
            ...

        @monitored("financials", source="yahoo")
        async def get_financials(symbol: str, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()

            # 提取 instrument_id
            instrument_id = kwargs.get(instrument_id_param, "")
            if not instrument_id and args:
                # 尝试从位置参数获取
                import inspect
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if instrument_id_param in params:
                    idx = params.index(instrument_id_param)
                    if idx < len(args):
                        instrument_id = args[idx]

            status = RequestStatus.SUCCESS
            error_message = None
            result = None
            fields_count = 0
            has_data = False

            try:
                result = await func(*args, **kwargs)

                # 提取字段数
                if extract_fields:
                    fields_count = extract_fields(result)
                elif isinstance(result, dict):
                    fields_count = len(result)
                elif isinstance(result, list):
                    fields_count = len(result)

                # 判断是否有数据
                if extract_has_data:
                    has_data = extract_has_data(result)
                elif result is not None:
                    if isinstance(result, dict):
                        has_data = any(v is not None and v != "" for v in result.values())
                    elif isinstance(result, list):
                        has_data = len(result) > 0
                    else:
                        has_data = True

                return result

            except TimeoutError:
                status = RequestStatus.TIMEOUT
                error_message = "请求超时"
                raise

            except Exception as e:
                status = RequestStatus.FAILED
                error_message = f"{type(e).__name__}: {str(e)}"
                raise

            finally:
                latency_ms = (time.time() - start_time) * 1000

                # 异步记录日志（不阻塞，Redis LPUSH）
                log_to_redis(
                    data_type=data_type,
                    source=source,
                    instrument_id=str(instrument_id),
                    status=status.value,
                    latency_ms=latency_ms,
                    error_message=error_message,
                    fields_count=fields_count,
                    has_data=has_data,
                    metadata={"function": func.__name__},
                )

                # 检查是否需要告警
                _check_and_alert(source, data_type, status, latency_ms)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            import asyncio
            return asyncio.run(async_wrapper(*args, **kwargs))

        # 根据原函数类型返回对应包装器
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def _check_and_alert(source: str, data_type: str, status: RequestStatus, latency_ms: float):
    """检查并触发告警（写入 Redis）"""
    # 延迟告警
    if latency_ms > 10000:  # > 10s
        alert_to_redis(
            source=source,
            severity=AlertSeverity.CRITICAL.value,
            message=f"数据源 {source} 延迟过高: {latency_ms:.0f}ms",
        )
    elif latency_ms > 5000:  # > 5s
        alert_to_redis(
            source=source,
            severity=AlertSeverity.WARNING.value,
            message=f"数据源 {source} 延迟较高: {latency_ms:.0f}ms",
        )

    # 失败告警
    if status == RequestStatus.TIMEOUT:
        alert_to_redis(
            source=source,
            severity=AlertSeverity.WARNING.value,
            message=f"数据源 {source} 请求超时 ({data_type})",
        )
    elif status == RequestStatus.FAILED:
        alert_to_redis(
            source=source,
            severity=AlertSeverity.WARNING.value,
            message=f"数据源 {source} 请求失败 ({data_type})",
        )


def _truncate_response(result: Any, max_length: int = 2000) -> Optional[str]:
    """截断响应用于存储"""
    if result is None:
        return None
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
        return text[:max_length] if len(text) > max_length else text
    except Exception:
        return str(result)[:max_length]


class MonitoringContext:
    """
    监控上下文管理器

    用于需要更精细控制的场景，比如手动指定字段数。
    """

    def __init__(
        self,
        data_type: str,
        source: str,
        instrument_id: str = "",
    ):
        self.data_type = data_type
        self.source = source
        self.instrument_id = instrument_id
        self.start_time = None
        self.status = RequestStatus.SUCCESS
        self.error_message = None
        self.fields_count = 0
        self.has_data = False
        self._result = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency_ms = (time.time() - self.start_time) * 1000

        if exc_type is not None:
            if issubclass(exc_type, TimeoutError):
                self.status = RequestStatus.TIMEOUT
                self.error_message = "请求超时"
            else:
                self.status = RequestStatus.FAILED
                self.error_message = f"{exc_type.__name__}: {str(exc_val)}"

        # 异步记录日志（不阻塞，Redis LPUSH）
        log_to_redis(
            data_type=self.data_type,
            source=self.source,
            instrument_id=self.instrument_id,
            status=self.status.value,
            latency_ms=latency_ms,
            error_message=self.error_message,
            fields_count=self.fields_count,
            has_data=self.has_data,
        )

        return False

    def set_result(self, result: Any, fields_count: Optional[int] = None):
        """设置结果"""
        self._result = result
        if fields_count is not None:
            self.fields_count = fields_count
        elif isinstance(result, dict):
            self.fields_count = len(result)
        elif isinstance(result, list):
            self.fields_count = len(result)

        if result is not None:
            if isinstance(result, dict):
                self.has_data = any(v is not None and v != "" for v in result.values())
            elif isinstance(result, list):
                self.has_data = len(result) > 0
            else:
                self.has_data = True

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)


# 便捷函数
def quick_log(
    data_type: str,
    source: str,
    instrument_id: str,
    status: str,
    latency_ms: float,
    error_message: Optional[str] = None,
    fields_count: int = 0,
    has_data: bool = False,
    raw_response: Any = None,
):
    """
    快速记录日志（不使用装饰器的场景）

    用法:
        quick_log(
            data_type="price",
            source="tushare",
            instrument_id="SSE:600519",
            status="success",
            latency_ms=150.5,
            fields_count=12,
            has_data=True,
        )
    """
    return log_to_redis(
        data_type=data_type,
        source=source,
        instrument_id=instrument_id,
        status=status,
        latency_ms=latency_ms,
        error_message=error_message,
        fields_count=fields_count,
        has_data=has_data,
    )
