"""Схема базы данных. Таблицы создаются автоматически при старте.

SCHEMA — для SQLite; PG_SCHEMA для PostgreSQL получается из неё автоматически."""
import re

VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    name          TEXT,
    cls           TEXT NOT NULL,
    level         INTEGER NOT NULL DEFAULT 1,
    xp            INTEGER NOT NULL DEFAULT 0,
    gold          INTEGER NOT NULL DEFAULT 150,
    essence       INTEGER NOT NULL DEFAULT 0,
    crystals      INTEGER NOT NULL DEFAULT 0,
    marks         INTEGER NOT NULL DEFAULT 0,
    energy        REAL    NOT NULL DEFAULT 100,
    energy_ts     REAL    NOT NULL DEFAULT 0,
    potions       INTEGER NOT NULL DEFAULT 3,
    last_collect  REAL    NOT NULL DEFAULT 0,
    premium_until REAL    NOT NULL DEFAULT 0,
    streak        INTEGER NOT NULL DEFAULT 0,
    last_daily    INTEGER NOT NULL DEFAULT 0,
    ref_by        INTEGER,
    ref_rewarded  INTEGER NOT NULL DEFAULT 0,
    guild_id      INTEGER,
    guild_role    TEXT,
    rating        INTEGER NOT NULL DEFAULT 1000,
    arena_tries   INTEGER NOT NULL DEFAULT 0,
    arena_day     INTEGER NOT NULL DEFAULT 0,
    title         TEXT,
    banned        INTEGER NOT NULL DEFAULT 0,
    kills         INTEGER NOT NULL DEFAULT 0,
    taps          INTEGER NOT NULL DEFAULT 0,
    gold_total    INTEGER NOT NULL DEFAULT 0,
    story         TEXT    NOT NULL DEFAULT '{}',
    starter_bought INTEGER NOT NULL DEFAULT 0,
    created_at    REAL    NOT NULL DEFAULT 0,
    last_seen     REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_players_level  ON players(level DESC, xp DESC);
CREATE INDEX IF NOT EXISTS ix_players_rating ON players(rating DESC);
CREATE INDEX IF NOT EXISTS ix_players_guild  ON players(guild_id);

CREATE TABLE IF NOT EXISTS buildings (
    user_id INTEGER NOT NULL,
    key     TEXT    NOT NULL,
    level   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    slot       TEXT    NOT NULL,
    rarity     TEXT    NOT NULL,
    ilvl       INTEGER NOT NULL,
    atk        INTEGER NOT NULL DEFAULT 0,
    def        INTEGER NOT NULL DEFAULT 0,
    hp         INTEGER NOT NULL DEFAULT 0,
    idle       INTEGER NOT NULL DEFAULT 0,
    plus       INTEGER NOT NULL DEFAULT 0,
    equipped   INTEGER NOT NULL DEFAULT 0,
    listed     INTEGER NOT NULL DEFAULT 0,
    created_at REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_items_owner ON items(owner_id);

CREATE TABLE IF NOT EXISTS battles (
    user_id INTEGER PRIMARY KEY,
    state   TEXT    NOT NULL,
    updated REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_quests (
    user_id  INTEGER NOT NULL,
    day      INTEGER NOT NULL,
    key      TEXT    NOT NULL,
    need     INTEGER NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    claimed  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, key)
);

CREATE TABLE IF NOT EXISTS guilds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    descr      TEXT NOT NULL DEFAULT '',
    leader_id  INTEGER NOT NULL,
    level      INTEGER NOT NULL DEFAULT 1,
    xp         INTEGER NOT NULL DEFAULT 0,
    boss_level INTEGER NOT NULL DEFAULT 1,
    boss_hp    INTEGER NOT NULL DEFAULT 0,
    boss_max   INTEGER NOT NULL DEFAULT 0,
    boss_cycle INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS guild_damage (
    guild_id INTEGER NOT NULL,
    cycle    INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    dmg      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, cycle, user_id)
);

CREATE TABLE IF NOT EXISTS guild_invites (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    inviter_id INTEGER NOT NULL,
    created_at REAL    NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_invites_user ON guild_invites(user_id);

CREATE TABLE IF NOT EXISTS market (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id  INTEGER NOT NULL,
    item_id    INTEGER NOT NULL UNIQUE,
    price      INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_market_price ON market(price);

CREATE TABLE IF NOT EXISTS payments (
    charge_id  TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    payload    TEXT NOT NULL,
    stars      INTEGER NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS arena_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    attacker   INTEGER NOT NULL,
    defender   INTEGER,
    winner     INTEGER,
    delta      INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS emoji_map (
    name      TEXT PRIMARY KEY,
    custom_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_rules (
    key      TEXT PRIMARY KEY,
    price    INTEGER,
    discount INTEGER NOT NULL DEFAULT 0,
    until    REAL
);
"""


def _to_pg(schema: str) -> str:
    out = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    out = out.replace(" UNIQUE COLLATE NOCASE", "")
    out = re.sub(r"\bINTEGER\b", "BIGINT", out)          # Telegram ID не влезают в int32
    out = re.sub(r"\bREAL\b", "DOUBLE PRECISION", out)
    return out + "\nCREATE UNIQUE INDEX IF NOT EXISTS ux_guilds_name ON guilds(lower(name));\n"


PG_SCHEMA = _to_pg(SCHEMA)
