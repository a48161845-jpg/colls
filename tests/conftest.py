import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.db.core import Database  # noqa: E402
from bot.services import items as items_svc, players  # noqa: E402


# Один общий event loop на все тесты: пул соединений PostgreSQL привязан к своему loop.
_LOOP = asyncio.new_event_loop()


def run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture
def db():
    """Свежая БД на каждый тест. TEST_DATABASE_URL=postgresql://... — прогнать тесты на PostgreSQL."""
    url = os.getenv("TEST_DATABASE_URL", "")
    if url:
        from bot.db.pg import PgDatabase
        database = PgDatabase(url)
        run(database.connect())

        async def _reset():
            async with database._pool.connection() as c:
                await c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        run(_reset())
        run(database.close())
        database = PgDatabase(url)
        run(database.connect())
    else:
        tmp = tempfile.mkdtemp()
        database = Database(os.path.join(tmp, "t.sqlite3"))
        run(database.connect())
    yield database
    run(database.close())


async def make_player(db, uid=1, cls="warrior", name="Тест", ref_by=None, **fields):
    """Создаёт игрока со стартовым набором. fields — прямое переопределение колонок."""
    async with db.transaction() as tx:
        await players.create(tx, uid, f"user{uid}", name, cls, ref_by)
        await items_svc.give_starter_kit(tx, uid)
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        await db.execute(f"UPDATE players SET {sets} WHERE user_id=?", list(fields.values()) + [uid])
    return await players.get(db, uid)
