import aiosqlite
import logging
import time
from contextlib import asynccontextmanager
logger = logging.getLogger("gavan.db")

from config import (
    DB_PATH,
    START_STATS,
    START_GOLD,
    FIRST_COLLECT_GOLD_BONUS,
    MILITARY_PER_BASE,
    MILITARY_UNIT_SIZE,
    MOBILIZE_POPULATION_PER_POINT,
    MOBILIZE_COOLDOWN_SECONDS,
    MAX_ARMY_POPULATION_SHARE,
    START_RESOURCES,
    START_MANPOWER,
    START_WATER,
    START_WOOD,
    START_MILITARY_BASES,
    START_FOOD,
    SECONDS_PER_GAME_YEAR,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS countries (
    user_id INTEGER PRIMARY KEY,
    chat_id INTEGER,
    name TEXT NOT NULL,
    economy INTEGER NOT NULL,
    military INTEGER NOT NULL,
    population INTEGER NOT NULL,
    tech INTEGER NOT NULL,
    diplomacy INTEGER NOT NULL,
    stability INTEGER NOT NULL DEFAULT 70,
    readiness INTEGER NOT NULL DEFAULT 50,
    war_exhaustion INTEGER NOT NULL DEFAULT 0,
    reputation INTEGER NOT NULL DEFAULT 50,
    policy TEXT NOT NULL DEFAULT 'development',
    last_policy_at INTEGER NOT NULL DEFAULT 0,
    points INTEGER NOT NULL DEFAULT 0,
    gold INTEGER NOT NULL DEFAULT 0,
    resources INTEGER NOT NULL DEFAULT 0,
    manpower INTEGER NOT NULL DEFAULT 0,
    water INTEGER NOT NULL DEFAULT 0,
    food INTEGER NOT NULL DEFAULT 0,
    wood INTEGER NOT NULL DEFAULT 0,
    iron INTEGER NOT NULL DEFAULT 0,
    coal INTEGER NOT NULL DEFAULT 0,
    oil INTEGER NOT NULL DEFAULT 0,
    uranium INTEGER NOT NULL DEFAULT 0,
    military_bases INTEGER NOT NULL DEFAULT 0,
    warheads INTEGER NOT NULL DEFAULT 0,
    territory_tier TEXT NOT NULL DEFAULT 'medium',
    created_at INTEGER NOT NULL,
    last_action_at INTEGER NOT NULL DEFAULT 0,
    last_collect_at INTEGER NOT NULL DEFAULT 0,
    last_attack_at INTEGER NOT NULL DEFAULT 0,
    last_spy_at INTEGER NOT NULL DEFAULT 0,
    last_nuke_at INTEGER NOT NULL DEFAULT 0,
    last_build_at INTEGER NOT NULL DEFAULT 0,
    last_upgrade_at INTEGER NOT NULL DEFAULT 0,
    last_mobilize_at INTEGER NOT NULL DEFAULT 0,
    last_buy_at INTEGER NOT NULL DEFAULT 0,
    last_base_at INTEGER NOT NULL DEFAULT 0,
    iso_code TEXT,
    data_year INTEGER,
    real_population INTEGER,
    real_gdp_usd REAL,
    real_gdp_per_capita_usd REAL,
    real_life_expectancy REAL
);

-- Альянсы (НАТО, ОДКБ и т.д.) — один игрок состоит максимум в одном альянсе.
CREATE TABLE IF NOT EXISTS alliances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS alliance_members (
    user_id INTEGER PRIMARY KEY,
    alliance_id INTEGER NOT NULL,
    joined_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    country_name TEXT,
    action_text TEXT,
    verdict_text TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS buildings (
    user_id INTEGER NOT NULL,
    building_type TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, building_type)
);

-- Единственная строка (id=1) хранит игровой год мира: базовый год плюс
-- момент (unix-время), с которого он начал расти автоматически.
CREATE TABLE IF NOT EXISTS world_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    base_year INTEGER NOT NULL,
    started_at INTEGER NOT NULL
);

