# src/server/domain/structured_data/normalize/financial_statements.py
"""Normalizer for financial statements (income/balance-sheet/cash-flow).

Maps source-specific field names from akshare and tushare into a unified
canonical schema. Each statement type is normalized independently with
its own field mapping.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

from .engine import FieldMapping, MISSING, Normalizer

# ---------------------------------------------------------------------------
# Canonical schema for financial statements
# ---------------------------------------------------------------------------
# Business key format: {exchange}:{symbol}:{report_period}:{statement_type}
# Example: SSE:600519:20240930:income_statement

INCOME_STATEMENT_FIELDS: List[tuple] = [
    # (source_key_pattern, canonical_key, value_type, default)
    # Populated dynamically based on source
]

# Unified field names for the three statements
INCOME_CANONICAL = {
    "revenue": "营业收入",
    "operating_cost": "营业成本",
    "gross_profit": "毛利润",
    "operating_profit": "营业利润",
    "total_profit": "利润总额",
    "net_income": "净利润",
    "net_income_attr_p": "归属于母公司所有者的净利润",
    "net_income_attr_minority": "少数股东损益",
    "operating_expense": "销售费用",
    "admin_expense": "管理费用",
    "finance_expense": "财务费用",
    "rd_expense": "研发费用",
    "investment_income": "投资收益",
    "asset_impairment": "资产减值损失",
    "credit_impairment": "信用减值损失",
    "other_income": "其他收益",
    "tax_expense": "所得税费用",
    "basic_eps": "基本每股收益",
    "diluted_eps": "稀释每股收益",
}

# Tushare field name mapping for income statement
INCOME_TUSHARE = {
    "revenue": "revenue",
    "operating_cost": "oper_cost",
    "total_profit": "total_profit",
    "net_income": "n_income",
    "net_income_attr_p": "n_income_attr_p",
    "operating_profit": "operate_profit",
    "tax_expense": "income_tax",
    "basic_eps": "basiceps",
    "diluted_eps": "dilutedeps",
    "operating_expense": "sell_exp",
    "admin_expense": "admin_exp",
    "finance_expense": "fin_exp",
    "rd_expense": "rd_exp",
}

BALANCE_SHEET_CANONICAL = {
    "total_assets": "资产总计",
    "total_current_assets": "流动资产合计",
    "total_noncurrent_assets": "非流动资产合计",
    "monetary_capital": "货币资金",
    "accounts_receivable": "应收账款",
    "inventory": "存货",
    "fixed_assets": "固定资产",
    "goodwill": "商誉",
    "total_liabilities": "负债合计",
    "total_current_liabilities": "流动负债合计",
    "total_noncurrent_liabilities": "非流动负债合计",
    "short_term_borrowing": "短期借款",
    "long_term_borrowing": "长期借款",
    "accounts_payable": "应付账款",
    "advance_payments": "预收款项",
    "total_equity": "所有者权益合计",
    "total_equity_inc_minority": "所有者权益合计(含少数股东)",
    "equity_attr_p": "归属于母公司所有者权益合计",
    "equity_attr_minority": "少数股东权益",
    "paid_in_capital": "实收资本",
    "capital_reserve": "资本公积金",
    "surplus_reserve": "盈余公积金",
    "retained_earnings": "未分配利润",
}

BALANCE_TUSHARE = {
    "total_assets": "total_assets",
    "total_current_assets": "total_cur_assets",
    "total_noncurrent_assets": "total_nca",
    "monetary_capital": "monetary_cap",
    "accounts_receivable": "account_receiv",
    "inventory": "inventories",
    "total_liabilities": "total_liab",
    "total_current_liabilities": "total_cur_liab",
    "total_noncurrent_liabilities": "total_ncl",
    "short_term_borrowing": "st_borr",
    "long_term_borrowing": "lt_borr",
    "accounts_payable": "acct_payable",
    "total_equity": "total_hldr_eqy_exc_min_int",
    "total_equity_inc_minority": "total_hldr_eqy_inc_min_int",
    "paid_in_capital": "cap_rese",
}

CASH_FLOW_CANONICAL = {
    "operating_cash_flow": "经营活动产生的现金流量净额",
    "investing_cash_flow": "投资活动产生的现金流量净额",
    "financing_cash_flow": "筹资活动产生的现金流量净额",
    "cash_received_from_sales": "销售商品、提供劳务收到的现金",
    "cash_paid_for_goods": "购买商品、接受劳务支付的现金",
    "cash_paid_to_employees": "支付给职工以及为职工支付的现金",
    "tax_paid": "支付的各项税费",
    "net_change_in_cash": "现金及现金等价物净增加额",
    "beginning_cash": "期初现金及现金等价物余额",
    "ending_cash": "期末现金及现金等价物余额",
    "depreciation": "固定资产折旧、油气资产折耗、生产性生物资产折旧",
    "capex": "购建固定资产、无形资产和其他长期资产支付的现金",
    "free_cash_flow": "自由现金流量",
}

CASH_FLOW_TUSHARE = {
    "operating_cash_flow": "n_cashflow_act",
    "investing_cash_flow": "n_cashflow_inv_act",
    "financing_cash_flow": "n_cashflow_fnc_act",
    "cash_received_from_sales": "c_sales_goods",
    "cash_paid_for_goods": "c_paid_goods",
    "cash_paid_to_employees": "c_paid_to_for_empl",
    "free_cash_flow": "free_cashflow",
}

# Financial indicators (financial ratios derived from the three statements)
INDICATORS_CANONICAL = {
    "roe": "净资产收益率",
    "roa": "总资产收益率",
    "gross_margin": "销售毛利率",
    "net_margin": "销售净利率",
    "debt_to_assets": "资产负债率",
    "current_ratio": "流动比率",
    "quick_ratio": "速动比率",
    "asset_turnover": "总资产周转率",
    "receivable_turnover": "应收账款周转率",
    "inventory_turnover": "存货周转率",
}

INDICATORS_TUSHARE = {
    "roe": "roe",
    "roa": "roa",
    "gross_margin": "grossprofit_margin",
    "net_margin": "netprofit_margin",
    "debt_to_assets": "debt_to_assets",
    "current_ratio": "current_ratio",
    "quick_ratio": "quick_ratio",
}


# Statement type enum for business key
STATEMENT_TYPES = {
    "income_statement": "income_statement",
    "balance_sheet": "balance_sheet",
    "cash_flow": "cash_flow",
    "financial_indicators": "financial_indicators",
}


def _safe_float(value: Any) -> Optional[float]:
    """Safely convert a value to float."""
    if value is None:
        return None
    try:
        f = float(value)
        import math
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _extract_report_period(raw: Dict[str, Any], source: str) -> Optional[str]:
    """Extract report period from raw data and normalize to YYYYMMDD."""
    candidates = []
    if source == "akshare":
        candidates = [raw.get("报告期"), raw.get("end_date"), raw.get("report_date")]
    else:
        candidates = [raw.get("end_date"), raw.get("ann_date"), raw.get("report_date")]

    for val in candidates:
        if val is None:
            continue
        s = str(val).strip().replace("-", "").replace("/", "")[:8]
        if len(s) == 8 and s.isdigit():
            return s
    return None


def _map_fields(
    raw_row: Dict[str, Any],
    canonical_map: Dict[str, str],
) -> Dict[str, Optional[float]]:
    """Map raw row fields to canonical field names, converting to float."""
    result = {}
    for canonical_key, source_key in canonical_map.items():
        val = raw_row.get(source_key)
        result[canonical_key] = _safe_float(val)
    return result


def _add_yoy_qoq(
    canonical: Dict[str, Any],
    raw_row: Dict[str, Any],
    source: str,
) -> None:
    """Extract YoY/QoQ growth fields from raw data."""
    # Common growth field suffixes
    yoy_fields = {
        "revenue_yoy": ["revenue_yoy", "营业收入_yoy", "营收同比增长"],
        "net_income_yoy": ["net_income_yoy", "净利润_yoy", "归属于母公司所有者的净利润_yoy", "n_income_attr_p_yoy"],
        "operating_profit_yoy": ["operating_profit_yoy", "营业利润_yoy", "operate_profit_yoy"],
        "total_profit_yoy": ["total_profit_yoy", "利润总额_yoy"],
    }

    for canon_key, source_keys in yoy_fields.items():
        for sk in source_keys:
            val = raw_row.get(sk)
            if val is not None:
                canonical[canon_key] = _safe_float(val)
                break


class FinancialStatementsNormalizer(Normalizer):
    """Normalizer for financial statement data from akshare and tushare.

    Takes raw financial data (which may contain income_statement, balance_sheet,
    cash_flow as nested dicts or flat rows) and produces canonical records
    with standardized field names and types.
    """

    @property
    def dataset_key(self) -> str:
        return "financial_statements"

    async def normalize(
        self,
        raw_data: Dict[str, Any],
        source: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Normalize raw financial data into canonical schema.

        Handles two input shapes:
        1. Structured: {income_statement: [...], balance_sheet: [...], cash_flow: [...]}
        2. Flat: single row with fields from one statement type

        Returns a dict with:
        - business_key: canonical primary key
        - statement_type: which statement this row represents
        - All canonical fields for the statement type
        - Metadata (symbol, report_period, source)
        """
        # Determine input shape
        if self._is_structured(raw_data):
            # Structured input — normalize each statement type separately
            return await self._normalize_structured(raw_data, source, **kwargs)
        else:
            # Flat row — normalize as a single statement
            return await self._normalize_flat_row(raw_data, source, **kwargs)

    async def normalize_batch(
        self,
        raw_items: List[Dict[str, Any]],
        source: str = "",
    ) -> List[Dict[str, Any]]:
        """Normalize a batch of raw financial data items."""
        results = []
        for item in raw_items:
            try:
                normalized = await self.normalize(item, source=source)
                results.append(normalized)
            except Exception as e:
                logger.warning(
                    "Financial statements normalization failed",
                    source=source,
                    error=str(e),
                )
                results.append({
                    "_normalization_error": str(e),
                    "_raw_data": item,
                })
        return results

    def _is_structured(self, raw_data: Dict[str, Any]) -> bool:
        """Check if raw data is the structured multi-statement format."""
        structured_keys = {
            "income_statement", "balance_sheet", "cash_flow",
            "financial_indicators", "income", "balance", "cashflow",
        }
        return bool(set(raw_data.keys()) & structured_keys)

    async def _normalize_structured(
        self,
        raw_data: Dict[str, Any],
        source: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Normalize structured multi-statement data.

        Produces a composite canonical record with all three statements
        plus financial indicators.
        """
        symbol = kwargs.get("symbol") or raw_data.get("symbol", "")
        exchange = kwargs.get("exchange") or raw_data.get("exchange", "")

        # Extract and normalize each statement
        income_raw = raw_data.get("income_statement") or raw_data.get("income") or []
        balance_raw = raw_data.get("balance_sheet") or raw_data.get("balance") or []
        cashflow_raw = raw_data.get("cash_flow") or raw_data.get("cashflow") or []
        indicators_raw = raw_data.get("financial_indicators") or raw_data.get("indicators") or []

        # Get the latest report period from any source
        report_period = self._find_latest_period(
            income_raw + balance_raw + cashflow_raw + indicators_raw, source,
        )

        if not report_period:
            # Try to get from kwargs
            report_period = kwargs.get("report_period", "")

        # Normalize each statement — take latest row from each
        income_fields = self._normalize_latest_row(
            income_raw, source, INCOME_CANONICAL, INCOME_TUSHARE,
        )
        balance_fields = self._normalize_latest_row(
            balance_raw, source, BALANCE_SHEET_CANONICAL, BALANCE_TUSHARE,
        )
        cashflow_fields = self._normalize_latest_row(
            cashflow_raw, source, CASH_FLOW_CANONICAL, CASH_FLOW_TUSHARE,
        )
        indicators_fields = self._normalize_latest_row(
            indicators_raw, source, INDICATORS_CANONICAL, INDICATORS_TUSHARE,
        )

        # Build business key
        business_key = self.build_business_key(
            exchange=exchange,
            symbol=symbol,
            report_period=report_period,
            statement_type="all",
        )

        # Calculate derived fields
        derived = self._calculate_derived_fields(
            income_fields, balance_fields, cashflow_fields,
        )

        result = {
            "business_key": business_key,
            "symbol": symbol,
            "exchange": exchange,
            "report_period": report_period,
            "statement_type": "all",
            "source": source,
            "_normalized_at": datetime.now(timezone.utc).isoformat(),
            # Statement data
            "income_statement": income_fields,
            "balance_sheet": balance_fields,
            "cash_flow": cashflow_fields,
            "financial_indicators": indicators_fields,
            # Derived
            **derived,
        }

        return result

    async def _normalize_flat_row(
        self,
        raw_data: Dict[str, Any],
        source: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Normalize a single flat row of financial data."""
        symbol = kwargs.get("symbol") or self._extract_symbol(raw_data, source)
        exchange = kwargs.get("exchange") or self._extract_exchange(raw_data, source)
        report_period = _extract_report_period(raw_data, source)

        # Detect statement type from field presence
        statement_type = self._detect_statement_type(raw_data, source)

        # Map fields based on source
        canonical_map = self._get_canonical_map(statement_type, source)
        fields = _map_fields(raw_data, canonical_map)

        # Add YoY/QoQ if present
        _add_yoy_qoq(fields, raw_data, source)

        # Build business key
        business_key = self.build_business_key(
            exchange=exchange,
            symbol=symbol,
            report_period=report_period or "unknown",
            statement_type=statement_type,
        )

        return {
            "business_key": business_key,
            "symbol": symbol,
            "exchange": exchange,
            "report_period": report_period,
            "statement_type": statement_type,
            "source": source,
            "_normalized_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }

    def _normalize_latest_row(
        self,
        rows: list,
        source: str,
        akshare_map: Dict[str, str],
        tushare_map: Dict[str, str],
    ) -> Dict[str, Optional[float]]:
        """Normalize the latest row from a list of raw rows.

        Finds the row with the most recent report_period rather than
        assuming rows are sorted.
        """
        if not rows:
            return {}

        if isinstance(rows, dict):
            rows = [rows]

        # Find the row with the latest report_period
        latest_row = rows[0]
        latest_period = _extract_report_period(rows[0], source) or ""

        for row in rows[1:]:
            period = _extract_report_period(row, source) or ""
            if period > latest_period:
                latest_period = period
                latest_row = row

        canonical_map = akshare_map if source == "akshare" else tushare_map

        result = _map_fields(latest_row, canonical_map)

        # Try both maps if the primary yields mostly None
        non_none = sum(1 for v in result.values() if v is not None)
        if non_none < 3 and source != "akshare":
            # Fallback to akshare map
            fallback = _map_fields(latest_row, akshare_map)
            for k, v in fallback.items():
                if result.get(k) is None and v is not None:
                    result[k] = v
        elif non_none < 3 and source == "akshare":
            # Fallback to tushare map
            fallback = _map_fields(latest_row, tushare_map)
            for k, v in fallback.items():
                if result.get(k) is None and v is not None:
                    result[k] = v

        # Add YoY/QoQ
        _add_yoy_qoq(result, latest_row, source)

        return result

    def _find_latest_period(self, rows: list, source: str) -> Optional[str]:
        """Find the latest report period from a list of rows."""
        periods = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            period = _extract_report_period(row, source)
            if period:
                periods.append(period)

        if not periods:
            return None
        return max(periods)

    def _detect_statement_type(self, raw_data: Dict[str, Any], source: str) -> str:
        """Detect which statement type a flat row represents."""
        if source == "akshare":
            # Check for Chinese field names
            if "营业收入" in raw_data or "净利润" in raw_data:
                return "income_statement"
            if "资产总计" in raw_data or "负债合计" in raw_data:
                return "balance_sheet"
            if "经营活动产生的现金流量净额" in raw_data:
                return "cash_flow"
        else:
            # Tushare field names
            if "revenue" in raw_data or "n_income" in raw_data:
                return "income_statement"
            if "total_assets" in raw_data or "total_liab" in raw_data:
                return "balance_sheet"
            if "n_cashflow_act" in raw_data:
                return "cash_flow"

        return "unknown"

    def _get_canonical_map(
        self,
        statement_type: str,
        source: str,
    ) -> Dict[str, str]:
        """Get the appropriate canonical field mapping."""
        if statement_type == "income_statement":
            return INCOME_CANONICAL if source == "akshare" else INCOME_TUSHARE
        elif statement_type == "balance_sheet":
            return BALANCE_SHEET_CANONICAL if source == "akshare" else BALANCE_TUSHARE
        elif statement_type == "cash_flow":
            return CASH_FLOW_CANONICAL if source == "akshare" else CASH_FLOW_TUSHARE
        elif statement_type == "financial_indicators":
            return INDICATORS_CANONICAL if source == "akshare" else INDICATORS_TUSHARE
        return {}

    def _extract_symbol(self, raw_data: Dict[str, Any], source: str) -> str:
        """Extract symbol from raw data."""
        if source == "tushare":
            ts_code = raw_data.get("ts_code", "")
            if ts_code:
                # 600519.SH -> 600519
                return ts_code.split(".")[0]
        return raw_data.get("symbol", raw_data.get("股票代码", ""))

    def _extract_exchange(self, raw_data: Dict[str, Any], source: str) -> str:
        """Extract exchange from raw data."""
        if source == "tushare":
            ts_code = raw_data.get("ts_code", "")
            if ts_code:
                suffix = ts_code.split(".")[-1] if "." in ts_code else ""
                exchange_map = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
                return exchange_map.get(suffix, "")
        return raw_data.get("exchange", "")

    def _calculate_derived_fields(
        self,
        income: Dict[str, Optional[float]],
        balance: Dict[str, Optional[float]],
        cashflow: Dict[str, Optional[float]],
    ) -> Dict[str, Optional[float]]:
        """Calculate derived financial metrics from the three statements."""
        derived = {}

        # Gross margin = (revenue - operating_cost) / revenue
        rev = income.get("revenue")
        cost = income.get("operating_cost")
        if rev and cost and rev != 0:
            derived["derived_gross_margin"] = round((rev - cost) / rev * 100, 2)

        # Net margin = net_income / revenue
        ni = income.get("net_income_attr_p") or income.get("net_income")
        if rev and ni and rev != 0:
            derived["derived_net_margin"] = round(ni / rev * 100, 2)

        # Debt ratio = total_liabilities / total_assets
        total_assets = balance.get("total_assets")
        total_liab = balance.get("total_liabilities")
        if total_assets and total_liab and total_assets != 0:
            derived["derived_debt_ratio"] = round(total_liab / total_assets * 100, 2)

        # Current ratio = total_current_assets / total_current_liabilities
        current_assets = balance.get("total_current_assets")
        current_liab = balance.get("total_current_liabilities")
        if current_assets and current_liab and current_liab != 0:
            derived["derived_current_ratio"] = round(current_assets / current_liab, 2)

        # Operating cash flow ratio = operating_cash_flow / net_income
        ocf = cashflow.get("operating_cash_flow")
        if ocf and ni and ni != 0:
            derived["derived_ocf_to_ni"] = round(ocf / ni, 2)

        return derived
