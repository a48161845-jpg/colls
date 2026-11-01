"""Перенос данных из локального SQLite в онлайн-PostgreSQL.

    python tools/migrate_sqlite_to_pg.py ashen_realm.sqlite3 "postgresql://user:pass@host:5432/db"

Таблицы в Postgres создаются сами. Если в целевых таблицах уже есть данные, скрипт остановится.
"""
import asyncio
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.db.pg import PgDatabase  # noqa: E402

TABLES = ["players", "buildings", "items", "battles", "daily_quests", "guilds", "guild_damage", "guild_invites",
          "market", "payments", "arena_log", "emoji_map", "price_rules"]
SERIAL = ["items", "guilds", "market", "arena_log"]


async def main(src: str, url: str) -> None:
    lite = sqlite3.connect(src)
    lite.row_factory = sqlite3.Row
    db = PgDatabase(url)
    await db.connect()
    try:
        for t in TABLES:
            if await db.scalar(f"SELECT COUNT(*) FROM {t}"):
                raise SystemExit(f"В Postgres таблица {t} не пустая — перенос отменён.")
        async with db.transaction() as tx:
            for t in TABLES:
                rows = lite.execute(f"SELECT * FROM {t}").fetchall()
                for r in rows:
                    cols = list(r.keys())
                    await tx.execute(f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", tuple(r))
                print(f"{t}: {len(rows)}")
            for t in SERIAL:  # чтобы новые id продолжили нумерацию
                await tx.execute(f"SELECT setval(pg_get_serial_sequence('{t}','id'), COALESCE((SELECT MAX(id) FROM {t}),0)+1, false)")
        print("Готово.")
    finally:
        await db.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
