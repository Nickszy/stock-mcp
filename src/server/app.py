# src/server/app.py
"""
Main application entry point.

This module creates a hybrid application that supports both:
- RESTful API (FastAPI) for standard HTTP JSON API calls
- MCP Protocol (Streamable HTTP) for AI Agent integration

Architecture:
- /api/v1/*  -> RESTful API endpoints
- /mcp       -> MCP protocol endpoint (JSON-RPC 2.0)
- /health    -> Health check endpoint
- /docs      -> OpenAPI documentation (Swagger UI)
- /redoc     -> ReDoc documentation
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from src.server.mcp.server import create_mcp_server
from src.server.mcp.registry import get_enabled_tool_count
from src.server.core.bootstrap import init_adapters
from src.server.domain.symbols.errors import SymbolResolutionError
from src.server.core.health import router as health_router
from src.server.api.routes import (
    market_data_router,
    filings_router,
    news_router,
    fundamental_router,
    money_flow_router,
    fact_pack_router,
    fund_router,
    etf_router,
    index_router,
    quantitative_router,
    us_market_router,
    corporate_action_router,
    preview_router,
    sector_research_router,
    cn_macro_router,
    fixed_income_router,
    research_reports_router,
    commodities_router,
    options_router,
    sentiment_router,
    hk_market_router,
)
from src.server.utils.logger import logger
from src.server.middleware import JsonArgumentsFixMiddleware, MarkdownNegotiationMiddleware


def create_app():
    """Create the hybrid application: FastAPI + MCP Protocol

    Returns:
        FastAPI: Application instance with both RESTful API and MCP support
    """

    # 1. Create MCP server instance early so we can integrate its lifespan
    mcp_server = None
    mcp_app = None
    try:
        mcp_server = create_mcp_server()
        mcp_app = mcp_server.streamable_http_app(path="/")
    except Exception as e:
        logger.error(f"Failed to create MCP server: {e}", exc_info=True)
        logger.warning("⚠️  MCP server creation failed, MCP features will be disabled")

    # 2. Define application lifespan - manages connections and adapters
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan - manages connections and adapters."""
        # Startup
        logger.info("🚀 Starting application")

        # Initialize shared dependencies (connections + adapters)
        await init_adapters()

        # Integrate MCP lifespan if available
        if mcp_app:
            logger.info("🔄 Initializing MCP server lifespan...")
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        else:
            yield

        # Shutdown
        logger.info("🛑 Shutting down application")

    # 3. Create FastAPI application
    app = FastAPI(
        title="Stock Tool Server",
        description="""
        ## 🚀 金融数据服务器
        
        提供两种协议支持,满足不同场景的集成需求:
        
        ### 📡 协议支持
        
        #### 1. RESTful API (推荐用于 Java/Spring 集成)
        - **Base URL**: `/api/v1`
        - **文档**: [Swagger UI](/docs) | [ReDoc](/redoc)
        - **特点**: 标准 HTTP JSON API,易于集成
        
        #### 2. MCP Protocol (用于 AI Agent 集成)
        - **Endpoint**: `/mcp`
        - **协议**: Streamable HTTP (JSON-RPC 2.0)
        - **用途**: Claude Desktop, Cursor 等 AI Agent
        
        ### 🎯 核心功能
        
        - 📊 **批量价格查询**: 一次请求获取多个资产的实时价格
        - 📈 **技术指标计算**: SMA, RSI, MACD, 布林带等 20+ 指标
        - 🔍 **资产搜索**: 支持股票、加密货币、ETF 搜索
        - 📰 **新闻与研究**: 获取市场新闻和深度研究报告
        
        ### 🌍 支持的市场
        
        - **美股**: NASDAQ, NYSE (通过 Yahoo Finance, Finnhub)
        - **A股**: 上交所, 深交所 (通过 Akshare, Tushare, Baostock)
        - **加密货币**: Binance, OKX 等 (通过 CCXT)
        
        ### 📖 快速开始
        
        **RESTful API 示例:**
        ```bash
        # 批量获取价格
        curl -X POST "http://localhost:9898/api/v1/market/prices/batch" \\
          -H "Content-Type: application/json" \\
          -d '{"tickers": ["BINANCE:BTCUSDT", "NASDAQ:AAPL"]}'
        
        # 计算技术指标
        curl -X POST "http://localhost:9898/api/v1/market/indicators/calculate" \\
          -H "Content-Type: application/json" \\
          -d '{"symbol": "BINANCE:BTCUSDT", "period": "30d", "interval": "1d"}'
        ```
        
        **MCP Protocol 示例:**
        ```bash
        curl -X POST "http://localhost:9898/mcp" \\
          -H "Content-Type: application/json" \\
          -d '{
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
              "name": "get_multiple_prices",
              "arguments": {"tickers": ["BINANCE:BTCUSDT"]}
            },
            "id": "1"
          }'
        ```
        """,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # 4. Add CORS middleware (允许跨域请求)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    logger.info("✅ CORS middleware configured")

    # Add Markdown content negotiation middleware for all /api/ endpoints
    app.add_middleware(MarkdownNegotiationMiddleware)
    logger.info("✅ Markdown content negotiation middleware configured")

    # Add JSON arguments fix middleware for MCP clients like OpenClaw
    app.add_middleware(JsonArgumentsFixMiddleware)
    logger.info("✅ JSON arguments fix middleware configured")

    # Global exception handler for symbol resolution
    @app.exception_handler(SymbolResolutionError)
    async def symbol_resolution_exception_handler(_, exc: SymbolResolutionError):
        return JSONResponse(
            status_code=400,
            content={"error": exc.to_dict()},
        )

    # 5. Register RESTful API routes
    app.include_router(health_router)
    app.include_router(market_data_router)
    app.include_router(filings_router, prefix="/api/v1")
    app.include_router(news_router)
    app.include_router(fundamental_router)
    app.include_router(money_flow_router)
    app.include_router(fact_pack_router)
    app.include_router(fund_router)
    app.include_router(etf_router)
    app.include_router(index_router)
    app.include_router(quantitative_router)
    app.include_router(us_market_router)
    app.include_router(corporate_action_router)
    app.include_router(preview_router)
    app.include_router(sector_research_router)
    app.include_router(cn_macro_router)
    app.include_router(fixed_income_router)
    app.include_router(research_reports_router)
    app.include_router(commodities_router)
    app.include_router(options_router)
    app.include_router(sentiment_router)
    app.include_router(hk_market_router)

    logger.info("✅ RESTful API routes registered")
    logger.info("   - Health check: /health")
    logger.info("   - Market data: /api/v1/market/*")
    logger.info("   - Filings: /api/v1/filings/*")
    logger.info("   - News: /api/v1/news/*")
    logger.info("   - Fundamental: /api/v1/fundamental/*")
    logger.info("   - Money Flow: /api/v1/money-flow/*")
    logger.info("   - Fact Pack: /api/v1/fact-pack/*")
    logger.info("   - Fund Data: /api/v1/fund/*")
    logger.info("   - ETF Data: /api/v1/etf/*")
    logger.info("   - Index Data: /api/v1/index/*")
    logger.info("   - Quantitative: /api/v1/quant/*")
    logger.info("   - US Market: /api/v1/us/*")
    logger.info("   - Corporate Action: /api/v1/corporate-action/*")
    logger.info("   - Sector Research: /api/v1/sector-research/*")
    logger.info("   - CN Macro: /api/v1/cn-macro/*")
    logger.info("   - Fixed Income: /api/v1/fixed-income/*")
    logger.info("   - Research Reports: /api/v1/research-reports/*")
    logger.info("   - Commodities: /api/v1/commodities/*")
    logger.info("   - Options: /api/v1/options/*")
    logger.info("   - Sentiment: /api/v1/sentiment/*")
    logger.info("   - HK Market: /api/v1/hk/*")

    # 6. Mount MCP protocol endpoint
    if mcp_app:
        try:
            app.mount("/mcp", mcp_app)
            logger.info("✅ MCP protocol endpoint mounted at /mcp")
        except Exception as e:
            logger.error(f"Failed to mount MCP endpoint: {e}", exc_info=True)
            logger.warning("⚠️  MCP endpoint not available, only RESTful API will work")

    # 7. Root "/" endpoint is handled by preview_router (HTML workbench page)
    # Service metadata moved to /api/meta (also in preview_router)

    logger.info("=" * 70)
    logger.info("🚀 Stock Tool Server Initialized")
    logger.info("=" * 70)
    logger.info("📡 Protocols:")
    logger.info("   - RESTful API: http://localhost:9898/api/v1")
    logger.info("   - MCP Protocol: http://localhost:9898/mcp")
    logger.info("📖 Documentation:")
    logger.info("   - Scalar API Docs: http://localhost:9898/api-docs")
    logger.info("   - Swagger UI: http://localhost:9898/docs")
    logger.info("   - ReDoc: http://localhost:9898/redoc")
    logger.info("   - Preview Workbench: http://localhost:9898/")
    logger.info("💚 Health Check: http://localhost:9898/health")
    logger.info("=" * 70)

    return app


# Create the app instance
app = create_app()
