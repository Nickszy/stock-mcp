# Stock MCP 数据质量监控方案设计

> **文档版本:** v1.0
> **创建日期:** 2026-03-26
> **状态:** 设计阶段

---

## 📋 目录

1. [评估框架](#评估框架)
2. [通用层指标](#通用层指标)
3. [类型层指标](#类型层指标)
4. [监控 Dashboard 设计](#监控-dashboard-设计)
5. [实施路线图](#实施路线图)

---

## 评估框架

### 三层评估体系

```
┌─────────────────────────────────────────────────────────┐
│                   最终输出评估                           │
│  (完整度/置信度/冲突情况/延迟/业务规则通过率)          │
└─────────────────────────────────────────────────────────┘
                           ▲
                           │
┌─────────────────────────────────────────────────────────┐
│                   路由策略评估                           │
│  (主源命中率/fallback触发率/查询成本/平均延迟)         │
└─────────────────────────────────────────────────────────┘
                           ▲
                           │
┌─────────────────────────────────────────────────────────┐
│                   数据源评估                             │
│  (覆盖率/准确性/时效性/稳定性/字段完整度)              │
└─────────────────────────────────────────────────────────┘
```

---

## 通用层指标

适用于**所有数据类型**的基础指标。

### 1. 覆盖度 (Coverage)

| 指标 | 计算方式 | 目标值 |
|------|----------|--------|
| **标的覆盖率** | `count(distinct instrument_id) / count(全市场标的)` | >= 95% |
| **时间覆盖率** | `count(交易日有数据) / count(总交易日)` | >= 99% |
| **字段覆盖率** | `count(非空字段) / count(总字段)` | >= 90% |

**示例:**
```python
# A股标的覆盖率
expected_stocks = 5000  # 沪深北总计
actual_stocks = count(distinct ticker where market in ['SSE', 'SZSE', 'BSE'])
coverage = actual_stocks / expected_stocks  # 目标 >= 95%
```

---

### 2. 正确性 (Correctness)

| 指标 | 说明 | 校验规则 |
|------|------|----------|
| **格式正确率** | 字段格式是否符合规范 | 正则表达式校验 |
| **范围正确率** | 数值是否在合理范围 | 业务规则校验 |
| **关系正确率** | 字段间关系是否合理 | 逻辑校验 |

**校验规则示例:**
```python
# 价格合理性
if not (low_price <= price <= high_price):
    return "FAIL: price not in [low, high]"

# 涨跌幅合理性（A股 ±20%）
if abs(change_percent) > 20:
    return "FAIL: change_percent exceeds limit"

# 成交量非负
if volume < 0:
    return "FAIL: volume negative"
```

---

### 3. 一致性 (Consistency)

| 指标 | 计算方式 | 目标值 |
|------|----------|--------|
| **多源偏差率** | `abs(source1_value - source2_value) / source1_value` | < 1% |
| **时间序列连续性** | 缺失bar比例 | < 0.1% |
| **单位一致性** | 混合单位比例 | 0% |

**多源价格偏差检测:**
```python
# 同一股票同一时间点，不同源价格偏差
tushare_price = 1800.00
akshare_price = 1798.50
deviation = abs(tushare_price - akshare_price) / tushare_price  # 0.083%
# 目标: < 1%
```

---

### 4. 时效性 (Freshness)

| 指标 | 计算方式 | 目标值 |
|------|----------|--------|
| **数据延迟** | `now() - max(fetch_time)` | < 5min (实时) / < 24h (历史) |
| **更新频率** | `count(updates) / count(expected_updates)` | >= 99% |

**延迟分级:**
```python
# 实时数据（行情）
if latency > 5min:
    severity = "CRITICAL"

# 历史数据（财报）
if latency > 24h:
    severity = "WARNING"
```

---

### 5. 稳定性 (Stability)

| 指标 | 计算方式 | 目标值 |
|------|----------|--------|
| **API 成功率** | `count(success) / count(total_requests)` | >= 95% |
| **错误率** | `count(errors) / count(total_requests)` | < 5% |
| **平均响应时间** | `avg(response_time)` | < 2s |

---

### 6. 可追溯性 (Lineage)

| 指标 | 计算方式 | 目标值 |
|------|----------|--------|
| **元数据完整率** | `count(有完整元数据记录) / count(总记录)` | 100% |
| **血缘链完整率** | 能追溯到原始请求的比例 | 100% |

**必需元数据字段:**
```python
{
    "instrument_id": "SSE:600519",
    "market": "SSE",
    "data_type": "price",
    "source": "tushare",
    "source_priority": 1,
    "fetch_time": "2026-03-26T13:00:00Z",
    "event_time": "2026-03-26T12:59:55Z",
    "parser_version": "1.2.3",
    "routing_path": "tushare→cache→response",
    "raw_id": "600519.SH_20260326",
    "confidence_score": 0.95
}
```

---

## 类型层指标

### A. 行情数据 (Market Data)

#### 核心指标

| 指标 | 说明 | 目标值 | 告警阈值 |
|------|------|--------|----------|
| **K线完整率** | 交易日有bar的比例 | >= 99% | < 95% |
| **缺失 bar 比例** | 应有但没有的bar | < 1% | > 5% |
| **OHLC 合法率** | `low <= open/close <= high` | 100% | < 99% |
| **成交量非负率** | volume >= 0 | 100% | < 100% |
| **时区正确率** | 时间戳时区正确 | 100% | < 100% |
| **复权一致率** | 前复权/后复权/不复权计算正确 | 100% | < 99% |
| **多源价格偏差** | 同一时间点不同源价格差异 | < 1% | > 2% |
| **延迟** | 实时行情延迟 | < 60s | > 5min |

#### 校验规则

```python
class MarketDataValidator:
    def validate(self, record):
        errors = []

        # 1. OHLC 合法性
        if not (record.low <= record.open <= record.high):
            errors.append("open not in [low, high]")
        if not (record.low <= record.close <= record.high):
            errors.append("close not in [low, high]")
        if not (record.low <= record.price <= record.high):
            errors.append("price not in [low, high]")

        # 2. 成交量非负
        if record.volume < 0:
            errors.append("volume negative")

        # 3. 价格非负
        if record.price <= 0:
            errors.append("price non-positive")

        # 4. 涨跌幅合理性（A股 ±20%，创业板/科创板 ±20%）
        max_change = 20  # A股
        if record.market in ['NASDAQ', 'NYSE']:
            max_change = None  # 美股无限制
        if max_change and abs(record.change_percent) > max_change:
            errors.append(f"change_percent exceeds {max_change}%")

        # 5. 交易日对齐
        if not is_trading_day(record.market, record.timestamp):
            errors.append("data on non-trading day")

        return errors
```

#### 常见问题

| 问题 | 影响 | 检测方法 |
|------|------|----------|
| A股美股交易日不一致 | 假数据 | 检查交易日历 |
| 停牌日误生成行情 | 假数据 | 交叉验证停牌信息 |
| 复权因子更新滞后 | 价格跳变 | 检查拆分/分红后价格 |
| 成交额当成交量 | 单位错误 | 检查数值量级 |
| 时区错位 | 时间错误 | 检查时间戳时区 |

---

### B. 财报数据 (Financial Statements)

#### 核心指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| **字段准确率** | 关键字段与官方财报一致 | 100% |
| **单位统一率** | 所有金额使用相同单位 | 100% |
| **币种统一率** | 币种标记正确 | 100% |
| **财报期口径正确率** | 报告期识别正确 | 100% |
| **restatement 处理率** | 重述财报正确处理 | 100% |
| **多源冲突率** | 不同源数据冲突 | < 1% |

#### 校验规则

```python
class FinancialStatementValidator:
    def validate(self, record):
        errors = []

        # 1. 三表勾稽关系
        # 资产 = 负债 + 所有者权益
        if abs(record.total_assets - (record.total_liab + record.equity)) > 1:
            errors.append("balance sheet equation broken")

        # 2. 利润表逻辑
        # 营业利润 = 营业收入 - 营业成本 - 费用
        if record.operate_profit:
            expected = record.revenue - record.oper_cost - record.expenses
            if abs(record.operate_profit - expected) > 1:
                errors.append("operate profit mismatch")

        # 3. 现金流逻辑
        # 自由现金流 = 经营现金流 - 资本支出
        if record.free_cashflow:
            calculated = record.operating_cf - record.capex
            if abs(record.free_cashflow - calculated) > 1:
                errors.append("free cashflow mismatch")

        # 4. YoY/QoQ 合理性
        if record.revenue_yoy and abs(record.revenue_yoy) > 500:
            errors.append("revenue_yoy exceeds 500%, verify")

        return errors
```

---

### C. 新闻数据 (News Data)

#### 核心指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| **新闻覆盖率** | 主要公司新闻覆盖 | >= 90% |
| **去重率** | 重复新闻比例 | < 10% |
| **标的映射准确率** | 正确映射到股票 | >= 95% |
| **发布时间准确率** | 时间戳是原始发布时间 | >= 95% |
| **正文完整率** | 正文成功抓取 | >= 90% |
| **噪声率** | 无关/低质新闻 | < 5% |
| **多源重复率** | 同一新闻多个源重复 | < 30% |

#### 校验规则

```python
class NewsDataValidator:
    def validate(self, record):
        errors = []

        # 1. 标的映射验证
        if not record.tickers:
            errors.append("no tickers mapped")
        else:
            # 验证映射准确性
            for ticker in record.tickers:
                if not is_valid_ticker(ticker):
                    errors.append(f"invalid ticker: {ticker}")

        # 2. 去重检测
        if is_duplicate(record.title, record.publish_time):
            errors.append("duplicate news")

        # 3. 时间合理性
        if record.publish_time > now():
            errors.append("publish_time in future")
        if record.publish_time < record.fetch_time - timedelta(days=30):
            errors.append("publish_time too old")

        # 4. 正文质量
        if not record.content or len(record.content) < 50:
            errors.append("content too short or missing")

        # 5. 噪声检测
        if is_clickbait(record.title):
            errors.append("clickbait title")

        return errors
```

---

### D. 事件数据 (Event Data)

#### 核心指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| **事件召回率** | 应捕获的事件被捕获 | >= 95% |
| **事件类型准确率** | 事件分类正确 | >= 95% |
| **事件时间准确率** | 事件时间正确 | >= 99% |
| **事件去重率** | 重复事件比例 | < 5% |
| **参数抽取准确率** | 关键参数抽取正确 | >= 90% |

#### 校验规则

```python
class EventDataValidator:
    def validate(self, record):
        errors = []

        # 1. 事件类型验证
        valid_types = ['dividend', 'split', 'buyback', 'merger', 'delisting']
        if record.event_type not in valid_types:
            errors.append(f"unknown event type: {record.event_type}")

        # 2. 事件参数完整性
        if record.event_type == 'dividend':
            if not record.dividend_amount:
                errors.append("dividend event missing amount")
            if not record.ex_dividend_date:
                errors.append("dividend event missing ex_date")

        # 3. 时间合理性
        if record.event_date > now():
            errors.append("event_date in future")

        # 4. 去重
        if is_duplicate_event(record.ticker, record.event_type, record.event_date):
            errors.append("duplicate event")

        return errors
```

---

### E. 宏观数据 (Macro Data)

#### 核心指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| **发布及时性** | 官方发布后立即可用 | < 1h |
| **数据连续性** | 时间序列无缺失 | 100% |
| **单位正确性** | 单位标记正确 | 100% |
| **口径一致性** | 统计口径一致 | 100% |

---

## 监控 Dashboard 设计

### Dashboard 布局

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Stock MCP 数据质量监控                             │
├─────────────────────────────────────────────────────────────────────┤
│  数据源健康度                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Tushare  │ │ Akshare  │ │  Yahoo   │ │ Finnhub  │ │   FRED   │  │
│  │ 🟢 98.5% │ │ 🟡 92.3% │ │ 🟢 99.1% │ │ 🟢 97.2% │ │ 🟢 99.9% │  │
│  │ 延迟: T+1 │ │延迟: T+0 │ │延迟: 15m │ │延迟: 实时 │ │延迟: 官方 │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
├─────────────────────────────────────────────────────────────────────┤
│  今日请求统计                                                         │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  总请求: 15,234  │  成功: 14,892  │  失败: 342  │  缓存命中: 67% │   │
│  └──────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────┤
│  数据完整性 (按数据类型)                                              │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  行情: 99.2%  │  财报: 98.5%  │  新闻: 94.3%  │  宏观: 100%   │   │
│  └──────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────┤
│  路由效率                                                             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  主源命中: 94.5%  │  Fallback触发: 5.5%  │  平均延迟: 1.2s    │   │
│  └──────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────┤
│  最近告警                                                             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 🟡 13:02  Akshare API 限流，已切换到 Baostock                   │   │
│  │ 🟡 12:45  Yahoo Finance 延迟 > 5s，触发重试                       │   │
│  │ 🟢 11:30  Tushare 积分充足，正常服务                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 告警规则

| 告警级别 | 触发条件 | 通知方式 | 示例 |
|----------|----------|----------|------|
| 🟢 **Info** | 正常运行 | 日志 | API 成功率 > 99% |
| 🟡 **Warning** | 轻微异常 | 日志 | 单源失败，已fallback |
| 🔴 **Critical** | 严重问题 | 日志+通知 | 全源故障 / 数据错误 |

**告警阈值:**

| 指标 | Warning | Critical |
|------|---------|----------|
| API 成功率 | < 95% | < 90% |
| 数据延迟 | > 5min | > 15min |
| 数据缺失率 | > 5% | > 10% |
| 多源冲突率 | > 2% | > 5% |

---

## 实施路线图

### Phase 1: 元数据层 (1-2周)

**目标:** 建立统一元数据层

**任务:**
- [ ] 定义 `DataQualityMetadata` 类
- [ ] 为所有数据类型添加元数据字段
- [ ] 实现 `confidence_score` 计算
- [ ] 添加 `routing_path` 追踪

**输出:**
```python
class DataQualityMetadata:
    instrument_id: str
    market: str
    data_type: str
    source: str
    source_priority: int
    fetch_time: datetime
    event_time: datetime
    parser_version: str
    routing_path: str
    raw_id: str
    confidence_score: float
```

---

### Phase 2: 通用层指标 (1-2周)

**目标:** 实现通用质量指标计算

**任务:**
- [ ] 实现 `QualityMetricsCalculator`
- [ ] 计算 success_rate
- [ ] 计算 freshness
- [ ] 计算 completeness
- [ ] 计算 consistency
- [ ] 计算 stability
- [ ] 计算 lineage_completeness

**输出:**
```python
class QualityMetricsCalculator:
    def calculate_success_rate(self, source: str) -> float
    def calculate_freshness(self, data_type: str) -> timedelta
    def calculate_completeness(self, instrument_id: str) -> float
    def calculate_consistency(self, ticker: str, timestamp: datetime) -> float
```

---

### Phase 3: 专项校验器 (2-3周)

**目标:** 按数据类型实现校验规则

**任务:**
- [ ] 实现 `MarketDataValidator`
- [ ] 实现 `FinancialStatementValidator`
- [ ] 实现 `NewsDataValidator`
- [ ] 实现 `EventDataValidator`
- [ ] 实现 `MacroDataValidator`

**输出:**
```python
class MarketDataValidator:
    def validate(self, record: AssetPrice) -> List[ValidationError]

class FinancialStatementValidator:
    def validate(self, record: Financials) -> List[ValidationError]
```

---

### Phase 4: 监控 Dashboard (2-3周)

**目标:** 可视化数据质量

**任务:**
- [ ] 设计 Dashboard UI
- [ ] 实现数据源健康度监控
- [ ] 实现请求统计
- [ ] 实现数据完整性监控
- [ ] 实现告警系统
- [ ] 实现路由效率监控

**技术选型:**
- 前端: React + Recharts / ECharts
- 后端: FastAPI + Redis
- 存储: PostgreSQL / InfluxDB

---

### Phase 5: 测试与优化 (1-2周)

**目标:** 验证监控方案有效性

**任务:**
- [ ] 创建黄金数据集 (Ground Truth)
  - 财报 benchmark: 10家公司 × 4季度
  - 行情 benchmark: 5只股票 × 30交易日
  - 新闻 benchmark: 100条新闻 + 人工标注
- [ ] 运行回测敏感性测试
- [ ] 优化告警阈值
- [ ] 性能测试

---

## 附录: 代码示例

### 统一元数据类

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class DataQualityMetadata:
    """统一元数据，所有数据类型都必须包含"""

    # 基础标识
    instrument_id: str  # SSE:600519
    market: str  # SSE
    data_type: str  # price, financials, news, event, macro

    # 数据来源
    source: str  # tushare, akshare, yahoo
    source_priority: int  # 路由优先级

    # 时间信息
    fetch_time: datetime  # 抓取时间
    event_time: Optional[datetime]  # 事件发生时间（如财报期）

    # 血缘追踪
    parser_version: str  # 解析器版本
    routing_path: str  # tushare→cache→response
    raw_id: str  # 原始ID（600519.SH_20260326）

    # 质量评估
    confidence_score: float  # 0-1，数据置信度

    def to_dict(self):
        return {
            "instrument_id": self.instrument_id,
            "market": self.market,
            "data_type": self.data_type,
            "source": self.source,
            "source_priority": self.source_priority,
            "fetch_time": self.fetch_time.isoformat(),
            "event_time": self.event_time.isoformat() if self.event_time else None,
            "parser_version": self.parser_version,
            "routing_path": self.routing_path,
            "raw_id": self.raw_id,
            "confidence_score": self.confidence_score,
        }
```

---

### 质量指标计算器

```python
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict

class QualityMetricsCalculator:
    """通用层质量指标计算器"""

    def __init__(self, redis_client, db_client):
        self.redis = redis_client
        self.db = db_client

    def calculate_success_rate(self, source: str, hours: int = 24) -> float:
        """计算API成功率"""
        since = datetime.now() - timedelta(hours=hours)

        # 从日志或数据库查询
        total = self.db.query("""
            SELECT COUNT(*) FROM api_logs
            WHERE source = %s AND timestamp >= %s
        """, (source, since)).scalar()

        success = self.db.query("""
            SELECT COUNT(*) FROM api_logs
            WHERE source = %s AND timestamp >= %s AND status = 'success'
        """, (source, since)).scalar()

        return success / total if total > 0 else 0.0

    def calculate_freshness(self, data_type: str, market: str) -> timedelta:
        """计算数据时效性"""
        # 查询最新数据时间
        latest = self.redis.get(f"latest_update:{market}:{data_type}")
        if not latest:
            return timedelta(days=999)  # 无数据

        latest_time = datetime.fromisoformat(latest)
        return datetime.now() - latest_time

    def calculate_completeness(self, instrument_id: str, data_type: str) -> float:
        """计算字段完整度"""
        # 从数据库获取最新记录
        record = self.db.query(f"""
            SELECT * FROM {data_type}
            WHERE instrument_id = %s
            ORDER BY timestamp DESC LIMIT 1
        """, (instrument_id,)).fetchone()

        if not record:
            return 0.0

        # 计算非空字段比例
        total_fields = len(record.keys())
        non_null_fields = sum(1 for v in record.values() if v is not None)

        return non_null_fields / total_fields

    def calculate_consistency(
        self,
        ticker: str,
        timestamp: datetime,
        data_type: str
    ) -> Dict[str, float]:
        """计算多源一致性"""
        # 查询同一时间点不同源的数据
        sources_data = self.db.query(f"""
            SELECT source, value FROM {data_type}
            WHERE ticker = %s AND timestamp = %s
        """, (ticker, timestamp)).fetchall()

        if len(sources_data) < 2:
            return {"deviation": 0.0, "sources": 1}

        # 计算偏差
        values = [row['value'] for row in sources_data]
        max_deviation = max(values) - min(values)
        avg_value = sum(values) / len(values)

        relative_deviation = max_deviation / avg_value if avg_value != 0 else 0

        return {
            "deviation": relative_deviation,
            "sources": len(sources_data),
            "values": values
        }
```

---

### 仪表板 API

```python
from fastapi import FastAPI, Query
from datetime import datetime, timedelta

app = FastAPI()

@app.get("/api/dashboard/health")
async def get_source_health():
    """获取数据源健康度"""
    return {
        "tushare": {
            "status": "healthy",
            "success_rate": 0.985,
            "latency": "T+1",
            "last_update": "2026-03-26T13:00:00Z"
        },
        "akshare": {
            "status": "degraded",
            "success_rate": 0.923,
            "latency": "T+0",
            "last_update": "2026-03-26T13:05:00Z"
        },
        # ...
    }

@app.get("/api/dashboard/stats")
async def get_request_stats(hours: int = Query(24)):
    """获取请求统计"""
    since = datetime.now() - timedelta(hours=hours)

    return {
        "total_requests": 15234,
        "success": 14892,
        "failed": 342,
        "cache_hit_rate": 0.67,
        "avg_latency_ms": 1200,
    }

@app.get("/api/dashboard/completeness")
async def get_data_completeness(market: str = None):
    """获取数据完整性"""
    return {
        "price": 0.992,
        "financials": 0.985,
        "news": 0.943,
        "macro": 1.000,
    }

@app.get("/api/dashboard/alerts")
async def get_recent_alerts(limit: int = 10):
    """获取最近告警"""
    return [
        {
            "level": "warning",
            "timestamp": "2026-03-26T13:02:00Z",
            "message": "Akshare API 限流，已切换到 Baostock",
            "resolved": True
        },
        # ...
    ]
```

---

## 总结

这个数据质量监控方案涵盖了：

1. **三层评估体系**: 源评估 → 路由评估 → 最终输出评估
2. **通用层指标**: 覆盖度/正确性/一致性/时效性/稳定性/可追溯性
3. **类型层指标**: 针对行情/财报/新闻/事件/宏观的专项指标
4. **可视化 Dashboard**: 数据源健康度/请求统计/完整性/告警
5. **实施路线图**: 5个阶段，6-12周完成

**下一步行动:**
1. 确认监控方案是否符合需求
2. 开始 Phase 1: 元数据层实现
