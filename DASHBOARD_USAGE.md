# 数据质量监控 Dashboard 使用指南

## 启动 Dashboard

```bash
cd .worktrees/data-quality-dashboard
streamlit run dashboard/app.py
```

## 访问地址

Dashboard 将在 http://localhost:8501 打开

## 测试步骤

### 1. 运行监控测试
```bash
uv run python test_monitoring.py
```

### 2. 启动 Dashboard
```bash
cd dashboard
streamlit run app.py
```

## 主要功能

### 📊 总览页面
- 数据源健康度监控（成功率、延迟、告警）
- 关键指标卡片
- 数据类型质量对比
- 最近告警列表

### 🔬 测试台
- 选择数据类型（行情/财报/新闻/事件/宏观）
- 输入标的代码（如 SSE:600519）
- 选择数据源（可多选，- 点击"开始测试"
- 对比结果：
  - 成功率、 延迟
  - 字段数
  - 埥看原始响应和解析结果

### 📜 历史记录
- 按数据源/数据类型过滤
- 查看请求趋势图
- 导出 CSV

### 🚨 告警管理
- 查看告警汇总
- 标记告警为已解决
- 查看告警规则

## 架构设计

```
src/server/monitoring/
├── models.py              # 数据模型
├── db.py                  # SQLite 操作
├── monitored_adapter.py   # Adapter 包装器
├── metrics_calculator.py  # 指标计算
└── alert_manager.py       # 告警管理

dashboard/
├── app.py                 # Streamlit 主程序
└── pages/
    ├── overview.py       # 总览页
    ├── test_bench.py       # 测试台
    ├── history.py          # 历史记录
    └── alerts.py            # 告警管理
```

## 数据库表

### request_logs
- `id`: 主键
- `timestamp`: 请求时间
- `data_type`: 数据类型
- `instrument_id`: 标的代码
- `source`: 数据源
- `status`: 状态（成功/失败/超时)
- `latency_ms`: 延迟(毫秒)
- `error_message`: 错误信息
- `fields_count`: 返回字段数
- `has_data`: 是否有数据
- `raw_response`: 原始响应
- `parsed_result`: 解析结果

### quality_metrics
- `date`: 日期
- `source`: 数据源
- `data_type`: 数据类型
- `success_rate`: 成功率
- `avg_latency_ms`: 平均延迟
- `total_requests`: 总请求数

### alerts
- `timestamp`: 告警时间
- `source`: 数据源
- `severity`: 级别
- `message`: 消息
- `resolved`: 是否已解决

## 娡拟数据说明

测试台使用模拟数据进行演示，没有连接真实数据源。

要接入真实数据源，### 方式 1: 使用 MonitoredAdapter 包装

```python
from src.server.monitoring import MonitoringDB, MonitoredAdapter

# 初始化监控数据库
db = MonitoringDB("monitoring.db")

# 包装现有 adapter
original_adapter = TushareAdapter()
monitored_adapter = MonitoredAdapter(original_adapter, db, "tushare")

# 使用包装后的 adapter
result = await monitored_adapter.fetch_price("SSE:600519")
```

### 方式 2: 直接调用 API

```python
# 直接使用数据库 API 记录日志
from src.server.monitoring import MonitoringDB, RequestLog

db = MonitoringDB("monitoring.db")

# 记录请求日志
log = RequestLog(
    data_type="price",
    instrument_id="SSE:600519",
    source="tushare",
    status="success",
    latency_ms=1200.5,
    fields_count=15,
    has_data=True,
    raw_response='{"price": 1800.50}',
    parsed_result='{"price": 1800.50}',
)

db.log_request(log)
```

## 匊警规则

| 规则 | 条件 | 级别 |
|------|------|------|
| 成功率过低 | < 80% | Critical |
| 成功率较低 | < 90% | Warning |
| 延迟过高 | > 10s | Critical |
| 延迟较高 | > 5s | Warning |
| 无可用数据 | 可用率 = 0% | Critical |

## 扩展计划

- [ ] 接入真实数据源（替换 mock 数据）
- [ ] 添加数据质量校验器
- [ ] 邮件/钉钉告警通知
- [ ] 数据质量报告生成
- [ ] 多租户支持
- [ ] 更复杂的数据血缘追踪

## 故障排查

### Dashboard 无法启动
```bash
# 检查依赖
pip install -r dashboard/requirements.txt

# 检查 Python 版本
python --version
```

### 无数据显示
- 确认已运行过测试或实际请求
- 检查时间范围设置（侧边栏）
- 查看数据库是否有数据

### 数据库错误
```bash
# 删除数据库重新初始化
rm monitoring.db
```

## 技术栈

- **Python**: >= 3.10
- **Streamlit**: >= 1.30.0
- **Plotly**: >= 5.18.0
- **Pandas**: >= 2.0.0
- **SQLite3**: 内置

## 许可证

MIT License
