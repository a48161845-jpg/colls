"""Слой доступа к БД. Здесь SQLite (локальный файл, без зависимостей); PostgreSQL — в pg.py.
Выбор бэкенда: open_database(settings) — по DATABASE_URL (онлайн PostgreSQL) или DB_PATH (файл SQLite).

Тонкая async-обёртка над sqlite3.

Одно соединение, все запросы выполняются в потоке через asyncio.to_thread
под общим замком, а транзакции (`async with db.transaction() as tx`) держат
замок целиком — поэтому «проверил баланс -> списал -> выдал» атомарно.

И Database, и Tx имеют одинаковый интерфейс: one / all / execute / insert / scalar,
поэтому сервисы принимают любой из них (параметр `q`).
"""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Iterable

from .schema import SCHEMA


def _do(conn: sqlite3.Connection, kind: str, sql: str, params: tuple) -> Any:
    cur = conn.execute(sql, params)
    if kind == "one":
        row = cur.fetchone()
        return dict(row) if row is not None else None
    if kind == "all":
        return [dict(r) for r in cur.fetchall()]
    if kind == "insert":
        return cur.lastrowid
    return cur.rowcount


class _Queries:
    async def _run(self, kind: str, sql: str, params: tuple) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def one(self, sql: str, params: Iterable = ()) -> dict | None:
        return await self._run("one", sql, tuple(params))

    async def all(self, sql: str, params: Iterable = ()) -> list[dict]:
        return await self._run("all", sql, tuple(params))

    async def execute(self, sql: str, params: Iterable = ()) -> int:
        """Возвращает число затронутых строк."""
        return await self._run("exec", sql, tuple(params))

    async def insert(self, sql: str, params: Iterable = ()) -> int:
        """Возвращает id вставленной строки."""
        return await self._run("insert", sql, tuple(params))

    async def scalar(self, sql: str, params: Iterable = (), default: Any = None) -> Any:
        row = await self.one(sql, params)
        if row is None:
            return default
        return next(iter(row.values()))


class Tx(_Queries):
    """Запросы внутри транзакции (замок уже взят)."""

    def __init__(self, db: "Database") -> None:
        self._db = db

    async def _run(self, kind: str, sql: str, params: tuple) -> Any:
        return await asyncio.to_thread(_do, self._db._conn, kind, sql, params)


class Database(_Queries):
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    def describe(self) -> str:
        return f"SQLite {self.path}"

    async def connect(self) -> None:
        def _open() -> sqlite3.Connection:
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(SCHEMA)
            return conn

        self._conn = await asyncio.to_thread(_open)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    async def _run(self, kind: str, sql: str, params: tuple) -> Any:
        async with self._lock:
            return await asyncio.to_thread(_do, self._conn, kind, sql, params)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Tx]:
        async with self._lock:
            await asyncio.to_thread(self._conn.execute, "BEGIN IMMEDIATE")
            tx = Tx(self)
            try:
                yield tx
            except BaseException:
                await asyncio.to_thread(self._conn.execute, "ROLLBACK")
                raise
            else:
                await asyncio.to_thread(self._conn.execute, "COMMIT")


async def open_database(settings) -> "Database":
    """Подключает нужную БД. DATABASE_URL=postgresql://... -> онлайн PostgreSQL, иначе локальный SQLite."""
    url = getattr(settings, "database_url", "") or ""
    if url:
        from .pg import PgDatabase
        db = PgDatabase(url)
    else:
        db = Database(settings.db_path)
    await db.connect()
    return db  # type: ignore[return-value]
