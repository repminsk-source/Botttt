import os
from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# --- AI providers ---
# Grok — основной провайдер, Gemini — запасной (используется, если Grok недоступен/упал).
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Модели
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4.3")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# --- Игровые настройки ---
DB_PATH = os.getenv("DB_PATH", "gavan.db")

# ID админов (список telegram user_id через запятую в .env: ADMIN_IDS=123,456)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# --- Исторический базовый год для реальных показателей страны ---
START_DATA_YEAR = int(os.getenv("START_DATA_YEAR", "2020"))

# --- Стартовые характеристики страны (игровая мощь; реальные показатели показываются отдельно) ---
START_STATS = {
    # Игровая шкала сверхдержавы: это не реальные единицы населения/ВВП.
    "economy": 100,
    "military": 100,
    "population": 100,
    "tech": 100,
    "diplomacy": 100,
}

# --- Стартовые ресурсы страны ---
START_GOLD = 2500
START_RESOURCES = 1500
START_MANPOWER = 1000  # игровой резерв людей сверхдержавы
START_WATER = 2000
START_FOOD = 3000

# Очки развития, начисляемые за тик (используешь по крону/вручную командой админа)
POINTS_PER_TICK = 20
POINTS_PER_COLLECT = 10

# Стоимость прокачки одной характеристики на 1 пункт очками развития
UPGRADE_COST = 10
MAX_UPGRADE_PER_ACTION = 5
MAX_MOBILIZE_PER_ACTION = 5

# Максимум символов в описании действия от игрока
MAX_ACTION_LEN = 1500

# Кулдаун между /action у одного игрока, в секундах (0 = выключен)
ACTION_COOLDOWN_SECONDS = int(os.getenv("ACTION_COOLDOWN_SECONDS", str(12 * 60 * 60)))
ATTACK_COOLDOWN_SECONDS = int(os.getenv("ATTACK_COOLDOWN_SECONDS", str(24 * 60 * 60)))
COLLECT_COOLDOWN_SECONDS = int(os.getenv("COLLECT_COOLDOWN_SECONDS", str(4 * 60 * 60)))
BUILD_COOLDOWN_SECONDS = int(os.getenv("BUILD_COOLDOWN_SECONDS", str(2 * 60 * 60)))
UPGRADE_COOLDOWN_SECONDS = int(os.getenv("UPGRADE_COOLDOWN_SECONDS", str(12 * 60 * 60)))
MOBILIZE_COOLDOWN_SECONDS = int(os.getenv("MOBILIZE_COOLDOWN_SECONDS", str(6 * 60 * 60)))
BUY_COOLDOWN_SECONDS = int(os.getenv("BUY_COOLDOWN_SECONDS", str(60 * 60)))
BASE_COOLDOWN_SECONDS = int(os.getenv("BASE_COOLDOWN_SECONDS", str(24 * 60 * 60)))
SPY_COOLDOWN_SECONDS = int(os.getenv("SPY_COOLDOWN_SECONDS", str(12 * 60 * 60)))

# --- Постройки ---
# Каждая постройка даёт прирост ресурса за один /collect, пропорционально уровню (level * amount_per_level).
# Стоимость постройки/улучшения растёт с уровнем: cost * (текущий_уровень + 1)
BUILDINGS = {
    "farm": {
        "name": "Ферма",
        "emoji": "🌾",
        "produces": "manpower",
        "produces_name": "резерв людей",
        "amount_per_level": 6,
        "cost_gold": 300,
        "cost_resources": 150,
    },
    "mine": {
        "name": "Шахта",
        "emoji": "⛏️",
        "produces": "resources",
        "produces_name": "ресурсы",
        "amount_per_level": 10,
        "cost_gold": 500,
        "cost_resources": 250,
    },
    "market": {
        "name": "Рынок",
        "emoji": "🏪",
        "produces": "gold",
        "produces_name": "золото",
        "amount_per_level": 12,
        "cost_gold": 400,
        "cost_resources": 300,
    },
    "well": {
        "name": "Колодец",
        "emoji": "💧",
        "produces": "water",
        "produces_name": "вода",
        "amount_per_level": 8,
        "cost_gold": 250,
        "cost_resources": 200,
    },
    "granary": {
        "name": "Амбар",
        "emoji": "🌽",
        "produces": "food",
        "produces_name": "еда",
        "amount_per_level": 9,
        "cost_gold": 350,
        "cost_resources": 250,
    },
}

