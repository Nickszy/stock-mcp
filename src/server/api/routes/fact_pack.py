# src/server/api/routes/fact_pack.py
"""Fact pack API routes.

Provides RESTful HTTP endpoints for aggregated fact pack data:
- Stock fact pack (COL-148)
- Fund fact pack (COL-150)
- Market fact pack (COL-152)
- US Stock fact pack (COL-164)
- ETF fact pack (COL-170)
- Index fact pack (COL-171)

Supports content negotiation:
  - JSON (default): standard REST envelope
  - Markdown: ?format=markdown or Accept: text/markdown
"""

from fastapi import APIRouter, HTTPException, Header, Query, status
from fastapi.responses import Response
from typing import Any, Dict, Optional

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response, maybe_markdown_response

router = APIRouter(prefix="/api/v1/fact-pack")


def _wants_md(fmt: str, accept: str) -> bool:
    return fmt.lower() == "markdown" or "text/markdown" in accept


def _safe_num(value: Any) -> Optional[float]:
    """Convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        f = float(value)
        return f if f == f else None  # NaN check
    except (ValueError, TypeError):
        return None


def _fuzzy_get(d: Dict[str, Any], *keys: str) -> Any:
    """Get value from dict trying multiple key names (exact match first).

    Fallback: contains-based matching for the first key, but only when
    target is >= 3 chars to avoid false positives (e.g. "pe" matching "dv_ratio").
    """
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    # Fallback: contains-based matching for the first key (min 3 chars)
    target = keys[0] if keys else ""
    if len(target) < 3:
        return None
    for dk, dv in d.items():
        if target in str(dk) and dv is not None:
            return dv
    return None


def _extract_valuation(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Extract valuation facts from market.valuation (adapter's _get_valuation_raw).

    Handles field names from akshare's stock_a_indicator_lg which returns
    columns like: pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, total_mv, etc.
    """
    market = facts.get("market", {})
    raw = dict(market) if isinstance(market, dict) and ("pe" in market or "pe_ttm" in market) else {}
    if not raw:
        val = market.get("valuation", {}) if isinstance(market, dict) else {}
        raw.update(val)
    return {
        "pe_ttm": _safe_num(_fuzzy_get(raw, "pe_ttm", "pe", "市盈率-动态", "滚动市盈率")),
        "pb": _safe_num(_fuzzy_get(raw, "pb", "市净率")),
        "ps_ttm": _safe_num(_fuzzy_get(raw, "ps_ttm", "ps", "市销率")),
        "peg": _safe_num(_fuzzy_get(raw, "peg")),
        "pe_percentile": _safe_num(_fuzzy_get(raw, "pe_percentile")),
        "dv_ratio": _safe_num(_fuzzy_get(raw, "dv_ratio", "股息率", "股息率(%)")),
    }


