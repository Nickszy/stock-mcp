from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger


_DDL_BOARD_CATALOG = """
CREATE TABLE IF NOT EXISTS board_catalog (
    board_code           TEXT NOT NULL,
    board_name           TEXT NOT NULL,
    board_type           TEXT NOT NULL,
    source               TEXT NOT NULL DEFAULT 'akshare',
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_refreshed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (board_code, board_type)
);
CREATE INDEX IF NOT EXISTS idx_board_catalog_type ON board_catalog(board_type);
CREATE INDEX IF NOT EXISTS idx_board_catalog_active ON board_catalog(is_active);
CREATE INDEX IF NOT EXISTS idx_board_catalog_name ON board_catalog(board_name);
"""


class BoardCatalogRepository:
    """Repository for persisted board catalog data."""

    def __init__(self, postgres_conn):
        self._pg = postgres_conn

    async def _get_pool(self):
        if not self._pg.connected:
            ok = await self._pg.connect()
            if not ok:
                return None
        return self._pg.get_client()

    async def ensure_schema(self) -> bool:
        pool = await self._get_pool()
        if not pool:
            logger.warning("BoardCatalog: PostgreSQL not available, schema not created")
            return False

        async with pool.acquire() as conn:
            await conn.execute(_DDL_BOARD_CATALOG)

        logger.info("✅ BoardCatalog schema ensured")
        return True

    async def list_boards(
        self,
        board_type: Optional[str] = None,
        keyword: str = "",
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        if not pool:
            return []

        conditions: List[str] = []
        params: List[Any] = []
        idx = 1

        if active_only:
            conditions.append("is_active = TRUE")

        if board_type:
            conditions.append(f"board_type = ${idx}")
            params.append(board_type)
            idx += 1

        if keyword:
            conditions.append(f"board_name ILIKE ${idx}")
            params.append(f"%{keyword}%")
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    board_code AS code,
                    board_name AS name,
                    board_type,
                    source,
                    is_active,
                    created_at,
                    updated_at,
                    last_refreshed_at
                FROM board_catalog
                {where}
                ORDER BY board_name ASC
                """,
                *params,
            )
            return [dict(r) for r in rows]

    async def count_boards(
        self,
        board_type: Optional[str] = None,
        active_only: bool = True,
    ) -> int:
        pool = await self._get_pool()
        if not pool:
            return 0

        conditions: List[str] = []
        params: List[Any] = []
        idx = 1

        if active_only:
            conditions.append("is_active = TRUE")

        if board_type:
            conditions.append(f"board_type = ${idx}")
            params.append(board_type)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        async with pool.acquire() as conn:
            value = await conn.fetchval(
                f"SELECT COUNT(*) FROM board_catalog {where}",
                *params,
            )
            return int(value or 0)

    async def replace_catalog(
        self,
        rows: List[Dict[str, str]],
        source: str = "akshare",
    ) -> Dict[str, int]:
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        normalized_rows = []
        for row in rows:
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            board_type = str(row.get("board_type", "")).strip().lower()
            if not code or not name or board_type not in {"concept", "industry"}:
                continue
            normalized_rows.append((code, name, board_type))

        active_keys = {(code, board_type) for code, _, board_type in normalized_rows}

        async with pool.acquire() as conn:
            async with conn.transaction():
                for code, name, board_type in normalized_rows:
                    await conn.execute(
                        """
                        INSERT INTO board_catalog (
                            board_code, board_name, board_type, source,
                            is_active, updated_at, last_refreshed_at
                        )
                        VALUES ($1, $2, $3, $4, TRUE, NOW(), NOW())
                        ON CONFLICT (board_code, board_type) DO UPDATE SET
                            board_name = EXCLUDED.board_name,
                            source = EXCLUDED.source,
                            is_active = TRUE,
                            updated_at = NOW(),
                            last_refreshed_at = NOW()
                        """,
                        code, name, board_type, source,
                    )

                if active_keys:
                    await conn.execute(
                        "UPDATE board_catalog SET is_active = FALSE, updated_at = NOW()"
                        " WHERE (board_code, board_type) NOT IN ("
                        "SELECT x.board_code, x.board_type FROM UNNEST($1::text[], $2::text[])"
                        " AS x(board_code, board_type))",
                        [code for code, board_type in active_keys],
                        [board_type for code, board_type in active_keys],
                    )

        return {
            "total": len(normalized_rows),
            "upserted": len(normalized_rows),
        }