# --- Сырьевые ресурсы и заводы (дерево/железо/уголь/нефть) ---
# Аналогично BUILDINGS, но это добывающие постройки нового поколения ресурсов.
# Не участвуют в приросте экономики (ECONOMY_GROWTH_DIVISOR) — только сырьё.
RESOURCE_BUILDINGS = {
    "sawmill": {
        "name": "Лесопилка",
        "emoji": "🌲",
        "produces": "wood",
        "produces_name": "дерево",
        "amount_per_level": 8,
        "cost_gold": 300,
        "cost_resources": 200,
    },
    "iron_mine": {
        "name": "Железный рудник",
        "emoji": "⛓️",
        "produces": "iron",
        "produces_name": "железо",
        "amount_per_level": 7,
        "cost_gold": 500,
        "cost_resources": 300,
    },
    "coal_mine": {
        "name": "Угольная шахта",
        "emoji": "🪨",
        "produces": "coal",
        "produces_name": "уголь",
        "amount_per_level": 9,
        "cost_gold": 400,
        "cost_resources": 300,
    },
    "oil_rig": {
        "name": "Нефтяная вышка",
        "emoji": "🛢️",
        "produces": "oil",
        "produces_name": "нефть",
        "amount_per_level": 6,
        "cost_gold": 700,
        "cost_resources": 400,
    },
    "uranium_mine": {
        "name": "Урановый рудник",
        "emoji": "☢️",
        "produces": "uranium",
        "produces_name": "уран",
        # Уран специально добывается очень медленно — редкий и дорогой ресурс,
        # который в первую очередь покупают на рынке или копят долго.
        "amount_per_level": 1,
        "cost_gold": 2000,
        "cost_resources": 1200,
    },
}

# Постройки, требующие минимального уровня технологий страны, чтобы вообще начать строить
# (проверяется в bot.py при /build). Отражает то, что не любая страна технически способна
# добывать/обогащать уран.
TECH_GATE_BUILDINGS = {
    "uranium_mine": 15,
}

RESOURCE_NAMES_RU_EXTRA = {
    "wood": "🌲 Дерево",
    "iron": "⛓️ Железо",
    "coal": "🪨 Уголь",
    "oil": "🛢️ Нефть",
    "uranium": "☢️ Уран",
}

# --- Динамический рынок ---
# Цена ресурса пересчитывается детерминированно по времени (без БД и планировщика):
# на каждый временной "тик" длиной MARKET_TICK_SECONDS цена случайно колеблется в пределах
# ±MARKET_PRICE_VARIANCE от базовой (см. market.py). Все инстансы бота в один и тот же момент
# времени видят одну и ту же цену — не нужно ничего хранить или синхронизировать.
MARKET_TICK_SECONDS = int(os.getenv("MARKET_TICK_SECONDS", "1800"))  # 30 минут
MARKET_PRICE_VARIANCE = 0.35  # ±35% от базовой цены

# Базовая цена за 1 единицу ресурса (вокруг неё колеблется динамическая цена).
RESOURCE_BUY_PRICE_GOLD = {
    "wood": 2,
    "iron": 3,
    "coal": 3,
    "oil": 5,
    "uranium": 40,  # уран дорогой и на рынке, покупка не даёт обойти "сложно добыть"
}
MAX_BUY_PER_ORDER = 500

# --- Территория страны (задаётся автоматически по реальной площади страны, см. territory.py) ---
# Максимальный уровень одной добывающей постройки (в т.ч. нефтевышки) — чем больше
# страна, тем больше вышек/шахт можно построить.
TERRITORY_BUILDING_LEVEL_CAP = {"small": 12, "medium": 30, "large": 60}
# Максимум характеристики population — чтобы маленькая страна не приписывала себе
# население крупной державы.
# Игровое население выражается в миллионах жителей, поэтому лимиты больше прежних абстрактных значений.
TERRITORY_POPULATION_CAP = {"small": 150, "medium": 1000, "large": 2500}
# Бонусные военные базы сверх формулы от армии (см. MILITARY_BASE_*).
TERRITORY_BASE_BONUS = {"small": 1, "medium": 2, "large": 4}

