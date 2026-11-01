"""Онлайн-БД: PostgreSQL через psycopg 3 (пул соединений). Тот же интерфейс, что у SQLite-Database:
one / all / execute / insert / scalar и `async with db.transaction() as tx`.

Работает с любым хостингом Postgres: Supabase, Neon, Railway, Render, свой сервер.
Строка подключения — DATABASE_URL=postgresql://user:pass@host:5432/dbname?sslmode=require

Атомарность: транзакции игровой логики берут общий asyncio-замок (бот — один процесс), так что
«проверил баланс -> списал -> выдал» не пересекается с другими такими же операциями, как и в SQLite.
Одиночные запросы идут через пул параллельно. prepare_threshold=None — совместимость с pgbouncer
(пулер Supabase в режиме transaction).
"""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

from .core import _Queries
from .schema import PG_SCHEMA

_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO", re.I)
_MAX = re.compile(r"\bMAX\(", re.I)
_MIN = re.compile(r"\bMIN\(", re.I)


def to_pg_sql(sql: str, kind: str = "exec") -> str:
    """SQLite-диалект проекта -> PostgreSQL."""
    s = sql.replace("%", "%%").replace("?", "%s")
    if _OR_IGNORE.match(s):
        s = _OR_IGNORE.sub("INSERT INTO", s, count=1)
        if "ON CONFLICT" not in s.upper():
            s = s.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    # двухаргументные MAX/MIN — это скалярные функции SQLite; в проекте агрегатов MAX/MIN нет
    if not re.search(r"\bSELECT\s+(MAX|MIN)\(", s, re.I):
        s = _MAX.sub("GREATEST(", s)
        s = _MIN.sub("LEAST(", s)
    if kind == "insert" and "RETURNING" not in s.upper():
        s = s.rstrip().rstrip(";") + " RETURNING id"
    return s


class _PgTx(_Queries):
    def __init__(self, conn) -> None:
        self._conn = conn

    async def _run(self, kind: str, sql: str, params: tuple) -> Any:
        async with self._conn.cursor() as cur:
            await cur.execute(to_pg_sql(sql, kind), params)
            if kind == "one":
                return await cur.fetchone()
            if kind == "all":
                return await cur.fetchall()
            if kind == "insert":
                row = await cur.fetchone()
                return next(iter(row.values()))
            return cur.rowcount


class PgDatabase(_Queries):
    def __init__(self, url: str, *, min_size: int = 1, max_size: int = 8) -> None:
        self.url = url
        self.min_size, self.max_size = min_size, max_size
        self._pool = None
        self._lock = asyncio.Lock()

    def describe(self) -> str:
        u = urlsplit(self.url)
        return f"PostgreSQL {u.hostname}:{u.port or 5432}{u.path}"

    async def connect(self) -> None:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool
        except ImportError as ex:  # pragma: no cover
            raise SystemExit("Для PostgreSQL нужен пакет: pip install \"psycopg[binary,pool]\"") from ex
        self._pool = AsyncConnectionPool(
            self.url, min_size=self.min_size, max_size=self.max_size, open=False,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            check=AsyncConnectionPool.check_connection)   # мёртвые соединения заменяются автоматически
        await self._pool.open(wait=True, timeout=30)
        async with self._pool.connection() as conn:
            await conn.execute("SELECT pg_advisory_lock(727001)")   # одновременный старт двух ботов не ломает схему
            try:
                await conn.execute(PG_SCHEMA)
            finally:
                await conn.execute("SELECT pg_advisory_unlock(727001)")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _run(self, kind: str, sql: str, params: tuple) -> Any:
        async with self._pool.connection() as conn:
            return await _PgTx(conn)._run(kind, sql, params)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_PgTx]:
        async with self._lock:
            async with self._pool.connection() as conn:
                async with conn.transaction():
                    yield _PgTx(conn)
