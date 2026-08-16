import os
from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# --- AI providers ---
# Ollama Cloud — основной провайдер; Grok и Gemini остаются необязательными резервами.
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Модели
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4.3")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# Ollama Cloud — доступен из Render без локального GPU/сервера.
# Для локального Ollama эти значения можно переопределить через Environment Variables.
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "1").lower() in {"1", "true", "yes", "on"}
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b-cloud")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
# Provider mode: ollama = Ollama only, fallback = Ollama then remote fallbacks.
AI_PROVIDER = os.getenv("AI_PROVIDER", "ollama").strip().lower()

# --- Игровые настройки ---
DB_PATH = os.getenv("DB_PATH", "gavan.db")

# ID админов (список telegram user_id через запятую в .env: ADMIN_IDS=123,456)
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# --- Исторический базовый год для реальных показателей страны ---
START_DATA_YEAR = int(os.getenv("START_DATA_YEAR", "2020"))

# --- Стартовые характеристики страны (игровая мощь; реальные показатели показываются отдельно) ---
START_STABILITY = 70
START_READINESS = 50
START_WAR_EXHAUSTION = 0
START_REPUTATION = 50

POLICY_DEFINITIONS = {
    "development": {
        "name": "Развитие",
        "description": "Ускоряет экономику и строительство, но не даёт военных бонусов.",
        "production_multiplier": 1.10,
        "stability_delta": 1,
        "readiness_delta": 0,
        "reputation_delta": 0,
    },
    "welfare": {
        "name": "Социальное государство",
        "description": "Улучшает еду, воду и стабильность, но немного замедляет экономический рост.",
        "production_multiplier": 1.05,
        "stability_delta": 2,
        "readiness_delta": 0,
        "reputation_delta": 1,
    },
    "militarism": {
        "name": "Милитаризм",
        "description": "Ускоряет подготовку армии и резерв людей, но повышает усталость и снижает репутацию.",
        "production_multiplier": 0.95,
        "stability_delta": -1,
        "readiness_delta": 2,
        "reputation_delta": -1,
    },
    "diplomacy": {
        "name": "Дипломатический курс",
        "description": "Повышает деньги и репутацию, но ограничивает военный темп.",
        "production_multiplier": 1.00,
        "stability_delta": 1,
        "readiness_delta": -1,
        "reputation_delta": 2,
    },
}

START_STATS = {
    # Игровая шкала сверхдержавы: это не реальные единицы населения/ВВП.
    "economy": 0,
    "military": 0,
    "population": 0,
    "tech": 0,
    "diplomacy": 0,
}

# --- Стартовые ресурсы страны ---
# Стартовый капитал при основании каждой страны.
START_GOLD = 100_000
# Одноразовый бонус за самый первый успешный /collect после основания.
FIRST_COLLECT_GOLD_BONUS = 14_000_000
# Стартовый запас общих строительных ресурсов: позволяет начать развитие сразу,
# не создавая тупик «для добычи ресурса сначала нужно уже построить шахту».
START_RESOURCES = 1_000
START_MANPOWER = 0
START_WATER = 0
START_FOOD = 0
START_WOOD = 40_000
START_MILITARY_BASES = 1

# Очки развития, начисляемые за тик (используешь по крону/вручную командой админа)
POINTS_PER_TICK = 20
# За каждые 45 минут игрок получает ощутимый прогресс, чтобы обычная страна
# могла выйти в топ примерно за десять дней регулярной игры.
POINTS_PER_COLLECT = 20

# Стоимость прокачки одной характеристики на 1 пункт очками развития
UPGRADE_COST = 10
# Лимиты одной команды: достаточно большие для стратегии, но защищают от мгновенного скачка.
MAX_UPGRADE_PER_ACTION = 20
MAX_MOBILIZE_PER_ACTION = 50

# Максимум символов в описании действия от игрока
MAX_ACTION_LEN = 1500
MIN_NARRATIVE_LEN = 50

# Глобальная защита от спама интерфейса. Она не заменяет игровые таймеры:
# повтор одного сообщения режется отдельно от честных игровых действий.
GLOBAL_MESSAGE_COOLDOWN_SECONDS = _env_float("GLOBAL_MESSAGE_COOLDOWN_SECONDS", 1.5)
# Interface cards stay readable before automatic cleanup; set to 0 to disable.
INTERFACE_MESSAGE_DELETE_SECONDS = _env_int("INTERFACE_MESSAGE_DELETE_SECONDS", 30)
DUPLICATE_MESSAGE_WINDOW_SECONDS = _env_float("DUPLICATE_MESSAGE_WINDOW_SECONDS", 4)
SPAM_BURST_WINDOW_SECONDS = _env_float("SPAM_BURST_WINDOW_SECONDS", 10)
SPAM_BURST_LIMIT = _env_int("SPAM_BURST_LIMIT", 8, minimum=1)