-- История войн между игроками.
CREATE TABLE IF NOT EXISTS wars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attacker_id INTEGER NOT NULL,
    attacker_name TEXT,
    defender_id INTEGER NOT NULL,
    defender_name TEXT,
    action_text TEXT,
    outcome TEXT,
    verdict_text TEXT,
    created_at INTEGER NOT NULL
);
"""

# Колонки, которые могли отсутствовать в базах, созданных до этого обновления.
MIGRATIONS = [
    "ALTER TABLE countries ADD COLUMN last_action_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN stability INTEGER NOT NULL DEFAULT 70",
    "ALTER TABLE countries ADD COLUMN readiness INTEGER NOT NULL DEFAULT 50",
    "ALTER TABLE countries ADD COLUMN war_exhaustion INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN reputation INTEGER NOT NULL DEFAULT 50",
    "ALTER TABLE countries ADD COLUMN policy TEXT NOT NULL DEFAULT 'development'",
    "ALTER TABLE countries ADD COLUMN last_policy_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN gold INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN resources INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN manpower INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN last_collect_at INTEGER NOT NULL DEFAULT 0",
    f"ALTER TABLE countries ADD COLUMN water INTEGER NOT NULL DEFAULT {START_WATER}",
    "ALTER TABLE countries ADD COLUMN last_attack_at INTEGER NOT NULL DEFAULT 0",
    f"ALTER TABLE countries ADD COLUMN food INTEGER NOT NULL DEFAULT {START_FOOD}",
    "ALTER TABLE countries ADD COLUMN wood INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN iron INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN coal INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN oil INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN military_bases INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN territory_tier TEXT NOT NULL DEFAULT 'medium'",
    "ALTER TABLE countries ADD COLUMN last_spy_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN uranium INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN warheads INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN last_nuke_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN last_build_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN last_upgrade_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN last_mobilize_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN last_buy_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN last_base_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN iso_code TEXT",
    "ALTER TABLE countries ADD COLUMN data_year INTEGER",
    "ALTER TABLE countries ADD COLUMN real_population INTEGER",
    "ALTER TABLE countries ADD COLUMN real_gdp_usd REAL",
    "ALTER TABLE countries ADD COLUMN real_gdp_per_capita_usd REAL",
    "ALTER TABLE countries ADD COLUMN real_life_expectancy REAL",
]

# Разрешённые имена колонок для update_stat/update_resource.
# Проверяем явным raise, а не assert — assert вырезается при запуске
# с флагом `python -O`, и тогда имя колонки подставлялось бы в SQL без проверки.
_STAT_COLUMNS = ("economy", "military", "population", "tech", "diplomacy", "stability", "readiness", "war_exhaustion", "reputation", "points")
_RESOURCE_COLUMNS = (
    "gold", "resources", "manpower", "water", "food",
    "wood", "iron", "coal", "oil", "uranium",
    "military_bases", "warheads",
)


def _stat_assignment(stat: str) -> str:
    """Build a safe atomic assignment with both base and factual population ceilings."""
    if stat == "military":
        return (
            "military = MAX(0, MIN("
            f"military_bases * {MILITARY_PER_BASE}, "
            f"COALESCE(CAST(real_population * {MAX_ARMY_POPULATION_SHARE} / {MILITARY_UNIT_SIZE} AS INTEGER), 9223372036854775807), "
            "military + ?))"
        )
    return f"{stat} = MAX(0, {stat} + ?)"


@asynccontextmanager
async def _connect():
    """
    Открывает соединение с WAL-режимом и таймаутом ожидания блокировки.
    WAL позволяет читателям не блокироваться на писателях (и наоборот),
    а busy_timeout заставляет sqlite ждать освобождения блокировки вместо
    немедленного "database is locked", что снижает число ошибок при
    параллельных командах разных игроков.
    """
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=30000")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db


async def init_db():
    async with _connect() as db:
        await db.executescript(SCHEMA)
        try:
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_countries_name_nocase ON countries(name COLLATE NOCASE)")
        except aiosqlite.IntegrityError:
            # Legacy databases with duplicate country names remain usable; new founding is still guarded by the application lock.
            pass
        for stmt in MIGRATIONS:
            try:
                await db.execute(stmt)
            except aiosqlite.OperationalError as exc:
                # ALTER TABLE повторно выдаёт duplicate column name на уже
                # обновлённой базе. Любую другую ошибку нельзя скрывать:
                # иначе Render продолжит работу с неполной схемой.
                if "duplicate column name" not in str(exc).lower():
                    raise
        await db.commit()


async def create_country(user_id: int, chat_id: int, name: str, territory_tier: str = "medium", profile: dict | None = None):
    async with _connect() as db:
        cur = await db.execute("SELECT name FROM countries")
        existing_names = await cur.fetchall()
        if any(str(row[0]).casefold() == str(name).casefold() for row in existing_names):
            return False
        now = int(time.time())
        cur = await db.execute(
            """INSERT OR IGNORE INTO countries
               (user_id, chat_id, name, economy, military, population, tech, diplomacy,
                points, gold, resources, manpower, water, food, wood, military_bases, territory_tier,
                created_at, last_action_at, last_collect_at, iso_code, data_year,
                real_population, real_gdp_usd, real_gdp_per_capita_usd, real_life_expectancy)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, chat_id, name,
                START_STATS["economy"], START_STATS["military"],
                (profile or {}).get("game_population", START_STATS["population"]),
                START_STATS["tech"], START_STATS["diplomacy"],
                START_GOLD, START_RESOURCES, START_MANPOWER, START_WATER, START_FOOD,
                START_WOOD, START_MILITARY_BASES, territory_tier, now, 0,
                (profile or {}).get("iso_code"), (profile or {}).get("selected_year"),
                (profile or {}).get("population"), (profile or {}).get("gdp_usd"),
                (profile or {}).get("gdp_per_capita_usd"), (profile or {}).get("life_expectancy"),
            ),
        )
        await db.commit()
        return cur.rowcount == 1


