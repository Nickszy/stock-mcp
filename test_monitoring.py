"""
Test monitoring system

Run:
    cd .worktrees/data-quality-dashboard
    uv run python test_monitoring.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from datetime import datetime
import random

print("=" * 60)
print("Stock MCP Monitoring System Test")
print("=" * 60)

# Test 1: Database
print("\n=== Test 1: Database ===")
from src.server.monitoring.db import MonitoringDB
from src.server.monitoring.models import RequestLog

db = MonitoringDB("test_monitoring.db")
print("OK Database initialized")

# Insert test log
log = RequestLog(
    data_type="price",
    instrument_id="SSE:600519",
    source="tushare",
    status="success",
    latency_ms=1200.5,
    fields_count=15,
    has_data=True,
)
log_id = db.log_request(log)
print(f"OK Inserted log ID: {log_id}")

# Query logs
logs = db.get_logs(source="tushare", hours=1, limit=10)
print(f"OK Found {len(logs)} logs")
for log in logs[:3]:
    print(f"   - {log.source}: {log.status} ({log.latency_ms:.0f}ms)")

# Test 2: Metrics Calculator
print("\n=== Test 2: Metrics Calculator ===")
from src.server.monitoring.metrics_calculator import MetricsCalculator

# Insert more test data
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

print("OK Inserted 20 test logs")

calculator = MetricsCalculator(db)
metrics = calculator.calculate_source_metrics("tushare", "price", hours=24)
print(f"OK Metrics calculated:")
print(f"   - Success rate: {metrics.success_rate:.1%}")
print(f"   - Avg latency: {metrics.avg_latency_ms:.0f}ms")
print(f"   - Total requests: {metrics.total_requests}")

# Test 3: Alert Manager
print("\n=== Test 3: Alert Manager ===")
from src.server.monitoring.alert_manager import AlertManager
from src.server.monitoring.models import Alert

alert_manager = AlertManager(db)
alert = Alert(
    source="tushare",
    severity="warning",
    message="Success rate below 90%",
)
alert_id = alert_manager.db.create_alert(alert)
print(f"OK Created alert ID: {alert_id}")

alerts = alert_manager.get_recent_alerts(hours=1)
print(f"OK Found {len(alerts)} alerts")

summary = alert_manager.get_alert_summary(hours=24)
print(f"OK Alert summary:")
print(f"   - Total: {summary['total']}")
print(f"   - Unresolved: {summary['unresolved']}")

# Test 4: Dashboard API
print("\n=== Test 4: Dashboard API ===")

source_summary = calculator.get_source_summary(hours=24)
print(f"OK Source summary: {len(source_summary)} sources")
for summary in source_summary[:3]:
    print(f"   - {summary['source']}: {summary['success_rate']:.1%}")

print("\n" + "=" * 60)
print("OK All tests passed!")
print("=" * 60)

print("\nDashboard ready to start:")
print("   cd .worktrees/data-quality-dashboard")
print("   streamlit run dashboard/app.py")

# Cleanup test database
import os
os.remove("test_monitoring.db")
print("\nCleaned up test database")
