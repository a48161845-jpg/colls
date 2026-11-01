"""Пул ежедневных заданий. Награда масштабируется с уровнем игрока."""

DAILY_POOL: list[dict] = [
    {"key": "kill",    "text": "Победить монстров",           "need": (5, 12),    "reward": {"gold": 150, "xp": 100}},
    {"key": "tap",     "text": "Ударов по жиле",              "need": (100, 300), "reward": {"gold": 180, "essence": 3}},
    {"key": "collect", "text": "Собрать добычу с построек",   "need": (2, 4),     "reward": {"gold": 120, "xp": 80}},
    {"key": "boss",    "text": "Победить босса локации",      "need": (1, 1),     "reward": {"gold": 300, "essence": 8}},
    {"key": "arena",   "text": "Провести боёв на арене",      "need": (2, 4),     "reward": {"gold": 250, "crystals": 2}},
    {"key": "upgrade", "text": "Улучшить здания",             "need": (1, 3),     "reward": {"gold": 200, "xp": 120}},
    {"key": "story",   "text": "Сделать выборов в сюжете",    "need": (3, 6),     "reward": {"gold": 150, "xp": 150}},
]
DAILY = {q["key"]: q for q in DAILY_POOL}