async def set_policy(user_id: int, policy: str, timestamp: int, cooldown_seconds: int) -> bool:
    if policy not in {"development", "welfare", "militarism", "diplomacy"}:
        raise ValueError(f"Недопустимая политика: {policy!r}")
    async with _connect() as db:
        cur = await db.execute(
            """UPDATE countries SET policy = ?, last_policy_at = ?
               WHERE user_id = ? AND (last_policy_at = 0 OR last_policy_at < ?)""",
            (policy, timestamp, user_id, timestamp - cooldown_seconds),
        )
        await db.commit()
        return cur.rowcount == 1


async def get_country(user_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM countries WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_country_by_name(name: str):
    """Ищет страну без учёта регистра Unicode — для проверки, занята ли страна."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM countries")
        rows = await cur.fetchall()
        wanted = str(name).casefold()
        for row in rows:
            if str(row["name"]).casefold() == wanted:
                return dict(row)
        return None


async def get_all_countries():
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM countries ORDER BY (economy+military+population+tech+diplomacy) DESC")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def update_stat(user_id: int, stat: str, delta: int):
    if stat not in _STAT_COLUMNS:
        raise ValueError(f"Недопустимая характеристика: {stat!r}")
    async with _connect() as db:
        await db.execute(f"UPDATE countries SET {_stat_assignment(stat)} WHERE user_id = ?", (delta, user_id))
        await db.commit()


async def update_stats(user_id: int, deltas: dict):
    """Обновляет сразу несколько характеристик одним коммитом (одна транзакция вместо нескольких)."""
    deltas = {k: v for k, v in deltas.items() if v}
    if not deltas:
        return
    for k in deltas:
        if k not in _STAT_COLUMNS:
            raise ValueError(f"Недопустимая характеристика: {k!r}")
    set_clause = ", ".join(_stat_assignment(k) for k in deltas)
    async with _connect() as db:
        await db.execute(
            f"UPDATE countries SET {set_clause} WHERE user_id = ?",
            (*deltas.values(), user_id),
        )
        await db.commit()


async def update_resource(user_id: int, resource: str, delta: int):
    if resource not in _RESOURCE_COLUMNS:
        raise ValueError(f"Недопустимый ресурс: {resource!r}")
    async with _connect() as db:
        await db.execute(
            f"UPDATE countries SET {resource} = MAX(0, {resource} + ?) WHERE user_id = ?",
            (delta, user_id),
        )
        await db.commit()


async def set_points_all(amount_delta: int):
    async with _connect() as db:
        await db.execute("UPDATE countries SET points = points + ?", (amount_delta,))
        await db.commit()


async def log_event(user_id: int, country_name: str, action_text: str, verdict_text: str):
    async with _connect() as db:
        await db.execute(
            "INSERT INTO events (user_id, country_name, action_text, verdict_text, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, country_name, action_text, verdict_text, int(time.time())),
        )
        await db.commit()


async def get_recent_events(limit: int = 10):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def delete_country(user_id: int) -> bool:
    """
    Удаляет страну игрока (кик). Возвращает True, если что-то было удалено.
    Заодно чистит связанные записи (events, wars, alliance_members, buildings) —
    иначе они остаются "сиротами" со ссылкой на несуществующий user_id, и /news
    или /wars могут показывать вердикты/столкновения от уже удалённых игроков.
    """
    async with _connect() as db:
        await db.execute("DELETE FROM events WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM wars WHERE attacker_id = ? OR defender_id = ?", (user_id, user_id))
        await db.execute("DELETE FROM buildings WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM alliance_members WHERE user_id = ?", (user_id,))
        cur = await db.execute("DELETE FROM countries WHERE user_id = ?", (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def transfer_country(old_user_id: int, new_user_id: int, new_chat_id: int = None) -> bool:
    """
    Передаёт страну от одного telegram-пользователя другому. Возвращает True при успехе.
    Если у нового user_id уже есть своя страна — операция отклоняется (False).
    """
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT 1 FROM countries WHERE user_id = ?", (new_user_id,))
        if await cur.fetchone():
            return False
        cur = await db.execute("SELECT 1 FROM countries WHERE user_id = ?", (old_user_id,))
        if not await cur.fetchone():
            return False
        if new_chat_id is not None:
            await db.execute(
                "UPDATE countries SET user_id = ?, chat_id = ? WHERE user_id = ?",
                (new_user_id, new_chat_id, old_user_id),
            )
        else:
            await db.execute(
                "UPDATE countries SET user_id = ? WHERE user_id = ?",
                (new_user_id, old_user_id),
            )
        await db.execute("UPDATE buildings SET user_id = ? WHERE user_id = ?", (new_user_id, old_user_id))
        await db.execute("UPDATE events SET user_id = ? WHERE user_id = ?", (new_user_id, old_user_id))
        await db.execute(
            "UPDATE wars SET attacker_id = ? WHERE attacker_id = ?", (new_user_id, old_user_id)
        )
        await db.execute(
            "UPDATE wars SET defender_id = ? WHERE defender_id = ?", (new_user_id, old_user_id)
        )
        try:
            await db.execute(
                "UPDATE alliance_members SET user_id = ? WHERE user_id = ?", (new_user_id, old_user_id)
            )
        except aiosqlite.IntegrityError:
            pass  # у нового user_id уже есть запись в alliance_members — не перезаписываем
        await db.commit()
        return True


async def touch_last_action(user_id: int, ts: int):
    async with _connect() as db:
        await db.execute("UPDATE countries SET last_action_at = ? WHERE user_id = ?", (ts, user_id))
        await db.commit()


async def touch_last_collect(user_id: int, ts: int):
    async with _connect() as db:
        await db.execute("UPDATE countries SET last_collect_at = ? WHERE user_id = ?", (ts, user_id))
        await db.commit()


async def touch_last_attack(user_id: int, ts: int):
    async with _connect() as db:
        await db.execute("UPDATE countries SET last_attack_at = ? WHERE user_id = ?", (ts, user_id))
        await db.commit()


async def touch_last_spy(user_id: int, ts: int):
    async with _connect() as db:
        await db.execute("UPDATE countries SET last_spy_at = ? WHERE user_id = ?", (ts, user_id))
        await db.commit()


async def touch_last_nuke(user_id: int, ts: int):
    async with _connect() as db:
        await db.execute("UPDATE countries SET last_nuke_at = ? WHERE user_id = ?", (ts, user_id))
        await db.commit()


_COOLDOWN_COLUMNS = {
    "build": "last_build_at",
    "upgrade": "last_upgrade_at",
    "mobilize": "last_mobilize_at",
    "buy": "last_buy_at",
    "base": "last_base_at",
}


async def touch_cooldown(user_id: int, action: str, ts: int) -> None:
    column = _COOLDOWN_COLUMNS.get(action)
    if not column:
        raise ValueError(f"Unknown cooldown action: {action!r}")
    async with _connect() as db:
        await db.execute(f"UPDATE countries SET {column} = ? WHERE user_id = ?", (ts, user_id))
        await db.commit()


# --- Постройки ---

async def get_buildings(user_id: int) -> dict:
    """Возвращает {building_type: level} для всех построек игрока (отсутствующие = 0)."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT building_type, level FROM buildings WHERE user_id = ?", (user_id,))
        rows = await cur.fetchall()
        return {r["building_type"]: r["level"] for r in rows}


