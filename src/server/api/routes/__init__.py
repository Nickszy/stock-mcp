# src/server/api/routes/__init__.py
"""API routes."""

from .market_data import router as market_data_router
from .filings import router as filings_router
from .news import router as news_router
from .fundamental import router as fundamental_router
from .money_flow import router as money_flow_router
from .fact_pack import router as fact_pack_router
from .fund import router as fund_router
from .etf import router as etf_router
from .index import router as index_router
from .quantitative import router as quantitative_router
from .us_market import router as us_market_router
from .corporate_action import router as corporate_action_router
from .preview import router as preview_router
from .sector_research import router as sector_research_router
from .cn_macro import router as cn_macro_router
from .fixed_income import router as fixed_income_router
from .research_reports import router as research_reports_router
from .commodities import router as commodities_router
from .options import router as options_router
from .sentiment import router as sentiment_router

__all__ = [
    "market_data_router",
    "filings_router",
    "news_router",
    "fundamental_router",
    "money_flow_router",
    "fact_pack_router",
    "fund_router",
    "etf_router",
    "index_router",
    "quantitative_router",
    "us_market_router",
    "corporate_action_router",
    "preview_router",
    "sector_research_router",
    "cn_macro_router",
    "fixed_income_router",
    "research_reports_router",
    "commodities_router",
    "options_router",
    "sentiment_router",
]
