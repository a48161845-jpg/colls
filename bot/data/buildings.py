"""Постройки для idle-части. Стоимость и доход считаются в services/formulas.py."""

BUILDINGS: dict[str, dict] = {
    "mine": {
        "name": "Рудник пепла", "emoji": "mine", "unlock": 1,
        "res": "gold", "base_out": 55, "base_cost": 72, "growth": 1.17,
        "desc": "Добывает золото. Усиливает силу удара по жиле.",
    },
    "shrine": {
        "name": "Святилище искры", "emoji": "shrine", "unlock": 3,
        "res": "xp", "base_out": 24, "base_cost": 180, "growth": 1.19,
        "desc": "Копит опыт героя, пока ты отдыхаешь.",
    },
    "forge": {
        "name": "Горн душ", "emoji": "forge", "unlock": 8,
        "res": "essence", "base_out": 1.6, "base_cost": 900, "growth": 1.22,
        "desc": "Выплавляет эссенцию — для усиления предметов.",
    },
    "tavern": {
        "name": "Таверна «Тлеющий уголёк»", "emoji": "tavern", "unlock": 5,
        "res": None, "base_out": 0, "base_cost": 480, "growth": 1.20,
        "desc": "+5 к максимуму энергии и быстрее её восстановление.",
    },
    "library": {
        "name": "Архив хроник", "emoji": "library", "unlock": 12,
        "res": None, "base_out": 0, "base_cost": 2400, "growth": 1.24,
        "desc": "+0.5 ч к лимиту офлайн-накопления за уровень.",
    },
}
BUILDING_ORDER = ["mine", "shrine", "forge", "tavern", "library"]