async def get_building_level(user_id: int, building_type: str) -> int:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT level FROM buildings WHERE user_id = ? AND building_type = ?",
            (user_id, building_type),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def upgrade_building(user_id: int, building_type: str):
    async with _connect() as db:
        await db.execute(
            """INSERT INTO buildings (user_id, building_type, level) VALUES (?, ?, 1)
               ON CONFLICT(user_id, building_type) DO UPDATE SET level = level + 1""",
            (user_id, building_type),
        )
        await db.commit()


async def apply_upgrade(user_id: int, stat: str, amount: int, points_cost: int) -> bool:
    if stat not in _STAT_COLUMNS or stat == "points":
        raise ValueError(f"Недопустимая характеристика для улучшения: {stat!r}")
    async with _connect() as db:
        cur = await db.execute(
            f"UPDATE countries SET {stat} = MAX(0, {stat} + ?), points = points - ? WHERE user_id = ? AND points >= ?",
            (amount, points_cost, user_id, points_cost),
        )
        await db.commit()
        return cur.rowcount == 1


async def apply_base(user_id: int, cost_gold: int, cost_resources: int, required_military: int = 0) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            """UPDATE countries SET gold = gold - ?, resources = resources - ?, military_bases = military_bases + 1
               WHERE user_id = ? AND gold >= ? AND resources >= ? AND military >= ?""",
            (cost_gold, cost_resources, user_id, cost_gold, cost_resources, required_military),
        )
        await db.commit()
        return cur.rowcount == 1