def _extract_profitability(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Extract profitability facts from financial.financial_indicators.

    Handles multiple akshare column name variants:
    - 净资产收益率(%) / roe
    - 净利率(%) / 销售净利率(%) / net_margin
    - 毛利率(%) / 销售毛利率(%) / gross_margin
    - YoY growth from income statement when indicators lack it
    """
    financial = facts.get("financial", {}) or {}
    indicators = financial.get("financial_indicators")

    # financial_indicators is a list of dicts from akshare; use latest entry
    if isinstance(indicators, list) and indicators:
        latest = indicators[-1] if isinstance(indicators[-1], dict) else {}
    elif isinstance(indicators, dict):
        latest = indicators
    else:
        latest = {}

    # ROE — akshare uses "净资产收益率(%)" or "加权净资产收益率(%)"
    roe = _safe_num(
        _fuzzy_get(latest, "净资产收益率(%)", "加权净资产收益率(%)", "roe", "净资产收益率")
    )
    # Net margin — akshare uses "净利率(%)" not "销售净利率(%)"
    net_margin = _safe_num(
        _fuzzy_get(latest, "净利率(%)", "销售净利率(%)", "net_margin", "净利率")
    )
    # Gross margin — akshare uses "毛利率(%)" not "销售毛利率(%)"
    gross_margin = _safe_num(
        _fuzzy_get(latest, "毛利率(%)", "销售毛利率(%)", "gross_margin", "毛利率")
    )

    # YoY growth — not typically in financial_indicators, calculate from income
    revenue_yoy = None
    profit_yoy = None
    income_data = financial.get("income_statement")
    if isinstance(income_data, list) and len(income_data) >= 2:
        # income_data is sorted newest-first from stock_financial_report_sina
        cur = income_data[0] if isinstance(income_data[0], dict) else {}
        # Find year-ago entry: look for same month in previous year
        cur_date_raw = str(cur.get("报告期", cur.get("end_date", "")))
        cur_date = cur_date_raw.replace("-", "").replace("/", "")[:8]
        cur_month = cur_date[4:6]
        prev = {}
        for entry in income_data[1:]:
            if not isinstance(entry, dict):
                continue
            ed_raw = str(entry.get("报告期", entry.get("end_date", "")))
            ed = ed_raw.replace("-", "").replace("/", "")[:8]
            if ed[4:6] == cur_month:
                prev = entry
                break
        if prev:
            cur_rev = _safe_num(_fuzzy_get(cur, "营业收入", "revenue"))
            prev_rev = _safe_num(_fuzzy_get(prev, "营业收入", "revenue"))
            if cur_rev and prev_rev and prev_rev != 0:
                revenue_yoy = round((cur_rev - prev_rev) / abs(prev_rev) * 100, 2)

            cur_profit = _safe_num(_fuzzy_get(cur, "净利润", "net_income", "归属于母公司所有者的净利润"))
            prev_profit = _safe_num(_fuzzy_get(prev, "净利润", "net_income", "归属于母公司所有者的净利润"))
            if cur_profit and prev_profit and prev_profit != 0:
                profit_yoy = round((cur_profit - prev_profit) / abs(prev_profit) * 100, 2)
    # Fallback: check if indicators has YoY columns
    if revenue_yoy is None:
        revenue_yoy = _safe_num(
            _fuzzy_get(latest, "营业收入同比增长率(%)", "revenue_yoy", "营收同比增长率(%)")
        )
    if profit_yoy is None:
        profit_yoy = _safe_num(
            _fuzzy_get(latest, "净利润同比增长率(%)", "profit_yoy", "利润同比增长率(%)")
        )

    return {
        "roe": roe,
        "net_margin": net_margin,
        "gross_margin": gross_margin,
        "revenue_yoy": revenue_yoy,
        "profit_yoy": profit_yoy,
    }


def _extract_financial(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Extract financial health facts from balance sheet and cash flow.

    Handles field name variants from akshare's stock_financial_report_sina:
    - 资产总计 / total_assets
    - 负债合计 / total_liabilities
    - 经营活动产生的现金流量净额 / operating_cashflow
    """
    financial = facts.get("financial", {}) or {}
    bs = financial.get("balance_sheet")
    if isinstance(bs, list) and bs:
        latest = bs[0] if isinstance(bs[0], dict) else {}
    elif isinstance(bs, dict):
        latest = bs
    else:
        latest = {}
    cf = financial.get("cash_flow")
    if isinstance(cf, list) and cf:
        cf_latest = cf[0] if isinstance(cf[0], dict) else {}
    elif isinstance(cf, dict):
        cf_latest = cf
    else:
        cf_latest = {}
    total_assets = _safe_num(_fuzzy_get(latest, "资产总计", "total_assets"))
    total_liabilities = _safe_num(_fuzzy_get(latest, "负债合计", "total_liabilities"))
    debt_ratio = None
    if total_assets and total_liabilities and total_assets > 0:
        debt_ratio = round(total_liabilities / total_assets * 100, 2)
    return {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "debt_ratio": debt_ratio,
        "operating_cashflow": _safe_num(
            _fuzzy_get(cf_latest, "经营活动产生的现金流量净额", "operating_cashflow")
        ),
        "free_cashflow": _safe_num(
            _fuzzy_get(cf_latest, "free_cashflow", "自由现金流量净额")
        ),
    }


def _extract_shareholder(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Extract shareholder facts from governance.top10_shareholders."""
    governance = facts.get("governance", {}) or {}
    raw_holders = governance.get("top10_shareholders", [])
    holders = []
    for h in (raw_holders or [])[:10]:
        if isinstance(h, dict):
            holders.append({
                "name": _fuzzy_get(h, "holder_name", "name", "股东名称") or "",
                "ratio": _safe_num(_fuzzy_get(h, "hold_ratio", "ratio", "持股比例")),
                "change": str(_fuzzy_get(h, "change", "增减") or ""),
            })
    return {
        "top10_shareholders": holders,
        "institutional_ratio": None,
    }


def _extract_dividend(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Extract dividend facts from events.dividends."""
    events = facts.get("events", {}) or {}
    div = events.get("dividends", {})
    if not isinstance(div, dict):
        return {"dividend_yield": None, "consecutive_years": None, "payout_ratio": None}
    # Dividends may have a nested data list or direct fields
    div_data = div.get("data")
    if isinstance(div_data, list) and div_data:
        latest = div_data[0] if isinstance(div_data[0], dict) else {}
    elif isinstance(div_data, dict):
        latest = div_data
    else:
        latest = div
    return {
        "dividend_yield": _safe_num(_fuzzy_get(latest, "dividend_yield", "股息率", "股息率(%)")),
        "consecutive_years": _safe_num(_fuzzy_get(latest, "consecutive_years", "连续分红年数")),
        "payout_ratio": _safe_num(_fuzzy_get(latest, "payout_ratio", "股利支付率")),
    }


def _extract_revenue_breakdown(facts: Dict[str, Any]) -> Dict[str, Any]:
    """Extract revenue breakdown from business_structure (mainbz rows)."""
    biz = facts.get("business_structure")
    rows = []
    if isinstance(biz, dict):
        rows = biz.get("rows", biz.get("data", []))
    elif isinstance(biz, list):
        rows = biz
    by_product = []
    by_region = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        biz_type = str(r.get("分类类型") or r.get("type") or "")
        name = r.get("主营构成") or r.get("item_name") or r.get("name") or ""
        ratio = _safe_num(r.get("主营收入占比") or r.get("ratio") or r.get("占比"))
        revenue = _safe_num(r.get("主营收入") or r.get("revenue"))
        item = {"name": name, "ratio": ratio, "revenue": revenue}
        if "产品" in biz_type or "product" in biz_type.lower():
            by_product.append(item)
        elif "地区" in biz_type or "region" in biz_type.lower():
            by_region.append(item)
        else:
            by_product.append(item)
    return {"by_product": by_product[:20], "by_region": by_region[:20]}


def _extract_technical(tech_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract technical facts from calculate_technical_indicators result."""
    indicators = tech_data.get("data", {}) if isinstance(tech_data, dict) else {}
    def _last_ma(period: str) -> Optional[float]:
        series = indicators.get(period, [])
        if series and isinstance(series[-1], dict):
            return _safe_num(series[-1].get("value"))
        return None
    rsi_14 = None
    rsi_series = indicators.get("rsi14", [])
    if rsi_series and isinstance(rsi_series[-1], dict):
        rsi_14 = _safe_num(rsi_series[-1].get("value"))
    macd_data = None
    macd_series = indicators.get("macd", [])
    if macd_series and isinstance(macd_series[-1], dict):
        last = macd_series[-1]
        macd_data = {
            "dif": _safe_num(last.get("dif")),
            "dea": _safe_num(last.get("dea")),
            "macd": _safe_num(last.get("macd_bar")),
        }
    return {
        "ma5": _last_ma("ma5"),
        "ma20": _last_ma("ma20"),
        "ma60": _last_ma("ma60"),
        "rsi_14": rsi_14,
        "macd": macd_data,
    }


async def _normalize_stock_fact_pack(
    result: Dict[str, Any],
    symbol: str,
) -> Dict[str, Any]:
    """Transform adapter's internal fact-pack into the frontend FactPackResponse contract.

    Maps: security_master→entity, market.valuation→valuation, financial→profitability,
    governance→shareholder, events.dividends→dividend, business_structure→revenue_breakdown.
    Enriches price and technical via additional gateway calls.
    """
    facts = result.get("facts", {}) or {}
    entity_raw = result.get("entity", {}) or {}
    source_trace_raw = result.get("source_trace", {}) or {}
    coverage_raw = result.get("coverage", {}) or {}
    sec_master = facts.get("security_master", {}) or {}
    company_master = facts.get("company_master", {}) or {}

    # --- Entity ---
    name = sec_master.get("name") or company_master.get("company_name") or company_master.get("short_name") or symbol
    industry = company_master.get("industry", "")
    entity = {
        "symbol": symbol,
        "name": name,
        "market": "A股",
        "asset_type": entity_raw.get("type", "stock"),
        "industry": industry,
        "sector": industry,
    }

    # --- Price (async enrichment) ---
    price_facts: Dict[str, Any] = {
        "current": None, "change": None, "change_pct": None,
        "high": None, "low": None, "open": None,
        "volume": None, "amount": None, "market_cap": None,
    }
    try:
        gw = Container.market_gateway()
        # get_asset_price is resolved via __getattr__ → adapter dispatch
        price_obj = await gw.get_asset_price(f"SSE:{symbol}")
        if price_obj is None:
            price_obj = await gw.get_asset_price(f"SZSE:{symbol}")
        if price_obj and hasattr(price_obj, "to_dict"):
            pd = price_obj.to_dict()
            price_facts = {
                "current": _safe_num(pd.get("price")),
                "change": _safe_num(pd.get("change")),
                "change_pct": _safe_num(pd.get("change_percent")),
                "high": _safe_num(pd.get("high_price")),
                "low": _safe_num(pd.get("low_price")),
                "open": _safe_num(pd.get("open_price")),
                "volume": _safe_num(pd.get("volume")),
                "amount": None,
                "market_cap": _safe_num(pd.get("market_cap")),
            }
    except Exception:
        pass

    # --- Technical (async enrichment) ---
    technical_facts: Dict[str, Any] = {
        "ma5": None, "ma20": None, "ma60": None,
        "rsi_14": None, "macd": None,
    }
    try:
        gw = Container.market_gateway()
        tech = await gw.calculate_technical_indicators(
            symbol=f"SSE:{symbol}",
            indicators=["MA", "RSI", "MACD"],
            days=60,
        )
        if tech and "error" not in tech:
            technical_facts = _extract_technical(tech)
    except Exception:
        pass

    # --- Source trace (flat array) ---
    source_trace = [
        {"source": k, "fields": [], "update_time": ""}
        for k in source_trace_raw
    ]

    # --- Coverage ---
    total = len(coverage_raw)
    covered = sum(1 for v in coverage_raw.values() if v in ("complete", "partial"))

    return {
        "entity": entity,
        "facts": {
            "price": price_facts,
            "valuation": _extract_valuation(facts),
            "profitability": _extract_profitability(facts),
            "financial": _extract_financial(facts),
            "shareholder": _extract_shareholder(facts),
            "dividend": _extract_dividend(facts),
            "revenue_breakdown": _extract_revenue_breakdown(facts),
            "technical": technical_facts,
        },
        "source_trace": source_trace,
        "coverage": {
            "total_fields": total,
            "covered_fields": covered,
            "coverage_pct": round(covered / total * 100, 1) if total > 0 else 0,
        },
        "fact_markdown": result.get("fact_markdown", ""),
    }


# ------------------------------------------------------------------
# get_stock_fact_pack
# ------------------------------------------------------------------
@router.get(
    "/stock/{symbol}",
    summary="获取股票事实包",
    tags=["A股个股 A-Share"],
    description=(
        "聚合全维度股票结构化事实数据: 证券主档、财务、市场估值、公司治理、"
        "事件(分红/回购/解禁)、业务结构。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_stock_fact_pack(
    symbol: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_stock_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_stock_fact_pack(symbol=symbol)

        # Markdown passthrough — return adapter's markdown directly
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md

        # Normalize into frontend FactPackResponse contract
        normalized = await _normalize_stock_fact_pack(result, symbol)
        return rest_response(data=normalized, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_stock_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stock fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_fund_fact_pack
# ------------------------------------------------------------------
@router.get(
    "/fund/{fund_code}",
    summary="获取基金事实包",
    tags=["基金 Fund"],
    description=(
        "聚合全维度基金结构化事实数据: 基金主档、净值收益、持仓穿透、基金经理、"
        "规模份额、资产配置、费率分红、同类比较。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_fund_fact_pack(
    fund_code: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_fund_fact_pack", fund_code=fund_code)
        result = await Container.market_gateway().get_fund_fact_pack(fund_code=fund_code)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, symbol=fund_code, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_fund_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_market_fact_pack
# ------------------------------------------------------------------
@router.get(
    "/market/{symbol}",
    summary="获取行情事实包",
    tags=["A股个股 A-Share"],
    description=(
        "聚合全维度行情结构化事实数据: 标的估值、技术快照、K线因子、资金流、"
        "市场广度、指数板块、衍生行情、相对强弱。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_market_fact_pack(
    symbol: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_market_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_market_fact_pack(symbol=symbol)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_market_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get market fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_us_stock_fact_pack (COL-164)
# ------------------------------------------------------------------
@router.get(
    "/us-stock/{ticker}",
    summary="获取美股事实包",
    tags=["美股个股 US Stock"],
    description=(
        "聚合全维度美股结构化事实数据: 公司档案、估值指标、财务健康、"
        "机构持仓与内部人交易、分析师评级与收入结构、量价技术分析。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_us_stock_fact_pack(
    ticker: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_us_stock_fact_pack", ticker=ticker)
        result = await Container.market_gateway().get_us_stock_fact_pack(ticker=ticker)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_stock_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get US stock fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_etf_fact_pack (COL-170)
# ------------------------------------------------------------------
@router.get(
    "/etf/{symbol}",
    summary="获取ETF事实包",
    tags=["指数与ETF Index & ETF"],
    description=(
        "聚合全维度ETF结构化事实数据: ETF主档、实时行情、历史表现、"
        "资金流/申赎、技术信号(RSI/MACD/BOLL)。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_etf_fact_pack(
    symbol: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_etf_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_etf_fact_pack(symbol=symbol)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_etf_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get ETF fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_index_fact_pack (COL-171)
# ------------------------------------------------------------------
@router.get(
    "/index/{symbol}",
    summary="获取指数事实包",
    tags=["指数与ETF Index & ETF"],
    description=(
        "聚合全维度指数结构化事实数据: 指数主档、PE/PB估值与历史分位、"
        "行情表现、成分股、技术信号(RSI/MACD/BOLL)。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_index_fact_pack(
    symbol: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_index_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_index_fact_pack(symbol=symbol)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_index_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get index fact pack: {str(e)}",
        )


@router.get(
    "/sector/{sector_name}",
    summary="获取行业事实包",
    tags=["行业 Sector"],
    description=(
        "聚合全维度行业结构化事实数据: 行业定位、成分股、结构快照、同业对比、"
        "证据摘要(资金流/PE-PB历史)。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_sector_fact_pack(
    sector_name: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_sector_fact_pack", sector_name=sector_name)
        result = await Container.market_gateway().get_sector_fact_pack(sector_name=sector_name)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_sector_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sector fact pack: {str(e)}",
        )
