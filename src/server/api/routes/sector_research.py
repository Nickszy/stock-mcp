# src/server/api/routes/sector_research.py
"""Sector research orchestration API routes.

Provides RESTful HTTP endpoints that mirror the sector-research MCP tool group:
- resolve_sector_scope
- build_sector_universe
- build_peer_benchmark_table
- classify_value_chain
- build_sector_evidence_pack
- build_sector_structure_snapshot
- quality_gate_sector_report
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.server.utils.logger import logger
from src.server.domain.response_contract import rest_response
from src.server.mcp.tools.sector_research_tools import (
    _build_cn_universe_from_tushare,
    _build_peer_rows,
    _contains_required_sections,
    _count_numeric_facts,
    _detect_market,
    _infer_value_chain_stage,
    _pick_numeric,
    _resolve_symbols,
)
from src.server.core.use_cases import (
    filings as filings_use_cases,
    fundamental as fundamental_use_cases,
    market as market_use_cases,
    money_flow as money_flow_use_cases,
    technical as technical_use_cases,
)

router = APIRouter(prefix="/api/v1/sector-research", tags=["行业 Sector"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SectorScopeRequest(BaseModel):
    sector_name: str = Field(..., description="行业/板块名称")
    market: str = Field("auto", description="市场 (auto/cn/us)")
    depth: str = Field("standard", description="研究深度 (standard/deep)")
    horizon_days: int = Field(365, ge=30, le=3650, description="观察窗口天数")
    peer_count: int = Field(10, ge=5, le=30, description="同业样本数")
    angle: str = Field("neutral", description="研究视角 (neutral/bullish/bearish)")


class SectorUniverseRequest(BaseModel):
    sector_name: str = Field(..., description="行业/板块名称")
    market: str = Field("auto", description="市场 (auto/cn/us)")
    symbols: Optional[List[str]] = Field(None, description="已知标的列表(可选)")
    max_companies: int = Field(10, ge=5, le=50, description="最大公司数")


class PeerBenchmarkRequest(BaseModel):
    sector_name: str = Field(..., description="行业/板块名称")
    symbols: List[str] = Field(..., description="标的列表")
    market: str = Field("auto", description="市场 (auto/cn/us)")


class ValueChainRequest(BaseModel):
    sector_name: str = Field(..., description="行业/板块名称")
    symbols: List[str] = Field(..., description="标的列表")
    market: str = Field("auto", description="市场 (auto/cn/us)")


class EvidencePackRequest(BaseModel):
    sector_name: str = Field(..., description="行业/板块名称")
    market: str = Field("auto", description="市场 (auto/cn/us)")
    symbols: Optional[List[str]] = Field(None, description="标的列表(可选)")
    days: int = Field(120, ge=30, le=750, description="回溯天数")
    include_filings: bool = Field(True, description="是否包含公告摘要")


class StructureSnapshotRequest(BaseModel):
    sector_name: str = Field(..., description="行业/板块名称")
    market: str = Field("auto", description="市场 (auto/cn/us)")
    days: int = Field(90, ge=30, le=365, description="回溯天数")


class QualityGateRequest(BaseModel):
    report_markdown: str = Field(..., description="报告Markdown文本")
    evidence_pack: Optional[Dict[str, Any]] = Field(None, description="关联的证据包")
    min_numeric_facts: int = Field(6, ge=3, le=30, description="最少数值型事实数")
    require_question: bool = Field(True, description="是否要求报告末尾有问题")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/scope",
    summary="规范化行业研究范围",
    description="标准化行业研究参数: 市场/深度/窗口/样本数/视角",
)
async def resolve_sector_scope(req: SectorScopeRequest) -> Dict[str, Any]:
    try:
        detected_market = _detect_market(req.market, req.sector_name, None)
        safe_peer_count = max(5, min(req.peer_count, 30))
        safe_horizon = max(30, min(req.horizon_days, 3650))

        scope = {
            "sector_name": req.sector_name,
            "market": detected_market,
            "depth": req.depth,
            "horizon_days": safe_horizon,
            "peer_count": safe_peer_count,
            "angle": req.angle,
            "as_of_date": datetime.utcnow().strftime("%Y-%m-%d"),
        }

        recommended_tools = (
            [
                "build_sector_universe",
                "build_peer_benchmark_table",
                "build_sector_evidence_pack",
            ]
            if detected_market == "US"
            else [
                "build_sector_universe",
                "get_sector_trend",
                "get_sector_valuation_metrics",
                "build_peer_benchmark_table",
                "build_sector_evidence_pack",
            ]
        )

        return rest_response(
            data={"scope": scope, "recommended_tools": recommended_tools},
            source="sector-research",
        )
    except Exception as e:
        logger.error(f"API error in resolve_sector_scope: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/universe",
    summary="构建行业研究样本池",
    description="构建行业公司样本池 (CN自动/Tushare, US手动指定)",
)
async def build_sector_universe(req: SectorUniverseRequest) -> Dict[str, Any]:
    try:
        symbols = req.symbols or []
        detected_market = _detect_market(req.market, req.sector_name, symbols)
        max_companies = max(5, min(req.max_companies, 50))

        if symbols:
            resolved = await _resolve_symbols(symbols)
            universe = []
            for ticker in resolved[:max_companies]:
                asset = await market_use_cases.get_asset_info(ticker) or {}
                universe.append({
                    "ticker": ticker,
                    "company_name": asset.get("name", ""),
                    "market": "US" if ticker.startswith(("NASDAQ:", "NYSE:", "AMEX:")) else "CN",
                })
            source = "manual"
            extra = {}
        elif detected_market == "CN":
            cn = await _build_cn_universe_from_tushare(
                sector_name=req.sector_name,
                max_companies=max_companies,
            )
            universe = cn.get("universe", [])
            source = cn.get("source", "manual")
            extra = {
                "index_code": cn.get("index_code"),
                "index_name": cn.get("index_name"),
                "candidates": cn.get("candidates", []),
                "note": cn.get("note"),
            }
        else:
            universe = []
            source = "manual"
            extra = {"note": "US market requires explicit symbols currently"}

        return rest_response(
            data={
                "sector_name": req.sector_name,
                "market": detected_market,
                "source": source,
                "universe": universe,
                **extra,
            },
            source="sector-research",
        )
    except Exception as e:
        logger.error(f"API error in build_sector_universe: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/peer-benchmark",
    summary="构建同业对比表",
    description="为指定标的构建同业估值对比 (PE/PB/EV-EBITDA/市值/增长率)",
)
async def build_peer_benchmark(req: PeerBenchmarkRequest) -> Dict[str, Any]:
    try:
        if not req.symbols:
            raise HTTPException(status_code=400, detail="symbols cannot be empty")

        resolved = await _resolve_symbols(req.symbols)
        rows = await _build_peer_rows(resolved)
        detected_market = _detect_market(req.market, req.sector_name, resolved)

        return rest_response(
            data={
                "sector_name": req.sector_name,
                "market": detected_market,
                "rows": rows,
            },
            source="sector-research",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API error in build_peer_benchmark: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/value-chain",
    summary="价值链分类",
    description="将行业公司分类到上游/中游/下游",
)
async def classify_value_chain(req: ValueChainRequest) -> Dict[str, Any]:
    try:
        if not req.symbols:
            raise HTTPException(status_code=400, detail="symbols cannot be empty")

        resolved = await _resolve_symbols(req.symbols)
        detected_market = _detect_market(req.market, req.sector_name, resolved)

        rows: List[Dict[str, Any]] = []
        stage_counts: Dict[str, int] = {"上游": 0, "中游": 0, "下游": 0, "待判定": 0}
        for ticker in resolved:
            asset = await market_use_cases.get_asset_info(ticker) or {}
            name = asset.get("name") or ticker
            company_market = "US" if ticker.startswith(("NASDAQ:", "NYSE:", "AMEX:")) else "CN"

            segment_lines: List[str] = []
            if company_market == "CN":
                try:
                    mainbz = await fundamental_use_cases.get_mainbz_info(ticker) or {}
                    bz_rows = mainbz.get("rows") if isinstance(mainbz, dict) else []
                    if isinstance(bz_rows, list) and bz_rows:
                        sorted_rows = sorted(
                            [r for r in bz_rows if isinstance(r, dict)],
                            key=lambda r: _pick_numeric(r, ["bz_sales", "bz_profit"]) or 0,
                            reverse=True,
                        )
                        for rec in sorted_rows[:5]:
                            item = str(rec.get("bz_item") or rec.get("bz_name") or "").strip()
                            if item:
                                segment_lines.append(item)
                except Exception:
                    segment_lines = []

            text_blob = " ".join([req.sector_name, str(name), *segment_lines])
            stage, confidence, matched_keywords = _infer_value_chain_stage(text_blob)
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

            rows.append({
                "ticker": ticker,
                "company_name": name,
                "market": company_market,
                "value_chain_stage": stage,
                "confidence": confidence,
                "evidence_keywords": matched_keywords[:5],
                "business_segments": segment_lines[:5],
            })

        return rest_response(
            data={
                "sector_name": req.sector_name,
                "market": detected_market,
                "rows": rows,
                "stage_counts": stage_counts,
            },
            source="sector-research",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API error in classify_value_chain: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/evidence-pack",
    summary="构建行业证据包",
    description="聚合行业快照+同业对比+公告摘要为结构化证据包",
)
async def build_sector_evidence_pack(req: EvidencePackRequest) -> Dict[str, Any]:
    try:
        symbols = req.symbols or []
        detected_market = _detect_market(req.market, req.sector_name, symbols)
        safe_days = max(30, min(req.days, 750))

        if symbols:
            universe = await _resolve_symbols(symbols)
        elif detected_market == "CN":
            cn = await _build_cn_universe_from_tushare(req.sector_name, max_companies=10)
            universe = [i["ticker"] for i in cn.get("universe", [])]
        else:
            universe = []

        # 1) sector snapshot
        sector_snapshot: Dict[str, Any] = {"market": detected_market}
        if detected_market == "CN":
            try:
                sector_snapshot["trend"] = await money_flow_use_cases.get_sector_trend(
                    req.sector_name, days=min(safe_days, 90)
                )
            except Exception as e:
                sector_snapshot["trend_error"] = str(e)
            try:
                sector_snapshot["valuation"] = await money_flow_use_cases.get_sector_valuation_metrics(
                    sector_name=req.sector_name,
                    days=min(safe_days, 250),
                    sample_size=max(20, len(universe) or 20),
                )
            except Exception as e:
                sector_snapshot["valuation_error"] = str(e)
        else:
            try:
                sector_snapshot["etf"] = await technical_use_cases.get_us_sector_etf_analysis(
                    sector_name=req.sector_name,
                    days=min(safe_days, 120),
                )
            except Exception as e:
                sector_snapshot["etf_error"] = str(e)

        # 2) peer rows
        peer_rows = await _build_peer_rows(universe) if universe else []

        # 3) filings digest
        filings_digest: List[Dict[str, Any]] = []
        if req.include_filings and universe:
            for ticker in universe[:5]:
                item: Dict[str, Any] = {"ticker": ticker}
                try:
                    if detected_market == "US":
                        periodic = await filings_use_cases.fetch_periodic_sec_filings(
                            ticker=ticker, forms=["10-K", "10-Q", "20-F"], limit=3,
                        )
                        event = await filings_use_cases.fetch_event_sec_filings(
                            ticker=ticker, forms=["8-K", "6-K"], limit=3,
                        )
                        item["periodic_count"] = len(periodic or [])
                        item["event_count"] = len(event or [])
                        latest = None
                        for rec in (periodic or []) + (event or []):
                            fd = rec.get("filingDate") or rec.get("filing_date")
                            if fd and (latest is None or str(fd) > str(latest)):
                                latest = fd
                        item["latest_filing_date"] = latest
                    else:
                        ashare = await filings_use_cases.fetch_ashare_filings(
                            symbol=ticker,
                            filing_types=["annual", "semi-annual", "quarterly"],
                            limit=3,
                        )
                        item["filing_count"] = len(ashare or [])
                        latest = None
                        for rec in ashare or []:
                            fd = rec.get("filing_date") or rec.get("filingDate")
                            if fd and (latest is None or str(fd) > str(latest)):
                                latest = fd
                        item["latest_filing_date"] = latest
                except Exception as e:
                    item["error"] = str(e)
                filings_digest.append(item)

        return rest_response(
            data={
                "scope": {
                    "sector_name": req.sector_name,
                    "market": detected_market,
                    "days": safe_days,
                    "generated_at": datetime.utcnow().isoformat(),
                },
                "universe": universe,
                "sector_snapshot": sector_snapshot,
                "peer_benchmark": peer_rows,
                "filings_digest": filings_digest,
            },
            source="sector-research",
        )
    except Exception as e:
        logger.error(f"API error in build_sector_evidence_pack: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/structure-snapshot",
    summary="行业结构快照",
    description="构建行业结构快照: 价格动量/资金信号/估值水位/结构评分",
)
async def build_sector_structure_snapshot(req: StructureSnapshotRequest) -> Dict[str, Any]:
    try:
        detected_market = _detect_market(req.market, req.sector_name, None)
        safe_days = max(30, min(req.days, 365))

        snapshot: Dict[str, Any] = {
            "sector_name": req.sector_name,
            "market": detected_market,
            "days": safe_days,
            "price_momentum": None,
            "flow_signal": "unknown",
            "valuation_level": "unknown",
            "structure_score": 0,
        }
        evidence: Dict[str, Any] = {}
        score = 0

        if detected_market == "CN":
            try:
                trend = await money_flow_use_cases.get_sector_trend(
                    req.sector_name, days=min(safe_days, 90)
                )
                evidence["trend"] = trend
                total_pct = trend.get("total_pct_chg") if isinstance(trend, dict) else None
                if isinstance(total_pct, (int, float)):
                    snapshot["price_momentum"] = float(total_pct)
                    score += 1 if total_pct > 0 else -1
            except Exception as e:
                evidence["trend_error"] = str(e)

            try:
                flow = await money_flow_use_cases.get_sector_money_flow_history(
                    req.sector_name, days=min(safe_days, 120)
                )
                evidence["flow"] = flow
                flow_trend = (flow.get("summary") or {}).get("trend") if isinstance(flow, dict) else None
                if isinstance(flow_trend, str) and flow_trend:
                    snapshot["flow_signal"] = flow_trend
                    if "流入" in flow_trend:
                        score += 1
                    elif "流出" in flow_trend:
                        score -= 1
            except Exception as e:
                evidence["flow_error"] = str(e)

            try:
                val = await money_flow_use_cases.get_sector_valuation_metrics(
                    sector_name=req.sector_name,
                    days=min(safe_days, 250),
                    sample_size=60,
                )
                evidence["valuation"] = val
                level = (val.get("summary") or {}).get("valuation_level") if isinstance(val, dict) else None
                if isinstance(level, str) and level:
                    snapshot["valuation_level"] = level
                    if level in {"低估", "偏低"}:
                        score += 1
                    elif level in {"高估", "偏高"}:
                        score -= 1
            except Exception as e:
                evidence["valuation_error"] = str(e)
        else:
            try:
                etf = await technical_use_cases.get_us_sector_etf_analysis(
                    sector_name=req.sector_name,
                    days=min(safe_days, 120),
                )
                evidence["etf"] = etf
                total_pct = etf.get("total_change_pct") if isinstance(etf, dict) else None
                if isinstance(total_pct, (int, float)):
                    snapshot["price_momentum"] = float(total_pct)
                    score += 1 if total_pct > 0 else -1
            except Exception as e:
                evidence["etf_error"] = str(e)
            snapshot["flow_signal"] = "limited_data"
            snapshot["valuation_level"] = "limited_data"

        snapshot["structure_score"] = max(-3, min(3, score))

        return rest_response(
            data={"snapshot": snapshot, "evidence": evidence},
            source="sector-research",
        )
    except Exception as e:
        logger.error(f"API error in build_sector_structure_snapshot: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/quality-gate",
    summary="行业报告质量门控",
    description="对行业研究报告草稿运行质量门控检查",
)
async def quality_gate_sector_report(req: QualityGateRequest) -> Dict[str, Any]:
    try:
        evidence_pack = req.evidence_pack or {}
        min_numeric = max(3, min(req.min_numeric_facts, 30))

        section_checks = _contains_required_sections(req.report_markdown or "")
        numeric_count = _count_numeric_facts(req.report_markdown or "")
        has_question = ("?" in (req.report_markdown or "")) or ("？" in (req.report_markdown or ""))

        peer_rows = (evidence_pack.get("peer_benchmark") or []) if isinstance(evidence_pack, dict) else []
        filings_digest = (evidence_pack.get("filings_digest") or []) if isinstance(evidence_pack, dict) else []
        universe = (evidence_pack.get("universe") or []) if isinstance(evidence_pack, dict) else []

        checks = [
            {
                "name": "required_sections",
                "pass": all(section_checks.values()),
                "detail": section_checks,
            },
            {
                "name": "numeric_facts",
                "pass": numeric_count >= min_numeric,
                "detail": {"count": numeric_count, "threshold": min_numeric},
            },
            {
                "name": "peer_rows",
                "pass": len(peer_rows) >= 3,
                "detail": {"count": len(peer_rows), "threshold": 3},
            },
            {
                "name": "filings_digest",
                "pass": len(filings_digest) >= 1,
                "detail": {"count": len(filings_digest), "threshold": 1},
            },
            {
                "name": "universe_non_empty",
                "pass": len(universe) >= 1,
                "detail": {"count": len(universe), "threshold": 1},
            },
            {
                "name": "ending_question",
                "pass": (has_question if req.require_question else True),
                "detail": {"required": req.require_question, "has_question": has_question},
            },
        ]

        failed = [c["name"] for c in checks if not c["pass"]]
        pass_all = len(failed) == 0

        return rest_response(
            data={
                "pass": pass_all,
                "failed_checks": failed,
                "checks": checks,
                "metrics": {
                    "numeric_facts": numeric_count,
                    "peer_rows": len(peer_rows),
                    "filings_digest": len(filings_digest),
                    "universe_count": len(universe),
                },
            },
            source="sector-research",
        )
    except Exception as e:
        logger.error(f"API error in quality_gate_sector_report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
