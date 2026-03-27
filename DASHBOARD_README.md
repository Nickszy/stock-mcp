# Stock MCP 数据质量监控 Dashboard

实时监控数据源质量，交互式测试不同数据源。

## 功能特性

✅ **数据源监控**
- 成功率、延迟、覆盖率实时监控
- 多数据源对比
- 历史趋势分析

✅ **交互式测试台**
- 手动触发数据获取
- 对比多个数据源结果
- 查看原始响应和解析结果

✅ **告警系统**
- 自动检测异常
- 三级告警（info/warning/critical）
- 告警历史追踪

✅ **历史记录**
- 请求日志查询
- 质量指标统计
- 数据导出

## 快速开始

### 1. 安装依赖

```bash
# 监控系统核心依赖（已包含在主项目 requirements.txt 中）
# Dashboard 额外依赖
cd dashboard
pip install -r requirements.txt
```

### 2. 运行测试

```bash
# 测试监控系统
uv run python test_monitoring.py
```

### 3. 启动 Dashboard

```bash
cd dashboard
streamlit run app.py
```

Dashboard 将在 http://localhost:8501 打开。

## 架构说明

```
src/server/monitoring/
├── models.py              # 数据模型（RequestLog, QualityMetrics, Alert）
├── db.py                  # SQLite 数据库操作
├── monitored_adapter.py   # Adapter 包装器（自动记录请求）
├── metrics_calculator.py  # 质量指标计算
└── alert_manager.py       # 告警管理

dashboard/
├── app.py                 # Streamlit 主程序
└── pages/
    ├── overview.py        # 总览页面
    ├── test_bench.py      # 测试台
    ├── history.py         # 历史记录
    └── alerts.py          # 告警管理
```

## 使用说明

### 总览页面
- 查看所有数据源健康度
- 关键指标卡片（成功率、延迟、告警数）
- 数据类型质量对比

### 测试台
1. 选择数据类型（行情/财报/新闻等）
2. 输入股票代码（如 SSE:600519）
3. 选择要测试的数据源（可多选）
4. 点击"开始测试"
5. 查看对比结果

### 历史记录
- 按数据源/数据类型过滤
- 查看请求趋势图
- 导出 CSV

### 告警管理
- 查看告警汇总
- 标记告警为已解决
- 查看告警规则

## 集成到现有系统

### 包装现有 Adapter

```python
from src.server.monitoring import MonitoringDB, MonitoredAdapter

# 初始化监控数据库
db = MonitoringDB("monitoring.db")

# 包装现有 adapter
original_adapter = TushareAdapter()
monitored_adapter = MonitoredAdapter(original_adapter, db, "tushare")

# 使用包装后的 adapter（自动记录日志）
result = await monitored_adapter.fetch_price("SSE:600519")
```

### 自动质量检查

```python
from src.server.monitoring import MetricsCalculator, AlertManager

calculator = MetricsCalculator(db)
alert_manager = AlertManager(db)

# 计算质量指标
metrics = calculator.calculate_source_metrics("tushare", "price", hours=24)

# 检查并生成告警
all_metrics = calculator.calculate_all_metrics(hours=24)
alert_manager.check_and_alert(all_metrics)
```

## 数据库表结构

### request_logs (请求日志)
- timestamp: 请求时间
- data_type: 数据类型
- instrument_id: 标的代码
- source: 数据源
- status: 状态（success/failed/timeout）
- latency_ms: 延迟（毫秒）
- error_message: 错误信息
- fields_count: 返回字段数
- has_data: 是否有数据
- raw_response: 原始响应
- parsed_result: 解析结果

### quality_metrics (质量指标)
- date: 日期
- source: 数据源
- data_type: 数据类型
- success_rate: 成功率
- avg_latency_ms: 平均延迟
- total_requests: 总请求数

### alerts (告警)
- timestamp: 告警时间
- source: 数据源
- severity: 级别（info/warning/critical）
- message: 告警消息
- resolved: 是否已解决
- resolved_at: 解决时间

## 告警规则

| 规则 | 条件 | 级别 |
|------|------|------|
| 成功率过低 | < 80% | 🔴 Critical |
| 成功率较低 | < 90% | 🟡 Warning |
| 延迟过高 | > 10s | 🔴 Critical |
| 延迟较高 | > 5s | 🟡 Warning |
| 无可用数据 | 可用率 = 0% | 🔴 Critical |

## 性能优化

- SQLite 索引优化（timestamp, source, data_type）
- 分页查询（默认限制 1000 条）
- 异步写入（不阻塞主流程）
- 数据聚合（按小时/天）

## 后续扩展

- [ ] 接入真实 Adapter（替换 mock 数据）
- [ ] 添加数据质量校验器（校验规则）
- [ ] 邮件/钉钉告警通知
- [ ] 数据质量报告生成
- [ ] 多租户支持
- [ ] 更复杂的数据血缘追踪

## 故障排查

### Dashboard 无法启动
```bash
# 检查依赖
pip install -r dashboard/requirements.txt

# 检查 Python 版本（需要 >= 3.10）
python --version
```

### 数据库错误
```bash
# 删除数据库重新初始化
rm monitoring.db
```

### 无数据显示
- 确认已运行过测试或实际请求
- 检查时间范围设置（侧边栏）
- 查看数据库是否有数据

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License
