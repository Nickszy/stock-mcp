"""
测试监控系统 - 简化版

运行方式:
    cd .worktrees/data-quality-dashboard
    uv run python test_monitoring.py
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from datetime import datetime
import random

print("=" * 60)
print("Stock MCP 监控系统测试")
print("=" * 60)

# 测试 1: 数据库
print("\n=== 测试 1: 数据库 ===")
from src.server.monitoring.db import MonitoringDB
from src.server.monitoring.models import RequestLog

db = MonitoringDB("test_monitoring.db")
print("✅ 数据库初始化成功")

# 插入测试日志
log = RequestLog(
    data_type="price",
    instrument_id="SSE:600519",
    source="tushare",
    status="success",
    latency_ms=1200.5,
    fields_count=15,
    has_data=True,
)
db.log_request(log)
print("✅ 插入日志成功")

# 查询日志
logs = db.get_logs(source="tushare", hours=1, limit=10)
print(f"✅ 查询到 {len(logs)} 条日志")

# 测试 2: 指标计算
print("\n=== 测试 2: 指标计算 ===")
from src.server.monitoring.metrics_calculator import MetricsCalculator

# 插入更多数据
for i in range(20):
    log = RequestLog(
        data_type=random.choice(["price", "financials"]),
        instrument_id=random.choice(["SSE:600519", "NASDAQ:AAPL"]),
        source=random.choice(["tushare", "akshare", "yahoo"]),
        status="success" if random.random() > 0.1 else "failed",
        latency_ms=random.uniform(500, 3000),
        fields_count=random.randint(5, 20),
        has_data=random.random() > 0.1,
    )
    db.log_request(log)

print("✅ 插入 20 条测试日志")

calculator = MetricsCalculator(db)
metrics = calculator.calculate_source_metrics("tushare", "price", hours=24)
print(f"✅ 计算指标成功:")
print(f"   - 成功率: {metrics.success_rate:.1%}")
print(f"   - 平均延迟: {metrics.avg_latency_ms:.0f}ms")
print(f"   - 总请求: {metrics.total_requests}")

# 测试 3: 告警管理
print("\n=== 测试 3: 告警管理 ===")
from src.server.monitoring.alert_manager import AlertManager
from src.server.monitoring.models import Alert

alert_manager = AlertManager(db)

alert = Alert(
    source="tushare",
    severity="warning",
    message="成功率低于 90%",
)
alert_manager.db.create_alert(alert)
print("✅ 创建告警成功")

alerts = alert_manager.get_recent_alerts(hours=1)
print(f"✅ 查询到 {len(alerts)} 条告警")

# 测试 4: Dashboard API（模拟）
print("\n=== 测试 4: Dashboard API ===")

source_summary = calculator.get_source_summary(hours=24)
print(f"✅ 数据源汇总: {len(source_summary)} 个数据源")
for summary in source_summary[:3]:
    print(f"   - {summary['source']}: 成功率 {summary['success_rate']:.1%}")

print("\n" + "=" * 60)
print("✅ 所有测试通过！")
print("=" * 60)

print("\n📊 现在可以启动 Dashboard:")
print("   cd .worktrees/data-quality-dashboard")
print("   streamlit run dashboard/app.py")

# 清理测试数据库
import os
os.remove("test_monitoring.db")
print("\n🧹 已清理测试数据库")
