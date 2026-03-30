# src/server/api/routes/sentiment.py
"""Market sentiment / QVIX REST API routes."""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from src.server.utils.logger import logger
from src.server.core.use_cases import sentiment as sent_uc
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/sentiment", tags=["市场情绪 Sentiment"])


@router.get("/qvix/50etf", summary="50ETF QVIX")
async def get_qvix_50etf() -> Dict[str, Any]:
    try:
        result = await sent_uc.get_qvix_50etf()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_qvix_50etf: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qvix/300etf", summary="300ETF QVIX")
async def get_qvix_300etf() -> Dict[str, Any]:
    try:
        result = await sent_uc.get_qvix_300etf()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_qvix_300etf: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qvix/1000index", summary="中证1000 QVIX")
async def get_qvix_1000index() -> Dict[str, Any]:
    try:
        result = await sent_uc.get_qvix_1000index()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_qvix_1000index: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qvix/cyb", summary="创业板 QVIX")
async def get_qvix_cyb() -> Dict[str, Any]:
    try:
        result = await sent_uc.get_qvix_cyb()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_qvix_cyb: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview", summary="市场情绪概览")
async def get_market_sentiment_overview() -> Dict[str, Any]:
    try:
        result = await sent_uc.get_market_sentiment_overview()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_market_sentiment_overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
