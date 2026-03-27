# Stock MCP 数据质量监控 Dashboard

实时监控数据源质量，交互式测试不同数据源。

## 🚀 快速开始

### Docker 部署（推荐）

#### Windows 用户
```bash
# 双击运行或命令行执行
start.bat
```

#### Linux/Mac 用户
```bash
chmod +x start.sh
./start.sh
```

#### 手动启动
```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 访问地址
- **Dashboard**: http://localhost:8501
- **API**: http://localhost:9898

### 本地开发（不使用 Docker）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行测试
uv run python test_monitoring.py

# 3. 启动 Dashboard
cd dashboard
streamlit run app.py
```

## ✨ 功能特性

### 📊 总览页面
- 数据源健康度监控（成功率、延迟、告警）
- 关键指标卡片
- 数据类型质量对比
- 最近告警列表

### 🔬 测试台
- 选择数据类型（行情/财报/新闻/事件/宏观）
- 输入标的代码（如 SSE:600519）
- 选择数据源（可多选，如 tushare, akshare）
- 点击"开始测试"
- 对比结果：
  - 成功率、延迟
  - 字段数
  - 查看原始响应和解析结果

### 📜 历史记录
- 按数据源/数据类型过滤
- 查看请求趋势图
- 导出 CSV

### 🚨 告警管理
- 查看告警汇总
- 标记告警为已解决
- 查看告警规则

## 🏗️ 架构设计

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

## 🐳 Docker 部署

### 服务架构
- **API 服务**（FastAPI + MCP）- 端口 9898
- **Dashboard 服务**（Streamlit）- 端口 8501
- **共享数据库**（SQLite）- `./data/monitoring.db`

### 常用命令

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f dashboard

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 进入容器
docker-compose exec dashboard bash

# 运行测试
docker-compose exec dashboard python test_monitoring.py
```

### 数据持久化

数据库存储在 `./data/monitoring.db`，容器重启不会丢失数据。

```bash
# 备份数据库
cp ./data/monitoring.db ./data/monitoring_backup_$(date +%Y%m%d).db

# 清理数据
rm ./data/monitoring.db
docker-compose restart dashboard
```

详细文档：[DOCKER_GUIDE.md](DOCKER_GUIDE.md)

## 📦 数据库表

### request_logs（请求日志）
- `timestamp`: 请求时间
- `data_type`: 数据类型（price/financials/news/event/macro）
- `instrument_id`: 标的代码（SSE:600519）
- `source`: 数据源（tushare/akshare/yahoo等）
- `status`: 状态（success/failed/timeout）
- `latency_ms`: 延迟（毫秒）
- `error_message`: 错误信息
- `fields_count`: 返回字段数
- `has_data`: 是否有数据
- `raw_response`: 原始响应（JSON）
- `parsed_result`: 解析结果（JSON）

### quality_metrics（质量指标）
- `date`: 日期
- `source`: 数据源
- `data_type`: 数据类型
- `success_rate`: 成功率
- `avg_latency_ms`: 平均延迟
- `total_requests`: 总请求数
- `success_count`: 成功次数
- `failed_count`: 失败次数

### alerts（告警）
- `timestamp`: 告警时间
- `source`: 数据源
- `severity`: 级别（info/warning/critical）
- `message`: 消息
- `resolved`: 是否已解决
- `resolved_at`: 解决时间

## 🔧 接入真实数据源

目前测试台使用模拟数据。要接入真实数据源：

### 方式 1: 使用 MonitoredAdapter 包装

```python
from src.server.monitoring import MonitoringDB, MonitoredAdapter

# 初始化监控数据库
db = MonitoringDB("data/monitoring.db")

# 包装现有 adapter
original_adapter = TushareAdapter()
monitored_adapter = MonitoredAdapter(original_adapter, db, "tushare")

# 使用包装后的 adapter（自动记录日志）
result = await monitored_adapter.fetch_price("SSE:600519")
```

### 方式 2: 直接调用 API

```python
from src.server.monitoring import MonitoringDB, RequestLog

db = MonitoringDB("data/monitoring.db")

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

## ⚠️ 告警规则

| 规则 | 条件 | 级别 |
|------|------|------|
| 成功率过低 | < 80% | 🔴 Critical |
| 成功率较低 | < 90% | 🟡 Warning |
| 延迟过高 | > 10s | 🔴 Critical |
| 延迟较高 | > 5s | 🟡 Warning |
| 无可用数据 | 可用率 = 0% | 🔴 Critical |

## 🧪 测试

```bash
# 运行测试（会自动清理测试数据库）
uv run python test_monitoring.py
```

测试内容：
- 数据库初始化
- 日志插入和查询
- 指标计算
- 告警生成
- Dashboard API

## 📚 文档

- [DOCKER_GUIDE.md](DOCKER_GUIDE.md) - Docker 详细部署指南
- [DASHBOARD_USAGE.md](DASHBOARD_USAGE.md) - Dashboard 使用说明
- [data_quality_monitoring_design.md](data_quality_monitoring_design.md) - 系统设计文档

## 🔍 故障排查

### Dashboard 无法启动

```bash
# 检查端口占用
netstat -tunlp | grep 8501

# 查看日志
docker-compose logs dashboard

# 检查依赖
pip install -r requirements.txt
```

### 无数据显示

```bash
# 运行测试生成数据
docker-compose exec dashboard python test_monitoring.py

# 或本地运行
uv run python test_monitoring.py
```

### 数据库锁定错误

SQLite 不支持高并发写入。解决方案：
1. 减少并发请求
2. 使用 PostgreSQL（修改 `db.py`）
3. 增加重试逻辑

### 完全重置

```bash
# 停止并删除容器
docker-compose down

# 删除数据
rm -rf ./data

# 重新构建
docker-compose build --no-cache

# 启动
docker-compose up -d
```

## 🚧 扩展计划

- [ ] 接入真实数据源（替换 mock 数据）
- [ ] 添加数据质量校验器（校验规则）
- [ ] 邮件/钉钉告警通知
- [ ] 数据质量报告生成（PDF/Excel）
- [ ] 多租户支持
- [ ] 数据血缘追踪
- [ ] 支持更多数据源（加密货币、期货等）
- [ ] API 请求限流和认证
- [ ] 历史数据归档策略

## 🛠️ 技术栈

- **Python**: >= 3.11
- **FastAPI**: >= 0.121.3
- **Streamlit**: >= 1.30.0
- **Plotly**: >= 5.18.0
- **Pandas**: >= 2.3.3
- **SQLite3**: 内置

## 📝 开发说明

### 添加新的数据类型

1. 在 `models.py` 中添加到 `DataType` 枚举
2. 在 `test_bench.py` 中添加测试逻辑
3. 在 `metrics_calculator.py` 中更新数据源映射

### 自定义告警规则

编辑 `alert_manager.py` 的 `check_and_alert` 方法。

### 修改 Dashboard UI

编辑 `dashboard/pages/*.py` 文件，Streamlit 会自动热重载。

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**开始使用**: `./start.bat` (Windows) 或 `./start.sh` (Linux/Mac)