async def apply_spy_operation(user_id: int, cost_gold: int, timestamp: int) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            """UPDATE countries SET gold = gold - ?, last_spy_at = ?
               WHERE user_id = ? AND gold >= ?""",
            (cost_gold, timestamp, user_id, cost_gold),
        )
        await db.commit()
        return cur.rowcount == 1


async def apply_collect(user_id: int, gains: dict, economy_growth: int, food_spend: int, population_growth: int, points_growth: int, timestamp: int, stability_delta: int = 0) -> bool:
    allowed_resources = set(_RESOURCE_COLUMNS) - {"military_bases", "warheads"}
    gains = {k: int(v) for k, v in (gains or {}).items() if k in allowed_resources and int(v) > 0}
    deltas = {k: v for k, v in gains.items()}
    if food_spend:
        deltas["food"] = deltas.get("food", 0) - food_spend
    gold_gain = deltas.pop("gold", 0)
    assignments = [
        "gold = gold + ? + CASE WHEN last_collect_at = 0 THEN ? ELSE 0 END",
        "last_collect_at = ?",
    ]
    params = [gold_gain, FIRST_COLLECT_GOLD_BONUS, timestamp]
    for key, value in deltas.items():
        assignments.append(f"{key} = MAX(0, {key} + ?)")
        params.append(value)
    if economy_growth:
        assignments.append("economy = MAX(0, economy + ?)")
        params.append(economy_growth)
    if population_growth:
        assignments.append("population = MAX(0, population + ?)")
        params.append(population_growth)
    if points_growth:
        assignments.append("points = MAX(0, points + ?)")
        params.append(points_growth)
    if stability_delta > 0:
        assignments.extend([
            "stability = MIN(100, stability + ?)",
            "readiness = MIN(100, readiness + 1)",
            "war_exhaustion = MAX(0, war_exhaustion - 1)",
        ])
        params.append(stability_delta)
    elif stability_delta < 0:
        assignments.append("stability = MAX(0, stability + ?)")
        params.append(stability_delta)
    params.append(user_id)
    async with _connect() as db:
        cur = await db.execute(
            f"UPDATE countries SET {', '.join(assignments)} WHERE user_id = ? AND last_collect_at < ?",
            (*params, timestamp),
        )
        await db.commit()
        return cur.rowcount == 1