# Кулдаун между /action у одного игрока, в секундах (0 = выключен)
ACTION_COOLDOWN_SECONDS = _env_int("ACTION_COOLDOWN_SECONDS", 10 * 60)
ATTACK_COOLDOWN_SECONDS = _env_int("ATTACK_COOLDOWN_SECONDS", 60 * 60)
WAR_DEFENSE_WINDOW_SECONDS = _env_int("WAR_DEFENSE_WINDOW_SECONDS", 24 * 60 * 60)
COLLECT_COOLDOWN_SECONDS = _env_int("COLLECT_COOLDOWN_SECONDS", 45 * 60)
BUILD_COOLDOWN_SECONDS = _env_int("BUILD_COOLDOWN_SECONDS", 60)
UPGRADE_COOLDOWN_SECONDS = _env_int("UPGRADE_COOLDOWN_SECONDS", 10 * 60)
MOBILIZE_COOLDOWN_SECONDS = _env_int("MOBILIZE_COOLDOWN_SECONDS", 10 * 60)
BUY_COOLDOWN_SECONDS = _env_int("BUY_COOLDOWN_SECONDS", 60)
BASE_COOLDOWN_SECONDS = _env_int("BASE_COOLDOWN_SECONDS", 10 * 60)
POLICY_COOLDOWN_SECONDS = _env_int("POLICY_COOLDOWN_SECONDS", 30 * 60)
SPY_COOLDOWN_SECONDS = _env_int("SPY_COOLDOWN_SECONDS", 15 * 60)

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
        "amount_per_level": 900,
        "cost_gold": 500,
        "cost_resources": 250,
    },
    "market": {
        "name": "Рынок",
        "emoji": "🏪",
        "produces": "gold",
        "produces_name": "деньги",
        "amount_per_level": 540,
        "cost_gold": 400,
        "cost_resources": 300,
    },
    "well": {
        "name": "Колодец",
        "emoji": "💧",
        "produces": "water",
        "produces_name": "вода",
        "amount_per_level": 360,
        "cost_gold": 250,
        "cost_resources": 200,
    },
    "granary": {
        "name": "Амбар",
        "emoji": "🌽",
        "produces": "food",
        "produces_name": "еда",
        "amount_per_level": 750,
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
        "amount_per_level": 450,
        "cost_gold": 300,
        "cost_resources": 200,
    },
    "iron_mine": {
        "name": "Железный рудник",
        "emoji": "⛓️",
        "produces": "iron",
        "produces_name": "железо",
        "amount_per_level": 660,
        "cost_gold": 500,
        "cost_resources": 300,
    },
    "coal_mine": {
        "name": "Угольная шахта",
        "emoji": "🪨",
        "produces": "coal",
        "produces_name": "уголь",
        "amount_per_level": 660,
        "cost_gold": 400,
        "cost_resources": 300,
    },
    "oil_rig": {
        "name": "Нефтяная вышка",
        "emoji": "🛢️",
        "produces": "oil",
        "produces_name": "нефть",
        "amount_per_level": 900,
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
        "amount_per_level": 1500,
        "cost_gold": 2000,
        "cost_resources": 600,
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
MAX_BUY_PER_ORDER = 10_000

# --- Территория страны (задаётся автоматически по реальной площади страны, см. territory.py) ---
# Максимальный уровень одной добывающей постройки (в т.ч. нефтевышки) — чем больше
# страна, тем больше вышек/шахт можно построить.
# Лимит уровня построек по масштабу территории.
TERRITORY_BUILDING_LEVEL_CAP = {"small": 50, "medium": 150, "large": 300}
# Игровое население не имеет искусственного территориального потолка.
# Реальное население страны хранится отдельно в профиле World Bank и используется
# для масштабирования военной силы.
# Бонусные военные базы сверх формулы от армии (см. MILITARY_BASE_*).
# Любая страна может иметь минимум 9 баз; крупные территории получают больший базовый лимит.
# Минимум баз: 9 для малой страны, 25 для средней, 50 для крупной.
TERRITORY_BASE_BONUS = {"small": 9, "medium": 25, "large": 50}

# --- Армия и военные базы ---
# Внутри базы 1 очко армии = 1 000 военнослужащих.
# Одна военная база поддерживает 30 000 военнослужащих.
MILITARY_UNIT_SIZE = 1_000
MILITARY_PER_BASE = 30
# На одно внутреннее очко армии требуется 100 единиц игрового населения.
MOBILIZE_POPULATION_PER_POINT = 100
# Фактическое население ограничивает армию на уровне 20% населения страны.
MAX_ARMY_POPULATION_SHARE = 0.20

# --- Военные базы ---
# Одна база стоит золото+ресурсы (растёт с числом уже построенных баз) и требует
# минимального уровня армии. Максимум баз = TERRITORY_BASE_BONUS[tier] + military // MILITARY_PER_BASE.
# Каждые 30 внутренних единиц армии открывают ещё одну базу сверх территориального минимума.
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
NUKE_COOLDOWN_SECONDS = int(os.getenv("NUKE_COOLDOWN_SECONDS", str(60 * 60))) # 60 минут

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
# Ограничиваем автоматический прирост за один сбор, чтобы еда не обнулялась
# полностью и могла накапливаться до крупных стратегических запасов.
MAX_POPULATION_GROWTH_PER_COLLECT = 10

# --- Понятная шкала развития страны ---
# Это игровые очки развития, а не реальные ВВП/население страны.
# Инфраструктура должна заметно влиять на итоговый статус, чтобы новичок
# мог стать великой державой не только через спам одной характеристики.
PROGRESS_BUILDING_POINTS = 12
PROGRESS_STAGES = [
    (0, "Основание", "Создай базовую экономику и начни собирать доход."),
    (300, "Стабилизация", "Обеспечь еду, воду, сырьё и резерв людей."),
    (500, "Развитие", "Подними технологии, экономику и армию."),
    (700, "Региональная сила", "Строй базы, развивай дипломатию и готовь внешние действия."),
    (900, "Великая держава", "Используй войны, альянсы и сложные действия для влияния на мир."),
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
