# Stock MCP 数据调用指南

## 触发条件
- 用户需要查询股票/加密货币/外汇行情数据
- 用户需要获取财报、技术指标、资金流向等金融数据
- 用户问如何使用 stock-mcp 的数据

## 项目简介

Stock MCP 是一个强大的金融数据服务器，通过 MCP (Model Context Protocol) 协议为 AI Agent 提供专业级股市分析能力。

**GitHub**: https://github.com/Nickszy/stock-mcp

### 核心能力
- 多源数据融合（自动故障转移）
- A股/美股/港股/加密货币全覆盖
- 20+ 技术指标 + K线形态识别
- 完整财报三表 + YoY/QoQ 计算
- 资金流向/北向资金/宏观数据

---

## 一、配置 MCP 连接

### Claude Desktop 配置

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "stock-tools": {
      "command": "bash",
      "args": ["start_stock_mcp_stdio.sh"],
      "cwd": "/path/to/stock-mcp"
    }
  }
}
```

### Cursor 配置

编辑 `.cursor/mcp_config.json`:

```json
{
  "mcpServers": {
    "stock-tools": {
      "command": "bash",
      "args": ["start_stock_mcp_stdio.sh"],
      "cwd": "/path/to/stock-mcp"
    }
  }
}
```

---

## 二、股票代码格式

| 市场 | 格式 | 示例 |
|------|------|------|
| 上交所 (A股) | `SSE:代码` | `SSE:600519` (贵州茅台) |
| 深交所 (A股) | `SZSE:代码` | `SZSE:000001` (平安银行) |
| 纳斯达克 | `NASDAQ:代码` | `NASDAQ:AAPL` (苹果) |
| 纽交所 | `NYSE:代码` | `NYSE:TSLA` (特斯拉) |
| 港交所 | `HKEX:代码` | `HKEX:00700` (腾讯) |
| 加密货币 | `CRYPTO:代码` | `CRYPTO:BTC`, `CRYPTO:ETH` |

---

## 三、常用工具调用示例

### 1. 行情数据

```
# 实时价格
get_real_time_price(ticker="SSE:600519")

# 历史K线
get_kline_data(ticker="SSE:600519", start_date="2024-01-01", end_date="2024-12-31")

# 批量价格
get_multiple_prices(tickers=["SSE:600519", "SZSE:000001"])
```

### 2. 基本面数据

```
# 完整财报三表（利润表/资产负债表/现金流量表 + YoY/QoQ）
get_financial_statements(symbol="SSE:600519", report_type="all", periods=8)

# 财务摘要图表
get_financial_reports(symbol="SSE:600519")

# 主营业务构成
get_mainbz_info(symbol="SSE:600519")

# 股东信息
get_shareholder_info(symbol="SSE:600519")

# 分红历史
get_dividend_info(symbol="SSE:600519")

# 业绩预告
get_forecast_info(symbol="SSE:600519")

# 估值指标
get_valuation_metrics(symbol="SSE:600519")
```

### 3. 技术分析

```
# 技术指标（RSI/MACD/布林带等）
get_technical_indicators(symbol="SSE:600519", period="90d", interval="1d")
```

### 4. 资金流向

```
# 个股资金流
get_money_flow(symbol="SSE:600519", days=20)

# 北向资金
get_north_bound_flow(days=30)

# 筹码分布
get_chip_distribution(symbol="SSE:600519")

# 板块资金流
get_market_money_flow(market="A股")
```

### 5. 宏观数据

```
# 中国宏观
get_money_supply(months=60)      # M0/M1/M2
get_inflation_data(months=60)    # CPI/PPI
get_gdp_data(quarters=20)        # GDP
get_pmi_data(months=60)          # PMI

# 美国宏观
get_us_economic_growth()         # GDP/失业率
get_us_inflation_employment()    # CPI/非农
get_us_interest_rates()          # 利率/国债收益率
```

### 6. 新闻资讯

```
# 股票新闻
get_stock_news(symbol="SSE:600519", days=30)

# 市场热点
get_latest_news(category="市场")
```

### 7. SEC 文件（美股）

```
# 周期性文件（10-K/10-Q）
fetch_periodic_sec_filings(ticker="NASDAQ:AAPL", form_type="10-K")

# 事件文件（8-K）
fetch_event_sec_filings(ticker="NASDAQ:TSLA", days=90)

# 获取 Markdown 内容
get_filing_markdown(doc_id="0000320193-24-000123")
```

---

## 四、数据源说明

### A股数据源
| 数据源 | 特点 | API Key |
|--------|------|---------|
| Tushare | 数据最全，财报完整 | 必需 |
| Akshare | 开源免费，覆盖广 | 无需 |
| Baostock | 历史数据全 | 无需 |

### 美股数据源
| 数据源 | 特点 | API Key |
|--------|------|---------|
| Yahoo Finance | 覆盖广，免费 | 无需 |
| Finnhub | 机构数据，实时性好 | 推荐 |

### 智能路由
- 自动选择最优数据源
- 失败自动故障转移
- 配额智能轮换

---

## 五、环境变量配置

```bash
# .env 文件

# Tushare（A股增强数据）
TUSHARE_ENABLED=true
TUSHARE_TOKEN=your_token_here

# Finnhub（美股机构数据）
FINNHUB_ENABLED=true
FINNHUB_API_KEY=your_key_here

# FRED（美国宏观数据）
FRED_API_KEY=your_key_here

# Redis 缓存（可选）
REDIS_URL=redis://localhost:6379
```

---

## 六、HTTP API 调用（可选）

如果需要通过 HTTP 调用而非 MCP：

```bash
# 启动服务器
export MCP_TRANSPORT=streamable-http
uv run python -m uvicorn src.server.app:app --host 0.0.0.0 --port 9898

# 调用工具
curl -X POST "http://localhost:9898/?_tool=get_kline_data" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "get_kline_data",
      "arguments": {
        "ticker": "SSE:600519"
      }
    },
    "id": "1"
  }'
```

---

## 七、常见问题

### Q: 如何获取 Token？
- Tushare: https://tushare.pro/register
- Finnhub: https://finnhub.io/
- FRED: https://fred.stlouisfed.org/docs/api/api_key.html

### Q: 没有 API Key 能用吗？
可以！Akshare、Baostock、Yahoo Finance 都是免费的，系统会自动使用这些数据源。

### Q: 数据更新频率？
- 实时行情：实时
- 技术指标：实时计算
- 财报数据：缓存 1 小时
- 宏观数据：缓存 24 小时

---

## 八、社区支持

遇到问题？扫码进群交流：

<img src="https://raw.githubusercontent.com/Nickszy/stock-mcp/main/docs/群二维码.jpg" width="200" alt="微信群二维码"/>
