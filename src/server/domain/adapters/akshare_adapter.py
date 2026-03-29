# src/server/domain/adapters/akshare_adapter.py
"""Akshare adapter for Chinese market data.

All methods are async via asyncio.run_in_executor to avoid blocking
the event loop.
"""

import asyncio
import logging
import math
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

    async def _patched_akshare_call(self, func, *args, **kwargs):
        """Run an akshare call with a pd.to_datetime monkey-patch.

        Some akshare functions (e.g. stock_index_pe_lg) internally call
        pd.to_datetime(series, unit='ms') on columns containing date strings
        like '2005-04-08', causing ValueError. This patch catches that and
        retries without the unit parameter.
        """
        import pandas as pd
        original = pd.to_datetime

        def patched(arg, *a, **kw):
            try:
                return original(arg, *a, **kw)
            except (ValueError, TypeError):
                if 'unit' in kw:
                    kw = {k: v for k, v in kw.items() if k != 'unit'}
                    return original(arg, *a, **kw)
                raise

        pd.to_datetime = patched
        try:
            return await self._run(func, *args, **kwargs)
        finally:
            pd.to_datetime = original

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return value
        if isinstance(value, int):
            return float(value)
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            f = float(text)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
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
        # Strip exchange prefix (e.g. "SSE:600519" → "600519")
        symbol = self._to_ak_code(symbol)
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

        # Strip exchange prefix (e.g. "SSE:600519" → "600519")
        symbol = self._to_ak_code(symbol)

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
                for w in [6, 12, 14, 24]:
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

    async def get_technical_signals(self, symbol: str) -> Dict[str, Any]:
        """Derive deterministic technical signals from indicator values.

        Fact-only output: reports signal state without analysis conclusions.
        Signals are mechanical thresholds, not trading recommendations.
        """
        try:
            tech = await self.calculate_technical_indicators(
                symbol, indicators=["RSI", "MACD", "BOLL"], days=60,
            )
        except Exception as e:
            return {"symbol": symbol, "signals": {}, "error": str(e)}

        data = tech.get("data", {})
        signals: Dict[str, Any] = {}

        # --- RSI Signal ---
        rsi14_list = data.get("rsi14", [])
        if rsi14_list:
            last_rsi = None
            for item in reversed(rsi14_list):
                v = item.get("value")
                if v is not None:
                    last_rsi = v
                    break
            if last_rsi is not None:
                if last_rsi > 70:
                    rsi_signal = "RSI超买区"
                elif last_rsi < 30:
                    rsi_signal = "RSI超卖区"
                else:
                    rsi_signal = "RSI中性区"
                signals["rsi"] = {
                    "value": last_rsi,
                    "signal": rsi_signal,
                    "threshold_overbought": 70,
                    "threshold_oversold": 30,
                }

        # --- MACD Signal ---
        macd_list = data.get("macd", [])
        if macd_list and len(macd_list) >= 2:
            curr = macd_list[-1]
            prev = macd_list[-2]
            dif_c = curr.get("dif")
            dea_c = curr.get("dea")
            dif_p = prev.get("dif")
            dea_p = prev.get("dea")
            if all(v is not None for v in [dif_c, dea_c, dif_p, dea_p]):
                if dif_p <= dea_p and dif_c > dea_c:
                    macd_signal = "MACD金叉"
                elif dif_p >= dea_p and dif_c < dea_c:
                    macd_signal = "MACD死叉"
                else:
                    macd_signal = "MACD无交叉"
                signals["macd"] = {
                    "dif": dif_c,
                    "dea": dea_c,
                    "macd_bar": curr.get("macd_bar"),
                    "signal": macd_signal,
                }

        # --- Bollinger Band Signal ---
        boll_list = data.get("boll", [])
        latest_close = tech.get("latest_close")
        if boll_list and latest_close is not None:
            last_boll = boll_list[-1]
            upper = last_boll.get("upper")
            lower = last_boll.get("lower")
            mid = last_boll.get("mid")
            if all(v is not None for v in [upper, lower, mid]):
                if latest_close > upper:
                    boll_signal = "突破上轨"
                elif latest_close < lower:
                    boll_signal = "跌破下轨"
                else:
                    boll_signal = "布林带内"
                signals["boll"] = {
                    "close": latest_close,
                    "upper": upper,
                    "mid": mid,
                    "lower": lower,
                    "signal": boll_signal,
                }

        return {
            "symbol": symbol,
            "date": tech.get("latest_date"),
            "signals": signals,
            "source": "akshare",
        }

    # ------------------------------------------------------------------
    # 融资融券 / 解禁 / 回购 / 指数成分 / 基金净值
    # ------------------------------------------------------------------

    async def get_margin_trading(self, ticker: str, days: int = 30) -> Dict[str, Any]:
        """获取个股融资融券数据."""
        cache_key = f"akshare:margin:{ticker}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        symbol = self._to_ak_code(ticker)
        is_sse = symbol.startswith("6")

        try:
            # These APIs take date param, return all stocks for that date
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

            if is_sse:
                # stock_margin_detail_sse(date) - returns all SSE margin stocks
                df = await self._run(ak.stock_margin_detail_sse, date=end_date)
                if df is not None and not df.empty:
                    # Filter for our stock
                    if "标的证券代码" in df.columns:
                        df = df[df["标的证券代码"].astype(str).str.contains(symbol)]
            else:
                df = await self._run(ak.stock_margin_detail_szse, date=end_date)
                if df is not None and not df.empty:
                    if "证券代码" in df.columns:
                        df = df[df["证券代码"].astype(str).str.contains(symbol)]

            if df is None or df.empty:
                return {"data": [], "symbol": symbol, "source": "akshare"}

            data = df.tail(days).to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "symbol": symbol,
                "source": "akshare",
                "exchange": "SSE" if is_sse else "SZSE",
                "data": data,
                "summary": {
                    "latest_margin_balance": data[-1].get("融资余额(元)") or data[-1].get("融资余额") if data else None,
                    "latest_short_balance": data[-1].get("融券余额(元)") or data[-1].get("融券余额") if data else None,
                },
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get margin trading for {ticker}: {e}")
            return {"data": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    async def get_restricted_release(self, symbol: str = "", days: int = 90) -> Dict[str, Any]:
        """获取限售解禁数据."""
        cache_key = f"akshare:restricted_release:{symbol}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        result: Dict[str, Any] = {"data": {}, "source": "akshare"}

        try:
            # Summary - upcoming releases
            df_summary = await self._run(ak.stock_restricted_release_summary_em)
            if df_summary is not None and not df_summary.empty:
                data = df_summary.to_dict(orient="records")
                for item in data:
                    for k, v in item.items():
                        if hasattr(v, "item"):
                            item[k] = v.item()
                result["data"]["summary"] = data
        except Exception as e:
            self.logger.error(f"Failed to get restricted release summary: {e}")

        try:
            # Queue - scheduled releases
            df_queue = await self._run(ak.stock_restricted_release_queue_em)
            if df_queue is not None and not df_queue.empty:
                data = df_queue.to_dict(orient="records")
                for item in data:
                    for k, v in item.items():
                        if hasattr(v, "item"):
                            item[k] = v.item()
                result["data"]["queue"] = data
        except Exception as e:
            self.logger.error(f"Failed to get restricted release queue: {e}")

        await self.cache.set(cache_key, result, ttl=3600)
        return result

    async def get_repurchase_info(self, symbol: str = "") -> Dict[str, Any]:
        """获取股票回购数据."""
        cache_key = f"akshare:repurchase:{symbol}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.stock_repurchase_em)
            if df is None or df.empty:
                return {"data": [], "source": "akshare"}

            # Filter by symbol if provided
            if symbol:
                df = df[df["股票代码"].str.contains(symbol, na=False)]

            data = df.to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "data": data,
                "total": len(data),
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get repurchase info: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    async def get_index_constituents(self, index_code: str = "000300") -> Dict[str, Any]:
        """获取指数成分股列表."""
        cache_key = f"akshare:index_constituents:{index_code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.index_stock_cons_csindex, symbol=index_code)
            if df is None or df.empty:
                return {"data": [], "index_code": index_code, "source": "akshare"}

            data = df.to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "index_code": index_code,
                "total_constituents": len(data),
                "data": data,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=86400)  # Daily refresh
            return result

        except Exception as e:
            self.logger.error(f"Failed to get index constituents: {e}")
            return {"data": [], "index_code": index_code, "source": "akshare", "error": str(e)}

    async def get_index_constituent_weights(self, index_code: str = "000300") -> Dict[str, Any]:
        """获取指数成分股权重."""
        cache_key = f"akshare:index_weights:{index_code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.index_stock_cons_weight_csindex, symbol=index_code)
            if df is None or df.empty:
                return {"data": [], "index_code": index_code, "source": "akshare"}

            data = df.to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "index_code": index_code,
                "total_constituents": len(data),
                "data": data,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=86400)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get index weights: {e}")
            return {"data": [], "index_code": index_code, "source": "akshare", "error": str(e)}

    async def get_fund_nav(self, fund_code: str = "", days: int = 30) -> Dict[str, Any]:
        """获取基金净值数据."""
        cache_key = f"akshare:fund_nav:{fund_code}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            if fund_code:
                df = await self._run(
                    ak.fund_open_fund_info_em, symbol=fund_code, indicator="单位净值走势"
                )
                if df is not None and not df.empty:
                    data = df.tail(days).to_dict(orient="records")
                    for item in data:
                        for k, v in item.items():
                            if hasattr(v, "item"):
                                item[k] = v.item()
                    result = {
                        "fund_code": fund_code,
                        "data": data,
                        "source": "akshare",
                    }
                    await self.cache.set(cache_key, result, ttl=1800)
                    return result

            # Default: get fund ranking
            df = await self._run(ak.fund_open_fund_rank_em)
            if df is None or df.empty:
                return {"data": [], "source": "akshare"}

            data = df.head(days).to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "data": data,
                "total": len(data),
                "source": "akshare",
                "note": "Top funds by ranking" if not fund_code else "",
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get fund NAV: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    async def get_bond_yield(self) -> Dict[str, Any]:
        """获取国债收益率曲线."""
        cache_key = "akshare:bond_yield"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.bond_china_yield, start_year="2024")
            if df is None or df.empty:
                return {"data": [], "source": "akshare"}

            data = df.to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "data": data,
                "source": "akshare",
                " curves": ["国债收益率曲线", "国开债收益率曲线"],
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get bond yield: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    async def get_futures_main(self, symbol: str = "IF0", days: int = 60) -> Dict[str, Any]:
        """获取期货主力合约行情."""
        cache_key = f"akshare:futures_main:{symbol}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.futures_main_sina, symbol=symbol, start_date="19900101", end_date="20991231")
            if df is None or df.empty:
                return {"data": [], "symbol": symbol, "source": "akshare"}

            data = df.tail(days).to_dict(orient="records")
            for item in data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "symbol": symbol,
                "data": data,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get futures main: {e}")
            return {"data": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    async def get_option_summary(self) -> Dict[str, Any]:
        """获取期权市场概览 (上交所 50ETF/300ETF)."""
        cache_key = "akshare:option_summary"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        result: Dict[str, Any] = {"data": {}, "source": "akshare"}

        try:
            df_stats = await self._run(ak.option_daily_stats_sse)
            if df_stats is not None and not df_stats.empty:
                data = df_stats.to_dict(orient="records")
                for item in data:
                    for k, v in item.items():
                        if hasattr(v, "item"):
                            item[k] = v.item()
                result["data"]["daily_stats"] = data
        except Exception as e:
            self.logger.error(f"Failed to get option daily stats: {e}")

        try:
            df_current = await self._run(ak.option_current_day_sse)
            if df_current is not None and not df_current.empty:
                # Calculate PCR from call/put data
                calls = df_current[df_current["类型"] == "认购"] if "类型" in df_current.columns else pd.DataFrame()
                puts = df_current[df_current["类型"] == "认沽"] if "类型" in df_current.columns else pd.DataFrame()

                call_volume = int(calls["成交量"].sum()) if not calls.empty and "成交量" in calls.columns else 0
                put_volume = int(puts["成交量"].sum()) if not puts.empty and "成交量" in puts.columns else 0
                pcr = round(put_volume / call_volume, 4) if call_volume > 0 else 0

                result["data"]["current"] = {
                    "total_contracts": len(df_current),
                    "call_count": len(calls),
                    "put_count": len(puts),
                    "call_volume": call_volume,
                    "put_volume": put_volume,
                    "pcr_volume": pcr,
                }
        except Exception as e:
            self.logger.error(f"Failed to get option current: {e}")

        await self.cache.set(cache_key, result, ttl=1800)
        return result

    # ------------------------------------------------------------------
    # COL-127: 行业估值PE/PB历史分位
    # ------------------------------------------------------------------

    async def get_sector_pe_pb_historical(
        self, sector_name: str = "小金属", days: int = 250
    ) -> Dict[str, Any]:
        """获取行业PE/PB历史分位数据.

        基于行业成分股动态PE/静态PE计算当前PE/PB在历史中的分位(percentile).
        """
        cache_key = f"akshare:sector_pe_pb:{sector_name}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            cons_df = await self._run(ak.stock_board_industry_cons_em, symbol=sector_name)
            if cons_df is None or cons_df.empty:
                return {"data": {}, "sector": sector_name, "source": "akshare"}

            pe_col = "市盈率-动态" if "市盈率-动态" in cons_df.columns else None
            pb_col = "市净率" if "市净率" in cons_df.columns else None
            code_col = "代码" if "代码" in cons_df.columns else None
            if pe_col is None:
                return {"data": {}, "sector": sector_name, "source": "akshare", "error": "No PE column found"}

            records = []
            for _, row in cons_df.iterrows():
                pe_val = self._safe_float(row.get(pe_col))
                pb_val = self._safe_float(row.get(pb_col))
                code_val = str(row.get(code_col, "")) if code_col else ""
                records.append({
                    "code": code_val,
                    "name": row.get("名称", ""),
                    "pe": pe_val,
                    "pb": pb_val,
                })

            if not records:
                return {"data": [], "sector": sector_name, "source": "akshare"}

            # Calculate percentile (fact-only, no analytical labels)
            pe_values = [r["pe"] for r in records if r["pe"] is not None]
            if not pe_values:
                return {"data": records, "sector": sector_name, "source": "akshare"}

            sorted_pe = sorted(pe_values)
            current_pe = records[-1].get("pe")
            rank = sum(1 for x in sorted_pe if x <= current_pe)
            percentile = round(rank / len(sorted_pe) * 100, 2)

            result = {
                "sector": sector_name,
                "source": "akshare",
                "current": {
                    "pe": current_pe,
                    "pb": records[-1].get("pb"),
                    "pe_percentile": percentile,
                },
                "summary": {
                    "total_stocks": len(records),
                    "pe_mean": round(sum(r["pe"] for r in records if r["pe"]) / len(records), 2),
                    "pb_mean": round(sum(r["pb"] for r in records if r["pb"]) / len(records), 2),
                },
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get sector PE/PB historical: {e}")
            return {"data": {}, "sector": sector_name, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # COL-129: ETF资金流
    # ------------------------------------------------------------------

    async def get_etf_flow(self, symbol: str = "510300", days: int = 30) -> Dict[str, Any]:
        """获取ETF资金流向数据."""
        cache_key = f"akshare:etf_flow:{symbol}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # Use ETF spot data for real-time info
            df = await self._run(ak.fund_etf_spot_em)
            if df is None or df.empty:
                return {"data": [], "symbol": symbol, "source": "akshare"}

            # Filter for target symbol
            if "代码" in df.columns:
                target_df = df[df["代码"].astype(str) == symbol]
            else:
                target_df = df

            records = target_df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "symbol": symbol,
                "source": "akshare",
                "data": records[:1] if records else [],
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get ETF flow: {e}")
            return {"data": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # COL-130: 风格轮动
    # ------------------------------------------------------------------

    async def get_style_rotation(self) -> Dict[str, Any]:
        """获取风格轮动指标 (大盘/小盘, 成长/价值).

        比较上证50(大盘) vs 中证1000(小盘) 和 创业板指(成长) vs 沪深300(价值) 的近期涨跌幅。
        使用指数历史行情计算。
        """
        cache_key = "akshare:style_rotation"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")

            # Fetch index data for style comparison
            indices = {
                "large_cap": ("000016", "上证50"),
                "small_cap": ("000852", "中证1000"),
                "growth": ("399006", "创业板指"),
                "value": ("000300", "沪深300"),
            }

            style_data = {}
            for style_key, (code, name) in indices.items():
                df = await self._run(
                    ak.index_zh_a_hist, symbol=code,
                    period="daily", start_date=start_date, end_date=end_date,
                )
                if df is not None and not df.empty and len(df) >= 2:
                    closes = df["收盘"].astype(float).tolist()
                    chg_pct = round((closes[-1] - closes[0]) / closes[0] * 100, 2)
                    style_data[style_key] = {
                        "name": name,
                        "code": code,
                        "change_pct": chg_pct,
                        "latest_close": closes[-1],
                    }

            if len(style_data) < 2:
                return {"styles": {}, "source": "akshare"}

            large_chg = style_data.get("large_cap", {}).get("change_pct", 0)
            small_chg = style_data.get("small_cap", {}).get("change_pct", 0)
            growth_chg = style_data.get("growth", {}).get("change_pct", 0)
            value_chg = style_data.get("value", {}).get("change_pct", 0)

            result = {
                "source": "akshare",
                "styles": style_data,
                "style_signal": {
                    "large_vs_small": "大盘强势" if large_chg > small_chg else "小盘强势",
                    "large_small_spread": round(large_chg - small_chg, 2),
                    "growth_vs_value": "成长强势" if growth_chg > value_chg else "价值强势",
                    "growth_value_spread": round(growth_chg - value_chg, 2),
                },
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get style rotation: {e}")
            return {"styles": {}, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # COL-131: 期货基差
    # ------------------------------------------------------------------

    async def get_futures_basis(self, index_code: str = "IF0", days: int = 60) -> Dict[str, Any]:
        """计算期货基差 (期货价格 - 现货指数价格)."""
        cache_key = f"akshare:futures_basis:{index_code}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            futures_df = await self._run(ak.futures_main_sina, symbol=index_code)
            if futures_df is None or futures_df.empty:
                return {"data": [], "index_code": index_code, "source": "akshare"}

            futures_data = futures_df.tail(days).to_dict(orient="records")
            for item in futures_data:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "index_code": index_code,
                "source": "akshare",
                "data": futures_data,
                "latest_basis": None,
            }

            # Try to get spot index price for basis calculation
            if futures_data:
                last_close = futures_data[-1].get("收盘")
                if last_close is not None:
                    # Map futures code to index code
                    index_map = {"IF0": "000300", "IC0": "000905", "IH0": "000016", "IM0": "000852"}
                    idx_code = index_map.get(index_code, "000300")
                    try:
                        spot_df = await self._run(ak.index_zh_a_hist, symbol=idx_code, period="daily")
                        if spot_df is not None and not spot_df.empty:
                            spot_close = float(spot_df.iloc[-1]["收盘"])
                            basis = last_close - spot_close
                            basis_pct = round(basis / spot_close * 100, 2)
                            result["latest_basis"] = basis
                            result["latest_basis_pct"] = basis_pct
                            result["spot_price"] = spot_close
                            result["futures_price"] = last_close
                    except Exception:
                        pass

            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get futures basis: {e}")
            return {"data": [], "index_code": index_code, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # COL-135: 量化分析（风险/因子）
    # ------------------------------------------------------------------

    async def calculate_risk_metrics(
        self,
        symbol: str,
        indicators: Optional[List[str]] = None,
        period: str = "daily",
        days: int = 120,
    ) -> Dict[str, Any]:
        """计算量化风险指标 (Beta/Sharpe/VaR/CVaR/最大回撤等).

        基于历史行情数据计算，不需要额外数据源。
        """
        # Strip exchange prefix (e.g. "SSE:600519" → "600519")
        symbol = self._to_ak_code(symbol)
        cache_key = f"akshare:risk_metrics:{symbol}:{indicators}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            prices = await self._run(
                ak.stock_zh_a_hist, symbol=symbol,
                period="daily", start_date=start_date, end_date=end_date
            )

            if prices is None or prices.empty:
                return {"data": {}, "symbol": symbol, "source": "akshare"}

            closes = prices["收盘"].astype(float).tolist()
            volumes = prices["成交量"].astype(float).tolist() if "成交量" in prices.columns else []

            # Daily returns
            daily_returns = []
            for i in range(1, len(closes)):
                daily_returns.append((closes[i] - closes[i - 1]) / closes[i - 1])

            result = {
                "symbol": symbol,
                "source": "akshare",
                "data": {},
                "risk_metrics": {},
            }

            if len(daily_returns) < 2:
                return result

            import numpy as np

            arr_ret = np.array(daily_returns)

            # Volatility (annualized)
            vol = float(np.std(arr_ret) * np.sqrt(252))
            result["risk_metrics"]["volatility_annual"] = round(vol * 100, 2)

            # Sharpe Ratio (annualized, risk-free rate ~2%)
            rf_daily = 0.02 / 252
            excess = arr_ret - rf_daily
            sharpe = float(np.mean(excess) / np.std(arr_ret) * np.sqrt(252))
            result["risk_metrics"]["sharpe_ratio"] = round(sharpe, 2)

            # Max Drawdown
            cum_prices = np.array(closes)
            running_max = np.maximum.accumulate(cum_prices)
            drawdowns = (cum_prices - running_max) / running_max
            max_dd = float(drawdowns.min())
            result["risk_metrics"]["max_drawdown_pct"] = round(max_dd * 100, 2)

            # Calmar Ratio (annualized return / max drawdown)
            ann_return = float(np.mean(arr_ret) * 252)
            if max_dd != 0:
                calmar = ann_return / abs(max_dd)
                result["risk_metrics"]["calmar_ratio"] = round(calmar, 2)

            # VaR (95% historical)
            if len(arr_ret) >= 20:
                var_95 = float(np.percentile(arr_ret, 5))
                result["risk_metrics"]["var_95"] = round(var_95 * 100, 4)

                # CVaR (Expected Shortfall)
                cvar = float(np.mean(arr_ret[arr_ret <= var_95]))
                result["risk_metrics"]["cvar_95"] = round(cvar * 100, 4)

            # Beta (vs CSI300 benchmark)
            try:
                idx_code = "000300"
                bench_df = await self._run(
                    ak.index_zh_a_hist, symbol=idx_code,
                    period="daily", start_date=start_date, end_date=end_date
                )
                if bench_df is not None and not bench_df.empty and len(bench_df) >= len(arr_ret) + 1:
                    bench_closes = bench_df["收盘"].astype(float).tolist()
                    bench_returns = [(bench_closes[i] - bench_closes[i - 1]) / bench_closes[i - 1]
                                     for i in range(1, len(bench_closes))]
                    n = min(len(arr_ret), len(bench_returns))
                    if n >= 20:
                        cov_mat = np.cov(arr_ret[:n], bench_returns[:n])
                        bench_var = cov_mat[1, 1]
                        if bench_var > 0:
                            beta = float(cov_mat[0, 1] / bench_var)
                            result["risk_metrics"]["beta"] = round(beta, 4)
            except Exception:
                pass

            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to calculate risk metrics: {e}")
            return {"data": {}, "symbol": symbol, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # 龙虎榜数据
    # ------------------------------------------------------------------

    async def get_dragon_tiger_list(
        self, start_date: str = "", end_date: str = "", days: int = 10,
    ) -> Dict[str, Any]:
        """获取龙虎榜每日明细.

        Args:
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            days: 最近N天 (当start_date为空时使用)
        """
        if not start_date or not end_date:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=days)
            start_date = start_dt.strftime("%Y%m%d")
            end_date = end_dt.strftime("%Y%m%d")

        cache_key = f"akshare:lhb:{start_date}:{end_date}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.stock_lhb_detail_em, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return {"data": [], "source": "akshare", "start_date": start_date, "end_date": end_date}

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "start_date": start_date,
                "end_date": end_date,
                "total": len(records),
                "data": records[:200],
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get dragon tiger list: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # 大宗交易数据
    # ------------------------------------------------------------------

    async def get_block_trade(
        self, start_date: str = "", end_date: str = "", days: int = 10,
    ) -> Dict[str, Any]:
        """获取大宗交易每日明细.

        Args:
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            days: 最近N天 (当start_date为空时使用)
        """
        if not start_date or not end_date:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=days)
            start_date = start_dt.strftime("%Y%m%d")
            end_date = end_dt.strftime("%Y%m%d")

        cache_key = f"akshare:block_trade:{start_date}:{end_date}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.stock_dzjy_mrmx, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return {"data": [], "source": "akshare", "start_date": start_date, "end_date": end_date}

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "start_date": start_date,
                "end_date": end_date,
                "total": len(records),
                "data": records[:200],
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get block trade: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # 可转债数据
    # ------------------------------------------------------------------

    async def get_convertible_bond(
        self, bond_code: str = "",
    ) -> Dict[str, Any]:
        """获取可转债实时行情数据."""
        cache_key = f"akshare:convertible_bond:{bond_code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.bond_zh_hs_cov_spot)
            if df is None or df.empty:
                return {"data": [], "source": "akshare"}

            if bond_code and "代码" in df.columns:
                df = df[df["代码"].astype(str) == bond_code]

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "total": len(records),
                "data": records[:100],
            }
            await self.cache.set(cache_key, result, ttl=300)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get convertible bond: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # 基金持仓数据
    # ------------------------------------------------------------------

    async def get_fund_holdings(
        self, fund_code: str = "", quarter: str = "",
    ) -> Dict[str, Any]:
        """获取基金重仓股数据.

        Args:
            fund_code: 基金代码 (如 110011)
            quarter: 季度 (如 20244)
        """
        cache_key = f"akshare:fund_holdings:{fund_code}:{quarter}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            kwargs = {}
            if fund_code:
                kwargs["symbol"] = fund_code
            if quarter:
                kwargs["date"] = quarter

            df = await self._run(ak.fund_portfolio_hold_em, **kwargs)
            if df is None or df.empty:
                return {"data": [], "fund_code": fund_code, "source": "akshare"}

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "fund_code": fund_code,
                "total": len(records),
                "data": records[:50],
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get fund holdings: {e}")
            return {"data": [], "fund_code": fund_code, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # 商品期货持仓数据
    # ------------------------------------------------------------------

    async def get_commodity_inventory(
        self, symbol: str = "螺纹钢",
    ) -> Dict[str, Any]:
        """获取商品期货仓单/库存数据.

        Args:
            symbol: 商品名称 (如 螺纹钢, 铁矿石, 原油)
        """
        cache_key = f"akshare:commodity_inventory:{symbol}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.futures_inventory_em, symbol=symbol)
            if df is None or df.empty:
                return {"data": [], "symbol": symbol, "source": "akshare"}

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "symbol": symbol,
                "total": len(records),
                "data": records[-60:],
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get commodity inventory: {e}")
            return {"data": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # 股票参与者数据 (COL-144)
    # ------------------------------------------------------------------

    async def get_stock_northbound_holdings(
        self, symbol: str, days: int = 30,
    ) -> Dict[str, Any]:
        """获取个股北向持股明细.

        使用 stock_hsgt_hold_stock_em 获取当前快照, 再用
        stock_hsgt_stock_statistics_em 获取历史统计.

        Args:
            symbol: 股票代码 (如 600519)
            days: 回溯天数 (用于历史统计)
        """
        cache_key = f"akshare:stock_northbound_holdings:{symbol}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # 1. Get current snapshot from ranking
            snapshot_df = await self._run(
                ak.stock_hsgt_hold_stock_em,
                market="北向",
                indicator="今日排行",
            )
            stock_snapshot = {}
            if snapshot_df is not None and not snapshot_df.empty:
                # Find the stock
                code_col = None
                for col in snapshot_df.columns:
                    if "代码" in str(col):
                        code_col = col
                        break
                if code_col:
                    match = snapshot_df[snapshot_df[code_col].astype(str) == symbol]
                    if not match.empty:
                        row = match.iloc[0]
                        for k, v in row.items():
                            if hasattr(v, "item"):
                                v = v.item()
                            stock_snapshot[str(k)] = v

            # 2. Try historical statistics
            history = []
            try:
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
                hist_df = await self._run(
                    ak.stock_hsgt_stock_statistics_em,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
                if hist_df is not None and not hist_df.empty:
                    records = hist_df.to_dict(orient="records")
                    for item in records:
                        for k, v in item.items():
                            if hasattr(v, "item"):
                                item[k] = v.item()
                    history = records[-days:]
            except Exception:
                pass  # Historical API may not have data

            result = {
                "source": "akshare",
                "symbol": symbol,
                "snapshot": stock_snapshot,
                "history": history,
                "total_history": len(history),
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get stock northbound holdings: {e}")
            return {"data": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    async def get_stock_northbound_ranking(
        self, market: str = "北向", indicator: str = "今日排行",
    ) -> Dict[str, Any]:
        """获取北向持股排行.

        Args:
            market: 市场类型 (北向/沪股通/深股通)
            indicator: 指标 (今日排行/5日排行/10日排行/1月排行...)
        """
        cache_key = f"akshare:stock_northbound_ranking:{market}:{indicator}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(
                ak.stock_hsgt_hold_stock_em,
                market=market,
                indicator=indicator,
            )
            if df is None or df.empty:
                return {"data": [], "market": market, "indicator": indicator, "source": "akshare"}

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "market": market,
                "indicator": indicator,
                "total": len(records),
                "data": records[:100],
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get stock northbound ranking: {e}")
            return {"data": [], "market": market, "indicator": indicator, "source": "akshare", "error": str(e)}

    async def get_stock_top10_shareholders(
        self, symbol: str, date: str = "",
    ) -> Dict[str, Any]:
        """获取十大流通股东.

        Args:
            symbol: 股票代码 (如 sh688686)
            date: 季度日期 (如 20240930)
        """
        cache_key = f"akshare:stock_top10_shareholders:{symbol}:{date}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            kwargs = {"symbol": symbol}
            if date:
                kwargs["date"] = date

            df = await self._run(ak.stock_gdfx_free_top_10_em, **kwargs)
            if df is None or df.empty:
                return {"data": [], "symbol": symbol, "source": "akshare"}

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "symbol": symbol,
                "total": len(records),
                "data": records[:50],
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get stock top10 shareholders: {e}")
            return {"data": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    async def get_stock_shareholder_changes(
        self, date: str = "",
    ) -> Dict[str, Any]:
        """获取股东持股变化统计.

        Args:
            date: 日期 (如 20240930)
        """
        cache_key = f"akshare:stock_shareholder_changes:{date}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            kwargs = {}
            if date:
                kwargs["date"] = date

            df = await self._run(ak.stock_gdfx_holding_change_em, **kwargs)
            if df is None or df.empty:
                return {"data": [], "date": date, "source": "akshare"}

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "date": date,
                "total": len(records),
                "data": records[:100],
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get stock shareholder changes: {e}")
            return {"data": [], "date": date, "source": "akshare", "error": str(e)}

    async def get_stock_institutional_research(
        self, date: str = "",
    ) -> Dict[str, Any]:
        """获取机构调研统计.

        Args:
            date: 日期 (如 20240630)
        """
        cache_key = f"akshare:stock_institutional_research:{date}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            kwargs = {}
            if date:
                kwargs["date"] = date

            df = await self._run(ak.stock_jgdy_tj_em, **kwargs)
            if df is None or df.empty:
                return {"data": [], "date": date, "source": "akshare"}

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "date": date,
                "total": len(records),
                "data": records[:100],
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get stock institutional research: {e}")
            return {"data": [], "date": date, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # A-share corporate action data (COL-147)
    # ------------------------------------------------------------------

    async def get_shareholder_holding_detail(
        self, symbol: str = "", date: str = "",
    ) -> Dict[str, Any]:
        """获取股东增减持明细（十大流通股东维度）.

        Args:
            symbol: 股票代码 (如 688235), 为空返回全市场
            date: 季度日期 (如 20240930)
        """
        cache_key = f"akshare:shareholder_holding_detail:{symbol}:{date}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            kwargs: Dict[str, Any] = {}
            if date:
                kwargs["date"] = date
            if symbol:
                kwargs["symbol"] = symbol

            df = await self._run(ak.stock_gdfx_free_holding_detail_em, **kwargs)
            if df is None or df.empty:
                return {"data": [], "symbol": symbol, "date": date, "source": "akshare"}

            # Normalize column names
            col_map = {
                "序号": "seq",
                "股东名称": "holder_name",
                "股东类型": "holder_type",
                "股票代码": "stock_code",
                "股票简称": "stock_name",
                "变动日期": "change_date",
                "期末持有-数量": "hold_qty",
                "期末持有-数量变化": "hold_change",
                "期末持有-数量变化比例": "hold_change_pct",
                "期末持有-持股变动": "hold_direction",
                "期末持有-流通市值": "hold_market_value",
                "公告日期": "announce_date",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()

            result = {
                "source": "akshare",
                "symbol": symbol,
                "date": date,
                "total": len(records),
                "data": records[:100],
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get shareholder holding detail: {e}")
            return {"data": [], "symbol": symbol, "date": date, "source": "akshare", "error": str(e)}

    async def get_ipo_calendar(self) -> Dict[str, Any]:
        """获取新股IPO日历（近期IPO/申购/上市计划）.

        Uses stock_new_ipo_cninfo for IPO calendar data.
        """
        cache_key = "akshare:ipo_calendar"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.stock_new_ipo_cninfo)
            if df is None or df.empty:
                return {"data": [], "source": "akshare"}

            # Normalize column names
            col_map = {
                "证券代码": "stock_code",
                "证券简称": "stock_name",
                "申购日期": "subscribe_date",
                "发行价格": "issue_price",
                "总发行数量(万股)": "total_issue_qty",
                "发行市盈率": "issue_pe",
                "网上发行中签率(%)": "online_win_rate",
                "摇号结果公告日": "lottery_announce_date",
                "中签号公布日": "winning_date",
                "中签缴费日": "payment_date",
                "上市日期": "listing_date",
                "发行总数(万股)": "total_issue_volume",
                "上网定价发行数量(万股)": "online_issue_volume",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

            records = df.to_dict(orient="records")
            for item in records:
                for k, v in item.items():
                    if hasattr(v, "item"):
                        item[k] = v.item()
                    # Convert NaT/Timestamp to string
                    if str(type(v)) == "<class 'pandas._libs.tslibs.nattype.NaTType'>":
                        item[k] = None
                    elif hasattr(v, "strftime"):
                        item[k] = v.strftime("%Y-%m-%d")

            result = {
                "source": "akshare",
                "total": len(records),
                "data": records[:50],
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get IPO calendar: {e}")
            return {"data": [], "source": "akshare", "error": str(e)}

    async def get_ipo_info(self, stock: str = "") -> Dict[str, Any]:
        """获取个股IPO详情.

        Args:
            stock: 股票代码 (如 600519)
        """
        if not stock:
            return {"data": {}, "source": "akshare", "error": "stock parameter required"}

        cache_key = f"akshare:ipo_info:{stock}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            df = await self._run(ak.stock_ipo_info, stock=stock)
            if df is None or df.empty:
                return {"data": {}, "stock": stock, "source": "akshare"}

            # Convert key-value pairs to dict
            info = {}
            for _, row in df.iterrows():
                key = str(row.iloc[0]).strip()
                value = row.iloc[1]
                if hasattr(value, "item"):
                    value = value.item()
                info[key] = value

            result = {
                "source": "akshare",
                "stock": stock,
                "data": info,
            }
            await self.cache.set(cache_key, result, ttl=86400)
            return result

        except Exception as e:
            self.logger.error(f"Failed to get IPO info: {e}")
            return {"data": {}, "stock": stock, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # Stock Fact Pack: aggregate facts by category (COL-148)
    # ------------------------------------------------------------------

    async def get_stock_fact_pack(self, symbol: str) -> Dict[str, Any]:
        """Aggregate stock facts across all categories into a single pack.

        Calls existing adapter methods and organizes results into fact
        categories: security_master, company_master, business_structure,
        governance, financial, market (incl. margin), events, peers.

        Each category includes: data, source_trace, coverage status.
        The pack also includes top-level missing_fields.

        Args:
            symbol: Stock code (e.g. 600519, 000001)
        """
        cache_key = f"akshare:stock_fact_pack:{symbol}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        import time as _time
        t0 = _time.perf_counter()

        entity = {"symbol": symbol, "type": "stock"}
        facts: Dict[str, Any] = {}
        source_trace: Dict[str, Any] = {}
        coverage: Dict[str, str] = {}
        missing_fields: List[str] = []

        # --- 1. Security Master (证券主档) ---
        try:
            info = await self.get_asset_info(f"SSE:{symbol}")
            if info is None:
                info = await self.get_asset_info(f"SZSE:{symbol}")
            if info and hasattr(info, "to_dict"):
                d = info.to_dict()
                facts["security_master"] = {
                    "code": d.get("symbol", symbol),
                    "name": d.get("name", ""),
                    "exchange": d.get("exchange", ""),
                    "asset_type": d.get("asset_type", ""),
                }
                coverage["security_master"] = "complete"
            else:
                coverage["security_master"] = "missing"
                missing_fields.append("security_master")
        except Exception as e:
            coverage["security_master"] = f"error: {e}"
            source_trace["security_master"] = {"error": str(e)}

        # --- 2. Financial Facts (财务事实) ---
        try:
            fin = await self.get_financials(f"SSE:{symbol}")
            if not fin or "error" in fin:
                fin = await self.get_financials(f"SZSE:{symbol}")
            if fin and "error" not in fin:
                facts["financial"] = fin
                coverage["financial"] = "complete"
            else:
                coverage["financial"] = "missing"
                missing_fields.append("financial")
        except Exception as e:
            coverage["financial"] = f"error: {e}"

        # --- 3. Market Facts (市场事实) ---
        market_data: Dict[str, Any] = {}
        try:
            val = await self._get_valuation_raw(symbol)
            if val:
                market_data["valuation"] = val
                source_trace["valuation"] = {"provider": "akshare"}
        except Exception:
            pass
        try:
            flow = await self.get_money_flow(f"SSE:{symbol}")
            if not flow or "error" in flow:
                flow = await self.get_money_flow(f"SZSE:{symbol}")
            if flow and "error" not in flow:
                market_data["money_flow"] = flow
        except Exception:
            pass
        try:
            margin = await self.get_margin_trading(symbol, days=5)
            if margin and "error" not in margin and margin.get("data"):
                market_data["margin"] = margin.get("summary", {})
                source_trace["margin"] = {"provider": "akshare", "api": "margin_detail"}
        except Exception:
            pass
        if market_data:
            facts["market"] = market_data
            coverage["market"] = "partial" if len(market_data) < 3 else "complete"
        else:
            coverage["market"] = "missing"
            missing_fields.append("market")

        # --- 4. Governance Facts (治理与股权) ---
        gov_data: Dict[str, Any] = {}
        try:
            holders = await self.get_stock_top10_shareholders(symbol)
            if holders and "error" not in holders:
                gov_data["top10_shareholders"] = holders.get("data", [])[:10]
        except Exception:
            pass
        # Note: get_stock_shareholder_changes() returns market-wide data (no symbol param),
        # so it is excluded from per-stock fact pack to avoid misleading AI agents.
        if gov_data:
            facts["governance"] = gov_data
            coverage["governance"] = "complete" if gov_data.get("top10_shareholders") else "partial"
        else:
            coverage["governance"] = "missing"
            missing_fields.append("governance")

        # --- 5. Event Facts (事件事实) ---
        event_data: Dict[str, Any] = {}
        try:
            div = await self.get_dividend_info(f"SSE:{symbol}")
            if not div or "error" in div:
                div = await self.get_dividend_info(f"SZSE:{symbol}")
            if div and "error" not in div:
                event_data["dividends"] = div
        except Exception:
            pass
        try:
            repo = await self.get_repurchase_info(symbol=symbol)
            if repo and "error" not in repo:
                event_data["repurchase"] = repo
        except Exception:
            pass
        try:
            restricted = await self.get_restricted_release(symbol=symbol, days=90)
            if restricted and "error" not in restricted:
                event_data["restricted_release"] = restricted
        except Exception:
            pass
        if event_data:
            facts["events"] = event_data
            coverage["events"] = "partial"
        else:
            coverage["events"] = "missing"
            missing_fields.append("events")

        # --- 6. Earnings Estimates (盈利预测) ---
        try:
            forecast = await self.get_profit_forecast(f"SSE:{symbol}")
            if not forecast or "error" in forecast:
                forecast = await self.get_profit_forecast(f"SZSE:{symbol}")
            if forecast and "error" not in forecast and forecast.get("rows"):
                facts["earnings_estimates"] = {
                    "forecasts": forecast.get("rows", [])[:10],
                    "source": forecast.get("source", "akshare"),
                }
                coverage["earnings_estimates"] = "complete"
            else:
                coverage["earnings_estimates"] = "missing"
                missing_fields.append("earnings_estimates")
        except Exception as e:
            coverage["earnings_estimates"] = f"error: {e}"

        # --- 7. Business Structure (业务结构) ---
        try:
            biz = await self.get_mainbz_info(f"SSE:{symbol}")
            if not biz or "error" in biz:
                biz = await self.get_mainbz_info(f"SZSE:{symbol}")
            if biz and "error" not in biz:
                facts["business_structure"] = biz
                coverage["business_structure"] = "complete"
            else:
                coverage["business_structure"] = "missing"
                missing_fields.append("business_structure")
        except Exception as e:
            coverage["business_structure"] = f"error: {e}"

        # --- 8. Company Master (公司主档) ---
        try:
            df = await self._run(ak.stock_individual_info_em, symbol=symbol)
            if df is not None and not df.empty:
                info = {}
                for _, row in df.iterrows():
                    k = row.get("item")
                    v = row.get("value")
                    if k:
                        info[k] = str(v) if v is not None else None
                if info:
                    facts["company_master"] = {
                        "company_name": info.get("公司名称", ""),
                        "short_name": info.get("股票简称", ""),
                        "established_date": info.get("成立日期"),
                        "ipo_date": info.get("上市日期"),
                        "registered_address": info.get("注册地址"),
                        "office_address": info.get("办公地址"),
                        "website": info.get("公司网址"),
                        "legal_representative": info.get("法人代表"),
                        "chairman": info.get("董事长"),
                        "general_manager": info.get("总经理"),
                        "secretary": info.get("董秘"),
                        "phone": info.get("电话"),
                        "email": info.get("邮箱"),
                        "employees": info.get("员工总数"),
                        "registered_capital": info.get("注册资本"),
                        "main_business": info.get("主营业务"),
                        "business_scope": info.get("经营范围"),
                        "company_profile": info.get("公司简介"),
                        "industry": info.get("行业"),
                    }
                    source_trace["company_master"] = {"provider": "akshare", "api": "stock_individual_info_em"}
                    coverage["company_master"] = "complete"
                else:
                    coverage["company_master"] = "missing"
                    missing_fields.append("company_master")
            else:
                coverage["company_master"] = "missing"
                missing_fields.append("company_master")
        except Exception as e:
            coverage["company_master"] = f"error: {e}"
            source_trace["company_master"] = {"error": str(e)}
            missing_fields.append("company_master")

        # --- 9. Peers (同业对比) ---
        try:
            cm = facts.get("company_master", {})
            industry = cm.get("industry") if cm else None
            if industry:
                cons_df = await self._run(ak.stock_board_industry_cons_em, symbol=industry)
                if cons_df is not None and not cons_df.empty:
                    cap_col = "总市值" if "总市值" in cons_df.columns else None
                    code_col = "代码" if "代码" in cons_df.columns else None
                    name_col = "名称" if "名称" in cons_df.columns else None
                    pe_col = "市盈率-动态" if "市盈率-动态" in cons_df.columns else None
                    pb_col = "市净率" if "市净率" in cons_df.columns else None
                    peers_list = []
                    target_code = str(symbol).strip()
                    for _, row in cons_df.iterrows():
                        code_val = str(row.get(code_col, "")).strip() if code_col else ""
                        if code_val == target_code:
                            continue
                        peers_list.append({
                            "code": code_val,
                            "name": str(row.get(name_col, "")) if name_col else "",
                            "pe": self._safe_float(row.get(pe_col)) if pe_col else None,
                            "pb": self._safe_float(row.get(pb_col)) if pb_col else None,
                            "market_cap": self._safe_float(row.get(cap_col)) if cap_col else None,
                        })
                    # Sort by market cap descending, take top 10
                    peers_list.sort(key=lambda x: x.get("market_cap") or 0, reverse=True)
                    peers_list = peers_list[:10]
                    facts["peers"] = {
                        "industry": industry,
                        "peers": peers_list,
                        "count": len(peers_list),
                    }
                    source_trace["peers"] = {"provider": "akshare", "api": "stock_board_industry_cons_em"}
                    coverage["peers"] = "complete"
                else:
                    coverage["peers"] = "missing"
                    missing_fields.append("peers")
            else:
                coverage["peers"] = "missing: no industry info"
                missing_fields.append("peers")
        except Exception as e:
            coverage["peers"] = f"error: {e}"
            source_trace["peers"] = {"error": str(e)}
            missing_fields.append("peers")

        # --- 10. Restricted Release (限售解禁) ---
        try:
            rr = await self.get_restricted_release(symbol=symbol, days=90)
            if rr and "error" not in rr and rr.get("data"):
                facts["restricted_release"] = rr
                coverage["restricted_release"] = "complete"
                source_trace["restricted_release"] = {"provider": "akshare", "api": "restricted_release_queue"}
            else:
                coverage["restricted_release"] = "missing"
                missing_fields.append("restricted_release")
        except Exception as e:
            coverage["restricted_release"] = f"error: {e}"
            source_trace["restricted_release"] = {"error": str(e)}
            missing_fields.append("restricted_release")

        # --- 11. Repurchase (回购) ---
        try:
            rp = await self.get_repurchase_info(symbol=symbol)
            if rp and "error" not in rp and rp.get("data"):
                facts["repurchase"] = rp
                coverage["repurchase"] = "complete"
                source_trace["repurchase"] = {"provider": "akshare", "api": "stock_repurchase_em"}
            else:
                coverage["repurchase"] = "missing"
                missing_fields.append("repurchase")
        except Exception as e:
            coverage["repurchase"] = f"error: {e}"
            source_trace["repurchase"] = {"error": str(e)}
            missing_fields.append("repurchase")

        elapsed = _time.perf_counter() - t0

        result = {
            "source": "akshare",
            "entity": entity,
            "facts": facts,
            "source_trace": source_trace,
            "coverage": coverage,
            "missing_fields": missing_fields,
            "categories_fetched": len([v for v in coverage.values() if v == "complete" or v == "partial"]),
            "categories_total": 11,
            "elapsed_seconds": round(elapsed, 2),
        }

        # Build fact_markdown view (COL-149)
        try:
            from src.server.domain.fact_markdown import build_stock_fact_markdown
            result["fact_markdown"] = build_stock_fact_markdown(result)
        except Exception as e:
            self.logger.warning(f"fact_markdown generation failed: {e}")

        await self.cache.set(cache_key, result, ttl=600)
        return result

    async def _get_valuation_raw(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get valuation data for a raw stock code (no ticker prefix)."""
        cache_key = f"akshare:valuation_raw:{symbol}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            df = await self._run(ak.stock_a_indicator_lg, symbol=symbol)
            if df is None or df.empty:
                return None
            latest = df.iloc[-1].to_dict()
            for k, v in latest.items():
                if hasattr(v, "item"):
                    latest[k] = v.item()
            await self.cache.set(cache_key, latest, ttl=600)
            return latest
        except Exception as e:
            self.logger.error(f"Failed to get valuation raw: {e}")
            return None

    # ------------------------------------------------------------------
    # A-share quantitative stock screener
    # ------------------------------------------------------------------

    async def screen_stocks(
        self,
        min_pe: Optional[float] = None,
        max_pe: Optional[float] = None,
        min_pb: Optional[float] = None,
        max_pb: Optional[float] = None,
        min_market_cap: Optional[float] = None,
        max_market_cap: Optional[float] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        min_turnover_rate: Optional[float] = None,
        max_turnover_rate: Optional[float] = None,
        min_volume_ratio: Optional[float] = None,
        max_volume_ratio: Optional[float] = None,
        min_change_pct: Optional[float] = None,
        max_change_pct: Optional[float] = None,
        min_ytd_change: Optional[float] = None,
        max_ytd_change: Optional[float] = None,
        min_60d_change: Optional[float] = None,
        max_60d_change: Optional[float] = None,
        min_amplitude: Optional[float] = None,
        max_amplitude: Optional[float] = None,
        exchange: Optional[str] = None,
        sector: Optional[str] = None,
        sort_by: str = "market_cap",
        sort_order: str = "desc",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Quantitative stock screener for all A-share stocks.

        Fetches the full A-share universe via stock_zh_a_spot_em and applies
        user-supplied filters to produce a ranked result set.

        Args:
            min_pe / max_pe: PE (TTM) range
            min_pb / max_pb: Price-to-Book range
            min_market_cap / max_market_cap: Total market cap range (in CNY billions)
            min_price / max_price: Latest price range
            min_turnover_rate / max_turnover_rate: Turnover rate % range
            min_volume_ratio / max_volume_ratio: Volume ratio range
            min_change_pct / max_change_pct: Daily change % range
            min_ytd_change / max_ytd_change: Year-to-date change % range
            min_60d_change / max_60d_change: 60-day change % range
            min_amplitude / max_amplitude: Amplitude % range
            exchange: Filter by exchange ("SSE", "SZSE", "BSE", or None for all)
            sector: Not yet implemented (reserved for future sector-level filtering)
            sort_by: Sort field (market_cap, pe, pb, price, turnover_rate, volume_ratio, change_pct, ytd_change)
            sort_order: "asc" or "desc"
            limit: Max number of results (default 50, max 200)

        Returns:
            Dict with filtered results, total count, applied filters, and metadata.
        """
        limit = min(max(limit, 1), 200)

        cache_key = "akshare:screen_stocks:snapshot"
        cached_df = await self.cache.get(cache_key)

        if cached_df is not None:
            df = pd.DataFrame(cached_df)
        else:
            try:
                df = await self._run(ak.stock_zh_a_spot_em)
                if df is None or df.empty:
                    return {
                        "results": [],
                        "total": 0,
                        "filters_applied": {},
                        "source": "akshare",
                    }
                # Cache raw snapshot for 5 minutes (screener runs frequently)
                await self.cache.set(cache_key, df.to_dict(orient="records"), ttl=300)
            except Exception as e:
                self.logger.error(f"screen_stocks: failed to fetch snapshot: {e}")
                return {
                    "results": [],
                    "total": 0,
                    "filters_applied": {},
                    "source": "akshare",
                    "error": str(e),
                }

        # Normalize columns
        col_map = {
            "代码": "code",
            "名称": "name",
            "最新价": "price",
            "涨跌幅": "change_pct",
            "涨跌额": "change_amt",
            "成交量": "volume",
            "成交额": "turnover",
            "振幅": "amplitude",
            "最高": "high",
            "最低": "low",
            "今开": "open",
            "昨收": "prev_close",
            "量比": "volume_ratio",
            "换手率": "turnover_rate",
            "市盈率-动态": "pe",
            "市净率": "pb",
            "总市值": "market_cap",
            "流通市值": "float_market_cap",
            "60日涨跌幅": "change_60d",
            "年初至今涨跌幅": "change_ytd",
        }
        df = df.rename(columns=col_map)

        # Derive exchange from code
        def _infer_exchange(code: str) -> str:
            c = str(code)
            if c.startswith("6"):
                return "SSE"
            elif c.startswith("0") or c.startswith("3"):
                return "SZSE"
            elif c.startswith("8") or c.startswith("4"):
                return "BSE"
            return "OTHER"

        if "exchange" not in df.columns:
            df["exchange"] = df["code"].apply(_infer_exchange)

        # Convert market cap to billions for user-friendly filtering
        df["market_cap_b"] = pd.to_numeric(df.get("market_cap", 0), errors="coerce").fillna(0) / 1e8

        # Apply filters
        filters_applied: Dict[str, Any] = {}

        def _apply_range(df_in, col: str, lo, hi):
            """Filter df_in by [lo, hi] on numeric col. Skips if col missing."""
            if col not in df_in.columns:
                return df_in
            series = pd.to_numeric(df_in[col], errors="coerce")
            if lo is not None:
                df_in = df_in[series >= lo]
            if hi is not None:
                df_in = df_in[series <= hi]
            return df_in

        if min_pe is not None or max_pe is not None:
            filters_applied["pe"] = {"min": min_pe, "max": max_pe}
            # Only keep rows with positive PE (exclude loss-makers)
            if "pe" in df.columns:
                df = df[pd.to_numeric(df["pe"], errors="coerce") > 0]
            df = _apply_range(df, "pe", min_pe, max_pe)

        if min_pb is not None or max_pb is not None:
            filters_applied["pb"] = {"min": min_pb, "max": max_pb}
            df = _apply_range(df, "pb", min_pb, max_pb)

        if min_market_cap is not None or max_market_cap is not None:
            filters_applied["market_cap_b"] = {"min": min_market_cap, "max": max_market_cap}
            df = _apply_range(df, "market_cap_b", min_market_cap, max_market_cap)

        if min_price is not None or max_price is not None:
            filters_applied["price"] = {"min": min_price, "max": max_price}
            df = _apply_range(df, "price", min_price, max_price)

        if min_turnover_rate is not None or max_turnover_rate is not None:
            filters_applied["turnover_rate"] = {"min": min_turnover_rate, "max": max_turnover_rate}
            df = _apply_range(df, "turnover_rate", min_turnover_rate, max_turnover_rate)

        if min_volume_ratio is not None or max_volume_ratio is not None:
            filters_applied["volume_ratio"] = {"min": min_volume_ratio, "max": max_volume_ratio}
            df = _apply_range(df, "volume_ratio", min_volume_ratio, max_volume_ratio)

        if min_change_pct is not None or max_change_pct is not None:
            filters_applied["change_pct"] = {"min": min_change_pct, "max": max_change_pct}
            df = _apply_range(df, "change_pct", min_change_pct, max_change_pct)

        if min_ytd_change is not None or max_ytd_change is not None:
            filters_applied["change_ytd"] = {"min": min_ytd_change, "max": max_ytd_change}
            df = _apply_range(df, "change_ytd", min_ytd_change, max_ytd_change)

        if min_60d_change is not None or max_60d_change is not None:
            filters_applied["change_60d"] = {"min": min_60d_change, "max": max_60d_change}
            df = _apply_range(df, "change_60d", min_60d_change, max_60d_change)

        if min_amplitude is not None or max_amplitude is not None:
            filters_applied["amplitude"] = {"min": min_amplitude, "max": max_amplitude}
            df = _apply_range(df, "amplitude", min_amplitude, max_amplitude)

        if exchange is not None:
            exchange_upper = exchange.upper()
            filters_applied["exchange"] = exchange_upper
            df = df[df["exchange"] == exchange_upper]

        # Sort
        sort_col_map = {
            "market_cap": "market_cap_b",
            "pe": "pe",
            "pb": "pb",
            "price": "price",
            "turnover_rate": "turnover_rate",
            "volume_ratio": "volume_ratio",
            "change_pct": "change_pct",
            "ytd_change": "change_ytd",
            "change_60d": "change_60d",
            "amplitude": "amplitude",
        }
        actual_sort_col = sort_col_map.get(sort_by, "market_cap_b")
        ascending = sort_order.lower() == "asc"

        if actual_sort_col in df.columns:
            df[actual_sort_col] = pd.to_numeric(df[actual_sort_col], errors="coerce")
            df = df.sort_values(by=actual_sort_col, ascending=ascending, na_position="last")

        total = len(df)
        df = df.head(limit)

        # Format output
        results = []
        for _, row in df.iterrows():
            price = self._safe_float(row.get("price"))
            market_cap_b = self._safe_float(row.get("market_cap_b"))

            results.append({
                "ticker": f"{row.get('exchange', 'SSE')}:{row.get('code', '')}",
                "code": str(row.get("code", "")),
                "name": str(row.get("name", "")),
                "price": round(price, 2) if price is not None else None,
                "change_pct": round(self._safe_float(row.get("change_pct")) or 0, 2),
                "pe": round(self._safe_float(row.get("pe")) or 0, 2),
                "pb": round(self._safe_float(row.get("pb")) or 0, 2),
                "market_cap_b": round(market_cap_b, 2) if market_cap_b is not None else None,
                "turnover_rate": round(self._safe_float(row.get("turnover_rate")) or 0, 2),
                "volume_ratio": round(self._safe_float(row.get("volume_ratio")) or 0, 2),
                "amplitude": round(self._safe_float(row.get("amplitude")) or 0, 2),
                "change_ytd": round(self._safe_float(row.get("change_ytd")) or 0, 2),
                "change_60d": round(self._safe_float(row.get("change_60d")) or 0, 2),
            })

        return {
            "results": results,
            "total": total,
            "returned": len(results),
            "sort_by": sort_by,
            "sort_order": sort_order,
            "filters_applied": filters_applied,
            "source": "akshare",
        }

    # ------------------------------------------------------------------
    # A-share industry performance ranking
    # ------------------------------------------------------------------

    async def get_industry_ranking(
        self,
        sort_by: str = "change_pct",
        sort_order: str = "desc",
        limit: int = 30,
    ) -> Dict[str, Any]:
        """Get real-time performance ranking of all A-share industry boards.

        Uses stock_board_industry_name_em to fetch current snapshot of all
        industry sectors, then ranks them by the specified metric.

        Args:
            sort_by: Sort field. Options:
                - change_pct (涨跌幅, default)
                - turnover_rate (换手率)
                - volume (成交量)
                - turnover (成交额)
                - amplitude (振幅)
                - rise_count (上涨家数)
                - fall_count (下跌家数)
            sort_order: "desc" or "asc"
            limit: Max sectors to return (default 30, max 100)

        Returns:
            Dict with ranked industry list, total count, and metadata.
        """
        limit = min(max(limit, 1), 100)

        cache_key = "akshare:industry_ranking:snapshot"
        cached_df = await self.cache.get(cache_key)

        if cached_df is not None:
            df = pd.DataFrame(cached_df)
        else:
            try:
                df = await self._run(ak.stock_board_industry_name_em)
                if df is None or df.empty:
                    return {"results": [], "total": 0, "source": "akshare"}
                await self.cache.set(cache_key, df.to_dict(orient="records"), ttl=300)
            except Exception as e:
                self.logger.error(f"get_industry_ranking: failed to fetch: {e}")
                return {"results": [], "total": 0, "source": "akshare", "error": str(e)}

        # Normalize columns
        col_map = {
            "板块名称": "name",
            "板块代码": "code",
            "最新价": "price",
            "涨跌幅": "change_pct",
            "涨跌额": "change_amt",
            "成交量": "volume",
            "成交额": "turnover",
            "振幅": "amplitude",
            "最高": "high",
            "最低": "low",
            "今开": "open",
            "昨收": "prev_close",
            "换手率": "turnover_rate",
            "上涨家数": "rise_count",
            "下跌家数": "fall_count",
            "领涨股票": "top_stock",
            "领涨股票涨跌幅": "top_stock_change",
        }
        df = df.rename(columns=col_map)

        # Sort
        sort_col_map = {
            "change_pct": "change_pct",
            "turnover_rate": "turnover_rate",
            "volume": "volume",
            "turnover": "turnover",
            "amplitude": "amplitude",
            "rise_count": "rise_count",
            "fall_count": "fall_count",
        }
        actual_sort_col = sort_col_map.get(sort_by, "change_pct")
        ascending = sort_order.lower() == "asc"

        if actual_sort_col in df.columns:
            df[actual_sort_col] = pd.to_numeric(df[actual_sort_col], errors="coerce")
            df = df.sort_values(by=actual_sort_col, ascending=ascending, na_position="last")

        total = len(df)
        df = df.head(limit)

        results = []
        for _, row in df.iterrows():
            results.append({
                "name": str(row.get("name", "")),
                "code": str(row.get("code", "")),
                "price": round(self._safe_float(row.get("price")) or 0, 2),
                "change_pct": round(self._safe_float(row.get("change_pct")) or 0, 2),
                "amplitude": round(self._safe_float(row.get("amplitude")) or 0, 2),
                "turnover_rate": round(self._safe_float(row.get("turnover_rate")) or 0, 2),
                "rise_count": int(self._safe_float(row.get("rise_count")) or 0),
                "fall_count": int(self._safe_float(row.get("fall_count")) or 0),
                "top_stock": str(row.get("top_stock", "")),
                "top_stock_change": round(self._safe_float(row.get("top_stock_change")) or 0, 2),
            })

        return {
            "results": results,
            "total": total,
            "returned": len(results),
            "sort_by": sort_by,
            "sort_order": sort_order,
            "source": "akshare",
        }

    # ------------------------------------------------------------------
    # A-share concept board ranking
    # ------------------------------------------------------------------
    async def get_concept_ranking(
        self,
        sort_by: str = "change_pct",
        sort_order: str = "desc",
        limit: int = 30,
    ) -> Dict[str, Any]:
        """Get real-time performance ranking of all A-share concept boards."""
        limit = min(max(limit, 1), 100)

        cache_key = "akshare:concept_ranking:snapshot"
        cached_df = await self.cache.get(cache_key)

        if cached_df is not None:
            df = pd.DataFrame(cached_df)
        else:
            try:
                df = await self._run(ak.stock_board_concept_name_em)
                if df is None or df.empty:
                    return {"results": [], "total": 0, "source": "akshare"}
                await self.cache.set(cache_key, df.to_dict(orient="records"), ttl=300)
            except Exception as e:
                self.logger.error(f"get_concept_ranking: failed to fetch: {e}")
                return {"results": [], "total": 0, "source": "akshare", "error": str(e)}

        col_map = {
            "板块名称": "name", "板块代码": "code", "最新价": "price",
            "涨跌幅": "change_pct", "涨跌额": "change_amt", "成交量": "volume",
            "成交额": "turnover", "振幅": "amplitude", "最高": "high", "最低": "low",
            "今开": "open", "昨收": "prev_close", "换手率": "turnover_rate",
            "上涨家数": "rise_count", "下跌家数": "fall_count",
            "领涨股票": "top_stock", "领涨股票涨跌幅": "top_stock_change",
        }
        df = df.rename(columns=col_map)

        sort_col_map = {
            "change_pct": "change_pct", "turnover_rate": "turnover_rate",
            "volume": "volume", "turnover": "turnover", "amplitude": "amplitude",
            "rise_count": "rise_count", "fall_count": "fall_count",
        }
        actual_sort_col = sort_col_map.get(sort_by, "change_pct")
        ascending = sort_order.lower() == "asc"

        if actual_sort_col in df.columns:
            df[actual_sort_col] = pd.to_numeric(df[actual_sort_col], errors="coerce")
            df = df.sort_values(by=actual_sort_col, ascending=ascending, na_position="last")

        total = len(df)
        df = df.head(limit)

        results = []
        for _, row in df.iterrows():
            results.append({
                "name": str(row.get("name", "")),
                "code": str(row.get("code", "")),
                "price": round(self._safe_float(row.get("price")) or 0, 2),
                "change_pct": round(self._safe_float(row.get("change_pct")) or 0, 2),
                "amplitude": round(self._safe_float(row.get("amplitude")) or 0, 2),
                "turnover_rate": round(self._safe_float(row.get("turnover_rate")) or 0, 2),
                "rise_count": int(self._safe_float(row.get("rise_count")) or 0),
                "fall_count": int(self._safe_float(row.get("fall_count")) or 0),
                "top_stock": str(row.get("top_stock", "")),
                "top_stock_change": round(self._safe_float(row.get("top_stock_change")) or 0, 2),
            })

        return {
            "results": results,
            "total": total,
            "returned": len(results),
            "sort_by": sort_by,
            "sort_order": sort_order,
            "source": "akshare",
        }

    # ==================================================================
    # 基金数据 (Fund Data)
    # ==================================================================

    @staticmethod
    def _clean_records(records: list, float_fields: tuple = ()) -> list:
        """Clean NaN/inf in record dicts, round float_fields to 2 decimals."""
        clean = []
        for item in records:
            row = {}
            for k, v in item.items():
                if isinstance(v, float):
                    if math.isnan(v) or math.isinf(v):
                        row[k] = None
                    elif k in float_fields:
                        row[k] = round(v, 2)
                    else:
                        row[k] = v
                elif hasattr(v, "item"):
                    row[k] = v.item()
                else:
                    row[k] = v
            clean.append(row)
        return clean

    async def search_funds(
        self,
        keyword: str = "",
        fund_type: str = "",
        sort_by: str = "近1年",
        sort_order: str = "desc",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """搜索基金列表，支持按名称/代码模糊搜索和多维度排序。"""
        cache_key = f"akshare:search_funds:{keyword}:{fund_type}:{sort_by}:{sort_order}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            df = await self._run(ak.fund_open_fund_rank_em, symbol="全部")
            if df is None or df.empty:
                return {"results": [], "total": 0, "source": "akshare"}

            col_map = {
                "基金代码": "fund_code", "基金简称": "fund_name", "日期": "date",
                "单位净值": "nav", "累计净值": "acc_nav",
                "近1周": "return_1w", "近1月": "return_1m", "近3月": "return_3m",
                "近6月": "return_6m", "近1年": "return_1y", "近2年": "return_2y",
                "近3年": "return_3y", "今年来": "return_ytd",
                "成立来": "return_since_inception", "手续费": "fee",
            }
            df = df.rename(columns=col_map)

            if keyword:
                mask = (
                    df["fund_code"].astype(str).str.contains(keyword, case=False, na=False)
                    | df["fund_name"].astype(str).str.contains(keyword, case=False, na=False)
                )
                df = df[mask]

            sort_col = col_map.get(sort_by, "return_1y")
            if sort_col in df.columns:
                df[sort_col] = pd.to_numeric(df[sort_col], errors="coerce")
                df = df.sort_values(by=sort_col, ascending=(sort_order.lower() == "asc"), na_position="last")

            total = len(df)
            df = df.head(min(limit, 50))
            float_fields = (
                "nav", "acc_nav", "return_1w", "return_1m", "return_3m",
                "return_6m", "return_1y", "return_2y", "return_3y",
                "return_ytd", "return_since_inception", "fee",
            )
            records = self._clean_records(df.to_dict(orient="records"), float_fields)
            result = {
                "results": records, "total": total, "returned": len(records),
                "keyword": keyword, "sort_by": sort_by, "sort_order": sort_order,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(f"search_funds failed: {e}")
            return {"results": [], "total": 0, "source": "akshare", "error": str(e)}

    async def get_fund_detail(self, fund_code: str) -> Dict[str, Any]:
        """获取基金详情：基本信息 + 资产配置。"""
        cache_key = f"akshare:fund_detail:{fund_code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            detail = {"fund_code": fund_code, "source": "akshare"}

            try:
                df_info = await self._run(ak.fund_individual_basic_info_xq, symbol=fund_code)
                if df_info is not None and not df_info.empty:
                    for _, row in df_info.iterrows():
                        key = str(row.iloc[0]).strip()
                        val = row.iloc[1]
                        if hasattr(val, "item"):
                            val = val.item()
                        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                            val = None
                        detail[key] = val
            except Exception:
                pass

            try:
                df_hold = await self._run(ak.fund_individual_detail_hold_xq, symbol=fund_code)
                if df_hold is not None and not df_hold.empty:
                    detail["asset_allocation"] = self._clean_records(df_hold.to_dict(orient="records"))
            except Exception:
                pass

            await self.cache.set(cache_key, detail, ttl=3600)
            return detail
        except Exception as e:
            self.logger.error(f"get_fund_detail failed: {e}")
            return {"fund_code": fund_code, "source": "akshare", "error": str(e)}

    async def get_fund_ranking(
        self, fund_type: str = "全部", sort_by: str = "近1年",
        sort_order: str = "desc", limit: int = 30,
    ) -> Dict[str, Any]:
        """基金排行：按类型和业绩周期筛选排序。"""
        cache_key = f"akshare:fund_ranking:{fund_type}:{sort_by}:{sort_order}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            df = await self._run(ak.fund_open_fund_rank_em, symbol=fund_type)
            if df is None or df.empty:
                return {"results": [], "total": 0, "source": "akshare"}

            col_map = {
                "基金代码": "fund_code", "基金简称": "fund_name", "日期": "date",
                "单位净值": "nav", "累计净值": "acc_nav",
                "近1周": "return_1w", "近1月": "return_1m", "近3月": "return_3m",
                "近6月": "return_6m", "近1年": "return_1y", "近2年": "return_2y",
                "近3年": "return_3y", "今年来": "return_ytd",
                "成立来": "return_since_inception", "手续费": "fee",
            }
            df = df.rename(columns=col_map)

            sort_col = col_map.get(sort_by, "return_1y")
            if sort_col in df.columns:
                df[sort_col] = pd.to_numeric(df[sort_col], errors="coerce")
                df = df.sort_values(by=sort_col, ascending=(sort_order.lower() == "asc"), na_position="last")

            total = len(df)
            df = df.head(min(limit, 100))
            float_fields = (
                "nav", "acc_nav", "return_1w", "return_1m", "return_3m",
                "return_6m", "return_1y", "return_2y", "return_3y",
                "return_ytd", "return_since_inception", "fee",
            )
            results = self._clean_records(df.to_dict(orient="records"), float_fields)
            result = {
                "results": results, "total": total, "returned": len(results),
                "fund_type": fund_type, "sort_by": sort_by, "sort_order": sort_order,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(f"get_fund_ranking failed: {e}")
            return {"results": [], "total": 0, "source": "akshare", "error": str(e)}

    async def get_fund_manager(
        self, manager_name: str = "", fund_company: str = "", limit: int = 20,
    ) -> Dict[str, Any]:
        """基金经理信息：从业时间、管理规模、最佳回报。"""
        cache_key = f"akshare:fund_manager:{manager_name}:{fund_company}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            df = await self._run(ak.fund_manager_em)
            if df is None or df.empty:
                return {"results": [], "total": 0, "source": "akshare"}

            col_map = {
                "姓名": "manager_name",
                "所属公司": "fund_company",
                "现任基金代码": "fund_code",
                "现任基金": "fund_name",
                "累计从业时间": "tenure_days",
                "现任基金资产总规模": "aum",
                "现任基金最佳回报": "best_return",
            }
            df = df.rename(columns=col_map)

            if manager_name:
                df = df[df["manager_name"].astype(str).str.contains(manager_name, case=False, na=False)]
            if fund_company:
                df = df[df["fund_company"].astype(str).str.contains(fund_company, case=False, na=False)]

            total = len(df)
            df = df.head(min(limit, 50))
            results = self._clean_records(df.to_dict(orient="records"), ("aum", "best_return"))
            result = {
                "results": results, "total": total, "returned": len(results),
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            self.logger.error(f"get_fund_manager failed: {e}")
            return {"results": [], "total": 0, "source": "akshare", "error": str(e)}

    async def get_fund_manager_changes(self, fund_code: str, limit: int = 10) -> Dict[str, Any]:
        """基金经理变更公告：聘任、解聘、离任等人事变动记录。

        Data source: akshare fund_announcement_personnel_em
        """
        cache_key = f"akshare:fund_manager_changes:{fund_code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            df = await self._run(ak.fund_announcement_personnel_em, symbol=fund_code)
            if df is None or df.empty:
                return {"fund_code": fund_code, "changes": [], "total": 0, "source": "akshare"}

            col_map = {}
            for c in df.columns:
                cl = str(c)
                if "公告标题" in cl or "标题" in cl:
                    col_map[c] = "title"
                elif "公告日期" in cl or "日期" in cl:
                    col_map[c] = "date"
                elif "基金简称" in cl or "简称" in cl:
                    col_map[c] = "fund_name"
                elif "公告ID" in cl:
                    col_map[c] = "announcement_id"

            df = df.rename(columns=col_map)

            changes = []
            for _, row in df.head(min(limit, 50)).iterrows():
                title = str(row.get("title", ""))
                date = str(row.get("date", ""))

                # Detect change type from title
                change_type = "other"
                if "解聘" in title:
                    change_type = "dismiss"
                elif "增聘" in title:
                    change_type = "appoint"
                elif "聘任" in title:
                    change_type = "appoint"
                elif "离任" in title:
                    change_type = "resign"
                elif "新任" in title:
                    change_type = "appoint"

                changes.append({
                    "date": date,
                    "title": title,
                    "change_type": change_type,
                    "fund_name": str(row.get("fund_name", "")),
                    "announcement_id": str(row.get("announcement_id", "")),
                })

            result = {
                "fund_code": fund_code,
                "changes": changes,
                "total": len(changes),
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            self.logger.error(f"get_fund_manager_changes failed: {e}")
            return {"fund_code": fund_code, "changes": [], "total": 0, "source": "akshare", "error": str(e)}

    async def get_fund_valuation(self, fund_code: str = "") -> Dict[str, Any]:
        """基金实时估值：估算净值、估算涨跌幅、实际净值、偏差。"""
        cache_key = f"akshare:fund_valuation:{fund_code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            df = await self._run(ak.fund_value_estimation_em)
            if df is None or df.empty:
                return {"results": [], "total": 0, "source": "akshare"}

            rename_map = {"序号": "rank", "基金代码": "fund_code", "基金名称": "fund_name"}
            for c in df.columns:
                if "估算值" in str(c):
                    rename_map[c] = "estimated_nav"
                elif "估算涨跌幅" in str(c):
                    rename_map[c] = "estimated_change_pct"
                elif "估算偏差" in str(c):
                    rename_map[c] = "estimation_deviation"
            for c in df.columns:
                if c in rename_map:
                    continue
                if "前单位净值" in str(c) or ("前" in str(c) and "净值" in str(c)):
                    rename_map[c] = "previous_nav"
                elif "单位净值" in str(c):
                    rename_map[c] = "actual_nav"
                elif "涨跌幅" in str(c) and "估算" not in str(c):
                    rename_map[c] = "actual_change_pct"
            df = df.rename(columns=rename_map)

            if fund_code and "fund_code" in df.columns:
                df = df[df["fund_code"].astype(str) == str(fund_code)]

            total = len(df)
            if not fund_code:
                df = df.head(20)

            float_fields = (
                "estimated_nav", "estimated_change_pct", "actual_nav",
                "actual_change_pct", "estimation_deviation", "previous_nav",
            )
            results = self._clean_records(df.to_dict(orient="records"), float_fields)
            result = {
                "results": results, "total": total, "returned": len(results),
                "fund_code": fund_code or "all", "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=300)
            return result
        except Exception as e:
            self.logger.error(f"get_fund_valuation failed: {e}")
            return {"results": [], "total": 0, "source": "akshare", "error": str(e)}

    async def get_fund_performance(self, fund_code: str) -> Dict[str, Any]:
        """基金业绩分析：各周期排名、超额收益、最大回撤、盈利概率。"""
        cache_key = f"akshare:fund_performance:{fund_code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            perf = {"fund_code": fund_code, "source": "akshare"}

            try:
                df_ach = await self._run(ak.fund_individual_achievement_xq, symbol=fund_code)
                if df_ach is not None and not df_ach.empty:
                    perf["achievement"] = self._clean_records(df_ach.to_dict(orient="records"))
            except Exception:
                pass

            try:
                df_ana = await self._run(ak.fund_individual_analysis_xq, symbol=fund_code)
                if df_ana is not None and not df_ana.empty:
                    perf["analysis"] = self._clean_records(df_ana.to_dict(orient="records"))
            except Exception:
                pass

            try:
                df_prof = await self._run(ak.fund_individual_profit_probability_xq, symbol=fund_code)
                if df_prof is not None and not df_prof.empty:
                    perf["profit_probability"] = self._clean_records(df_prof.to_dict(orient="records"))
            except Exception:
                pass

            await self.cache.set(cache_key, perf, ttl=3600)
            return perf
        except Exception as e:
            self.logger.error(f"get_fund_performance failed: {e}")
            return {"fund_code": fund_code, "source": "akshare", "error": str(e)}

    async def get_fund_scale(self) -> Dict[str, Any]:
        """全市场基金规模变动：基金家数/期间申购/赎回/期末净资产变化趋势。"""
        cache_key = "akshare:fund_scale:market"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            # fund_scale_change_em takes NO params, returns market-wide data
            df = await self._run(ak.fund_scale_change_em)
            if df is None or df.empty:
                return {"results": [], "source": "akshare"}

            col_map = {
                "截止日期": "date", "基金家数": "fund_count",
                "期间申购": "subscription", "期间赎回": "redemption",
                "期末总份额": "total_shares", "期末净资产": "total_nav",
            }
            df = df.rename(columns=col_map)
            records = self._clean_records(
                df.to_dict(orient="records"),
                ("subscription", "redemption", "total_shares", "total_nav"),
            )
            result = {
                "results": records, "total": len(records), "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            self.logger.error(f"get_fund_scale failed: {e}")
            return {"results": [], "source": "akshare", "error": str(e)}

    # ==================================================================
    # 指数数据 (Index Data)
    # ==================================================================

    async def get_index_list(self) -> Dict[str, Any]:
        """获取A股指数列表：代码、名称、发布日期。"""
        cache_key = "akshare:index_list"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            df = await self._run(ak.index_stock_info)
            if df is None or df.empty:
                return {"results": [], "total": 0, "source": "akshare"}

            col_map = {
                "index_code": "index_code",
                "display_name": "index_name",
                "publish_date": "publish_date",
            }
            df = df.rename(columns=col_map)
            records = self._clean_records(df.to_dict(orient="records"))
            result = {
                "results": records, "total": len(records), "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=86400)
            return result
        except Exception as e:
            self.logger.error(f"get_index_list failed: {e}")
            return {"results": [], "total": 0, "source": "akshare", "error": str(e)}

    async def get_index_pe_pb(
        self, symbol: str = "沪深300", limit: int = 30,
    ) -> Dict[str, Any]:
        """获取指数估值（PE/PB）历史数据。

        Args:
            symbol: 指数名称 (如 '沪深300', '上证50', '创业板指')
            limit: 返回最近N条数据
        """
        cache_key = f"akshare:index_pe_pb:{symbol}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            df = await self._patched_akshare_call(ak.stock_index_pe_lg, symbol=symbol)
            if df is None or df.empty:
                return {"results": [], "symbol": symbol, "source": "akshare"}

            col_map = {
                "日期": "date",
                "市盈率": "pe",
                "市净率": "pb",
            }
            # Only rename columns that exist
            for cn, en in col_map.items():
                if cn in df.columns:
                    df = df.rename(columns={cn: en})

            total = len(df)
            df = df.tail(min(limit, 100))
            records = self._clean_records(df.to_dict(orient="records"))

            result = {
                "results": records, "total": total,
                "returned": len(records),
                "symbol": symbol, "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            self.logger.error(f"get_index_pe_pb failed: {e}")
            return {"results": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    async def get_index_performance(
        self, symbol: str = "000300", period: str = "daily",
        start_date: str = "", end_date: str = "", limit: int = 60,
    ) -> Dict[str, Any]:
        """获取指数行情数据：开盘/收盘/最高/最低/成交量/涨跌幅。

        Args:
            symbol: 指数代码 (如 '000300'=沪深300, '000001'=上证指数, '399006'=创业板指)
            period: 周期 (daily/weekly/monthly)
            start_date: 开始日期 (如 '20250101')
            end_date: 结束日期 (如 '20260328')
            limit: 返回最近N条 (default 60)
        """
        cache_key = f"akshare:index_perf:{symbol}:{period}:{start_date}:{end_date}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached
        try:
            kwargs = {"symbol": symbol, "period": period}
            if start_date:
                kwargs["start_date"] = start_date
            if end_date:
                kwargs["end_date"] = end_date
            df = await self._run(ak.index_zh_a_hist, **kwargs)
            if df is None or df.empty:
                return {"results": [], "symbol": symbol, "source": "akshare"}

            col_map = {
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude",
                "涨跌幅": "change_pct", "涨跌额": "change", "换手率": "turnover",
            }
            df = df.rename(columns=col_map)

            total = len(df)
            df = df.tail(min(limit, 500))
            float_fields = (
                "open", "close", "high", "low", "volume", "amount",
                "amplitude", "change_pct", "change", "turnover",
            )
            records = self._clean_records(df.to_dict(orient="records"), float_fields)

            result = {
                "results": records, "total": total,
                "returned": len(records),
                "symbol": symbol, "period": period,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(f"get_index_performance failed: {e}")
            return {"results": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # ETF data methods
    # ------------------------------------------------------------------

    async def get_etf_list(self, etf_type: str = "", limit: int = 50) -> Dict[str, Any]:
        """Get ETF list with real-time quotes from East Money.

        Args:
            etf_type: Filter by type (e.g. '股票型', '债券型', '商品型', '跨境型')
            limit: Max results (default 50, max 500)
        """
        cache_key = f"etf_list:{etf_type}:{limit}"
        try:
            cached = await self.cache.get(cache_key)
            if cached:
                return cached

            df = await self._run(ak.fund_etf_spot_em)
            if df is None or df.empty:
                return {"results": [], "total": 0, "returned": 0, "source": "akshare"}

            # Column mapping (Chinese → English)
            col_map = {
                "代码": "etf_code", "名称": "etf_name", "最新价": "price",
                "IOPV实时估值": "iopv", "涨跌额": "change", "涨跌幅": "change_pct",
                "成交量": "volume", "成交额": "amount", "开盘价": "open",
                "最高价": "high", "最低价": "low", "昨收": "prev_close",
                "换手率": "turnover", "流通市值": "circulating_market_cap",
                "总市值": "total_market_cap",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

            # Apply type filter if provided
            if etf_type:
                if "etf_name" in df.columns:
                    type_keywords = {
                        "股票型": ["ETF", "指数"],
                        "债券型": ["债", "国债", "国开"],
                        "商品型": ["黄金", "原油", "商品"],
                        "跨境型": ["纳斯达克", "标普", "恒生", "日经", "德国", "QDII"],
                    }
                    keywords = type_keywords.get(etf_type, [etf_type])
                    mask = df["etf_name"].apply(
                        lambda x: any(kw in str(x) for kw in keywords) if pd.notna(x) else False
                    )
                    df = df[mask]

            total = len(df)
            df = df.head(min(limit, 500))
            float_fields = (
                "price", "change", "change_pct", "volume", "amount",
                "open", "high", "low", "prev_close", "turnover",
            )
            records = self._clean_records(df.to_dict(orient="records"), float_fields)

            result = {
                "results": records, "total": total,
                "returned": len(records),
                "etf_type": etf_type or "all",
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=300)
            return result
        except Exception as e:
            self.logger.error(f"get_etf_list failed: {e}")
            return {"results": [], "total": 0, "source": "akshare", "error": str(e)}

    async def get_etf_detail(self, symbol: str) -> Dict[str, Any]:
        """Get ETF detail info from East Money fund daily data.

        Args:
            symbol: ETF code (e.g. '510300', '159919')
        """
        cache_key = f"etf_detail:{symbol}"
        try:
            cached = await self.cache.get(cache_key)
            if cached:
                return cached

            df = await self._run(ak.fund_etf_fund_daily_em)
            if df is None or df.empty:
                return {"results": [], "source": "akshare", "error": "No ETF data"}

            # Filter for the specific ETF
            code_col = [c for c in df.columns if "代码" in c]
            if code_col:
                target_df = df[df[code_col[0]].astype(str) == symbol]
            else:
                target_df = df[df.iloc[:, 0].astype(str) == symbol]

            if target_df.empty:
                return {"results": [], "symbol": symbol, "source": "akshare", "error": "ETF not found"}

            row = target_df.iloc[0]
            # Build detail dict from available columns
            detail = {}
            for col in df.columns:
                val = row[col]
                if pd.isna(val):
                    detail[col] = None
                else:
                    detail[col] = val

            result = {
                "symbol": symbol, "detail": detail,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=600)
            return result
        except Exception as e:
            self.logger.error(f"get_etf_detail failed: {e}")
            return {"results": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    async def get_etf_performance(
        self, symbol: str = "510300",
        period: str = "daily",
        start_date: str = "",
        end_date: str = "",
        limit: int = 60,
    ) -> Dict[str, Any]:
        """Get ETF price history with OHLCV data.

        Args:
            symbol: ETF code (e.g. '510300')
            period: 'daily', 'weekly', 'monthly'
            start_date: Start date (e.g. '20260101')
            end_date: End date (e.g. '20260328')
            limit: Max results (default 60, max 500)
        """
        cache_key = f"etf_perf:{symbol}:{period}:{start_date}:{end_date}:{limit}"
        try:
            cached = await self.cache.get(cache_key)
            if cached:
                return cached

            df = await self._run(
                ak.fund_etf_hist_em,
                symbol=symbol, period=period,
                start_date=start_date, end_date=end_date,
                adjust="qfq",
            )
            if df is None or df.empty:
                return {"results": [], "symbol": symbol, "source": "akshare"}

            # Column mapping
            col_map = {
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude",
                "涨跌幅": "change_pct", "涨跌额": "change", "换手率": "turnover",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

            total = len(df)
            df = df.tail(min(limit, 500))
            float_fields = (
                "open", "close", "high", "low", "change_pct",
                "change", "amplitude", "turnover",
            )
            records = self._clean_records(df.to_dict(orient="records"), float_fields)

            result = {
                "results": records, "total": total,
                "returned": len(records),
                "symbol": symbol, "period": period,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(f"get_etf_performance failed: {e}")
            return {"results": [], "symbol": symbol, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # ETF Fact Pack
    # ------------------------------------------------------------------

    async def get_etf_fact_pack(self, symbol: str) -> Dict[str, Any]:
        """Aggregate ETF fact pack: master, realtime, performance, flow, technical.

        Args:
            symbol: ETF code (e.g. '510300', '159919')
        """
        symbol = self._to_ak_code(symbol)
        import asyncio as _asyncio

        entity = {"symbol": symbol, "type": "etf", "source": "akshare"}
        facts: Dict[str, Any] = {}
        source_trace: Dict[str, str] = {}
        coverage: Dict[str, str] = {}
        missing_fields: List[str] = []
        categories_total = 5

        async def _fetch_master():
            try:
                detail = await self.get_etf_detail(symbol)
                d = detail.get("detail", {})
                if d and not detail.get("error"):
                    facts["master"] = d
                    source_trace["master"] = "akshare: fund_etf_fund_daily_em"
                    coverage["master"] = "complete"
                else:
                    missing_fields.append("master")
                    coverage["master"] = "missing"
            except Exception as e:
                source_trace["master"] = f"error: {e}"
                coverage["master"] = "error"

        async def _fetch_realtime():
            try:
                df = await self._run(ak.fund_etf_spot_em)
                if df is not None and not df.empty:
                    code_col = "代码" if "代码" in df.columns else df.columns[0]
                    target = df[df[code_col].astype(str) == symbol]
                    if not target.empty:
                        row = target.iloc[0]
                        col_map = {
                            "名称": "name", "最新价": "price",
                            "涨跌额": "change", "涨跌幅": "change_pct",
                            "成交量": "volume", "成交额": "amount",
                            "开盘价": "open", "最高价": "high",
                            "最低价": "low", "昨收": "prev_close",
                            "IOPV实时估值": "iopv", "总市值": "total_market_cap",
                        }
                        rt = {}
                        for cn, en in col_map.items():
                            if cn in row.index:
                                v = row[cn]
                                rt[en] = v.item() if hasattr(v, "item") else v
                        facts["realtime"] = rt
                        source_trace["realtime"] = "akshare: fund_etf_spot_em"
                        coverage["realtime"] = "complete"
                        return
                missing_fields.append("realtime")
                coverage["realtime"] = "missing"
            except Exception as e:
                source_trace["realtime"] = f"error: {e}"
                coverage["realtime"] = "error"

        async def _fetch_performance():
            try:
                perf = await self.get_etf_performance(symbol, period="daily", limit=60)
                results = perf.get("results", [])
                if results and not perf.get("error"):
                    # Derive summary stats from recent data
                    latest = results[-1] if results else {}
                    closes = [r.get("close", 0) for r in results if r.get("close")]
                    if len(closes) >= 2:
                        chg_1d = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0
                        chg_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0
                        chg_20d = (closes[-1] - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 and closes[-21] else 0
                    else:
                        chg_1d = chg_5d = chg_20d = None
                    facts["performance"] = {
                        "latest_date": latest.get("date", ""),
                        "latest_close": latest.get("close"),
                        "latest_volume": latest.get("volume"),
                        "change_pct_1d": round(chg_1d, 2) if chg_1d is not None else None,
                        "change_pct_5d": round(chg_5d, 2) if chg_5d is not None else None,
                        "change_pct_20d": round(chg_20d, 2) if chg_20d is not None else None,
                        "data_points": len(results),
                        "history": results[-10:],
                    }
                    source_trace["performance"] = "akshare: fund_etf_hist_em"
                    coverage["performance"] = "complete"
                else:
                    missing_fields.append("performance")
                    coverage["performance"] = "missing"
            except Exception as e:
                source_trace["performance"] = f"error: {e}"
                coverage["performance"] = "error"

        async def _fetch_flow():
            try:
                flow = await self.get_etf_flow(symbol, days=30)
                data = flow.get("data", [])
                if data and not flow.get("error"):
                    facts["flow"] = data[0] if len(data) == 1 else data
                    source_trace["flow"] = "akshare: fund_etf_spot_em"
                    coverage["flow"] = "complete"
                else:
                    missing_fields.append("flow")
                    coverage["flow"] = "missing"
            except Exception as e:
                source_trace["flow"] = f"error: {e}"
                coverage["flow"] = "error"

        async def _fetch_technical():
            try:
                perf = await self.get_etf_performance(symbol, period="daily", limit=120)
                results = perf.get("results", [])
                if len(results) < 30:
                    missing_fields.append("technical")
                    coverage["technical"] = "missing"
                    return
                closes = [r.get("close", 0) for r in results if r.get("close")]
                if len(closes) < 30:
                    missing_fields.append("technical")
                    coverage["technical"] = "missing"
                    return
                import numpy as np
                s = np.array(closes, dtype=float)
                # RSI(14)
                delta = np.diff(s)
                gain = np.where(delta > 0, delta, 0)
                loss = np.where(delta < 0, -delta, 0)
                avg_gain = np.mean(gain[-14:])
                avg_loss = np.mean(loss[-14:])
                rs = avg_gain / avg_loss if avg_loss != 0 else 100
                rsi14 = 100 - (100 / (1 + rs))
                # MACD
                ema12 = pd.Series(s).ewm(span=12, adjust=False).mean()
                ema26 = pd.Series(s).ewm(span=26, adjust=False).mean()
                dif = ema12 - ema26
                dea = dif.ewm(span=9, adjust=False).mean()
                macd_bar = (dif - dea) * 2
                # Bollinger
                ma20 = np.mean(s[-20:])
                std20 = np.std(s[-20:])
                upper = ma20 + 2 * std20
                lower = ma20 - 2 * std20
                last_close = s[-1]
                # Signal summary
                signals = {}
                if rsi14 > 70:
                    signals["rsi"] = f"RSI({rsi14:.1f}) 超买区"
                elif rsi14 < 30:
                    signals["rsi"] = f"RSI({rsi14:.1f}) 超卖区"
                else:
                    signals["rsi"] = f"RSI({rsi14:.1f}) 中性区"
                if len(dif) >= 2:
                    if dif.iloc[-2] <= dea.iloc[-2] and dif.iloc[-1] > dea.iloc[-1]:
                        signals["macd"] = "MACD金叉"
                    elif dif.iloc[-2] >= dea.iloc[-2] and dif.iloc[-1] < dea.iloc[-1]:
                        signals["macd"] = "MACD死叉"
                    else:
                        signals["macd"] = "MACD无交叉"
                if last_close > upper:
                    signals["boll"] = "突破上轨"
                elif last_close < lower:
                    signals["boll"] = "跌破下轨"
                else:
                    signals["boll"] = "布林带内"
                facts["technical"] = {
                    "rsi14": round(float(rsi14), 2),
                    "macd_dif": round(float(dif.iloc[-1]), 4),
                    "macd_dea": round(float(dea.iloc[-1]), 4),
                    "macd_bar": round(float(macd_bar.iloc[-1]), 4),
                    "boll_upper": round(float(upper), 4),
                    "boll_mid": round(float(ma20), 4),
                    "boll_lower": round(float(lower), 4),
                    "signals": signals,
                }
                source_trace["technical"] = "akshare: derived from fund_etf_hist_em"
                coverage["technical"] = "complete"
            except Exception as e:
                source_trace["technical"] = f"error: {e}"
                coverage["technical"] = "error"

        await _asyncio.gather(
            _fetch_master(),
            _fetch_realtime(),
            _fetch_performance(),
            _fetch_flow(),
            _fetch_technical(),
        )

        categories_fetched = sum(
            1 for v in coverage.values() if v in ("complete", "partial")
        )
        result = {
            "entity": entity,
            "facts": facts,
            "source_trace": source_trace,
            "coverage": coverage,
            "categories_fetched": categories_fetched,
            "categories_total": categories_total,
            "missing_fields": missing_fields,
        }

        # Build fact_markdown view
        try:
            from src.server.domain.fact_markdown import build_etf_fact_markdown
            result["fact_markdown"] = build_etf_fact_markdown(result)
        except Exception as e:
            self.logger.warning(f"fact_markdown generation failed: {e}")

        return result

    # ------------------------------------------------------------------
    # Index Fact Pack
    # ------------------------------------------------------------------

    # Common index code → name mapping for PE/PB lookup
    _INDEX_NAME_MAP: Dict[str, str] = {
        "000001": "上证指数", "000016": "上证50",
        "000300": "沪深300", "000905": "中证500",
        "000852": "中证1000", "399006": "创业板指",
        "399673": "创业板50", "399001": "深证成指",
        "399005": "中小板指", "399673": "创业板50",
    }

    async def get_index_fact_pack(self, symbol: str) -> Dict[str, Any]:
        """Aggregate Index fact pack: master, valuation, performance, constituents, technical.

        Args:
            symbol: Index code (e.g. '000300', '000001')
        """
        import asyncio as _asyncio

        entity = {"symbol": symbol, "type": "index", "source": "akshare"}
        facts: Dict[str, Any] = {}
        source_trace: Dict[str, str] = {}
        coverage: Dict[str, str] = {}
        missing_fields: List[str] = []
        categories_total = 5

        # Resolve index name for PE/PB API
        index_name = self._INDEX_NAME_MAP.get(symbol, "")

        async def _fetch_master():
            try:
                idx_list = await self.get_index_list()
                results = idx_list.get("results", [])
                match = None
                for r in results:
                    code = str(r.get("index_code", ""))
                    if code == symbol or code == symbol.lstrip("0"):
                        match = r
                        break
                if match:
                    facts["master"] = match
                    # Update name from master if not in static map
                    nonlocal index_name
                    if not index_name:
                        index_name = match.get("index_name", "")
                    source_trace["master"] = "akshare: index_stock_info"
                    coverage["master"] = "complete"
                else:
                    facts["master"] = {"index_code": symbol, "index_name": index_name or symbol}
                    source_trace["master"] = "akshare: index_stock_info (not found)"
                    coverage["master"] = "partial"
            except Exception as e:
                source_trace["master"] = f"error: {e}"
                coverage["master"] = "error"

        async def _fetch_valuation():
            try:
                if not index_name:
                    missing_fields.append("valuation")
                    coverage["valuation"] = "missing"
                    source_trace["valuation"] = "skipped: no index name for PE/PB API"
                    return
                pepb = await self.get_index_pe_pb(symbol=index_name, limit=30)
                results = pepb.get("results", [])
                if results and not pepb.get("error"):
                    latest = results[-1] if results else {}
                    pe_values = [r.get("pe") for r in results if r.get("pe") is not None]
                    pb_values = [r.get("pb") for r in results if r.get("pb") is not None]
                    pe_pct = None
                    pb_pct = None
                    if pe_values and latest.get("pe") is not None:
                        pe_pct = sum(1 for v in pe_values if v < latest["pe"]) / len(pe_values) * 100
                    if pb_values and latest.get("pb") is not None:
                        pb_pct = sum(1 for v in pb_values if v < latest["pb"]) / len(pb_values) * 100
                    facts["valuation"] = {
                        "latest_date": latest.get("date", ""),
                        "pe": latest.get("pe"),
                        "pb": latest.get("pb"),
                        "pe_percentile": round(pe_pct, 1) if pe_pct is not None else None,
                        "pb_percentile": round(pb_pct, 1) if pb_pct is not None else None,
                        "data_points": len(results),
                    }
                    source_trace["valuation"] = f"akshare: stock_index_pe_lg ({index_name})"
                    coverage["valuation"] = "complete"
                else:
                    missing_fields.append("valuation")
                    coverage["valuation"] = "missing"
            except Exception as e:
                source_trace["valuation"] = f"error: {e}"
                coverage["valuation"] = "error"

        async def _fetch_performance():
            try:
                perf = await self.get_index_performance(symbol=symbol, period="daily", limit=60)
                results = perf.get("results", [])
                if results and not perf.get("error"):
                    latest = results[-1] if results else {}
                    closes = [r.get("close", 0) for r in results if r.get("close")]
                    changes = {}
                    if len(closes) >= 2 and closes[-2]:
                        changes["change_pct_1d"] = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)
                    if len(closes) >= 6 and closes[-6]:
                        changes["change_pct_5d"] = round((closes[-1] - closes[-6]) / closes[-6] * 100, 2)
                    if len(closes) >= 21 and closes[-21]:
                        changes["change_pct_20d"] = round((closes[-1] - closes[-21]) / closes[-21] * 100, 2)
                    facts["performance"] = {
                        "latest_date": latest.get("date", ""),
                        "latest_close": latest.get("close"),
                        "latest_volume": latest.get("volume"),
                        "latest_amount": latest.get("amount"),
                        **changes,
                        "data_points": len(results),
                        "history": results[-10:],
                    }
                    source_trace["performance"] = "akshare: index_zh_a_hist"
                    coverage["performance"] = "complete"
                else:
                    missing_fields.append("performance")
                    coverage["performance"] = "missing"
            except Exception as e:
                source_trace["performance"] = f"error: {e}"
                coverage["performance"] = "error"

        async def _fetch_constituents():
            try:
                cons = await self.get_index_constituents(index_code=symbol)
                data = cons.get("data", [])
                if data and not cons.get("error"):
                    # Summarize top constituents
                    facts["constituents"] = {
                        "total": cons.get("total_constituents", len(data)),
                        "top10": data[:10],
                    }
                    source_trace["constituents"] = "akshare: index_stock_cons_csindex"
                    coverage["constituents"] = "complete"
                else:
                    missing_fields.append("constituents")
                    coverage["constituents"] = "missing"
            except Exception as e:
                source_trace["constituents"] = f"error: {e}"
                coverage["constituents"] = "error"

        async def _fetch_technical():
            try:
                perf = await self.get_index_performance(symbol=symbol, period="daily", limit=120)
                results = perf.get("results", [])
                if len(results) < 30:
                    missing_fields.append("technical")
                    coverage["technical"] = "missing"
                    return
                closes = [r.get("close", 0) for r in results if r.get("close")]
                if len(closes) < 30:
                    missing_fields.append("technical")
                    coverage["technical"] = "missing"
                    return
                import numpy as np
                s = np.array(closes, dtype=float)
                # RSI(14)
                delta = np.diff(s)
                gain = np.where(delta > 0, delta, 0)
                loss = np.where(delta < 0, -delta, 0)
                avg_gain = np.mean(gain[-14:])
                avg_loss = np.mean(loss[-14:])
                rs = avg_gain / avg_loss if avg_loss != 0 else 100
                rsi14 = 100 - (100 / (1 + rs))
                # MACD
                ema12 = pd.Series(s).ewm(span=12, adjust=False).mean()
                ema26 = pd.Series(s).ewm(span=26, adjust=False).mean()
                dif = ema12 - ema26
                dea = dif.ewm(span=9, adjust=False).mean()
                macd_bar = (dif - dea) * 2
                # Bollinger
                ma20 = np.mean(s[-20:])
                std20 = np.std(s[-20:])
                upper = ma20 + 2 * std20
                lower = ma20 - 2 * std20
                last_close = s[-1]
                signals = {}
                if rsi14 > 70:
                    signals["rsi"] = f"RSI({rsi14:.1f}) 超买区"
                elif rsi14 < 30:
                    signals["rsi"] = f"RSI({rsi14:.1f}) 超卖区"
                else:
                    signals["rsi"] = f"RSI({rsi14:.1f}) 中性区"
                if len(dif) >= 2:
                    if dif.iloc[-2] <= dea.iloc[-2] and dif.iloc[-1] > dea.iloc[-1]:
                        signals["macd"] = "MACD金叉"
                    elif dif.iloc[-2] >= dea.iloc[-2] and dif.iloc[-1] < dea.iloc[-1]:
                        signals["macd"] = "MACD死叉"
                    else:
                        signals["macd"] = "MACD无交叉"
                if last_close > upper:
                    signals["boll"] = "突破上轨"
                elif last_close < lower:
                    signals["boll"] = "跌破下轨"
                else:
                    signals["boll"] = "布林带内"
                facts["technical"] = {
                    "rsi14": round(float(rsi14), 2),
                    "macd_dif": round(float(dif.iloc[-1]), 4),
                    "macd_dea": round(float(dea.iloc[-1]), 4),
                    "macd_bar": round(float(macd_bar.iloc[-1]), 4),
                    "boll_upper": round(float(upper), 4),
                    "boll_mid": round(float(ma20), 4),
                    "boll_lower": round(float(lower), 4),
                    "signals": signals,
                }
                source_trace["technical"] = "akshare: derived from index_zh_a_hist"
                coverage["technical"] = "complete"
            except Exception as e:
                source_trace["technical"] = f"error: {e}"
                coverage["technical"] = "error"

        # Run valuation after master (needs index_name)
        await _fetch_master()
        await _asyncio.gather(
            _fetch_valuation(),
            _fetch_performance(),
            _fetch_constituents(),
            _fetch_technical(),
        )

        categories_fetched = sum(
            1 for v in coverage.values() if v in ("complete", "partial")
        )
        result = {
            "entity": entity,
            "facts": facts,
            "source_trace": source_trace,
            "coverage": coverage,
            "categories_fetched": categories_fetched,
            "categories_total": categories_total,
            "missing_fields": missing_fields,
        }

        # Build fact_markdown view
        try:
            from src.server.domain.fact_markdown import build_index_fact_markdown
            result["fact_markdown"] = build_index_fact_markdown(result)
        except Exception as e:
            self.logger.warning(f"fact_markdown generation failed: {e}")

        return result

    # ------------------------------------------------------------------
    # COL-142: 量价因子 / 相关性 / 组合分析
    # ------------------------------------------------------------------

    async def get_stock_factors(self, symbol: str, days: int = 250) -> Dict[str, Any]:
        """计算单只股票的量化因子 (动量/波动率/换手率/市值/流动性).

        Args:
            symbol: 股票代码 (如 '600519')
            days: 计算窗口天数 (default 250 ≈ 1年交易日)
        """
        # Strip exchange prefix (e.g. "SSE:600519" → "600519")
        symbol = self._to_ak_code(symbol)
        cache_key = f"stock_factors:{symbol}:{days}"
        try:
            cached = await self.cache.get(cache_key)
            if cached:
                return cached

            import numpy as np

            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

            prices = await self._run(
                ak.stock_zh_a_hist, symbol=symbol,
                period="daily", start_date=start_date, end_date=end_date,
            )
            if prices is None or prices.empty:
                return {"symbol": symbol, "factors": {}, "source": "akshare", "error": "No price data"}

            df = prices.copy()
            df["收盘"] = df["收盘"].astype(float)
            df["成交量"] = df["成交量"].astype(float)
            df["成交额"] = df["成交额"].astype(float) if "成交额" in df.columns else 0.0

            closes = df["收盘"].values
            volumes = df["成交量"].values
            amounts = df["成交额"].values

            factors: Dict[str, Any] = {}

            # --- Momentum factors ---
            n = len(closes)
            for period, label in [(22, "1M"), (66, "3M"), (132, "6M"), (264, "12M")]:
                if n > period:
                    ret = (closes[-1] / closes[-period - 1] - 1) * 100
                    factors[f"momentum_{label}"] = round(float(ret), 2)
                else:
                    factors[f"momentum_{label}"] = None

            # --- Volatility factor (annualized) ---
            if n > 22:
                daily_ret = np.diff(closes) / closes[:-1]
                vol = float(np.std(daily_ret[-22:]) * np.sqrt(252) * 100)
                factors["volatility_1M"] = round(vol, 2)
                if n > 66:
                    vol3 = float(np.std(daily_ret[-66:]) * np.sqrt(252) * 100)
                    factors["volatility_3M"] = round(vol3, 2)

            # --- Turnover factor (from amount/price data) ---
            if n > 5:
                avg_amount_5d = float(np.mean(amounts[-5:]))
                avg_amount_20d = float(np.mean(amounts[-20:])) if n > 20 else None
                factors["avg_amount_5d"] = round(avg_amount_5d, 0)
                if avg_amount_20d:
                    factors["avg_amount_20d"] = round(avg_amount_20d, 0)

            # --- Liquidity factor (Amihud illiquidity) ---
            if n > 22:
                daily_ret_abs = np.abs(np.diff(closes[-23:]) / closes[-23:-1])
                dollar_vol = amounts[-22:]
                mask = dollar_vol > 0
                if mask.any():
                    illiq = float(np.mean(daily_ret_abs[mask] / dollar_vol[mask] * 1e8))
                    factors["amihud_illiquidity"] = round(illiq, 6)

            # --- Latest values ---
            factors["latest_close"] = round(float(closes[-1]), 2)
            factors["latest_volume"] = round(float(volumes[-1]), 0)
            factors["latest_amount"] = round(float(amounts[-1]), 0)
            factors["data_days"] = n

            result = {
                "symbol": symbol,
                "factors": factors,
                "calculation_date": end_date,
                "window_days": days,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            self.logger.error(f"get_stock_factors failed: {e}")
            return {"symbol": symbol, "factors": {}, "source": "akshare", "error": str(e)}

    async def get_stock_correlation(
        self, symbols: str, days: int = 60,
    ) -> Dict[str, Any]:
        """计算多只股票之间的相关系数矩阵.

        Args:
            symbols: 逗号分隔的股票代码 (如 '600519,000858,000333')
            days: 计算窗口天数 (default 60)
        """
        cache_key = f"stock_corr:{symbols}:{days}"
        try:
            cached = await self.cache.get(cache_key)
            if cached:
                return cached

            import numpy as np

            code_list = [s.strip() for s in symbols.split(",") if s.strip()]
            # Strip exchange prefixes (e.g. "SSE:600519" → "600519")
            code_list = [self._to_ak_code(c) for c in code_list]
            if len(code_list) < 2:
                return {"error": "Need at least 2 symbols", "source": "akshare"}

            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

            price_series: Dict[str, list] = {}
            for code in code_list:
                df = await self._run(
                    ak.stock_zh_a_hist, symbol=code,
                    period="daily", start_date=start_date, end_date=end_date,
                )
                if df is not None and not df.empty:
                    closes = df["收盘"].astype(float).values
                    if len(closes) > 1:
                        rets = np.diff(closes) / closes[:-1]
                        price_series[code] = rets.tolist()

            if len(price_series) < 2:
                return {"error": "Not enough price data", "symbols": code_list, "source": "akshare"}

            min_len = min(len(v) for v in price_series.values())
            aligned: Dict[str, np.ndarray] = {}
            for code, rets in price_series.items():
                aligned[code] = np.array(rets[-min_len:])

            codes = list(aligned.keys())
            n_codes = len(codes)
            corr_matrix = np.zeros((n_codes, n_codes))

            for i in range(n_codes):
                for j in range(n_codes):
                    if i == j:
                        corr_matrix[i][j] = 1.0
                    else:
                        corr = float(np.corrcoef(aligned[codes[i]], aligned[codes[j]])[0, 1])
                        corr_matrix[i][j] = round(corr, 4)

            matrix_rows = []
            for i, code in enumerate(codes):
                row = {"symbol": code}
                for j, code2 in enumerate(codes):
                    row[f"corr_{code2}"] = corr_matrix[i][j]
                matrix_rows.append(row)

            upper_tri = []
            for i in range(n_codes):
                for j in range(i + 1, n_codes):
                    upper_tri.append(corr_matrix[i][j])
            avg_corr = round(float(np.mean(upper_tri)), 4) if upper_tri else None

            result = {
                "symbols": codes,
                "days": days,
                "data_points": min_len,
                "avg_correlation": avg_corr,
                "correlation_matrix": matrix_rows,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(f"get_stock_correlation failed: {e}")
            return {"symbols": symbols.split(","), "source": "akshare", "error": str(e)}

    async def get_factor_ranking(
        self,
        factor: str = "change_pct",
        direction: str = "desc",
        limit: int = 30,
        exchange: str = "",
    ) -> Dict[str, Any]:
        """全市场因子排名.

        Args:
            factor: 因子名称 (change_pct/turnover_rate/volume_ratio/amplitude)
            direction: 'desc' 或 'asc'
            limit: 返回数量 (default 30, max 100)
            exchange: 交易所筛选 (SSE/SZSE/BSE, 空=全部)
        """
        cache_key = f"factor_rank:{factor}:{direction}:{limit}:{exchange}"
        try:
            cached = await self.cache.get(cache_key)
            if cached:
                return cached

            df = await self._run(ak.stock_zh_a_spot_em)
            if df is None or df.empty:
                return {"results": [], "factor": factor, "source": "akshare", "error": "No spot data"}

            factor_col_map = {
                "change_pct": "涨跌幅",
                "turnover_rate": "换手率",
                "volume_ratio": "量比",
                "amplitude": "振幅",
            }

            col = factor_col_map.get(factor, "涨跌幅")
            if col not in df.columns:
                return {"results": [], "factor": factor, "source": "akshare", "error": f"Column {col} not found"}

            if exchange and "代码" in df.columns:
                exchange_map = {"SSE": "6", "SZSE": ("0", "3"), "BSE": "8"}
                prefix = exchange_map.get(exchange)
                if prefix:
                    if isinstance(prefix, tuple):
                        mask = df["代码"].astype(str).str[0].isin(prefix)
                    else:
                        mask = df["代码"].astype(str).str[0] == prefix
                    df = df[mask]

            df[factor] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=[factor])

            ascending = direction == "asc"
            df = df.sort_values(by=factor, ascending=ascending)

            total = len(df)
            df = df.head(min(limit, 100))

            records = []
            for _, row in df.iterrows():
                r = {
                    "symbol": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "factor_value": round(float(row[factor]), 4) if pd.notna(row[factor]) else None,
                    "factor_name": factor,
                }
                for extra in ["涨跌幅", "换手率", "量比", "最新价", "总市值"]:
                    if extra in df.columns:
                        val = row.get(extra)
                        r[extra] = round(float(val), 2) if pd.notna(val) else None
                records.append(r)

            result = {
                "results": records,
                "total": total,
                "returned": len(records),
                "factor": factor,
                "direction": direction,
                "source": "akshare",
            }
            await self.cache.set(cache_key, result, ttl=300)
            return result
        except Exception as e:
            self.logger.error(f"get_factor_ranking failed: {e}")
            return {"results": [], "factor": factor, "source": "akshare", "error": str(e)}

    # ------------------------------------------------------------------
    # Fund Fact Pack (COL-150)
    # ------------------------------------------------------------------

    async def get_fund_fact_pack(self, fund_code: str) -> Dict[str, Any]:
        """Aggregate fund facts across all categories into a single pack.

        Calls existing fund adapter methods and organizes results into 8 fact
        categories: master, nav, holdings, manager, scale, allocation, fees, peer.

        Args:
            fund_code: Fund code (e.g. 110011, 005827)
        """
        cache_key = f"akshare:fund_fact_pack:{fund_code}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        import time as _time
        t0 = _time.perf_counter()

        entity = {"fund_code": fund_code, "type": "fund"}
        facts: Dict[str, Any] = {}
        source_trace: Dict[str, Any] = {}
        coverage: Dict[str, str] = {}
        missing_fields: List[str] = []

        # --- 1. Fund Master (基金主档) ---
        try:
            detail = await self.get_fund_detail(fund_code)
            if detail and "error" not in detail:
                master: Dict[str, Any] = {
                    "fund_code": fund_code,
                    "source": "akshare",
                }
                # Copy useful fields from detail (skip asset_allocation, raw data)
                skip_keys = {"fund_code", "source", "asset_allocation"}
                for k, v in detail.items():
                    if k not in skip_keys and not isinstance(v, (list, dict)):
                        master[k] = v
                facts["master"] = master
                # Extract allocation separately
                alloc = detail.get("asset_allocation")
                if alloc:
                    facts["allocation"] = alloc
                    coverage["allocation"] = "complete"
                    source_trace["allocation"] = {"provider": "akshare"}
                else:
                    coverage["allocation"] = "missing"
                coverage["master"] = "complete"
            else:
                coverage["master"] = "missing"
                coverage["allocation"] = "missing"
                missing_fields.extend(["master", "allocation"])
        except Exception as e:
            coverage["master"] = f"error: {e}"
            coverage["allocation"] = "missing"
            source_trace["master"] = {"error": str(e)}

        # --- 2. NAV & Performance (净值与收益事实) ---
        nav_data: Dict[str, Any] = {}
        try:
            nav = await self.get_fund_nav(fund_code=fund_code)
            if nav and "error" not in nav:
                nav_data["nav_history"] = nav.get("data", [])[:10]
                coverage["nav"] = "complete" if nav_data["nav_history"] else "partial"
        except Exception:
            pass
        try:
            perf = await self.get_fund_performance(fund_code)
            if perf and "error" not in perf:
                nav_data["performance"] = {
                    k: v for k, v in perf.items()
                    if k not in ("fund_code", "source", "error")
                }
        except Exception:
            pass
        try:
            val = await self.get_fund_valuation(fund_code=fund_code)
            if val and "error" not in val:
                nav_data["valuation"] = {
                    k: v for k, v in val.items()
                    if k not in ("fund_code", "source", "error")
                }
        except Exception:
            pass
        if nav_data:
            facts["nav"] = nav_data
            if "nav" not in coverage:
                coverage["nav"] = "partial"
            source_trace["nav"] = {"provider": "akshare"}
        else:
            coverage["nav"] = "missing"
            missing_fields.append("nav")

        # --- 3. Holdings (持仓与穿透事实) ---
        try:
            holdings = await self.get_fund_holdings(fund_code=fund_code)
            if holdings and "error" not in holdings:
                facts["holdings"] = {
                    "data": holdings.get("data", [])[:20],
                    "total": holdings.get("total", 0),
                }
                coverage["holdings"] = "complete"
                source_trace["holdings"] = {"provider": "akshare"}
            else:
                coverage["holdings"] = "missing"
                missing_fields.append("holdings")
        except Exception as e:
            coverage["holdings"] = f"error: {e}"

        # --- 4. Manager (基金经理与治理事实) ---
        try:
            mgr = await self.get_fund_manager()
            if mgr and "error" not in mgr and "data" in mgr:
                # Filter to the specific fund's manager
                mgr_data = mgr.get("data", [])
                filtered = [
                    m for m in mgr_data
                    if isinstance(m, dict) and str(m.get("基金代码", "")) == fund_code
                ][:5]
                if filtered:
                    facts["manager"] = filtered
                    coverage["manager"] = "complete"
                else:
                    facts["manager"] = mgr_data[:3]  # top managers as reference
                    coverage["manager"] = "partial"
                source_trace["manager"] = {"provider": "akshare"}
            else:
                coverage["manager"] = "missing"
                missing_fields.append("manager")

            # Manager changes sub-field (COL-161)
            try:
                mc = await self.get_fund_manager_changes(fund_code=fund_code, limit=10)
                if mc and "error" not in mc and mc.get("changes"):
                    if isinstance(facts.get("manager"), list):
                        facts["manager"] = {
                            "current": facts["manager"],
                            "changes": mc["changes"][:10],
                            "changes_total": mc.get("total", len(mc["changes"])),
                        }
                    else:
                        facts["manager_changes"] = mc["changes"][:10]
                    if "manager" not in coverage:
                        coverage["manager"] = "partial"
                    source_trace["manager_changes"] = {"provider": "akshare", "api": "fund_announcement_personnel_em"}
            except Exception as e:
                source_trace["manager_changes"] = {"error": str(e)}
        except Exception as e:
            coverage["manager"] = f"error: {e}"

        # --- 5. Scale (规模与份额事实) ---
        try:
            scale = await self.get_fund_scale()
            if scale and "error" not in scale:
                facts["scale"] = {
                    k: v for k, v in scale.items()
                    if k not in ("source", "error")
                }
                coverage["scale"] = "partial"  # market-wide, not fund-specific
                source_trace["scale"] = {"provider": "akshare"}
            else:
                coverage["scale"] = "missing"
                missing_fields.append("scale")
        except Exception as e:
            coverage["scale"] = f"error: {e}"

        # --- 6. Fees & Dividend (费率与分红事实) ---
        try:
            # Extract fees from fund detail (already fetched in category 1)
            detail_raw = facts.get("master", {})
            if not detail_raw:
                # Try fetching detail directly
                detail_raw = await self.get_fund_detail(fund_code)
                if detail_raw and "error" not in detail_raw:
                    detail_raw = {k: v for k, v in detail_raw.items()
                                  if k not in ("fund_code", "source", "asset_allocation")}

            fees_data: Dict[str, Any] = {}
            fee_fields = {
                "管理费率": "management_fee",
                "托管费率": "custody_fee",
                "申购费率": "subscription_fee",
                "赎回费率": "redemption_fee",
                "销售服务费率": "sales_service_fee",
                "最高申购费": "max_subscription_fee",
                "最低申购额": "min_subscription_amount",
            }
            for cn_key, en_key in fee_fields.items():
                val = detail_raw.get(cn_key)
                if val is not None:
                    fees_data[en_key] = self._safe_float(val)

            # Also try akshare fund_purchase_fee for more fee details
            try:
                fee_df = await self._run(ak.fund_purchase_fee, fund=fund_code)
                if fee_df is not None and not fee_df.empty:
                    for _, row in fee_df.iterrows():
                        fees_data["purchase_fee_detail"] = self._clean_records(
                            fee_df.to_dict(orient="records")
                        )
            except Exception:
                pass

            if fees_data:
                facts["fees"] = fees_data
                coverage["fees"] = "complete"
                source_trace["fees"] = {"provider": "akshare", "api": "fund_individual_basic_info_xq"}
            else:
                coverage["fees"] = "missing"
                missing_fields.append("fees")
        except Exception as e:
            coverage["fees"] = f"error: {e}"
            source_trace["fees"] = {"error": str(e)}
            missing_fields.append("fees")

        # --- 7. Peer Comparison (同类比较事实) ---
        try:
            # Determine fund type from master data
            fund_type = None
            master_data = facts.get("master", {})
            if isinstance(master_data, dict):
                # Try common type field names
                for tf in ("基金类型", "fund_type", "类型"):
                    ft = master_data.get(tf)
                    if ft:
                        fund_type = str(ft)
                        break

            if fund_type:
                ranking = await self.get_fund_ranking(fund_type=fund_type, limit=20)
                if ranking and "error" not in ranking and ranking.get("results"):
                    peers_list = []
                    for item in ranking.get("results", [])[:10]:
                        # Exclude the target fund itself
                        if str(item.get("fund_code", "")) == str(fund_code):
                            continue
                        peers_list.append({
                            "fund_code": item.get("fund_code"),
                            "fund_name": item.get("fund_name"),
                            "nav": item.get("nav"),
                            "return_1y": item.get("return_1y"),
                            "return_ytd": item.get("return_ytd"),
                        })
                    facts["peer"] = {
                        "fund_type": fund_type,
                        "peers": peers_list,
                        "count": len(peers_list),
                    }
                    coverage["peer"] = "complete"
                    source_trace["peer"] = {"provider": "akshare", "api": "fund_open_fund_rank_em"}
                else:
                    coverage["peer"] = "missing"
                    missing_fields.append("peer")
            else:
                coverage["peer"] = "missing: no fund type info"
                missing_fields.append("peer")
        except Exception as e:
            coverage["peer"] = f"error: {e}"
            source_trace["peer"] = {"error": str(e)}
            missing_fields.append("peer")

        elapsed = _time.perf_counter() - t0

        result = {
            "source": "akshare",
            "entity": entity,
            "facts": facts,
            "source_trace": source_trace,
            "coverage": coverage,
            "missing_fields": missing_fields,
            "categories_fetched": len([v for v in coverage.values() if v in ("complete", "partial")]),
            "categories_total": 8,
            "elapsed_seconds": round(elapsed, 2),
        }

        # Build fact_markdown view (COL-151)
        try:
            from src.server.domain.fact_markdown import build_fund_fact_markdown
            result["fact_markdown"] = build_fund_fact_markdown(result)
        except Exception as e:
            self.logger.warning(f"fact_markdown generation failed: {e}")

        await self.cache.set(cache_key, result, ttl=600)
        return result

    # ------------------------------------------------------------------
    # Market Fact Pack (COL-152)
    # ------------------------------------------------------------------

    async def get_market_fact_pack(self, symbol: str) -> Dict[str, Any]:
        """Aggregate market/quote facts across all categories into a single pack.

        Calls existing adapter methods and organizes results into 10 fact
        categories: master, snapshot, kline, money_flow, breadth, index,
        derivative, relative, north_bound, margin.

        Args:
            symbol: Stock code (e.g. 600519, 000001)
        """
        cache_key = f"akshare:market_fact_pack:{symbol}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        import time as _time
        t0 = _time.perf_counter()

        entity = {"symbol": symbol, "type": "market"}
        facts: Dict[str, Any] = {}
        source_trace: Dict[str, Any] = {}
        coverage: Dict[str, str] = {}
        missing_fields: List[str] = []

        # --- 1. Master (标的估值指标) ---
        try:
            val = await self._get_valuation_raw(symbol)
            if val:
                facts["master"] = val
                coverage["master"] = "complete"
                source_trace["master"] = {"provider": "akshare"}
            else:
                coverage["master"] = "missing"
                missing_fields.append("master")
        except Exception as e:
            coverage["master"] = f"error: {e}"

        # --- 2. Snapshot (技术指标快照) ---
        try:
            tech = await self.calculate_technical_indicators(symbol, days=30)
            if tech and "error" not in tech:
                snap: Dict[str, Any] = {}
                for ind_name, ind_data in tech.items():
                    if isinstance(ind_data, list) and ind_data:
                        snap[ind_name] = ind_data[-1] if len(ind_data) <= 5 else ind_data[-5:]
                    elif isinstance(ind_data, dict):
                        snap[ind_name] = ind_data
                facts["snapshot"] = snap
                coverage["snapshot"] = "complete"
                source_trace["snapshot"] = {"provider": "akshare"}
            else:
                coverage["snapshot"] = "missing"
                missing_fields.append("snapshot")
        except Exception as e:
            coverage["snapshot"] = f"error: {e}"

        # --- 2b. Technical Signals (确定性技术信号) ---
        try:
            sig = await self.get_technical_signals(symbol)
            if sig and "error" not in sig and sig.get("signals"):
                if "snapshot" in facts:
                    facts["snapshot"]["signals"] = sig["signals"]
                else:
                    facts["snapshot"] = {"signals": sig["signals"]}
                source_trace["signals"] = {"provider": "akshare"}
                if coverage.get("snapshot") == "missing":
                    coverage["snapshot"] = "partial"
        except Exception:
            pass

        # --- 3. Kline (K线与因子数据) ---
        try:
            factors = await self.get_stock_factors(symbol, days=60)
            if factors and "error" not in factors:
                facts["kline"] = {
                    "factors": factors.get("factors", {}),
                    "symbol": factors.get("symbol", symbol),
                }
                coverage["kline"] = "complete"
                source_trace["kline"] = {"provider": "akshare"}
            else:
                coverage["kline"] = "missing"
                missing_fields.append("kline")
        except Exception as e:
            coverage["kline"] = f"error: {e}"

        # --- 4. Money Flow (资金流) ---
        try:
            flow = await self.get_money_flow(f"SSE:{symbol}")
            if not flow or "error" in flow:
                flow = await self.get_money_flow(f"SZSE:{symbol}")
            if flow and "error" not in flow:
                facts["money_flow"] = flow
                coverage["money_flow"] = "complete"
                source_trace["money_flow"] = {"provider": "akshare"}
            else:
                coverage["money_flow"] = "missing"
                missing_fields.append("money_flow")
        except Exception as e:
            coverage["money_flow"] = f"error: {e}"

        # --- 5. Market Breadth (市场广度) ---
        try:
            breadth = await self.get_market_breadth(days=20)
            if breadth and "error" not in breadth:
                facts["breadth"] = {
                    k: v for k, v in breadth.items()
                    if k not in ("source", "error")
                }
                coverage["breadth"] = "complete"
                source_trace["breadth"] = {"provider": "akshare"}
            else:
                coverage["breadth"] = "missing"
                missing_fields.append("breadth")
        except Exception as e:
            coverage["breadth"] = f"error: {e}"

        # --- 6. Index / Sector (指数/板块行情) ---
        try:
            sector = await self.get_sector_trend()
            index_data: Dict[str, Any] = {
                k: v for k, v in sector.items()
                if k not in ("source", "error")
            } if sector and "error" not in sector else {}

            # Add sector valuation percentile if we can determine the industry
            try:
                cm_df = await self._run(ak.stock_individual_info_em, symbol=symbol)
                if cm_df is not None and not cm_df.empty:
                    industry = None
                    for _, row in cm_df.iterrows():
                        if str(row.get("item", "")) == "行业":
                            industry = str(row.get("value", ""))
                            break
                    if industry:
                        sv = await self.get_sector_pe_pb_historical(sector_name=industry)
                        if sv and "error" not in sv and "current" in sv:
                            # Only keep fact fields, strip analytical labels
                            sv_current = sv.get("current", {})
                            index_data["sector_valuation"] = {
                                "industry": industry,
                                "pe": sv_current.get("pe"),
                                "pb": sv_current.get("pb"),
                                "pe_percentile": sv_current.get("pe_percentile"),
                                "total_stocks": sv.get("summary", {}).get("total_stocks"),
                                "pe_mean": sv.get("summary", {}).get("pe_mean"),
                                "pb_mean": sv.get("summary", {}).get("pb_mean"),
                            }
                            source_trace["sector_valuation"] = {"provider": "akshare", "api": "get_sector_pe_pb_historical"}
            except Exception:
                pass

            if index_data:
                facts["index"] = index_data
                coverage["index"] = "partial" if "sector_valuation" not in index_data else "complete"
                source_trace["index"] = {"provider": "akshare"}
            else:
                coverage["index"] = "missing"
                missing_fields.append("index")
        except Exception as e:
            coverage["index"] = f"error: {e}"

        # --- 7. Derivative (衍生行情/期货基差) ---
        try:
            basis = await self.get_futures_basis(days=30)
            if basis and "error" not in basis:
                facts["derivative"] = {
                    k: v for k, v in basis.items()
                    if k not in ("source", "error")
                }
                coverage["derivative"] = "partial"
                source_trace["derivative"] = {"provider": "akshare"}
            else:
                coverage["derivative"] = "missing"
                missing_fields.append("derivative")
        except Exception as e:
            coverage["derivative"] = f"error: {e}"

        # --- 8. Relative Strength (相对强弱) ---
        try:
            rs = await self.get_relative_strength(symbol)
            if rs and "error" not in rs:
                facts["relative"] = {
                    k: v for k, v in rs.items()
                    if k not in ("source", "error")
                }
                coverage["relative"] = "complete"
                source_trace["relative"] = {"provider": "akshare"}
            else:
                coverage["relative"] = "missing"
                missing_fields.append("relative")
        except Exception as e:
            coverage["relative"] = f"error: {e}"

        # --- 9. North Bound Flow (北向资金) ---
        try:
            nb = await self.get_north_bound_flow(days=10)
            if nb and "error" not in nb and nb.get("data"):
                latest = nb["data"][-1] if nb["data"] else {}
                facts["north_bound"] = {
                    "latest_net_inflow": latest.get("north_net_inflow") or latest.get("净买入"),
                    "latest_date": latest.get("date") or latest.get("日期"),
                    "trend": nb["data"][-5:] if len(nb.get("data", [])) >= 5 else nb.get("data", []),
                }
                coverage["north_bound"] = "complete"
                source_trace["north_bound"] = {"provider": "akshare", "api": "north_bound_flow"}
            else:
                coverage["north_bound"] = "missing"
                missing_fields.append("north_bound")
        except Exception as e:
            coverage["north_bound"] = f"error: {e}"

        # --- 10. Margin (融资融券) ---
        try:
            mg = await self.get_margin_trading(symbol, days=5)
            if mg and "error" not in mg and mg.get("data"):
                facts["margin"] = {
                    "summary": mg.get("summary", {}),
                    "exchange": mg.get("exchange", ""),
                }
                coverage["margin"] = "complete"
                source_trace["margin"] = {"provider": "akshare", "api": "margin_detail"}
            else:
                coverage["margin"] = "missing"
                missing_fields.append("margin")
        except Exception as e:
            coverage["margin"] = f"error: {e}"

        elapsed = _time.perf_counter() - t0

        result = {
            "source": "akshare",
            "entity": entity,
            "facts": facts,
            "source_trace": source_trace,
            "coverage": coverage,
            "missing_fields": missing_fields,
            "categories_fetched": len([v for v in coverage.values() if v in ("complete", "partial")]),
            "categories_total": 10,
            "elapsed_seconds": round(elapsed, 2),
        }

        # Build fact_markdown view (COL-153)
        try:
            from src.server.domain.fact_markdown import build_market_fact_markdown
            result["fact_markdown"] = build_market_fact_markdown(result)
        except Exception as e:
            self.logger.warning(f"fact_markdown generation failed: {e}")

        await self.cache.set(cache_key, result, ttl=600)
        return result