async def apply_purchase(user_id: int, resource: str, amount: int, gold_cost: int) -> bool:
    if resource not in _RESOURCE_COLUMNS or resource in ("gold", "military_bases", "warheads"):
        raise ValueError(f"Недопустимый ресурс для покупки: {resource!r}")
    async with _connect() as db:
        cur = await db.execute(
            f"UPDATE countries SET gold = gold - ?, {resource} = {resource} + ? WHERE user_id = ? AND gold >= ?",
            (gold_cost, amount, user_id, gold_cost),
        )
        await db.commit()
        return cur.rowcount == 1


async def apply_building_upgrade(user_id: int, building_type: str, cost_gold: int, cost_resources: int) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            """UPDATE countries SET gold = gold - ?, resources = resources - ?
               WHERE user_id = ? AND gold >= ? AND resources >= ?""",
            (cost_gold, cost_resources, user_id, cost_gold, cost_resources),
        )
        if cur.rowcount != 1:
            await db.rollback()
            return False
        await db.execute(
            """INSERT INTO buildings (user_id, building_type, level) VALUES (?, ?, 1)
               ON CONFLICT(user_id, building_type) DO UPDATE SET level = level + 1""",
            (user_id, building_type),
        )
        await db.commit()
        return True


async def apply_mobilization(user_id: int, manpower_cost: int, gold_cost: int, military_gain: int, timestamp: int | None = None):
    """Atomically mobilize with base, population, resources, factual cap, and cooldown checks."""
    population_required = military_gain * MOBILIZE_POPULATION_PER_POINT
    timestamp = int(time.time()) if timestamp is None else int(timestamp)
    async with _connect() as db:
        cur = await db.execute(
            """UPDATE countries
               SET manpower = manpower - ?, gold = gold - ?,
                   military = military + ?,
                   readiness = MAX(0, readiness - 2),
                   war_exhaustion = MIN(100, war_exhaustion + 1),
                   last_mobilize_at = ?
               WHERE user_id = ?
                 AND manpower >= ?
                 AND gold >= ?
                 AND population >= ?
                 AND military + ? <= military_bases * ?
                 AND military + ? <= COALESCE(CAST(real_population * ? / ? AS INTEGER), 9223372036854775807)
                 AND (last_mobilize_at = 0 OR last_mobilize_at < ?)""",
            (
                manpower_cost, gold_cost, military_gain, timestamp, user_id,
                manpower_cost, gold_cost, population_required,
                military_gain, MILITARY_PER_BASE,
                military_gain, MAX_ARMY_POPULATION_SHARE, MILITARY_UNIT_SIZE,
                timestamp - MOBILIZE_COOLDOWN_SECONDS,
            ),
        )
        await db.commit()
        return cur.rowcount == 1


