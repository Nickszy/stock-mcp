# 完整财报三大表功能设计

## 1. 目标

扩展现有 `get_financials` 方法，提供完整的三表数据（利润表、资产负债表、现金流量表），支持：
- 全字段输出（260+ 字段）
- 季度 + 年度数据
- 同比（YoY）和环比（QoQ）计算
- 统一接口：A 股（Tushare）+ 海外（Yahoo Finance）

## 2. 实现状态

✅ **已完成** (2026-03-24)

### 修改的文件

1. **src/server/domain/adapters/tushare_adapter.py**
   - 新增 `get_financial_statements()` 方法
   - 新增 `_add_yoy_qoq()` 辅助方法
   - 支持季度/年度数据、同比/环比计算

2. **src/server/domain/adapters/yahoo_adapter.py**
   - 新增 `get_financial_statements()` 方法
   - 新增 `_add_yoy_qoq_yahoo()` 辅助方法
   - 支持美股/港股财报数据

3. **src/server/domain/adapter_manager.py**
   - 新增 `get_financial_statements()` 路由方法

4. **src/server/domain/market_gateway.py**
   - 在 `_TICKER_METHODS` 中添加 `get_financial_statements`

5. **src/server/core/use_cases/fundamental.py**
   - 新增 `get_financial_statements = _gw_usecase("get_financial_statements")`

6. **src/server/mcp/tools/fundamental_tools.py**
   - 新增 MCP tool `get_financial_statements`

## 3. API 接口

### MCP Tool

```python
@mcp.tool(tags={"fundamental"})
async def get_financial_statements(
    symbol: str,
    report_type: str = "all",  # "quarterly" | "annual" | "all"
    periods: int | None = None,  # None = 全部历史
) -> Dict[str, Any]:
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| symbol | str | 必填 | 股票代码 (SSE:600519, NASDAQ:AAPL) |
| report_type | str | "all" | "quarterly" / "annual" / "all" |
| periods | int\|None | None | 返回期数，None=全部历史 |

### 返回结构

```json
{
  "summary": "SSE:600519 完整财报三表（数据源: tushare）",
  "artifacts": [
    {
      "component_type": "financial_statement",
      "name": "利润表 - SSE:600519",
      "content": {
        "statement_type": "income_statement",
        "quarterly": [...],
        "annual": [...]
      }
    },
    {
      "component_type": "financial_statement",
      "name": "资产负债表 - SSE:600519",
      "content": {...}
    },
    {
      "component_type": "financial_statement",
      "name": "现金流量表 - SSE:600519",
      "content": {...}
    }
  ]
}
```

### YoY/QoQ 字段

每条记录中关键指标会自动添加：
- `{field}_yoy`: 同比增长率（与去年同期比较）
- `{field}_qoq`: 环比增长率（仅季度数据，与上一季度比较）

示例：
```json
{
  "end_date": "20240930",
  "revenue": 1000000000,
  "revenue_yoy": 15.5,   // 同比 +15.5%
  "revenue_qoq": 5.2     // 环比 +5.2%
}
```

## 4. 数据源路由

| 市场 | 数据源 | Adapter |
|------|--------|---------|
| A股 (SSE/SZSE) | Tushare Pro | TushareAdapter |
| 美股 (NASDAQ/NYSE) | Yahoo Finance | YahooAdapter |
| 港股 (HKEX) | Yahoo Finance | YahooAdapter |

## 5. 缓存策略

- Cache key: `{source}:financial_statements:{ticker}:{report_type}:{periods}:v1`
- TTL: 3600 秒（1小时）
