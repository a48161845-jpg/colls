"""Все числа баланса в одном месте — правь здесь."""

# --- энергия ---
ENERGY_MAX = 100
ENERGY_PER_TAVERN = 5          # +к максимуму за уровень таверны
ENERGY_REGEN_SEC = 180         # 1 энергия за 3 минуты
ENERGY_REGEN_PER_TAVERN = 0.03  # -3% к времени регена за уровень таверны (макс -60%)
EXPEDITION_COST = 10
BOSS_COST = 25
GUILD_BOSS_COST = 15

# --- бой ---
POTION_PRICE = 80
POTION_HEAL = 0.40
FLEE_CHANCE = 0.55
SKILL_COOLDOWN = 3
BASE_CRIT = 0.08
ROGUE_CRIT = 0.18
CRIT_MULT = 1.8
DEFEAT_GOLD_LOSS = 0.05

# --- idle ---
OFFLINE_CAP_H = 6
OFFLINE_CAP_PER_LIBRARY = 0.5
PREMIUM_CAP_BONUS_H = 6
PREMIUM_IDLE_MULT = 1.5
PREMIUM_REWARD_MULT = 1.25
MARK_IDLE_BONUS = 0.25          # +25% к idle за каждую метку пепла
MARK_STAT_BONUS = 0.05          # +5% к статам за метку
MAX_BUILDING_LEVEL = 100
GUILD_IDLE_PER_LEVEL = 0.03
REBIRTH_MIN_LEVEL = 30

# --- гильдии ---
GUILD_CREATE_COST = 2500
GUILD_BASE_MEMBERS = 20
GUILD_MAX_MEMBERS = 50
GUILD_NAME_MIN, GUILD_NAME_MAX = 3, 20

# --- рынок ---
MARKET_TAX = 0.05
MARKET_TAX_PREMIUM = 0.02
MARKET_MAX_LISTINGS = 8
MARKET_MAX_PRICE = 1_000_000_000

# --- арена ---
ARENA_TRIES = 5
ARENA_TRIES_PREMIUM = 8
ARENA_START_RATING = 1000
ARENA_K = 32

# --- ежедневка ---
DAILY_REWARDS = [
    {"gold": 200},
    {"gold": 300, "potions": 1},
    {"gold": 400, "essence": 5},
    {"gold": 600, "potions": 2},
    {"gold": 800, "essence": 10},
    {"gold": 1200, "potions": 3},
    {"gold": 2000, "crystals": 10, "essence": 20},
]
DAILY_QUESTS_PER_DAY = 3
DAILY_QUESTS_BONUS_CRYSTALS = 3

# --- рефералка ---
REF_BONUS_NEW = {"gold": 500, "crystals": 10}
REF_BONUS_INVITER = {"gold": 1000, "crystals": 15}
REF_LEVEL_REQUIRED = 5

GUILD_INVITE_TTL = 3 * 24 * 3600   # приглашение живёт 3 дня
GUILD_INVITES_MAX = 20            # не больше стольких активных приглашений от одной гильдии

# --- жила: если долбить без остановки, она перегревается и обрушивается
VEIN_HEAT_MAX = 100.0       # при достижении жила рушится
VEIN_HEAT_PER_TAP = 4.5     # нагрев за удар (≈22 удара подряд без пауз)
VEIN_COOL_PER_SEC = 5.0     # остывание в секунду (медленный ритм ~1 удар/сек жилу не ломает)
VEIN_COOL_PER_MINE_LVL = 0.03   # каждый уровень рудника ускоряет остывание на 3%
VEIN_PREMIUM_COOL = 1.5     # Premium остужает на 50% быстрее
VEIN_BROKEN_SECONDS = 75    # столько жила восстанавливается сама
VEIN_REPAIR_PER_LEVEL = 25  # починка за золото сразу: уровень героя * это число (минимум 100)
VEIN_WARN_AT = 70           # с этого нагрева бот предупреждает «жила трещит»