# --- Игровой год мира ---

async def set_world_year(base_year: int):
    """Фиксирует год мира прямо сейчас. Дальше он растёт сам (см. get_current_year)."""
    now = int(time.time())
    async with _connect() as db:
        await db.execute(
            """INSERT INTO world_state (id, base_year, started_at) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET base_year = excluded.base_year, started_at = excluded.started_at""",
            (base_year, now),
        )
        await db.commit()


async def get_world_year_row():
    """Возвращает {base_year, started_at} или None, если год ещё не задавали."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT base_year, started_at FROM world_state WHERE id = 1")
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_current_year():
    """Текущий игровой год с учётом автоприроста (1 реальные сутки = 1 игровой год), или None если не задан."""
    row = await get_world_year_row()
    if row is None:
        return None
    elapsed_years = (int(time.time()) - row["started_at"]) // SECONDS_PER_GAME_YEAR
    return row["base_year"] + elapsed_years


# --- Войны между игроками ---

async def apply_action_result(user_id: int, deltas: dict, country_name: str, action_text: str, verdict_text: str) -> None:
    deltas = {k: int(v) for k, v in (deltas or {}).items() if k in _STAT_COLUMNS and int(v) != 0}
    async with _connect() as db:
        if deltas:
            set_clause = ", ".join(_stat_assignment(k) for k in deltas)
            await db.execute(
                f"UPDATE countries SET {set_clause} WHERE user_id = ?",
                (*deltas.values(), user_id),
            )
        await db.execute(
            "INSERT INTO events (user_id, country_name, action_text, verdict_text, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, country_name, action_text, verdict_text, int(time.time())),
        )
        await db.commit()


async def apply_war_result(
    attacker_id: int,
    defender_id: int,
    attacker_deltas: dict,
    defender_deltas: dict,
    loot_gold: int = 0,
    loot_resources: int = 0,
):
    """
    Применяет результат войны обеим сторонам одной транзакцией:
    - меняет характеристики (economy/military/population/tech/diplomacy) обеих стран
    - переносит трофеи (gold/resources) от защищающегося к нападающему, если loot > 0
    Всё в одном соединении/коммите, чтобы избежать частичного применения при сбое.
    """
    async with _connect() as db:
        for user_id, deltas in ((attacker_id, attacker_deltas), (defender_id, defender_deltas)):
            deltas = {k: v for k, v in (deltas or {}).items() if v and k in _STAT_COLUMNS}
            if deltas:
                set_clause = ", ".join(_stat_assignment(k) for k in deltas)
                await db.execute(
                    f"UPDATE countries SET {set_clause} WHERE user_id = ?",
                    (*deltas.values(), user_id),
                )
        await db.execute(
            """UPDATE countries SET
                stability = MAX(0, stability - 3),
                readiness = MAX(0, readiness - 10),
                war_exhaustion = MIN(100, war_exhaustion + 10),
                reputation = MAX(0, reputation - 2)
               WHERE user_id = ?""",
            (attacker_id,),
        )
        await db.execute(
            """UPDATE countries SET
                stability = MAX(0, stability - 6),
                readiness = MAX(0, readiness - 15),
                war_exhaustion = MIN(100, war_exhaustion + 15),
                reputation = MAX(0, reputation - 1)
               WHERE user_id = ?""",
            (defender_id,),
        )

        if loot_gold or loot_resources:
            if loot_gold > 0 or loot_resources > 0:
                source_id, target_id = defender_id, attacker_id
                amount_gold, amount_resources = loot_gold, loot_resources
            else:
                source_id, target_id = attacker_id, defender_id
                amount_gold, amount_resources = -loot_gold, -loot_resources
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT gold, resources FROM countries WHERE user_id = ?",
                (source_id,),
            )
            source = await cur.fetchone()
            if source:
                amount_gold = min(amount_gold, max(0, source["gold"]))
                amount_resources = min(amount_resources, max(0, source["resources"]))
            else:
                amount_gold = amount_resources = 0
            await db.execute(
                "UPDATE countries SET gold = gold - ?, resources = resources - ? WHERE user_id = ?",
                (amount_gold, amount_resources, source_id),
            )
            await db.execute(
                "UPDATE countries SET gold = gold + ?, resources = resources + ? WHERE user_id = ?",
                (amount_gold, amount_resources, target_id),
            )

        await db.commit()


async def log_war(attacker_id: int, attacker_name: str, defender_id: int, defender_name: str,
                   action_text: str, outcome: str, verdict_text: str):
    async with _connect() as db:
        await db.execute(
            """INSERT INTO wars (attacker_id, attacker_name, defender_id, defender_name,
                                  action_text, outcome, verdict_text, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (attacker_id, attacker_name, defender_id, defender_name,
             action_text, outcome, verdict_text, int(time.time())),
        )
        await db.commit()