# --- Военные базы ---
# Одна база стоит золото+ресурсы (растёт с числом уже построенных баз) и требует
# минимального уровня армии. Максимум баз = TERRITORY_BASE_BONUS[tier] + military // MILITARY_PER_BASE.
MILITARY_PER_BASE = 15
BASE_COST_GOLD = 5000
BASE_COST_RESOURCES = 3000

# --- Шпионаж ---
# /spy — скрытная операция: цель никогда не получает уведомление, независимо от исхода.
SPY_COST_GOLD = 25
# Базовый шанс успеха (0-100), модифицируется разницей tech/diplomacy атакующего и цели.
SPY_BASE_SUCCESS_CHANCE = 55

# --- Ядерное оружие ---
# Боеголовка строится отдельно от обычной армии — дорого, требует урана и высокого tech,
# и жёстко ограничена по количеству (нельзя накопить произвольно много).
NUKE_TECH_REQUIRED = 25
NUKE_URANIUM_COST = 150
NUKE_GOLD_COST = 400
NUKE_MAX_WARHEADS = 3  # жёсткий потолок независимо от территории/армии
NUKE_COOLDOWN_SECONDS = int(os.getenv("NUKE_COOLDOWN_SECONDS", str(24 * 60 * 60)))  # 24 часа

# --- Мобилизация армии ---
# Чтобы поднять military на 1 пункт, тратится столько резерва людей (manpower) и золота.
MOBILIZE_MANPOWER_PER_POINT = 25
MOBILIZE_GOLD_PER_POINT = 50

# --- Прогрессивная стоимость прокачки экономики ---
# В отличие от остальных характеристик (флэт-цена UPGRADE_COST), экономика дорожает с каждым уровнем:
# цена N-го пункта экономики = ECONOMY_BASE_COST + текущий_уровень_экономики * ECONOMY_COST_STEP
ECONOMY_BASE_COST = 30
ECONOMY_COST_STEP = 5

# При каждом /collect экономика также немного растёт сама, в зависимости от построек
# (шахта+рынок), не только очками через /upgrade. Прирост = (mine_level + market_level) // ECONOMY_GROWTH_DIVISOR
ECONOMY_GROWTH_DIVISOR = 4

# Еда — если накопленный запас еды достигает этого порога при /collect, часть еды
# тратится на рост населения (+1 к population). Делает "еду" не просто числом,
# а ресурсом с игровой ценностью, а не только визуальным дополнением.
FOOD_GROWTH_THRESHOLD = 50

# --- Понятная шкала развития страны ---
# Это игровые очки развития, а не реальные ВВП/население страны.
PROGRESS_BUILDING_POINTS = 3
PROGRESS_STAGES = [
    (0, "Основание", "Создай базовую экономику и начни собирать доход."),
    (600, "Стабилизация", "Обеспечь еду, воду, сырьё и резерв людей."),
    (800, "Развитие", "Подними технологии, экономику и армию."),
    (1100, "Региональная сила", "Строй базы, развивай дипломатию и готовь внешние действия."),
    (1500, "Великая держава", "Используй войны, альянсы и сложные действия для влияния на мир."),
]

# --- Игровой год мира ---
# Год фиксируется один раз админом командой /set_year <год> и дальше растёт
# автоматически: 1 реальные сутки = SECONDS_PER_GAME_YEAR секунд = +1 игровой год.
SECONDS_PER_GAME_YEAR = int(os.getenv("SECONDS_PER_GAME_YEAR", str(24 * 60 * 60)))

# --- Войны между игроками ---
# Трофеи победителя войны: % золота и ресурсов, отнимаемый у проигравшего и
# передаваемый победителю. При ничьей трофеев нет.
WAR_LOOT_PERCENT = 20

# --- Альянсы ---
# Канонические альянсы, создаваемые админом командой /seed_alliances (обычно сразу
# после вайпа сервера). Игроки вступают в них командой /alliance_join ТЕГ.
CANONICAL_ALLIANCES = [
    {"tag": "NATO", "name": "НАТО — Организация Североатлантического договора"},
    {"tag": "CSTO", "name": "ОДКБ — Организация Договора о коллективной безопасности"},
    {"tag": "EU", "name": "Евросоюз"},
    {"tag": "SCO", "name": "ШОС — Шанхайская организация сотрудничества"},
]
MAX_ALLIANCE_TAG_LEN = 12
MAX_ALLIANCE_NAME_LEN = 64
