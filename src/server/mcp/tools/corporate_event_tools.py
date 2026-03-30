# src/server/mcp/tools/corporate_event_tools.py
"""MCP tools for A-share corporate event calendar (COL-226).

Exposes adapter-level corporate event data as unified MCP tools:
  - get_earnings_calendar: 财报披露预约日历
  - get_dividend_calendar: 个股分红送股日历
  - get_restricted_release_calendar: 限售解禁日历
  - get_stock_repurchase: 股票回购
  - get_block_trade: 大宗交易
"""

import time
from typing import Any, Dict

from fastmcp import FastMCP, Context

from src.server.core.dependencies import Container
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_standard_artifact_response,
)


def register_corporate_event_tools(mcp: FastMCP):
    """Register corporate event calendar MCP tools."""

    # ------------------------------------------------------------------
    # get_earnings_calendar — 财报披露预约日历
    # ------------------------------------------------------------------
    @mcp.tool(tags={"corporate-event", "earnings"})
    async def get_earnings_calendar(
        market: str = "沪深京",
        period: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股财报披露预约日历.

        WHEN TO USE: 用户问"财报季有哪些公司披露"、"什么时候出年报/季报".
        CONCEPT: 财报披露日历展示各公司预约的财报披露时间, 是跟踪业绩发布节奏的关键工具.
        DIFFERENTIATION: 日历视图覆盖全市场; 个股分红用 get_dividend_calendar;
        限售解禁用 get_restricted_release_calendar.
        next_recommended_tools: get_dividend_calendar -> get_restricted_release_calendar

        Typical use cases:
        - "2024年报哪些公司预约披露？"
        - "查看科创板最近财报披露日历"
        - "下周有哪些公司出季报？"

        Args:
            market: 市场范围 {"沪深京", "深市", "深主板", "创业板",
                     "沪市", "沪主板", "科创板", "北交所"}, 默认"沪深京"
            period: 报告期 (如 "2024年报", "2025一季", "2025半年报", "2025三季"),
                    为空自动推断当前报告期
            ctx: FastMCP Context.

        Returns:
            财报披露预约日历数据
        """
        if ctx:
            await ctx.info(f"获取财报披露日历: market={market}, period={period}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_earnings_calendar", market=market, period=period)

            gateway = Container.market_gateway()
            result = await gateway.get_earnings_calendar(market=market, period=period)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            resolved_period = result.get("period", period)

            summary = f"财报披露日历({resolved_period}): {market} 共{total}家 (耗时 {elapsed:.1f}s)"

            md = f"## 财报披露预约日历 - {resolved_period}\n\n"
            md += f"**市场**: {market} | **公司数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 代码 | 名称 | 首次预约 | 变更日期 | 实际披露 |\n"
            md += "|------|------|---------|----------|----------|\n"
            for r in data[:50]:
                first = r.get("first_scheduled") or "-"
                actual = r.get("actual_date") or "-"
                change = r.get("first_change") or "-"
                md += (
                    f"| {r.get('stock_code', '')} "
                    f"| {r.get('stock_name', '')} "
                    f"| {first} "
                    f"| {change} "
                    f"| {actual} |\n"
                )
            if total > 50:
                md += f"\n*... 还有 {total - 50} 家*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"财报披露日历: {resolved_period}",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_earnings_calendar failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取财报披露日历失败: {e}",
                component_type=ComponentType.TABLE,
                name="财报日历错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取财报披露日历失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_dividend_calendar — 个股分红送股日历
    # ------------------------------------------------------------------
    @mcp.tool(tags={"corporate-event", "dividend"})
    async def get_dividend_calendar(
        symbol: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取个股分红送股日历 (巨潮资讯数据).

        WHEN TO USE: 用户问"这只股票什么时候分红"、"历史分红记录"、"除权除息日期".
        CONCEPT: 展示个股完整的分红送股时间线, 包括实施方案、除权日、派息日等关键日期.
        DIFFERENTIATION: 个股分红日历(含除权/派息日期); 财报日历用 get_earnings_calendar;
        回购用 get_stock_repurchase.
        next_recommended_tools: get_earnings_calendar -> get_stock_repurchase

        Typical use cases:
        - "600519贵州茅台历史分红记录"
        - "查看某只股票的除权除息日"
        - "最近几年这家公司分了多少红？"

        Args:
            symbol: 股票代码 (如 600519), 必填
            ctx: FastMCP Context.

        Returns:
            分红送股日历数据
        """
        if not symbol:
            return create_standard_artifact_response(
                summary="需要提供股票代码",
                component_type=ComponentType.TABLE,
                name="分红日历",
                data={"error": "symbol参数必填"},
                source="akshare",
                description="请提供股票代码查询分红日历",
            )

        if ctx:
            await ctx.info(f"获取分红送股日历: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_dividend_calendar", symbol=symbol)

            gateway = Container.market_gateway()
            result = await gateway.get_dividend_calendar(symbol=symbol)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)

            summary = f"分红送股日历: {symbol} 共{total}期 (耗时 {elapsed:.1f}s)"

            md = f"## 分红送股日历 - {symbol}\n\n"
            md += f"**记录数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 报告期 | 分红类型 | 送股 | 转增 | 派息 | 登记日 | 除权日 | 派息日 |\n"
            md += "|--------|---------|------|------|------|--------|--------|--------|\n"
            for r in data[:30]:
                md += (
                    f"| {r.get('report_period', '-')} "
                    f"| {r.get('dividend_type', '-')} "
                    f"| {r.get('bonus_share_ratio', '-')} "
                    f"| {r.get('conversion_ratio', '-')} "
                    f"| {r.get('cash_div_ratio', '-')} "
                    f"| {r.get('record_date', '-')} "
                    f"| {r.get('ex_date', '-')} "
                    f"| {r.get('pay_date', '-')} |\n"
                )
            if total > 30:
                md += f"\n*... 还有 {total - 30} 期*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"分红送股: {symbol}",
                data=data,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_dividend_calendar failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取分红日历失败: {e}",
                component_type=ComponentType.TABLE,
                name="分红日历错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取分红日历失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_restricted_release_calendar — 限售解禁日历
    # ------------------------------------------------------------------
    @mcp.tool(tags={"corporate-event", "restricted-release"})
    async def get_restricted_release_calendar(
        symbol: str = "",
        days: int = 90,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股限售股解禁日历 (解禁压力).

        WHEN TO USE: 用户问"最近有哪些解禁"、"解禁压力"、"限售股释放".
        CONCEPT: 限售股解禁是重要的供给端事件, 大量解禁可能带来卖压.
        包含近期解禁概览和解禁排队日历.
        DIFFERENTIATION: 解禁日历; 回购用 get_stock_repurchase;
        大宗交易用 get_block_trade.
        next_recommended_tools: get_stock_repurchase -> get_block_trade

        Typical use cases:
        - "最近一个月有哪些股票限售解禁？"
        - "查看某只股票的解禁安排"
        - "未来90天解禁压力最大的股票"

        Args:
            symbol: 股票代码 (可选, 为空返回全市场)
            days: 查询天数 (默认90天)
            ctx: FastMCP Context.

        Returns:
            限售解禁日历数据
        """
        if ctx:
            await ctx.info(f"获取限售解禁日历: symbol={symbol}, days={days}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_restricted_release_calendar", symbol=symbol, days=days)

            gateway = Container.market_gateway()
            result = await gateway.get_restricted_release(symbol=symbol, days=days)

            elapsed = time.perf_counter() - t0
            summary_data = result.get("data", {}).get("summary", [])
            queue_data = result.get("data", {}).get("queue", [])

            summary = (
                f"限售解禁日历: 概览{len(summary_data)}条 + 排队{len(queue_data)}条"
                f" (耗时 {elapsed:.1f}s)"
            )

            md = f"## 限售股解禁日历\n\n"
            md += f"**概览**: {len(summary_data)}条 | **排队**: {len(queue_data)}条"
            md += f" | **耗时**: {elapsed:.1f}s\n\n"

            if queue_data:
                md += "### 解禁排队\n\n"
                md += "| 代码 | 名称 | 解禁日期 | 解禁数量(万股) | 解禁市值(万元) |\n"
                md += "|------|------|---------|--------------|---------------|\n"
                for r in queue_data[:30]:
                    code = r.get("股票代码", "")
                    name = r.get("股票简称", "")
                    date = r.get("解禁日期", "-")
                    qty = r.get("解禁数量", "-")
                    val = r.get("解禁市值", "-")
                    md += f"| {code} | {name} | {date} | {qty} | {val} |\n"
                if len(queue_data) > 30:
                    md += f"\n*... 还有 {len(queue_data) - 30} 条*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"限售解禁日历",
                data={
                    "summary": summary_data[:50],
                    "queue": queue_data[:100],
                },
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_restricted_release_calendar failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取限售解禁日历失败: {e}",
                component_type=ComponentType.TABLE,
                name="解禁日历错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取限售解禁日历失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_stock_repurchase — 股票回购
    # ------------------------------------------------------------------
    @mcp.tool(tags={"corporate-event", "repurchase"})
    async def get_stock_repurchase(
        symbol: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股股票回购数据 (公司行为).

        WHEN TO USE: 用户问"最近有哪些公司回购"、"回购力度"、"公司自家买股票".
        CONCEPT: 股票回购是公司传递股价被低估信号的重要行为, 也是减少流通盘的手段.
        DIFFERENTIATION: 回购数据; 解禁用 get_restricted_release_calendar;
        大宗交易用 get_block_trade.
        next_recommended_tools: get_restricted_release_calendar -> get_block_trade

        Typical use cases:
        - "最近有哪些公司回购？"
        - "查看某只股票的回购计划"
        - "回购金额最大的公司"

        Args:
            symbol: 股票代码 (可选, 为空返回全市场)
            ctx: FastMCP Context.

        Returns:
            股票回购数据
        """
        if ctx:
            await ctx.info(f"获取股票回购数据: symbol={symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_stock_repurchase", symbol=symbol)

            gateway = Container.market_gateway()
            result = await gateway.get_repurchase_info(symbol=symbol)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", len(data))

            summary = f"股票回购: {symbol or '全市场'} 共{total}条 (耗时 {elapsed:.1f}s)"

            md = f"## 股票回购 {'- ' + symbol if symbol else '- 全市场'}\n\n"
            md += f"**记录数**: {total} | **耗时**: {elapsed:.1f}s\n\n"

            if data:
                md += "| 代码 | 名称 | 回购进度 | 计划金额 | 已回购金额 | 实施比例 |\n"
                md += "|------|------|---------|---------|-----------|----------|\n"
                for r in data[:30]:
                    code = r.get("股票代码", "")
                    name = r.get("股票简称", "")
                    progress = r.get("回购进度", "-")
                    plan_amount = r.get("计划金额", "-")
                    done_amount = r.get("已回购金额", "-")
                    ratio = r.get("实施比例", "-")
                    md += (
                        f"| {code} | {name} | {progress} "
                        f"| {plan_amount} | {done_amount} | {ratio} |\n"
                    )
                if total > 30:
                    md += f"\n*... 还有 {total - 30} 条*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"股票回购: {symbol or '全市场'}",
                data=data[:100],
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_stock_repurchase failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取股票回购数据失败: {e}",
                component_type=ComponentType.TABLE,
                name="回购数据错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取股票回购数据失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_block_trade — 大宗交易
    # ------------------------------------------------------------------
    @mcp.tool(tags={"corporate-event", "block-trade"})
    async def get_block_trade(
        start_date: str = "",
        end_date: str = "",
        days: int = 10,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股大宗交易明细 (机构/大股东大宗买卖).

        WHEN TO USE: 用户问"大宗交易"、"机构大宗买卖"、"折价率".
        CONCEPT: 大宗交易反映机构和大股东的大额买卖行为, 折价率是重要观察指标.
        DIFFERENTIATION: 大宗交易明细; 回购用 get_stock_repurchase;
        解禁用 get_restricted_release_calendar.
        next_recommended_tools: get_stock_repurchase -> get_restricted_release_calendar

        Typical use cases:
        - "最近10天大宗交易明细"
        - "查看某只股票的大宗交易记录"
        - "最近大宗交易折价率最高的有哪些？"

        Args:
            start_date: 开始日期 YYYYMMDD (可选)
            end_date: 结束日期 YYYYMMDD (可选)
            days: 最近N天 (默认10, 当start_date为空时使用)
            ctx: FastMCP Context.

        Returns:
            大宗交易明细数据
        """
        if ctx:
            await ctx.info(f"获取大宗交易: days={days}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_block_trade", days=days)

            gateway = Container.market_gateway()
            result = await gateway.get_block_trade(
                start_date=start_date, end_date=end_date, days=days,
            )

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", len(data))
            resp_start = result.get("start_date", "")
            resp_end = result.get("end_date", "")

            summary = f"大宗交易({resp_start}~{resp_end}): 共{total}笔 (耗时 {elapsed:.1f}s)"

            md = f"## 大宗交易明细 ({resp_start} ~ {resp_end})\n\n"
            md += f"**成交笔数**: {total} | **耗时**: {elapsed:.1f}s\n\n"

            if data:
                md += "| 日期 | 代码 | 名称 | 成交价 | 收盘价 | 折溢价率 | 成交量 | 成交额 |\n"
                md += "|------|------|------|--------|--------|---------|--------|--------|\n"
                for r in data[:40]:
                    date_val = r.get("交易日期", "-")
                    code = r.get("证券代码", "")
                    name = r.get("证券简称", "")
                    price = r.get("成交价", "-")
                    close = r.get("收盘价", "-")
                    premium = r.get("折溢价率", "-")
                    vol = r.get("成交量", "-")
                    amount = r.get("成交额", "-")
                    md += (
                        f"| {date_val} | {code} | {name} "
                        f"| {price} | {close} | {premium} | {vol} | {amount} |\n"
                    )
                if total > 40:
                    md += f"\n*... 还有 {total - 40} 笔*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"大宗交易: {resp_start}~{resp_end}",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_block_trade failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取大宗交易数据失败: {e}",
                component_type=ComponentType.TABLE,
                name="大宗交易错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取大宗交易数据失败: {e}",
            )