async def get_recent_wars(limit: int = 10):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM wars ORDER BY id DESC LIMIT ?", (limit,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# --- Альянсы ---

async def create_alliance(tag: str, name: str) -> bool:
    """Создаёт альянс. Возвращает False, если тег уже занят."""
    async with _connect() as db:
        try:
            await db.execute(
                "INSERT INTO alliances (tag, name, created_at) VALUES (?, ?, ?)",
                (tag, name, int(time.time())),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def get_alliance_by_tag(tag: str):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM alliances WHERE tag = ? COLLATE NOCASE", (tag,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_alliance(alliance_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM alliances WHERE id = ?", (alliance_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_alliances():
    """Все альянсы вместе с числом участников."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT a.*, COUNT(m.user_id) AS member_count
               FROM alliances a
               LEFT JOIN alliance_members m ON m.alliance_id = a.id
               GROUP BY a.id
               ORDER BY member_count DESC, a.name"""
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_user_alliance(user_id: int):
    """Возвращает альянс игрока (dict) или None, если он ни в каком не состоит."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT a.* FROM alliance_members m
               JOIN alliances a ON a.id = m.alliance_id
               WHERE m.user_id = ?""",
            (user_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def join_alliance(user_id: int, alliance_id: int):
    async with _connect() as db:
        await db.execute(
            """INSERT INTO alliance_members (user_id, alliance_id, joined_at) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET alliance_id = excluded.alliance_id, joined_at = excluded.joined_at""",
            (user_id, alliance_id, int(time.time())),
        )
        await db.execute(
            "UPDATE countries SET reputation = MIN(100, reputation + 2), stability = MIN(100, stability + 1) WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()


async def leave_alliance(user_id: int) -> bool:
    async with _connect() as db:
        cur = await db.execute("DELETE FROM alliance_members WHERE user_id = ?", (user_id,))
        if cur.rowcount:
            await db.execute(
                "UPDATE countries SET reputation = MAX(0, reputation - 1), stability = MAX(0, stability - 1) WHERE user_id = ?",
                (user_id,),
            )
        await db.commit()
        return cur.rowcount > 0


async def get_alliance_members(alliance_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT c.user_id, c.name FROM alliance_members m
               JOIN countries c ON c.user_id = m.user_id
               WHERE m.alliance_id = ?""",
            (alliance_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
