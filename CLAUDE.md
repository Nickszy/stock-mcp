# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Stock-MCP is a Model Context Protocol (MCP) server for financial market data. It provides AI agents (Claude, Cursor, etc.) with professional-grade stock market analysis capabilities through multi-source data aggregation.

## Development Commands

### Environment Setup (uv)
```bash
# Create virtual environment
uv venv

# Activate environment
uv venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Install dependencies
uv pip install -r requirements.txt
```

### Running the Server

```bash
# HTTP mode (recommended for development)
set MCP_TRANSPORT=streamable-http
uv run uvicorn src.server.app:app --host 0.0.0.0 --port 9898

# stdio mode (for AI agent integration)
uv run python -c "import src.server.mcp.server as m; m.create_mcp_server().run(transport='stdio')"
```

### Testing

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest test_adapter_precision.py

# Run with marker filter (skip integration tests)
uv run pytest -m "not integration"

# Quick syntax check on a file
uv run python -m py_compile src/server/app.py
```

### Automated Validation

This project uses Claude Code hooks for automatic validation:

- **Post-edit**: After editing `.py` files in `src/`, runs syntax check + import validation
- **Pre-commit**: Before committing, validates all staged Python files

To manually trigger validation:
```bash
bash .claude/hooks/post-edit.sh src/server/app.py
bash .claude/hooks/pre-commit.sh
```

### Type Checking
```bash
uv run mypy src/
```

## Architecture

This project uses DDD + layered architecture:

```
src/server/
├── app.py                 # FastAPI + MCP entry point
├── api/                   # REST layer (routes + request models)
├── mcp/                   # MCP protocol layer
│   ├── registry.py        # MCP tool registry (single source of truth for enabled tools)
│   ├── server.py          # MCP server creation and lifecycle
│   └── tools/             # MCP tool definitions by domain
├── core/                  # Application layer
│   ├── bootstrap.py       # Connection/adapter initialization
│   ├── dependencies.py    # Dependency injection container (dependency-injector)
│   └── use_cases/          # Shared use cases (MCP/REST)
├── domain/                # Domain layer (core capabilities)
│   ├── market_gateway.py  # Unified gateway (resolve + route entry)
│   ├── adapter_manager.py # Multi-source adapter orchest + failover
│   ├── adapters/           # Data adapters (Yahoo/Akshare/Tushare/Baostock/Finnhub/CCXT/etc.)
│   ├── symbols/            # Symbol normalization (EXCHANGE:SYMBOL format)
│   ├── routing/             # Routing policy + health tracking + cooldown
│   └── security_master/    # Master data (listing/alias/identifier)
├── infrastructure/        # Infrastructure layer
│   ├── connections/       # Redis/Postgres/Tushare/Finnhub/Baostock connections
│   └── cache/             # Redis cache wrapper
└── config/                # Settings (pydantic-settings) and routing policies
```

### Key Design Patterns

1. **Adapter Pattern**: Unified multi-source interface with provider abstraction
2. **Dependency Injection**: Using `dependency-injector` for service lifecycle management
3. **Policy-Driven Routing**: Provider selection by `asset_type + exchange + data_type`
4. **Resilience**: Health tracking + cooldown + fallback layers
5. **Symbol Standardization**: Normalize inputs into `EXCHANGE:SYMBOL` format

### Request Flow

1. API/MCP receives request → use_case
2. `MarketGateway` calls `SymbolResolver` for normalization
3. `SymbolResolver` persists master data (asset/listing/alias/identifier)
4. `MarketRouter` selects providers by policy and executes with health checks
5. If all providers fail, fallback to legacy `AdapterManager` routing

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Description |
|----------|-------------|
| TUSHARE_TOKEN | A-share data (tushare.pro) |
| FINNHUB_API_KEY | US stock data (finnhub.io) |
| FRED_API_KEY | US macro data (fred.stlouisfed.org) |
| DATABASE_URL | PostgreSQL for security master |
| PROXY_ENABLED | Enable proxy for foreign APIs |

## Tool Groups (registry.py)

Tool groups are defined in `TOOL_GROUPS` list in `src/server/mcp/registry.py`:
- fundamental: 基本面分析 (财务报表/主营构成/股东/分红/业绩预测/估值)
- asset: 资产搜索与管理 (搜索/行情/K线)
- technical: 技术分析 (技术指标/价格形态/支撑阻力)
- money-flow: 资金流向 (个股资金流/北向资金/筹码分布/宏观)
- news: 新闻与检索 (disabled by default)
- us-fundamental: 美股基本面 (EPS/现金流/估值/机构持仓)
- us-technical: 美股技术分析 (指标/量价/K线/综合)
- us-sector: 美股行业ETF分析
- us-macro: 美股宏观分析 (GDP/CPI/利率)
- filings: SEC文档处理
- trade: 交易执行 (CCXT)

## Symbol Format

- A-share: `SSE:600519` (Shanghai), `SZSE:000001` (Shenzhen)
- US stock: `NASDAQ:AAPL`, `NYSE:TSLA`
- Crypto: `CRYPTO:BTC`, `CRYPTO:ETH`

## Data Sources

| Source | Market | API Key |
|--------|--------|---------|
| Tushare | A-share | Required |
| Akshare | A-share/HK | Free |
| Baostock | A-share | Free |
| Yahoo Finance | US/HK/International | Free |
| Finnhub | US | Optional |
| CCXT | Crypto | Exchange API |
| FRED | US Macro | Optional |
| Edgar | SEC Filings | Free |

## Important Files

- `src/server/mcp/registry.py`: Tool group registration (enable/disable tools)
- `src/server/core/dependencies.py`: DI container configuration
- `src/server/core/bootstrap.py`: Connection/adapter initialization
- `src/server/config/routing_policy.json`: Provider routing rules
- `src/server/domain/market_gateway.py`: Unified market data gateway
- `src/server/domain/adapter_manager.py`: Multi-source orchestration
