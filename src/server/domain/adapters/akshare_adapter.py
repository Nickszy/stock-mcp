# src/server/domain/adapters/akshare_adapter.py
"""Akshare adapter for Chinese market data.

All methods are async via asyncio.run_in_executor to avoid blocking
the event loop.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import akshare as ak
import pandas as pd

from src.server.domain.adapters.base import BaseDataAdapter
from src.server.domain.cninfo_helper import (
    _normalize_stock_code,
    fetch_cninfo_data,
)
from src.server.domain.types import (
    AdapterCapability,
    Asset,
    AssetPrice,
    AssetType,
    DataSource,
    Exchange,
    MarketInfo,
    MarketStatus,
)
from src.server.utils.logger import logger


class AkshareAdapter(BaseDataAdapter):
    name = "akshare"

    def __init__(self, cache):
        super().__init__(DataSource.AKSHARE)
        self.cache = cache
        self.logger = logger

    def get_capabilities(self) -> List[AdapterCapability]:
        """Declare AkShare's capabilities."""
        return [
            AdapterCapability(
                asset_type=AssetType.STOCK,
                exchanges={Exchange.SSE, Exchange.SZSE, Exchange.BSE, Exchange.HKEX},
            ),
            AdapterCapability(
                asset_type=AssetType.INDEX, exchanges={Exchange.SSE, Exchange.SZSE}
            ),
            AdapterCapability(
                asset_type=AssetType.ETF, exchanges={Exchange.SSE, Exchange.SZSE}
            ),
        ]

    def convert_to_source_ticker(self, internal_ticker: str) -> str:
        """Convert EXCHANGE:SYMBOL to AKShare format."""
        if ":" in internal_ticker:
            return internal_ticker.split(":")[1]
        return internal_ticker

    def convert_to_internal_ticker(
        self, source_ticker: str, default_exchange: Optional[str] = None
    ) -> str:
        """Convert AKShare format to EXCHANGE:SYMBOL."""
        if source_ticker.startswith("6") and len(source_ticker) == 6:
            return f"SSE:{source_ticker}"
        elif (source_ticker.startswith("0") or source_ticker.startswith("3")) and len(
            source_ticker
        ) == 6:
            return f"SZSE:{source_ticker}"
        elif len(source_ticker) == 5:
            return f"HKEX:{source_ticker}"
        elif source_ticker.startswith("8") and len(source_ticker) == 6:
            return f"BSE:{source_ticker}"
        elif default_exchange:
            return f"{default_exchange}:{source_ticker}"
        else:
            return f"SSE:{source_ticker}"

    async def _run(self, func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None

    @staticmethod
    def _to_trade_date_yyyymmdd(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        text = text.replace("/", "-")
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10].replace("-", "")
        if len(text) == 8 and text.isdigit():
            return text
        try:
            dt = datetime.fromisoformat(text)
            return dt.strftime("%Y%m%d")
        except Exception:
            return text.replace("-", "")

    async def _get_board_catalog(self) -> List[Dict[str, str]]:
        """Get unified industry/concept board name catalog with cache."""
        cache_key = "akshare:board_catalog:v1"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        catalog: List[Dict[str, str]] = []
        try:
            ind_df, concept_df = await asyncio.gather(
                self._run(ak.stock_board_industry_name_em),
                self._run(ak.stock_board_concept_name_em),
                return_exceptions=True,
            )
            if isinstance(ind_df, pd.DataFrame) and not ind_df.empty:
                for _, row in ind_df.iterrows():
                    name = str(row.get("板块名称", "")).strip()
                    code = str(row.get("板块代码", "")).strip()
                    if name:
                        catalog.append(
                            {
                                "name": name,
                                "code": code,
                                "board_type": "industry",
                            }
                        )
            if isinstance(concept_df, pd.DataFrame) and not concept_df.empty:
                for _, row in concept_df.iterrows():
                    name = str(row.get("板块名称", "")).strip()
                    code = str(row.get("板块代码", "")).strip()
                    if name:
                        catalog.append(
                            {
                                "name": name,
                                "code": code,
                                "board_type": "concept",
                            }
                        )
        except Exception as e:
            self.logger.warning(f"Failed to build AK board catalog: {e}")

        if catalog:
            await self.cache.set(cache_key, catalog, ttl=3600)
        return catalog

    async def _resolve_board(
        self, sector_name: str
    ) -> tuple[Optional[Dict[str, str]], Optional[List[str]]]:
        """Resolve board by exact/fuzzy matching."""
        catalog = await self._get_board_catalog()
        if not catalog:
            return None, None

        exact = [x for x in catalog if x["name"] == sector_name]
        if len(exact) == 1:
            return exact[0], None
        if len(exact) > 1:
            return exact[0], None

        contains = [x for x in catalog if sector_name and sector_name in x["name"]]
        if len(contains) == 1:
            return contains[0], None
        if len(contains) > 1:
            return None, [x["name"] for x in contains[:10]]

        reverse = [
            x
            for x in catalog
            if len(x["name"]) >= 2 and x["name"] in sector_name
        ]
        if len(reverse) == 1:
            return reverse[0], None
        if len(reverse) > 1:
            reverse_sorted = sorted(reverse, key=lambda x: len(x["name"]), reverse=True)
            return reverse_sorted[0], None

        return None, None

    async def _resolve_board_by_code(self, sector_id: str) -> Optional[Dict[str, str]]:
        """Resolve board by code."""
        sid = (sector_id or "").strip().upper()
        if not sid:
            return None
        catalog = await self._get_board_catalog()
        if not catalog:
            return None
        for item in catalog:
            if str(item.get("code", "")).upper() == sid:
                return item
        return None

    async def resolve_sector(
        self, query_text: str, intent: str = "trend"
    ) -> Dict[str, Any]:
        """Resolve sector query into stable sector_id."""
        query = (query_text or "").strip()
        if not query:
            return {
                "component_type": "sector_resolve",
                "source": "akshare",
                "status": "not_found",
                "query_text": query_text,
                "intent": intent,
                "reason": "empty query_text",
            }

        board = await self._resolve_board_by_code(query)
        if board:
            return {
                "component_type": "sector_resolve",
                "source": "akshare",
                "status": "resolved",
                "query_text": query_text,
                "intent": intent,
                "sector_id": board.get("code", ""),
                "canonical_name": board.get("name", query),
                "board_type": board.get("board_type", ""),
            }

        board, candidates = await self._resolve_board(query)
        if board:
            return {
                "component_type": "sector_resolve",
                "source": "akshare",
                "status": "resolved",
                "query_text": query_text,
                "intent": intent,
                "sector_id": board.get("code", ""),
                "canonical_name": board.get("name", query),
                "board_type": board.get("board_type", ""),
            }

        if candidates:
            catalog = await self._get_board_catalog()
            name_map = {str(x.get("name", "")): x for x in catalog}
            candidate_rows = []
            for name in candidates:
                row = name_map.get(name, {})
                candidate_rows.append(
                    {
                        "sector_id": row.get("code", ""),
                        "canonical_name": name,
                        "board_type": row.get("board_type", ""),
                        "source": "akshare",
                    }
                )
            return {
                "component_type": "sector_resolve",
                "source": "akshare",
                "status": "ambiguous",
                "query_text": query_text,
                "intent": intent,
                "candidates": candidate_rows,
            }

        return {
            "component_type": "sector_resolve",
            "source": "akshare",
            "status": "not_found",
            "query_text": query_text,
            "intent": intent,
            "reason": f"no sector matched for '{query}'",
        }

    async def _fetch_board_hist(
        self, board: Dict[str, str], days: int
    ) -> pd.DataFrame:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=max(days * 3, 40))
        symbol = board["name"]
        if board.get("board_type") == "industry":
            df = await self._run(
                ak.stock_board_industry_hist_em,
                symbol=symbol,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                period="日k",
                adjust="",
            )
        else:
            df = await self._run(
                ak.stock_board_concept_hist_em,
                symbol=symbol,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="",
            )
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

    def _to_ak_code(self, ticker: str) -> str:
        return self.convert_to_source_ticker(ticker)

    async def get_asset_info(self, ticker: str) -> Optional[Asset]:
        """Fetch detailed asset information."""
        cache_key = f"akshare:info:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return Asset.model_validate(cached)

        symbol = self._to_ak_code(ticker)
        try:
            # Use stock_individual_info_em for A-shares
            if ticker.startswith("HKEX"):
                # HK stocks might need different API, for now fallback or simple
                return None

            df = await self._run(ak.stock_individual_info_em, symbol=symbol)
            if df.empty:
                return None

            info = {}
            for _, row in df.iterrows():
                key = row.get("item")
                val = row.get("value")
                if key:
                    info[key] = val

            exchange = ticker.split(":")[0]

            asset = Asset(
                ticker=ticker,
                asset_type=AssetType.STOCK,
                name=str(info.get("股票简称", ticker)),
                market_info=MarketInfo(
                    exchange=exchange,
                    country="CN",
                    currency="CNY",
                    timezone="Asia/Shanghai",
                    market_status=MarketStatus.UNKNOWN,
                ),
                source_mappings={DataSource.AKSHARE: symbol},
                properties={
                    "industry": str(info.get("行业", "")),
                    "listing_date": str(info.get("上市时间", "")),
                    "total_shares": str(info.get("总股本", "")),
                    "float_shares": str(info.get("流通股", "")),
                },
            )

            await self.cache.set(cache_key, asset.model_dump(), ttl=3600)
            return asset
        except Exception as e:
            self.logger.warning(f"Failed to fetch asset info for {ticker}: {e}")
            return None

    async def get_real_time_price(self, ticker: str) -> Optional[AssetPrice]:
        """Fetch current price."""
        cache_key = f"akshare:price:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return AssetPrice.from_dict(cached)

        symbol = self._to_ak_code(ticker)
        is_hk = ticker.startswith("HKEX:")

        try:
            if is_hk:
                df = await self._run(
                    ak.stock_hk_hist_min_em, symbol=symbol, period="1", adjust=""
                )
            else:
                df = await self._run(
                    ak.stock_zh_a_hist_min_em, symbol=symbol, period="1", adjust="qfq"
                )

            if df.empty:
                # Fallback to daily
                if is_hk:
                    df = await self._run(
                        ak.stock_hk_hist,
                        symbol=symbol,
                        period="daily",
                        start_date="20240101",
                        adjust="qfq",
                    )
                else:
                    df = await self._run(
                        ak.stock_zh_a_hist,
                        symbol=symbol,
                        period="daily",
                        start_date="20240101",
                        adjust="qfq",
                    )

            if df.empty:
                return None

            row = df.iloc[-1]
            price_val = float(row["收盘"])

            # Try to get other fields if available (daily data usually has them)
            open_val = float(row.get("开盘", 0))
            high_val = float(row.get("最高", 0))
            low_val = float(row.get("最低", 0))
            prev_close = float(row.get("前收盘", 0))  # Might not exist
            volume = float(row.get("成交量", 0))

            # Date handling
            date_val = row.get("日期") or row.get("时间")
            if isinstance(date_val, str):
                try:
                    timestamp = datetime.strptime(date_val, "%Y-%m-%d %H:%M:%S")
                except:
                    try:
                        timestamp = datetime.strptime(date_val, "%Y-%m-%d")
                    except:
                        timestamp = datetime.utcnow()
            else:
                timestamp = datetime.utcnow()

            asset_price = AssetPrice(
                ticker=ticker,
                price=Decimal(str(price_val)),
                currency="HKD" if is_hk else "CNY",
                timestamp=timestamp,
                volume=Decimal(str(volume)),
                open_price=Decimal(str(open_val)) if open_val else None,
                high_price=Decimal(str(high_val)) if high_val else None,
                low_price=Decimal(str(low_val)) if low_val else None,
                close_price=None,  # Akshare history doesn't give prev close easily in this call
                source=DataSource.AKSHARE,
            )

            await self.cache.set(cache_key, asset_price.to_dict(), ttl=60)
            return asset_price

        except Exception as e:
            self.logger.warning(f"Failed to fetch price for {ticker}: {e}")
            return None

    async def get_historical_prices(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> List[AssetPrice]:
        """Fetch historical prices."""
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        cache_key = f"akshare:history:{ticker}:{start_str}:{end_str}:{interval}"
        cached = await self.cache.get(cache_key)
        if cached:
            return [AssetPrice.from_dict(item) for item in cached]

        symbol = self._to_ak_code(ticker)
        is_hk = ticker.startswith("HKEX:")
        # Detect index codes (000xxx for SSE indices, 399xxx for SZSE indices)
        is_index = (
            symbol.startswith("000") and len(symbol) == 6
            and not symbol.startswith("0000")  # exclude stock codes like 000001 bank
            or symbol.startswith("399")
        )
        # More precise: common index prefixes
        _INDEX_CODES = {
            "000300", "000016", "000905", "000852", "000903",
            "399001", "399006", "399005", "399673",
            "000001",  # 上证指数
        }
        is_index = symbol in _INDEX_CODES

        try:
            if is_hk:
                df = await self._run(
                    ak.stock_hk_hist,
                    symbol=symbol,
                    period="daily",
                    start_date=start_str,
                    end_date=end_str,
                    adjust="qfq",
                )
            elif is_index:
                df = await self._run(
                    ak.index_zh_a_hist,
                    symbol=symbol,
                    period="daily",
                    start_date=start_str,
                    end_date=end_str,
                )
            else:
                # A-share daily
                df = await self._run(
                    ak.stock_zh_a_hist,
                    symbol=symbol,
                    period="daily",
                    start_date=start_str,
                    end_date=end_str,
                    adjust="qfq",
                )

            if df.empty:
                return []

            prices = []
            for _, row in df.iterrows():
                date_val = row["日期"]
                if isinstance(date_val, str):
                    timestamp = datetime.strptime(date_val, "%Y-%m-%d")
                else:
                    timestamp = date_val  # Assuming date object

                price = AssetPrice(
                    ticker=ticker,
                    price=Decimal(str(row["收盘"])),
                    currency="HKD" if is_hk else "CNY",
                    timestamp=timestamp,
                    volume=Decimal(str(row["成交量"])),
                    open_price=Decimal(str(row["开盘"])),
                    high_price=Decimal(str(row["最高"])),
                    low_price=Decimal(str(row["最低"])),
                    close_price=Decimal(str(row["收盘"])),
                    source=DataSource.AKSHARE,
                )
                prices.append(price)

            await self.cache.set(cache_key, [p.to_dict() for p in prices], ttl=3600)
            return prices

        except Exception as e:
            self.logger.error(f"Failed to fetch history for {ticker}: {e}")
            return []

    async def get_market_money_flow(
        self,
        trade_date: Optional[str] = None,
        top_n: int = 20,
        include_outflow: bool = True,
    ) -> Dict[str, Any]:
        """Get sector money flow ranking via AkShare Eastmoney endpoints."""
        safe_top_n = max(1, min(int(top_n), 100))
        cache_key = (
            f"akshare:market_money_flow:{trade_date or 'latest'}:"
            f"{safe_top_n}:{int(bool(include_outflow))}"
        )
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        requested_date = str(trade_date) if trade_date else None
        as_of_date = datetime.now().strftime("%Y%m%d")
        data_freshness = "exact"
        if requested_date and requested_date != as_of_date:
            data_freshness = "fallback_other_trade_date"

        try:
            df = await self._run(
                ak.stock_sector_fund_flow_rank,
                indicator="今日",
                sector_type="行业资金流",
            )
            if df is None or df.empty:
                result = {
                    "component_type": "market_money_flow",
                    "source": "akshare",
                    "data_source": "stock_sector_fund_flow_rank",
                    "data": [],
                    "requested_trade_date": requested_date,
                    "as_of_trade_date": as_of_date,
                    "data_freshness": "empty",
                    "top_n": safe_top_n,
                    "include_outflow": bool(include_outflow),
                    "market_overview": {
                        "inflow_count": 0,
                        "outflow_count": 0,
                        "total_net_amount": 0.0,
                    },
                    "top_inflow": [],
                    "top_outflow": [],
                    "trend_conclusion_allowed": False,
                    "blocked_reason": "market_money_flow_empty",
                }
                await self.cache.set(cache_key, result, ttl=1800)
                return result

            name_col = "名称" if "名称" in df.columns else "行业"
            net_col = (
                "今日主力净流入-净额"
                if "今日主力净流入-净额" in df.columns
                else ("净额" if "净额" in df.columns else None)
            )
            pct_col = (
                "今日涨跌幅"
                if "今日涨跌幅" in df.columns
                else ("行业-涨跌幅" if "行业-涨跌幅" in df.columns else "涨跌幅")
            )
            if net_col is None:
                raise ValueError("No net amount column in stock_sector_fund_flow_rank")

            rows: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                name = str(row.get(name_col, "")).strip()
                if not name:
                    continue
                net_amount = self._safe_float(row.get(net_col))
                if net_amount is None:
                    continue
                pct = self._safe_float(row.get(pct_col))
                rows.append(
                    {
                        "name": name,
                        "net_mf_amount": net_amount,
                        "pct_chg": pct,
                        "trade_date": as_of_date,
                    }
                )

            inflow_rows = sorted(
                [r for r in rows if (r.get("net_mf_amount") or 0) >= 0],
                key=lambda x: x.get("net_mf_amount", 0),
                reverse=True,
            )
            outflow_rows = sorted(
                [r for r in rows if (r.get("net_mf_amount") or 0) < 0],
                key=lambda x: x.get("net_mf_amount", 0),
            )
            top_inflow = [
                {
                    "rank": idx,
                    "sector_name": r.get("name"),
                    "net_amount": r.get("net_mf_amount"),
                    "pct_chg": r.get("pct_chg"),
                    "trade_date": r.get("trade_date"),
                }
                for idx, r in enumerate(inflow_rows[:safe_top_n], start=1)
            ]
            top_outflow = (
                [
                    {
                        "rank": idx,
                        "sector_name": r.get("name"),
                        "net_amount": r.get("net_mf_amount"),
                        "pct_chg": r.get("pct_chg"),
                        "trade_date": r.get("trade_date"),
                    }
                    for idx, r in enumerate(outflow_rows[:safe_top_n], start=1)
                ]
                if include_outflow
                else []
            )

            total_net_amount = sum(float(r.get("net_mf_amount", 0)) for r in rows)
            trend_conclusion_allowed = data_freshness == "exact" and len(top_inflow) > 0
            blocked_reason = None
            if not trend_conclusion_allowed:
                if not rows:
                    blocked_reason = "market_money_flow_empty"
                elif data_freshness != "exact":
                    blocked_reason = f"stale_data:{data_freshness}"
                else:
                    blocked_reason = "insufficient_rank_data"

            result = {
                "component_type": "market_money_flow",
                "source": "akshare",
                "data_source": "stock_sector_fund_flow_rank",
                "data": rows,
                "requested_trade_date": requested_date,
                "as_of_trade_date": as_of_date,
                "data_freshness": data_freshness,
                "top_n": safe_top_n,
                "include_outflow": bool(include_outflow),
                "market_overview": {
                    "inflow_count": len(inflow_rows),
                    "outflow_count": len(outflow_rows),
                    "total_net_amount": total_net_amount,
                },
                "top_inflow": top_inflow,
                "top_outflow": top_outflow,
                "trend_conclusion_allowed": trend_conclusion_allowed,
                "blocked_reason": blocked_reason,
            }
            await self.cache.set(cache_key, result, ttl=900)
            return result
        except Exception as e:
            self.logger.warning(f"Akshare get_market_money_flow failed: {e}")
            raise ValueError(f"Failed to get market money flow: {e}")

    async def get_sector_trend(
        self,
        sector_name: str = "",
        days: int = 10,
        sector_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get sector trend with fuzzy board resolution via AkShare."""
        cache_key = (
            f"akshare:sector_trend:{(sector_id or '').strip().upper()}:"
            f"{sector_name}:{days}"
        )
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        query_name = (sector_name or "").strip()
        query_sector_id = (sector_id or "").strip().upper()
        candidates = None
        if query_sector_id:
            board = await self._resolve_board_by_code(query_sector_id)
        else:
            board, candidates = await self._resolve_board(query_name)

        if board is None:
            if candidates:
                return {
                    "error": f"板块名称 '{query_name}' 不明确，请从以下候选中选择",
                    "candidates": candidates,
                    "sector_name": query_name,
                    "sector_id": query_sector_id,
                    "component_type": "sector_trend",
                    "source": "akshare",
                }
            if query_sector_id:
                raise ValueError(f"No sector index found for id '{query_sector_id}'")
            raise ValueError(f"No sector index found for '{query_name}'")

        try:
            hist_df = await self._fetch_board_hist(board, days)
            if hist_df is None or hist_df.empty:
                raise ValueError(f"No sector daily data for {board['name']}")

            hist_df = hist_df.sort_values("日期").tail(days)
            trend: List[Dict[str, Any]] = []
            total_pct_chg = 0.0
            for _, row in hist_df.iterrows():
                pct = self._safe_float(row.get("涨跌幅")) or 0.0
                total_pct_chg += pct
                trend.append(
                    {
                        "ts_code": board.get("code", ""),
                        "trade_date": self._to_trade_date_yyyymmdd(row.get("日期")),
                        "open": self._safe_float(row.get("开盘")),
                        "high": self._safe_float(row.get("最高")),
                        "low": self._safe_float(row.get("最低")),
                        "close": self._safe_float(row.get("收盘")),
                        "change": self._safe_float(row.get("涨跌额")),
                        "pct_chg": pct,
                        "vol": self._safe_float(row.get("成交量")),
                        "turnover_rate": self._safe_float(row.get("换手率")),
                    }
                )

            result = {
                "component_type": "sector_trend",
                "source": "akshare",
                "sector_name": board["name"],
                "index_code": board.get("code", ""),
                "days": len(trend),
                "total_pct_chg": round(total_pct_chg, 4),
                "trend": trend,
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.warning(
                f"Akshare get_sector_trend failed for {query_name or query_sector_id}: {e}"
            )
            raise ValueError(f"Failed to get sector trend: {e}")

    async def get_sector_money_flow_history(
        self,
        sector_name: str = "",
        days: int = 20,
        sector_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get sector price + capital flow history via AkShare."""
        cache_key = (
            f"akshare:sector_money_flow:{(sector_id or '').strip().upper()}:"
            f"{sector_name}:{days}"
        )
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        query_name = (sector_name or "").strip()
        query_sector_id = (sector_id or "").strip().upper()
        candidates = None
        if query_sector_id:
            board = await self._resolve_board_by_code(query_sector_id)
        else:
            board, candidates = await self._resolve_board(query_name)

        if board is None:
            if candidates:
                return {
                    "error": f"板块名称 '{query_name}' 不明确，请从以下候选中选择",
                    "candidates": candidates,
                    "sector_name": query_name,
                    "sector_id": query_sector_id,
                    "component_type": "sector_flow",
                    "source": "akshare",
                }
            if query_sector_id:
                return {
                    "error": f"未找到板块ID: {query_sector_id}",
                    "sector_name": query_name,
                    "sector_id": query_sector_id,
                    "component_type": "sector_flow",
                    "source": "akshare",
                }
            return {
                "error": f"未找到板块: {query_name}",
                "sector_name": query_name,
                "component_type": "sector_flow",
                "source": "akshare",
            }

        try:
            hist_df = await self._fetch_board_hist(board, days)
            if hist_df is None or hist_df.empty:
                raise ValueError(f"No sector daily data for {board['name']}")
            hist_df = hist_df.sort_values("日期").tail(days)

            flow_map: Dict[str, Dict[str, Any]] = {}
            flow_source = None
            try:
                flow_df = await self._run(
                    ak.stock_sector_fund_flow_hist, symbol=board["name"]
                )
                if isinstance(flow_df, pd.DataFrame) and not flow_df.empty:
                    flow_source = "stock_sector_fund_flow_hist"
                    flow_df = flow_df.sort_values("日期")
                    for _, row in flow_df.iterrows():
                        td = self._to_trade_date_yyyymmdd(row.get("日期"))
                        flow_map[td] = {
                            "main_net_inflow": self._safe_float(
                                row.get("主力净流入-净额")
                            ),
                            "net_amount_rate": self._safe_float(
                                row.get("主力净流入-净占比")
                            ),
                        }
            except Exception as flow_err:
                self.logger.debug(
                    f"Akshare sector flow history unavailable for {board['name']}: {flow_err}"
                )

            records: List[Dict[str, Any]] = []
            for _, row in hist_df.iterrows():
                td = self._to_trade_date_yyyymmdd(row.get("日期"))
                rec = {
                    "trade_date": td,
                    "close": self._safe_float(row.get("收盘")),
                    "pct_chg": self._safe_float(row.get("涨跌幅")),
                    "vol": self._safe_float(row.get("成交量")),
                    "turnover_rate": self._safe_float(row.get("换手率")),
                }
                flow = flow_map.get(td)
                if flow and flow.get("main_net_inflow") is not None:
                    rec["main_net_inflow"] = round(float(flow["main_net_inflow"]), 2)
                    rec["retail_net_inflow"] = None
                    rec["total_net_inflow"] = round(float(flow["main_net_inflow"]), 2)
                    if flow.get("net_amount_rate") is not None:
                        rec["net_amount_rate"] = round(float(flow["net_amount_rate"]), 2)
                records.append(rec)

            has_flow = any("main_net_inflow" in r for r in records)
            total_main = sum(float(r.get("main_net_inflow", 0)) for r in records)
            total_pct_chg = sum(float(r.get("pct_chg", 0) or 0) for r in records)
            if has_flow:
                trend = "主力资金持续流入" if total_main > 0 else "主力资金持续流出"
            else:
                trend = "仅行情数据"

            result = {
                "component_type": "sector_money_flow",
                "source": "akshare",
                "sector_name": board["name"],
                "index_code": board.get("code", ""),
                "days": len(records),
                "has_money_flow": has_flow,
                "amount_unit": "unknown",
                "records": records,
                "summary": {
                    "total_pct_chg": round(total_pct_chg, 2),
                    "total_main_net": (round(total_main, 2) if has_flow else None),
                    "trend": trend,
                    "flow_source": flow_source,
                    "amount_unit": "unknown",
                },
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.warning(
                "Akshare get_sector_money_flow_history failed for "
                f"{query_name or query_sector_id}: {e}"
            )
            raise ValueError(f"Failed to get sector money flow: {e}")

    async def get_north_bound_flow(self, days: int = 30) -> Dict[str, Any]:
        """Get north-bound flow series via AkShare."""
        cache_key = f"akshare:hsgt:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.stock_hsgt_hist_em)
            if df is None or df.empty:
                return {"error": "No north bound flow data", "source": "akshare"}
            df = df.copy()
            if "日期" not in df.columns:
                raise ValueError("No 日期 column in stock_hsgt_hist_em")
            df["日期"] = df["日期"].astype(str)
            df = df.sort_values("日期").tail(days)

            dates = [str(x) for x in df["日期"].tolist()]
            total = [
                self._safe_float(v) or 0.0
                for v in df.get("当日成交净买额", pd.Series(dtype=float)).tolist()
            ]

            result = {
                "component_type": "north_bound_flow",
                "source": "akshare",
                "data": {
                    "dates": dates,
                    "hk_to_sh": [0.0 for _ in dates],
                    "hk_to_sz": [0.0 for _ in dates],
                    "total": total,
                },
                "summary": {
                    "total_net": round(sum(total), 2),
                    "period_days": len(dates),
                },
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.warning(f"Akshare get_north_bound_flow failed: {e}")
            raise ValueError(f"Failed to get north bound flow: {e}")

    async def get_market_liquidity(self, days: int = 60) -> Dict[str, Any]:
        """Get market liquidity (north flow + margin) via AkShare."""
        cache_key = f"akshare:market_liquidity:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            north_result = await self.get_north_bound_flow(days)
            north_flow: List[Dict[str, Any]] = []
            if isinstance(north_result, dict) and north_result.get("data"):
                nd = north_result["data"]
                dates = nd.get("dates") or []
                totals = nd.get("total") or []
                hk_to_sh = nd.get("hk_to_sh") or [0.0] * len(dates)
                hk_to_sz = nd.get("hk_to_sz") or [0.0] * len(dates)
                for i, d in enumerate(dates):
                    north_flow.append(
                        {
                            "trade_date": self._to_trade_date_yyyymmdd(d),
                            "hgt": hk_to_sh[i] if i < len(hk_to_sh) else 0.0,
                            "sgt": hk_to_sz[i] if i < len(hk_to_sz) else 0.0,
                            "north_money": totals[i] if i < len(totals) else 0.0,
                        }
                    )

            margin: List[Dict[str, Any]] = []
            sh_df, sz_df = await asyncio.gather(
                self._run(ak.macro_china_market_margin_sh),
                self._run(ak.macro_china_market_margin_sz),
                return_exceptions=True,
            )
            merged: Dict[str, Dict[str, float]] = {}

            def _merge_margin(df_like: Any) -> None:
                if not isinstance(df_like, pd.DataFrame) or df_like.empty:
                    return
                for _, row in df_like.iterrows():
                    td = self._to_trade_date_yyyymmdd(row.get("日期"))
                    if not td:
                        continue
                    item = merged.setdefault(
                        td, {"rzye": 0.0, "rqye": 0.0, "rzrqye": 0.0}
                    )
                    item["rzye"] += self._safe_float(row.get("融资余额")) or 0.0
                    item["rqye"] += self._safe_float(row.get("融券余额")) or 0.0
                    item["rzrqye"] += self._safe_float(row.get("融资融券余额")) or 0.0

            _merge_margin(sh_df)
            _merge_margin(sz_df)

            for td in sorted(merged.keys())[-days:]:
                v = merged[td]
                margin.append(
                    {
                        "trade_date": td,
                        "rzye": v["rzye"],
                        "rqye": v["rqye"],
                        "rzrqye": v["rzrqye"],
                    }
                )

            result = {
                "component_type": "market_liquidity",
                "source": "akshare",
                "data": {
                    "north_flow": north_flow,
                    "margin": margin,
                },
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.warning(f"Akshare get_market_liquidity failed: {e}")
            raise ValueError(f"Failed to get market liquidity: {e}")

    async def _get_all_stocks_cached(self) -> List[Dict]:
        """Helper to get all stocks with caching."""
        cache_key = "akshare:all_stocks_v2"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.stock_zh_a_spot_em)
            if df.empty:
                return []

            stocks = []
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                name = str(row.get("名称", ""))
                if not code:
                    continue

                if code.startswith("6"):
                    exchange = "SSE"
                elif code.startswith("0") or code.startswith("3"):
                    exchange = "SZSE"
                elif code.startswith("8"):
                    exchange = "BSE"
                else:
                    exchange = "SSE"

                stocks.append(
                    {"ticker": f"{exchange}:{code}", "code": code, "name": name}
                )

            await self.cache.set(cache_key, stocks, ttl=3600)
            return stocks
        except Exception as e:
            self.logger.warning(f"Failed to fetch all stocks: {e}")
            return []

    async def get_financials(self, ticker: str) -> Dict[str, Any]:
        """Fetch financial statements and company info for A-share stocks."""
        cache_key = f"akshare:financials:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        symbol = self._to_ak_code(ticker)

        try:
            # Fetch all financial data in parallel
            balance_task = self._run(
                ak.stock_financial_report_sina, stock=symbol, symbol="资产负债表"
            )
            income_task = self._run(
                ak.stock_financial_report_sina, stock=symbol, symbol="利润表"
            )
            cashflow_task = self._run(
                ak.stock_financial_report_sina, stock=symbol, symbol="现金流量表"
            )
            indicator_task = self._run(
                ak.stock_financial_analysis_indicator, symbol=symbol
            )
            company_task = self._run(ak.stock_individual_info_em, symbol=symbol)

            balance_df, income_df, cashflow_df, indicator_df, company_df = (
                await asyncio.gather(
                    balance_task,
                    income_task,
                    cashflow_task,
                    indicator_task,
                    company_task,
                    return_exceptions=True,
                )
            )

            # Convert company DataFrame to dict
            company_info = {}
            if (
                not isinstance(company_df, Exception)
                and company_df is not None
                and not company_df.empty
            ):
                for _, row in company_df.iterrows():
                    key = row.get("item", row.get("项目", ""))
                    value = row.get("value", row.get("值", ""))
                    if key:
                        company_info[key] = value

            # Helper function to convert DataFrame to serializable format
            def df_to_dict(df):
                if isinstance(df, Exception) or df is None or df.empty:
                    return None
                # Convert DataFrame to list of dicts (JSON serializable)
                return df.to_dict("records")

            result = {
                "balance_sheet": df_to_dict(balance_df),
                "income_statement": df_to_dict(income_df),
                "cash_flow": df_to_dict(cashflow_df),
                "financial_indicators": df_to_dict(indicator_df),
                "company_info": company_info,
            }

            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to fetch financials for {ticker}: {e}")
            raise ValueError(f"Failed to fetch financials for {ticker}: {e}")

    async def get_financial_statements(
        self,
        ticker: str,
        report_type: str = "all",
        periods: int | None = None,
    ) -> Dict[str, Any]:
        """Fetch complete financial statements with YoY/QoQ calculations.

        Unified interface matching TushareAdapter for A-share stocks using Akshare.

        Args:
            ticker: Asset ticker in internal format (e.g., SSE:600519)
            report_type: "quarterly" | "annual" | "all" (default: "all")
            periods: Number of periods to return. None = all available history.

        Returns:
            Dictionary containing:
            - income_statement: {quarterly: [...], annual: [...]}
            - balance_sheet: {quarterly: [...], annual: [...]}
            - cash_flow: {quarterly: [...], annual: [...]}
            - Each record includes YoY (同比) and QoQ (环比) for key metrics
        """
        cache_key = f"akshare:financial_statements:{ticker}:{report_type}:{periods}:v1"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        symbol = self._to_ak_code(ticker)

        try:
            # Fetch all financial statements in parallel
            balance_task = self._run(
                ak.stock_financial_report_sina, stock=symbol, symbol="资产负债表"
            )
            income_task = self._run(
                ak.stock_financial_report_sina, stock=symbol, symbol="利润表"
            )
            cashflow_task = self._run(
                ak.stock_financial_report_sina, stock=symbol, symbol="现金流量表"
            )

            balance_df, income_df, cashflow_df = await asyncio.gather(
                balance_task, income_task, cashflow_task, return_exceptions=True
            )

            # Define core fields for YoY/QoQ (mapped to common field names in Sina data)
            # Note: Sina field names may vary; these are typical column names
            income_yoy_fields = [
                "营业收入", "营业成本", "营业利润", "利润总额",
                "净利润", "归属于母公司所有者的净利润"
            ]
            balance_yoy_fields = [
                "资产总计", "负债合计", "所有者权益合计",
                "货币资金", "应收账款", "存货"
            ]
            cashflow_yoy_fields = [
                "经营活动产生的现金流量净额", "投资活动产生的现金流量净额",
                "筹资活动产生的现金流量净额"
            ]

            def process_df(df, yoy_fields, is_quarterly=False):
                """Process DataFrame: add YoY/QoQ calculations."""
                if isinstance(df, Exception):
                    self.logger.warning(f"Failed to fetch data: {df}")
                    return []
                if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                    return []

                # Try to identify date column (handle encoding issues)
                date_col = None
                for col in df.columns:
                    col_str = str(col).strip()
                    if col_str in ["报告期", "日期", "date", "end_date"]:
                        date_col = col
                        break
                    # Try first column if no match
                    if date_col is None and col == df.columns[0]:
                        date_col = col

                if date_col is None:
                    self.logger.warning("No date column found in DataFrame")
                    return df.to_dict("records")

                # Rename to standard end_date
                if date_col != "end_date":
                    df = df.rename(columns={date_col: "end_date"})

                # Convert end_date to string format YYYYMMDD for consistency
                try:
                    df["end_date"] = df["end_date"].astype(str).str[:8]
                except Exception:
                    pass

                # Sort by end_date (ascending for YoY/QoQ calculation)
                df = df.sort_values("end_date", ascending=True)

                # Calculate YoY and QoQ
                df = self._add_yoy_qoq_akshare(df, yoy_fields, is_quarterly)

                # Sort by time descending (newest first)
                df = df.sort_values("end_date", ascending=False)

                # Limit rows
                if periods is not None:
                    df = df.head(periods)

                # Handle NaN
                df = df.where(df.notnull(), None)
                return df.to_dict("records")

            # Note: Akshare's stock_financial_report_sina returns combined quarterly+annual data
            # We need to separate them based on date patterns (0331, 0630, 0930, 1231)
            def separate_quarterly_annual(df):
                """Separate DataFrame into quarterly and annual reports."""
                if isinstance(df, Exception) or df is None:
                    return None, None
                if not isinstance(df, pd.DataFrame) or df.empty:
                    return None, None

                # Identify date column (handle encoding issues)
                date_col = None
                for col in df.columns:
                    col_str = str(col).strip()
                    if col_str in ["报告期", "日期", "date", "end_date"]:
                        date_col = col
                        break
                    # Try first column if no match
                    if date_col is None and col == df.columns[0]:
                        date_col = col

                if date_col is None:
                    return None, None

                # Work with a copy
                df_work = df.copy()

                # Rename to end_date
                if date_col != "end_date":
                    df_work = df_work.rename(columns={date_col: "end_date"})

                # Normalize date format to YYYYMMDD
                try:
                    df_work["end_date"] = df_work["end_date"].astype(str).str[:8]
                except Exception:
                    pass

                # Separate based on month
                df_work["_month"] = df_work["end_date"].astype(str).str[4:6]

                # Annual reports end in 12 (December)
                annual_df = df_work[df_work["_month"] == "12"].drop(columns=["_month"])

                # Quarterly reports end in 03, 06, 09 (but not annual)
                quarterly_df = df_work[df_work["_month"].isin(["03", "06", "09"])].drop(columns=["_month"])

                return quarterly_df, annual_df

            # Separate quarterly and annual data
            income_q, income_a = separate_quarterly_annual(income_df)
            balance_q, balance_a = separate_quarterly_annual(balance_df)
            cashflow_q, cashflow_a = separate_quarterly_annual(cashflow_df)

            result = {
                "ts_code": symbol,
                "source": "akshare",
                "income_statement": {
                    "quarterly": process_df(income_q, income_yoy_fields, is_quarterly=True) if report_type in ("all", "quarterly") else [],
                    "annual": process_df(income_a, income_yoy_fields, is_quarterly=False) if report_type in ("all", "annual") else [],
                },
                "balance_sheet": {
                    "quarterly": process_df(balance_q, balance_yoy_fields, is_quarterly=True) if report_type in ("all", "quarterly") else [],
                    "annual": process_df(balance_a, balance_yoy_fields, is_quarterly=False) if report_type in ("all", "annual") else [],
                },
                "cash_flow": {
                    "quarterly": process_df(cashflow_q, cashflow_yoy_fields, is_quarterly=True) if report_type in ("all", "quarterly") else [],
                    "annual": process_df(cashflow_a, cashflow_yoy_fields, is_quarterly=False) if report_type in ("all", "annual") else [],
                },
            }

            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to fetch financial statements for {ticker}: {e}")
            raise ValueError(f"Failed to fetch financial statements for {ticker}: {e}")

    def _add_yoy_qoq_akshare(
        self, df: pd.DataFrame, yoy_fields: List[str], is_quarterly: bool
    ) -> pd.DataFrame:
        """Add Year-over-Year and Quarter-over-Quarter calculations for Akshare data.

        Args:
            df: DataFrame with financial data sorted by end_date (ascending)
            yoy_fields: List of field names to calculate YoY/QoQ for
            is_quarterly: If True, also calculate QoQ

        Returns:
            DataFrame with added _yoy and _qoq columns for each field
        """
        df = df.copy()

        # Create year and month columns for alignment
        if "end_date" in df.columns:
            df["_year"] = df["end_date"].astype(str).str[:4].astype(int)
            df["_month"] = df["end_date"].astype(str).str[4:6].astype(int)

        for field in yoy_fields:
            if field not in df.columns:
                continue

            yoy_col = f"{field}_yoy"
            qoq_col = f"{field}_qoq"

            # Calculate YoY: current vs same period last year
            df[yoy_col] = None
            if "_year" in df.columns:
                for i in range(len(df)):
                    curr_year = df.iloc[i]["_year"]
                    curr_month = df.iloc[i]["_month"]
                    curr_val = df.iloc[i][field]

                    if curr_val is None or pd.isna(curr_val):
                        continue

                    # Find same period last year
                    last_year_mask = (df["_year"] == curr_year - 1) & (df["_month"] == curr_month)
                    last_year_rows = df[last_year_mask]

                    if len(last_year_rows) > 0:
                        last_year_val = last_year_rows.iloc[0][field]
                        if last_year_val is not None and not pd.isna(last_year_val) and last_year_val != 0:
                            df.iloc[i, df.columns.get_loc(yoy_col)] = round(
                                (curr_val - last_year_val) / abs(last_year_val) * 100, 2
                            )

            # Calculate QoQ: only for quarterly data
            if is_quarterly:
                df[qoq_col] = None
                for i in range(1, len(df)):
                    curr_val = df.iloc[i][field]
                    prev_val = df.iloc[i - 1][field]

                    if curr_val is None or pd.isna(curr_val) or prev_val is None or pd.isna(prev_val):
                        continue

                    if prev_val != 0:
                        df.iloc[i, df.columns.get_loc(qoq_col)] = round(
                            (curr_val - prev_val) / abs(prev_val) * 100, 2
                        )

        # Clean up temporary columns
        df = df.drop(columns=["_year", "_month"], errors="ignore")
        return df

    async def get_filings(
        self,
        ticker: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 10,
        filing_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch A-share filings/announcements from CNINFO.

        Args:
            ticker: Stock ticker (e.g., "SSE:600519" or "600519")
            start_date: Start date for filtering (optional)
            end_date: End date for filtering (optional)
            limit: Maximum number of filings to return
            filing_types: List of filing types (e.g., ["annual", "quarterly"])

        Returns:
            List of filing dictionaries with metadata and PDF URLs
        """
        try:
            # Normalize stock code
            stock_code = _normalize_stock_code(ticker)

            # Use provided filing_types or default to all
            report_types = filing_types or ["annual", "semi-annual", "quarterly"]

            # Extract years from date range or use recent years
            years = []
            if start_date and end_date:
                start_year = start_date.year
                end_year = end_date.year
                years = list(range(start_year, end_year + 1))

            # Fetch data from CNINFO
            filings_data = await fetch_cninfo_data(
                stock_code=stock_code,
                report_types=report_types,
                years=years,
                quarters=[],  # No quarter filtering by default
                limit=limit,
            )

            # Transform to standard format
            results = []
            for filing in filings_data:
                # Filter by date if specified
                if start_date or end_date:
                    filing_date_str = filing.get("filing_date", "")
                    try:
                        filing_date = datetime.strptime(filing_date_str, "%Y-%m-%d")
                        if start_date and filing_date < start_date:
                            continue
                        if end_date and filing_date > end_date:
                            continue
                    except ValueError:
                        pass  # Skip date filtering if parsing fails

                result = {
                    "filing_id": filing.get("announcement_id", ""),
                    "symbol": filing.get("stock_code", ""),
                    "company_name": filing.get("company", ""),
                    "exchange": filing.get("market", ""),
                    "title": filing.get("announcement_title", ""),
                    "type": filing.get("doc_type", ""),
                    "form": self._map_report_type_to_form(filing.get("doc_type", "")),
                    "filing_date": filing.get("filing_date", ""),
                    "period_of_report": filing.get("period_of_report", ""),
                    "url": filing.get("pdf_url", ""),
                    "content_summary": filing.get("announcement_title", "")[:200],
                }
                results.append(result)

            return results[:limit]

        except Exception as e:
            self.logger.error(f"Failed to fetch filings for {ticker}: {e}")
            return []

    def _map_report_type_to_form(self, doc_type: str) -> str:
        """Map English report type to Chinese form name.

        Args:
            doc_type: Report type ("annual", "semi-annual", "quarterly")

        Returns:
            Chinese form name
        """
        mapping = {
            "annual": "年报",
            "semi-annual": "半年报",
            "quarterly": "季报",
        }
        return mapping.get(doc_type, doc_type)

    # Keep extra methods for NewsService usage
    async def get_news(self, ticker: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch specific stock news from Eastmoney."""
        # ... (Keep existing implementation)
        # For brevity, I'm not pasting the full news implementation here again unless requested,
        # but in a real refactor I would keep it.
        # I will include it to avoid breaking NewsService.
        cache_key = f"akshare:news:{ticker}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        symbol = self._to_ak_code(ticker)
        try:
            import requests
            import json
            from datetime import datetime as dt

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://guba.eastmoney.com/",
            }

            url = "https://search-api-web.eastmoney.com/search/jsonp"
            params = {
                "cb": "jQuery_callback",
                "param": json.dumps(
                    {
                        "uid": "",
                        "keyword": symbol,
                        "type": ["cmsArticleWebOld"],
                        "client": "web",
                        "clientType": "web",
                        "clientVersion": "curr",
                        "param": {
                            "cmsArticleWebOld": {
                                "searchScope": "default",
                                "sort": "default",
                                "pageIndex": 1,
                                "pageSize": max(limit, 20),
                                "preTag": "",
                                "postTag": "",
                            }
                        },
                    }
                ),
                "_": str(int(dt.now().timestamp() * 1000)),
            }

            def fetch_news():
                response = requests.get(url, params=params, headers=headers, timeout=10)
                if response.status_code != 200:
                    return []
                text = response.text
                start = text.find("(")
                end = text.rfind(")")
                if start == -1 or end == -1:
                    return []
                json_text = text[start + 1 : end]
                data = json.loads(json_text)
                return data.get("result", {}).get("cmsArticleWebOld", [])

            articles = await self._run(fetch_news)

            news_list = []
            for article in articles[:limit]:
                news_list.append(
                    {
                        "title": article.get("title", ""),
                        "url": article.get("url", ""),
                        "publish_time": article.get("date", "")
                        or article.get("showTime", ""),
                        "source": article.get("mediaName", "Eastmoney"),
                        "snippet": article.get("content", "")[:200],
                        "keyword": symbol,
                    }
                )

            await self.cache.set(cache_key, news_list, ttl=600)
            return news_list
        except Exception as e:
            self.logger.error(f"Failed to fetch news for {ticker}: {e}")
            return []


    async def get_mainbz_info(self, ticker: str) -> Dict[str, Any]:
        """获取主营业务构成（来自东方财富）.

        Args:
            ticker: 股票代码 (如 SSE:600519 或 600519)

        Returns:
            主营业务构成数据，格式与 Tushare 兼容
        """
        cache_key = f"akshare:mainbz:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        symbol = self._to_ak_code(ticker)

        # 判断市场类型
        exchange = ""
        if ":" in ticker:
            exchange, code = ticker.split(":", 1)

        # stock_zygc_em 需要市场前缀
        # 只支持 A 股 (SSE/SZSE/BSE)
        if exchange == "HKEX":
            return {
                "component_type": "mainbz_info",
                "source": "akshare",
                "ts_code": self._to_ts_code(ticker),
                "rows": [],
                "error": "港股主营业务构成需要使用其他接口",
            }

        # 构建前缀
        if exchange == "SSE":
            prefix = "SH"
        elif exchange == "SZSE":
            prefix = "SZ"
        elif exchange == "BSE":
            prefix = "BJ"
        else:
            # 根据代码判断
            if symbol.startswith("6"):
                prefix = "SH"
            elif symbol.startswith(("0", "3")):
                prefix = "SZ"
            elif symbol.startswith("8"):
                prefix = "BJ"
            else:
                prefix = "SH"  # 默认

        ak_symbol = f"{prefix}{symbol}"

        try:
            # 使用东方财富主营构成接口
            df = await self._run(ak.stock_zygc_em, symbol=ak_symbol)

            if df is None or df.empty:
                return {
                    "component_type": "mainbz_info",
                    "source": "akshare",
                    "ts_code": self._to_ts_code(ticker),
                    "rows": [],
                }

            # 转换为与 Tushare 兼容的格式
            rows = []
            for _, row in df.iterrows():
                row_dict = row.where(pd.notnull(row), None).to_dict()

                # 标准化字段名 (akshare 实际返回的列名)
                end_date = str(row_dict.get("报告日期") or row_dict.get("报告期", ""))
                biz_type = row_dict.get("分类类型", "")  # 按产品分类/按地区分类
                item_name = row_dict.get("主营构成", "")  # 具体产品/地区名称

                # 映射分类类型到中文
                type_map = {
                    "分产品类型": "分产品",
                    "分产品": "分产品",
                    "按产品分类": "分产品",
                    "分地区类型": "分地区",
                    "分地区": "分地区",
                    "按地区分类": "分地区",
                    "分行业类型": "分行业",
                    "分行业": "分行业",
                    "按行业分类": "分行业",
                }
                biz_type_cn = type_map.get(biz_type, "分行业")

                # 获取数据并解析单位
                revenue_raw = row_dict.get("主营收入")
                cost_raw = row_dict.get("主营成本")
                gross_profit_raw = row_dict.get("主营利润")

                # 使用 _parse_number 解析数值
                revenue = self._parse_number(revenue_raw)
                cost = self._parse_number(cost_raw)
                gross_profit = self._parse_number(gross_profit_raw)

                rows.append({
                    "报告期": end_date,
                    "分类类型": biz_type_cn,
                    "业务名称": item_name,
                    "主营收入(元)": revenue,
                    "主营成本(元)": cost,
                    "主营利润(元)": gross_profit,
                })

            result = {
                "component_type": "mainbz_info",
                "source": "akshare",
                "ts_code": self._to_ts_code(ticker),
                "rows": rows,
            }

            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get main business info from akshare: {e}")
            raise ValueError(f"Failed to get main business info: {e}")

    async def get_profit_forecast(self, ticker: str) -> Dict[str, Any]:
        """获取盈利预测（来自东方财富）.

        Args:
            ticker: 股票代码 (如 SSE:600519)

        Returns:
            盈利预测数据
        """
        cache_key = f"akshare:profit_forecast:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        # 提取纯股票代码
        symbol = self._to_ak_code(ticker)

        try:
            # stock_profit_forecast_em 接口参数是行业名称，不是股票代码
            # 使用空字符串获取全部数据，然后过滤
            df = await self._run(ak.stock_profit_forecast_em, symbol="")

            if df is None or df.empty:
                return {
                    "component_type": "profit_forecast",
                    "source": "akshare",
                    "ticker": ticker,
                    "rows": [],
                }

            # 过滤出目标股票的数据
            # akshare 返回的列名包含 "代码" 列
            filtered_df = df[df["代码"] == symbol] if "代码" in df.columns else df

            if filtered_df.empty:
                return {
                    "component_type": "profit_forecast",
                    "source": "akshare",
                    "ticker": ticker,
                    "rows": [],
                }

            # 转换为标准格式
            rows = []
            for _, row in filtered_df.iterrows():
                row_dict = row.where(pd.notnull(row), None).to_dict()

                rows.append({
                    "预测年份": str(row_dict.get("预测年份", "")),
                    "预测机构": row_dict.get("预测机构", ""),
                    "预测研报": row_dict.get("预测研报", ""),
                    "预测股东净利润(元)": self._parse_number(row_dict.get("预测股本净利润")),
                    "预测每股收益(元)": self._parse_number(row_dict.get("预测每股收益")),
                })

            result = {
                "component_type": "profit_forecast",
                "source": "akshare",
                "ticker": ticker,
                "rows": rows,
            }

            await self.cache.set(cache_key, result, ttl=3600 * 6)  # 盈利预测更新较慢
            return result

        except Exception as e:
            self.logger.error(f"Failed to get profit forecast from akshare: {e}")
            # 不抛出异常，返回空数据或降级
            return {
                "component_type": "profit_forecast",
                "source": "akshare",
                "ticker": ticker,
                "rows": [],
                "error": str(e)
            }

    def _to_ts_code(self, ticker: str) -> str:
        """转换内部格式到 ts_code 格式."""
        if "." in ticker:
            return ticker
        if ":" in ticker:
            exchange, code = ticker.split(":", 1)
            suffix_map = {
                "SSE": "SH",
                "SZSE": "SZ",
                "BSE": "BJ",
            }
            suffix = suffix_map.get(exchange, "SH")
            return f"{code}.{suffix}"
        # 默认处理
        if ticker.startswith("6"):
            return f"{ticker}.SH"
        elif ticker.startswith(("0", "3")):
            return f"{ticker}.SZ"
        elif ticker.startswith("8"):
            return f"{ticker}.BJ"
        return f"{ticker}.SH"

    def _parse_date(self, date_val: Any) -> str:
        """解析日期格式."""
        if date_val is None:
            return ""
        date_str = str(date_val)
        # 尝试解析各种日期格式
        for fmt in ["%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y%m%d")
            except ValueError:
                continue
        return date_str.replace("-", "").replace("/", "")[:8]

    def _parse_number(self, val: Any) -> float | None:
        """解析数字."""
        if val is None or val == "" or val == "-":
            return None
        try:
            if isinstance(val, (int, float)):
                return float(val)
            # 处理字符串格式（可能包含亿、万等单位）
            clean = str(val).replace(",", "").strip()
            if clean.endswith("亿"):
                return float(clean[:-1]) * 100000000
            elif clean.endswith("万"):
                return float(clean[:-1]) * 10000
            return float(clean)
        except (ValueError, TypeError):
            return None

    async def get_money_supply(self, months: int = 60) -> Dict[str, Any]:
        """获取货币供应量数据 (M0/M1/M2)."""
        cache_key = f"akshare:money_supply:{months}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.macro_china_money_supply)
            if df is None or df.empty:
                return {"data": [], "source": "akshare"}

            col_map = {
                "月份": "date",
                "货币和准货币(M2)数量(亿元)": "m2",
                "货币(M1)数量(亿元)": "m1",
                "流通中的现金(M0)数量(亿元)": "m0",
                "货币和准货币(M2)同比增长(%)": "m2_yoy",
                "货币(M1)同比增长(%)": "m1_yoy",
                "流通中的现金(M0)同比增长(%)": "m0_yoy",
            }
            df = df.rename(columns=col_map)
            data = df.tail(months).to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {"data": data, "source": "akshare"}
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get money supply: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    async def get_interest_rates(
        self, shibor_days: int = 252, lpr_months: int = 60
    ) -> Dict[str, Any]:
        """获取利率数据 (Shibor + LPR)."""
        cache_key = f"akshare:interest_rates:{shibor_days}:{lpr_months}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        result: Dict[str, Any] = {"data": {}, "source": "akshare"}

        try:
            # Shibor data
            df_shibor = await self._run(ak.macro_china_shibor_all)
            if df_shibor is not None and not df_shibor.empty:
                col_map = {
                    "日期": "date",
                    "隔夜": "overnight",
                    "1周": "week_1",
                    "2周": "week_2",
                    "1个月": "month_1",
                    "3个月": "month_3",
                    "6个月": "month_6",
                    "9个月": "month_9",
                    "1年": "year_1",
                }
                df_shibor = df_shibor.rename(columns=col_map)
                shibor_data = df_shibor.tail(shibor_days).to_dict(orient="records")
                for item in shibor_data:
                    for k, v in item.items():
                        if hasattr(v, "item"):
                            item[k] = v.item()
                result["data"]["shibor"] = shibor_data
        except Exception as e:
            self.logger.error(f"Failed to get shibor: {e}")
            result["data"]["shibor"] = []

        try:
            # LPR data
            df_lpr = await self._run(ak.macro_china_lpr)
            if df_lpr is not None and not df_lpr.empty:
                col_map = {
                    "TRADE_DATE": "date",
                    "LPR1Y": "lpr_1y",
                    "LPR5Y": "lpr_5y",
                }
                df_lpr = df_lpr.rename(columns=col_map)
                lpr_data = df_lpr.tail(lpr_months).to_dict(orient="records")
                for item in lpr_data:
                    for k, v in item.items():
                        if hasattr(v, "item"):
                            item[k] = v.item()
                result["data"]["lpr"] = lpr_data
        except Exception as e:
            self.logger.error(f"Failed to get LPR: {e}")
            result["data"]["lpr"] = []

        await self.cache.set(cache_key, result, ttl=3600)
        return result

    async def get_inflation_data(self, months: int = 60) -> Dict[str, Any]:
        """获取通胀数据 (CPI/PPI 月度同比)."""
        cache_key = f"akshare:inflation:{months}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        result: Dict[str, Any] = {"data": {}, "source": "akshare"}

        try:
            df_cpi = await self._run(ak.macro_china_cpi_monthly)
            if df_cpi is not None and not df_cpi.empty:
                result["data"]["cpi"] = df_cpi.tail(months).to_dict(orient="records")
        except Exception as e:
            self.logger.error(f"Failed to get CPI: {e}")

        try:
            df_ppi = await self._run(ak.macro_china_ppi)
            if df_ppi is not None and not df_ppi.empty:
                result["data"]["ppi"] = df_ppi.tail(months).to_dict(orient="records")
        except Exception as e:
            self.logger.error(f"Failed to get PPI: {e}")

        # Clean numpy types in records
        for key in ("cpi", "ppi"):
            records = result["data"].get(key, [])
            if isinstance(records, list):
                for item in records:
                    for k, v in item.items():
                        if hasattr(v, "item"):
                            item[k] = v.item()

        await self.cache.set(cache_key, result, ttl=3600)
        return result

    async def get_pmi_data(self, months: int = 60) -> Dict[str, Any]:
        """获取PMI数据 (制造业/非制造业)."""
        cache_key = f"akshare:pmi:{months}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.macro_china_pmi)
            if df is None or df.empty:
                return {"data": [], "source": "akshare"}

            data = df.tail(months).to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {"data": data, "source": "akshare"}
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get PMI: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    async def get_gdp_data(self, quarters: int = 20) -> Dict[str, Any]:
        """获取GDP季度数据."""
        cache_key = f"akshare:gdp:{quarters}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.macro_china_gdp)
            if df is None or df.empty:
                return {"data": [], "source": "akshare"}

            data = df.tail(quarters).to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {"data": data, "source": "akshare"}
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get GDP: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    async def get_social_financing(self, months: int = 60) -> Dict[str, Any]:
        """获取社会融资规模数据 (新增人民币信贷作为替代)."""
        cache_key = f"akshare:social_financing:{months}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        result: Dict[str, Any] = {"data": [], "source": "akshare"}

        # Try primary API first
        try:
            df = await self._run(ak.macro_china_shrzgm)
            if df is not None and not df.empty:
                data = df.tail(months).to_dict(orient="records")
                for item in data:
                    for k, v in item.items():
                        if hasattr(v, "item"):
                            item[k] = v.item()
                result["data"] = data
                await self.cache.set(cache_key, result, ttl=3600)
                return result
        except Exception as e:
            self.logger.warning(f"Primary social financing API failed: {e}")

        # Fallback to new_financial_credit (新增人民币信贷)
        try:
            df = await self._run(ak.macro_china_new_financial_credit)
            if df is not None and not df.empty:
                data = df.tail(months).to_dict(orient="records")
                for item in data:
                    for k, v in item.items():
                        if hasattr(v, "item"):
                            item[k] = v.item()
                result["data"] = data
                result["note"] = "Using macro_china_new_financial_credit as fallback"
                await self.cache.set(cache_key, result, ttl=3600)
                return result
        except Exception as e:
            self.logger.error(f"Failed to get social financing: {e}")
            result["error"] = str(e)

        return result

    async def get_ggt_daily(self, days: int = 60) -> Dict[str, Any]:
        """获取港股通每日资金流向数据."""
        cache_key = f"akshare:ggt_daily:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            records = []
            for symbol in ["沪股通", "深股通"]:
                df = await self._run(ak.stock_hsgt_hist_em, symbol=symbol)
                if df is not None and not df.empty:
                    items = df.tail(days).to_dict(orient="records")
                    for item in items:
                        item["channel"] = symbol
                        for k, v in item.items():
                            if hasattr(v, "item"):
                                item[k] = v.item()
                    records.extend(items)

            result = {
                "component_type": "ggt_daily",
                "source": "akshare",
                "data": records,
                "summary": {
                    "total_records": len(records),
                    "channels": ["沪股通", "深股通"],
                },
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get GGT daily: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    async def get_market_breadth(
        self, days: int = 20
    ) -> Dict[str, Any]:
        """Get market breadth indicators: up/down count, new high/low, median return.

        Args:
            days: Number of trading days to look back for new high/low calculation

        Returns:
            Dictionary containing:
            - up_count: Number of stocks with positive return
            - down_count: Number of stocks with negative return
            - unchanged_count: Number of stocks with zero return
            - new_high_count: Stocks at 20-day high (simplified)
            - new_low_count: Stocks at 20-day low (simplified)
            - median_return: Median daily return
            - advance_decline_ratio: Advance/Decline ratio
            - date: The date of the snapshot
        """
        cache_key = f"akshare:market_breadth:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # Get all A-share stocks real-time data
            df = await self._run(ak.stock_zh_a_spot_em)
            if df.empty:
                raise ValueError("No stock data available")

            # Calculate up/down counts
            up_count = 0
            down_count = 0
            unchanged_count = 0
            total_returns = []

            for _, row in df.iterrows():
                pct_change = self._safe_float(row.get("涨跌幅"))
                if pct_change is not None:
                    total_returns.append(pct_change)
                    if pct_change > 0:
                        up_count += 1
                    elif pct_change < 0:
                        down_count += 1
                    else:
                        unchanged_count += 1

            # Calculate median return
            import statistics
            median_return = statistics.median(total_returns) if total_returns else 0.0

            # Calculate advance/decline ratio
            advance_decline_ratio = (
                up_count / down_count if down_count > 0 else 0.0
            )

            # For new high/low, we need historical data
            # Simplified: count stocks at daily limit high/low
            new_high_count = len([r for r in total_returns if r > 9.05])  # Stocks up more than 5%
            new_low_count = len([r for r in total_returns if r < -0.05])  # Stocks down more than 5%

            result = {
                "component_type": "market_breadth",
                "source": "akshare",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "data": {
                    "up_count": up_count,
                    "down_count": down_count,
                    "unchanged_count": unchanged_count,
                    "total_stocks": len(df),
                    "new_high_count": new_high_count,
                    "new_low_count": new_low_count,
                    "median_return": round(median_return, 4),
                    "advance_decline_ratio": round(advance_decline_ratio, 2),
                },
            }

            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get market breadth: {e}")
            raise ValueError(f"Failed to get market breadth: {e}")

    async def get_relative_strength(
        self,
        symbol: str,
        benchmark: str = "000300",
        days: int = 60,
    ) -> Dict[str, Any]:
        """Calculate relative strength (RS) of a stock vs benchmark index.

        RS = (stock_return - benchmark_return) over the lookback period.
        Positive RS means outperformance; negative means underperformance.

        Args:
            symbol: Stock code without exchange prefix (e.g. 600519, 000001)
            benchmark: Index code (default 000300 = CSI300)
            days: Lookback trading days (default 60)

        Returns:
            Dict with symbol, benchmark, rs_pct, trend, and history.
        """
        cache_key = f"akshare:rs:{symbol}:{benchmark}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # Fetch stock price history
            df_stock = await self._run(
                ak.stock_zh_a_hist,
                symbol=symbol,
                period="daily",
                adjust="qfq",
            )
            if df_stock is None or df_stock.empty:
                raise ValueError(f"No price data for {symbol}")

            # Fetch benchmark index history (use index-specific API)
            df_bench = await self._run(
                ak.index_zh_a_hist,
                symbol=benchmark,
                period="daily",
            )
            if df_bench is None or df_bench.empty:
                raise ValueError(f"No benchmark data for {benchmark}")

            # Normalize Chinese column names to English
            col_map = {
                "日期": "trade_date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude", "涨跌幅": "pct_change",
                "涨跌额": "change", "换手率": "turnover",
            }
            df_stock = df_stock.rename(columns=col_map).tail(days)
            df_bench = df_bench.rename(columns=col_map).tail(days)

            # Align on common trade dates
            stock_dates = set(df_stock["trade_date"].astype(str))
            bench_dates = set(df_bench["trade_date"].astype(str))
            common = sorted(stock_dates & bench_dates)
            if not common:
                raise ValueError("No overlapping dates between stock and benchmark")

            df_s = df_stock[df_stock["trade_date"].astype(str).isin(common)].copy()
            df_b = df_bench[df_bench["trade_date"].astype(str).isin(common)].copy()
            # Normalize index to string for consistent alignment
            df_s["trade_date"] = df_s["trade_date"].astype(str)
            df_b["trade_date"] = df_b["trade_date"].astype(str)
            df_s = df_s.set_index("trade_date")
            df_b = df_b.set_index("trade_date")

            # Calculate returns and RS
            s_close = df_s["close"].astype(float)
            b_close = df_b["close"].astype(float)

            s_ret = (s_close / s_close.iloc[0] - 1) * 100
            b_ret = (b_close / b_close.iloc[0] - 1) * 100
            rs_series = s_ret - b_ret

            latest_rs = float(rs_series.iloc[-1])
            latest_date = str(rs_series.index[-1])

            if latest_rs > 2:
                trend = "outperform"
            elif latest_rs < -2:
                trend = "underperform"
            else:
                trend = "neutral"

            # Build history list using rs_series index for alignment
            history = []
            for idx in rs_series.index:
                history.append({
                    "trade_date": str(idx),
                    "stock_return_pct": round(float(s_ret.loc[idx]), 2),
                    "benchmark_return_pct": round(float(b_ret.loc[idx]), 2),
                    "rs": round(float(rs_series.loc[idx]), 2),
                })

            result = {
                "symbol": symbol,
                "benchmark": benchmark,
                "days": days,
                "rs_pct": round(latest_rs, 2),
                "trend": trend,
                "history": history,
                "latest_date": latest_date,
                "latest_stock_return_pct": round(float(s_ret.iloc[-1]), 2),
                "latest_benchmark_return_pct": round(float(b_ret.iloc[-1]), 2),
            }

            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get relative strength: {e}")
            raise ValueError(f"Failed to get relative strength: {e}")

    # ------------------------------------------------------------------
    # COL-127: 行业估值与历史分位
    # ------------------------------------------------------------------

    async def get_sector_valuation_metrics(
        self,
        sector_name: str = "",
        days: int = 250,
        sample_size: int = 60,
        sector_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Calculate sector-level valuation metrics using EM board industry API.

        Uses 东方财富行业板块历史行情数据，计算价格分位数作为估值代理指标。
        """
        cache_key = f"akshare:sv:{sector_name}:{sector_id}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            query = sector_name or sector_id or ""
            if not query:
                raise ValueError("sector_name or sector_id is required")

            # Fetch sector board historical prices via EM API
            df_board = await self._run(
                ak.stock_board_industry_hist_em,
                symbol=query,
                period="日k",
                start_date="20200101",
                end_date="20991231",
                adjust="",
            )
            if df_board is None or df_board.empty:
                raise ValueError(f"No board data for {query}")

            # Map Chinese column names
            col_map = {
                "日期": "trade_date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude", "涨跌幅": "pct_change",
                "涨跌额": "change", "换手率": "turnover",
            }
            df = df_board.rename(columns=col_map).tail(days)

            closes = df["close"].astype(float)
            latest_close = float(closes.iloc[-1])
            latest_date = str(df["trade_date"].iloc[-1])

            # Percentile of current price within the lookback window
            price_pct_rank = float((closes.rank(pct=True) * 100).iloc[-1])

            # PE proxy: current price / mean price
            mean_close = closes.mean()
            pe_proxy = round(latest_close / mean_close, 2)

            # PB proxy: current price / min price
            min_close = closes.min()
            pb_proxy = round(latest_close / min_close, 2)

            # Valuation level based on percentile
            if price_pct_rank >= 80:
                level = "高估"
            elif price_pct_rank >= 60:
                level = "偏高"
            elif price_pct_rank >= 40:
                level = "合理"
            elif price_pct_rank >= 20:
                level = "偏低"
            else:
                level = "低估"

            # Build history
            history = []
            for i in range(len(closes)):
                c = float(closes.iloc[i])
                rank = float((closes.iloc[:i+1].rank(pct=True) * 100).iloc[-1]) if i > 0 else 50.0
                history.append({
                    "trade_date": str(df["trade_date"].iloc[i]),
                    "close": round(c, 2),
                    "pe_percentile": round(rank, 1),
                })

            result = {
                "sector_name": query,
                "index_code": "",
                "current": {
                    "pe_ttm": pe_proxy,
                    "pb": pb_proxy,
                    "close": latest_close,
                },
                "summary": {
                    "pe_ttm_percentile": round(price_pct_rank, 1),
                    "pb_percentile": round(price_pct_rank, 1),
                    "valuation_level": level,
                    "coverage_latest": sample_size,
                },
                "history": history,
                "member_count_total": 0,
                "member_count_used": 0,
                "member_count_with_data": 0,
                "latest_date": latest_date,
            }

            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get sector valuation: {e}")
            raise ValueError(f"Failed to get sector valuation: {e}")

    async def _resolve_sector_to_index(self, query: str) -> tuple:
        """Map sector name to akshare index code."""
        # Shenwan L1 sector → index code mapping (common ones)
        sector_map = {
            "银行": "801780", "房地产": "801180", "保险": "801790",
            "证券": "801193", "医药生物": "801150", "食品饮料": "801120",
            "白酒": "801120", "电子": "801080", "计算机": "801750",
            "传媒": "801760", "通信": "801770", "电力设备": "801730",
            "新能源": "801730", "汽车": "801880", "家用电器": "801110",
            "纺织服饰": "801130", "轻工制造": "801140", "机械设备": "801890",
            "国防军工": "801740", "化工": "801040", "钢铁": "801040",
            "有色金属": "801050", "采掘": "801020", "煤炭": "801020",
            "石油石化": "801030", "建筑材料": "801710", "建筑装饰": "801720",
            "交通运输": "801170", "公用事业": "801160", "农林牧渔": "801010",
            "综合": "801230", "环保": "801190", "社会服务": "801210",
            "美容护理": "801200", "商贸零售": "801200",
        }
        for name, code in sector_map.items():
            if name in query or query in name:
                return code, name
        # Default to CSI300 if no match
        return "000300", query

    # ------------------------------------------------------------------
    # 技术指标计算
    # ------------------------------------------------------------------

    async def calculate_technical_indicators(
        self,
        symbol: str,
        indicators: Optional[List[str]] = None,
        period: str = "daily",
        days: int = 120,
    ) -> Dict[str, Any]:
        """Calculate technical indicators for a stock.

        Supported indicators: MA, EMA, MACD, RSI, BOLL, KDJ, VOL_MA

        Args:
            symbol: Stock code (e.g. 600519)
            indicators: List of indicator names (default: all)
            period: daily/weekly/monthly
            days: Number of trading days to return

        Returns:
            Dict with indicator data series
        """
        if indicators is None:
            indicators = ["MA", "MACD", "RSI", "BOLL", "KDJ"]

        cache_key = f"akshare:tech:{symbol}:{','.join(sorted(indicators))}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(
                ak.stock_zh_a_hist,
                symbol=symbol,
                period=period,
                adjust="qfq",
            )
            if df is None or df.empty:
                raise ValueError(f"No price data for {symbol}")

            col_map = {
                "日期": "trade_date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude", "涨跌幅": "pct_change",
                "涨跌额": "change", "换手率": "turnover",
            }
            df = df.rename(columns=col_map).tail(days)
            close = df["close"].astype(float)
            high = df["high"].astype(float)
            low = df["low"].astype(float)
            volume = df["volume"].astype(float)

            result_data: Dict[str, Any] = {}
            dates = df["trade_date"].astype(str).tolist()

            # --- MA (Moving Averages) ---
            if "MA" in indicators:
                for w in [5, 10, 20, 60]:
                    ma = close.rolling(window=w).mean()
                    result_data[f"ma{w}"] = [
                        {"date": d, "value": round(float(v), 2) if not pd.isna(v) else None}
                        for d, v in zip(dates, ma)
                    ]

            # --- EMA ---
            if "EMA" in indicators:
                for w in [12, 26]:
                    ema = close.ewm(span=w, adjust=False).mean()
                    result_data[f"ema{w}"] = [
                        {"date": d, "value": round(float(v), 2)}
                        for d, v in zip(dates, ema)
                    ]

            # --- MACD ---
            if "MACD" in indicators:
                ema12 = close.ewm(span=12, adjust=False).mean()
                ema26 = close.ewm(span=26, adjust=False).mean()
                dif = ema12 - ema26
                dea = dif.ewm(span=9, adjust=False).mean()
                macd_bar = (dif - dea) * 2

                result_data["macd"] = [
                    {
                        "date": d,
                        "dif": round(float(dif_v), 2),
                        "dea": round(float(dea_v), 2),
                        "macd_bar": round(float(bar_v), 2),
                    }
                    for d, dif_v, dea_v, bar_v in zip(dates, dif, dea, macd_bar)
                ]

            # --- RSI ---
            if "RSI" in indicators:
                for w in [6, 12, 24]:
                    delta = close.diff()
                    gain = delta.where(delta > 0, 0)
                    loss = (-delta).where(delta < 0, 0)
                    avg_gain = gain.rolling(window=w).mean()
                    avg_loss = loss.rolling(window=w).mean()
                    rs = avg_gain / avg_loss.replace(0, 1e-10)
                    rsi = 100 - (100 / (1 + rs))

                    result_data[f"rsi{w}"] = [
                        {"date": d, "value": round(float(v), 2) if not pd.isna(v) else None}
                        for d, v in zip(dates, rsi)
                    ]

            # --- BOLL (Bollinger Bands) ---
            if "BOLL" in indicators:
                mid = close.rolling(window=20).mean()
                std = close.rolling(window=20).std()
                upper = mid + 2 * std
                lower = mid - 2 * std

                result_data["boll"] = [
                    {
                        "date": d,
                        "upper": round(float(u), 2) if not pd.isna(u) else None,
                        "mid": round(float(m), 2) if not pd.isna(m) else None,
                        "lower": round(float(l), 2) if not pd.isna(l) else None,
                    }
                    for d, u, m, l in zip(dates, upper, mid, lower)
                ]

            # --- KDJ ---
            if "KDJ" in indicators:
                low_9 = low.rolling(window=9).min()
                high_9 = high.rolling(window=9).max()
                rsv = (close - low_9) / (high_9 - low_9).replace(0, 1e-10) * 100

                k = rsv.ewm(com=2, adjust=False).mean()
                d = k.ewm(com=2, adjust=False).mean()
                j = 3 * k - 2 * d

                result_data["kdj"] = [
                    {
                        "date": dt,
                        "k": round(float(kv), 2) if not pd.isna(kv) else None,
                        "d": round(float(dv), 2) if not pd.isna(dv) else None,
                        "j": round(float(jv), 2) if not pd.isna(jv) else None,
                    }
                    for dt, kv, dv, jv in zip(dates, k, d, j)
                ]

            # --- VOL_MA (Volume Moving Average) ---
            if "VOL_MA" in indicators:
                for w in [5, 10, 20]:
                    vol_ma = volume.rolling(window=w).mean()
                    result_data[f"vol_ma{w}"] = [
                        {"date": d, "value": round(float(v), 0) if not pd.isna(v) else None}
                        for d, v in zip(dates, vol_ma)
                    ]

            result = {
                "symbol": symbol,
                "period": period,
                "days": days,
                "indicators": indicators,
                "data": result_data,
                "latest_date": dates[-1] if dates else None,
                "latest_close": round(float(close.iloc[-1]), 2),
            }

            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to calculate technical indicators: {e}")
            raise ValueError(f"Failed to calculate technical indicators: {e}")
