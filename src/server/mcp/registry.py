# src/server/mcp/registry.py
"""Central MCP tool registry.

Keeps tool registration and metadata in one place to avoid drift between
server setup, docs, and helper functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

from fastmcp import FastMCP

from src.server.mcp.tools.fundamental_tools import register_fundamental_tools
from src.server.mcp.tools.asset_tools import register_asset_tools
from src.server.mcp.tools.technical_tools import register_technical_tools
from src.server.mcp.tools.money_flow_tools import register_money_flow_tools
from src.server.mcp.tools.filings_tools import register_filings_tools
from src.server.mcp.tools.trade_tools import register_trade_tools
from src.server.mcp.tools.chunking_tools import register_chunking_tools
from src.server.mcp.tools.news_tools import register_news_tools
from src.server.mcp.tools.us_fundamental_tools import register_us_fundamental_tools
from src.server.mcp.tools.us_technical_tools import register_us_technical_tools
from src.server.mcp.tools.us_sector_tools import register_us_sector_tools
from src.server.mcp.tools.us_macro_tools import register_us_macro_tools
from src.server.mcp.tools.sector_research_tools import register_sector_research_tools
from src.server.mcp.tools.quantitative_tools import register_quantitative_tools
from src.server.mcp.tools.fund_tools import register_fund_tools
from src.server.mcp.tools.index_tools import register_index_tools
from src.server.mcp.tools.etf_tools import register_etf_tools
from src.server.mcp.tools.factor_tools import register_factor_tools
from src.server.mcp.tools.corporate_action_tools import register_corporate_action_tools
from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
from src.server.mcp.tools.cn_macro_tools import register_cn_macro_tools
from src.server.mcp.tools.fixed_income_tools import register_fixed_income_tools
from src.server.mcp.tools.research_report_tools import register_research_report_tools
from src.server.mcp.tools.commodity_tools import register_commodity_tools
from src.server.mcp.tools.option_tools import register_option_tools
from src.server.mcp.tools.sentiment_tools import register_sentiment_tools
from src.server.mcp.tools.hk_market_tools import register_hk_market_tools
from src.server.mcp.tools.hk_connect_tools import register_hk_connect_tools
from src.server.mcp.tools.canonical_data_tools import register_canonical_data_tools
from src.server.mcp.tools.entity_tools import register_entity_tools
from src.server.mcp.tools.financial_analytics_tools import register_financial_analytics_tools
from src.server.mcp.tools.stock_comparison_tools import register_stock_comparison_tools
from src.server.mcp.tools.corporate_event_tools import register_corporate_event_tools
from src.server.mcp.tools.shareholder_behavior_tools import register_shareholder_behavior_tools


@dataclass(frozen=True)
class ToolGroup:
    name: str
    register: Callable[[FastMCP], None]
    enabled: bool
    description: str
    count: int


TOOL_GROUPS: List[ToolGroup] = [
    ToolGroup(
        name="fundamental",
        register=register_fundamental_tools,
        enabled=True,
        description="基本面分析 (财务报表/报告/主营构成/股东/分红/业绩预测/估值/盈利预测/财务比率)",
        count=9,
    ),
    ToolGroup(
        name="asset",
        register=register_asset_tools,
        enabled=True,
        description="资产搜索与管理",
        count=4,
    ),
    ToolGroup(
        name="technical",
        register=register_technical_tools,
        enabled=True,
        description="技术分析 (技术指标/确定性信号)",
        count=2,
    ),
    ToolGroup(
        name="money-flow",
        register=register_money_flow_tools,
        enabled=True,
        description="资金流向",
        count=42,
    ),
    ToolGroup(
        name="filings",
        register=register_filings_tools,
        enabled=True,
        description="公告文件",
        count=8,
    ),
    ToolGroup(
        name="trade",
        register=register_trade_tools,
        enabled=False,
        description="交易执行",
        count=2,
    ),
    ToolGroup(
        name="chunking",
        register=register_chunking_tools,
        enabled=True,
        description="文档切片",
        count=1,
    ),
    ToolGroup(
        name="news",
        register=register_news_tools,
        enabled=False,
        description="新闻与检索",
        count=1,
    ),
    # ---- 美股工具集 (ValueCell 竞品对齐) ----
    ToolGroup(
        name="us-fundamental",
        register=register_us_fundamental_tools,
        enabled=True,
        description="美股基本面 (公司概况/EPS/现金流/估值/机构持仓/分析师评级/收入构成/内部人交易/做空数据/财务健康)",
        count=10,
    ),
    ToolGroup(
        name="us-technical",
        register=register_us_technical_tools,
        enabled=True,
        description="美股技术分析 (指标/量价/K线/综合摘要/市场概览)",
        count=5,
    ),
    ToolGroup(
        name="us-sector",
        register=register_us_sector_tools,
        enabled=True,
        description="美股行业ETF分析",
        count=1,
    ),
    ToolGroup(
        name="us-macro",
        register=register_us_macro_tools,
        enabled=True,
        description="美股宏观分析 (GDP/通胀就业/利率)",
        count=3,
    ),
    ToolGroup(
        name="sector-research",
        register=register_sector_research_tools,
        enabled=True,
        description="行业研究编排（scope/universe/peer/evidence）",
        count=7,
    ),
    ToolGroup(
        name="quantitative",
        register=register_quantitative_tools,
        enabled=True,
        description="A股量化分析 (多条件选股/行业排名/概念排名)",
        count=3,
    ),
    ToolGroup(
        name="fund",
        register=register_fund_tools,
        enabled=True,
        description="基金数据 (搜索/详情/排行/经理/估值/业绩/规模)",
        count=7,
    ),
    ToolGroup(
        name="index",
        register=register_index_tools,
        enabled=True,
        description="A股指数数据 (指数列表/PE-PB估值/行情历史)",
        count=3,
    ),
    ToolGroup(
        name="etf",
        register=register_etf_tools,
        enabled=True,
        description="A股ETF数据 (列表/详情/行情历史)",
        count=3,
    ),
    ToolGroup(
        name="factor",
        register=register_factor_tools,
        enabled=True,
        description="量化因子分析 (个股因子/相关性矩阵/全市场因子排名)",
        count=3,
    ),
    ToolGroup(
        name="corporate-action",
        register=register_corporate_action_tools,
        enabled=True,
        description="A股企业行为数据 (股东增减持明细/IPO日历/IPO详情)",
        count=3,
    ),
    ToolGroup(
        name="fact-pack",
        register=register_fact_pack_tools,
        enabled=True,
        description="事实包聚合 (股票/基金/行情/美股/ETF/指数/行业事实包)",
        count=7,
    ),
    ToolGroup(
        name="cn-macro",
        register=register_cn_macro_tools,
        enabled=True,
        description="中国宏观经济数据 (GDP/CPI/PPI/PMI/M2/利率/贸易差额/社融/宏观概览)",
        count=9,
    ),
    ToolGroup(
        name="fixed-income",
        register=register_fixed_income_tools,
        enabled=True,
        description="固定收益/债券研究 (收益率曲线/可转债列表/可转债历史/可转债详情/信用利差/回购利率/同业拆借/债券发行/固收概览)",
        count=9,
    ),
    ToolGroup(
        name="research-report",
        register=register_research_report_tools,
        enabled=True,
        description="研报数据 (研报搜索/个股研报 — 接入news-mcp)",
        count=2,
    ),
    ToolGroup(
        name="commodity",
        register=register_commodity_tools,
        enabled=True,
        description="大宗商品 (黄金/白银/原油/铜/工业金属/商品概览)",
        count=6,
    ),
    ToolGroup(
        name="option",
        register=register_option_tools,
        enabled=True,
        description="期权数据 (合约列表/Greeks/历史行情)",
        count=3,
    ),
    ToolGroup(
        name="sentiment",
        register=register_sentiment_tools,
        enabled=True,
        description="市场情绪/QVIX (50ETF/300ETF/1000/CYB/总览)",
        count=5,
    ),
    ToolGroup(
        name="hk-market",
        register=register_hk_market_tools,
        enabled=True,
        description="港股市场 (全市场/热度榜/主板/总览)",
        count=4,
    ),
    ToolGroup(
        name="hk-connect",
        register=register_hk_connect_tools,
        enabled=True,
        description="港股通/南向资金 (成分股/资金流/持股排行/总览)",
        count=4,
    ),
    # ---- AI投研增强: Canonical数据桥接 + 实体知识图谱 + 财务分析 ----
    ToolGroup(
        name="canonical-data",
        register=register_canonical_data_tools,
        enabled=True,
        description="Canonical数据桥接 (已验证财报/已验证行情/数据中台状态)",
        count=3,
    ),
    ToolGroup(
        name="entity",
        register=register_entity_tools,
        enabled=True,
        description="实体知识图谱 (实体解析/实体详情/同行发现/实体搜索)",
        count=4,
    ),
    ToolGroup(
        name="financial-analytics",
        register=register_financial_analytics_tools,
        enabled=True,
        description="AI财务分析 (增长率分析/财务健康评分)",
        count=2,
    ),
    ToolGroup(
        name="stock-comparison",
        register=register_stock_comparison_tools,
        enabled=True,
        description="多股对比 (2-5只股票横向对比)",
        count=1,
    ),
    ToolGroup(
        name="corporate-event",
        register=register_corporate_event_tools,
        enabled=True,
        description="企业事件日历 (财报披露/分红送股/限售解禁/回购/大宗交易)",
        count=5,
    ),
    ToolGroup(
        name="shareholder-behavior",
        register=register_shareholder_behavior_tools,
        enabled=True,
        description="股东行为/风险信号 (机构调研/股票质押)",
        count=2,
    ),
]


def register_tools(mcp: FastMCP) -> None:
    """Register all enabled tools with the MCP instance."""
    for group in TOOL_GROUPS:
        if group.enabled:
            group.register(mcp)


def get_tool_group_info() -> Dict[str, Dict[str, str | int | bool]]:
    """Return tool group metadata for server info endpoints."""
    info: Dict[str, Dict[str, str | int | bool]] = {}
    for group in TOOL_GROUPS:
        info[group.name] = {
            "count": group.count if group.enabled else 0,
            "description": group.description,
            "enabled": group.enabled,
        }
    return info


def get_enabled_tool_count() -> int:
    return sum(group.count for group in TOOL_GROUPS if group.enabled)
