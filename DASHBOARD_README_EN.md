# Stock MCP Data Quality Monitoring Dashboard

Real-time monitoring of data source quality with interactive testing capabilities.

## Features

- Data source monitoring
- Interactive test bench
- Alert system
- Historical records

## Quick Start

### 1. Install Dependencies

```bash
cd dashboard
pip install -r requirements.txt
```

### 2. Run Tests

```bash
uv run python test_monitoring_simple.py
```

### 3. Start Dashboard

```bash
cd dashboard
streamlit run app.py
```

Dashboard will open at http://localhost:8501

## Architecture

```
src/server/monitoring/
  - models.py              # Data models
  - db.py                  # SQLite operations
  - monitored_adapter.py   # Adapter wrapper
  - metrics_calculator.py  # Metrics calculation
  - alert_manager.py       # Alert management

dashboard/
  - app.py                 # Streamlit main app
  - pages/
    - overview.py         # Overview page
    - test_bench.py       # Test bench
    - history.py          # History records
    - alerts.py           # Alert management
```

## Usage

### Overview Page
- View health status of all data sources
- Key metrics cards
- Data type comparison

### Test Bench
1. Select data type
2. Enter instrument code
3. Choose data sources
4. Click "Start Test"
5. Compare results

### History Records
- Filter by source/data type
- View request trends
- Export to CSV

### Alerts
- View alert summary
- Mark alerts as resolved
- View alert rules

## Integration

### Wrap Existing Adapter

```python
from src.server.monitoring import MonitoringDB, MonitoredAdapter

# Initialize monitoring database
db = MonitoringDB("monitoring.db")

# Wrap existing adapter
original_adapter = TushareAdapter()
monitored_adapter = MonitoredAdapter(original_adapter, db, "tushare")

# Use wrapped adapter (auto-logs requests)
result = await monitored_adapter.fetch_price("SSE:600519")
```

## Database Tables

### request_logs
- timestamp, data_type, instrument_id, source
- status, latency_ms, error_message
- fields_count, has_data
- raw_response, parsed_result

### quality_metrics
- date, source, data_type
- success_rate, avg_latency_ms
- total_requests, success_count

### alerts
- timestamp, source, severity
- message, resolved, resolved_at

## Alert Rules

| Rule | Condition | Severity |
|------|-----------|----------|
| Low success rate | < 80% | Critical |
| Moderate success rate | < 90% | Warning |
| High latency | > 10s | Critical |
| Moderate latency | > 5s | Warning |
| No data | Availability = 0% | Critical |

## License

MIT License
