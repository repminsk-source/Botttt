import aiosqlite
import logging
import time
import json
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
    PMC_STARTING_FUNDS,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS countries (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
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
    labor_focus TEXT NOT NULL DEFAULT 'balanced',
    tax_rate INTEGER NOT NULL DEFAULT 10,
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
    territory INTEGER NOT NULL DEFAULT 100000,
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
CREATE TABLE IF NOT EXISTS alliance_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alliance_id INTEGER NOT NULL,
    inviter_id INTEGER NOT NULL,
    invitee_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected', 'cancelled')),
    created_at INTEGER NOT NULL,
    resolved_at INTEGER,
    UNIQUE(alliance_id, invitee_id, status)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    country_name TEXT,
    action_text TEXT,
    verdict_text TEXT,
    created_at INTEGER NOT NULL
);

-- Глобальные события отделены от локальных действий игроков.
CREATE TABLE IF NOT EXISTS world_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'world',
    game_year INTEGER,
    effects_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    expires_at INTEGER
);

CREATE TABLE IF NOT EXISTS country_statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    country_name TEXT NOT NULL,
    statement TEXT NOT NULL,
    game_year INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_country_statements_created ON country_statements(created_at DESC);

CREATE TABLE IF NOT EXISTS trade_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposer_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    resource TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount > 0),
    price INTEGER NOT NULL CHECK(price >= 0),
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    resolved_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_world_events_active ON world_events(active, created_at);
CREATE INDEX IF NOT EXISTS idx_trade_contracts_target ON trade_contracts(target_id, status);
CREATE INDEX IF NOT EXISTS idx_trade_contracts_proposer ON trade_contracts(proposer_id, status);

CREATE TABLE IF NOT EXISTS diplomatic_pacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposer_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    pact_type TEXT NOT NULL DEFAULT 'non_aggression',
    terms TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'active', 'rejected', 'expired', 'breached', 'cancelled')),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    resolved_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_diplomatic_pacts_parties ON diplomatic_pacts(proposer_id, target_id, status);

CREATE TABLE IF NOT EXISTS country_sanctions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issuer_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    sanction_type TEXT NOT NULL CHECK(sanction_type IN ('economic', 'trade', 'diplomatic')),
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'expired', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_country_sanctions_target ON country_sanctions(target_id, status, expires_at);
CREATE INDEX IF NOT EXISTS idx_country_sanctions_issuer ON country_sanctions(issuer_id, status);

CREATE TABLE IF NOT EXISTS pmc_statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pmc_id INTEGER NOT NULL,
    organization_name TEXT NOT NULL,
    statement TEXT NOT NULL,
    game_year INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pmc_statements_created ON pmc_statements(created_at DESC);

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

CREATE TABLE IF NOT EXISTS pending_wars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attacker_id INTEGER NOT NULL,
    attacker_name TEXT NOT NULL,
    defender_id INTEGER NOT NULL,
    defender_name TEXT NOT NULL,
    attack_text TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    defense_text TEXT
);

CREATE TABLE IF NOT EXISTS premium_wallets (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS premium_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    reason TEXT NOT NULL,
    actor_id INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS premium_items (
    user_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    expires_at INTEGER,
    PRIMARY KEY (user_id, item_key)
);

-- Отдельные организации ЧВК/террористических группировок.
CREATE TABLE IF NOT EXISTS pmcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL UNIQUE,
    org_type TEXT NOT NULL DEFAULT 'pmc' CHECK(org_type IN ('pmc', 'terror')),
    reputation INTEGER NOT NULL DEFAULT 50,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'suspended', 'disqualified')),
    personnel INTEGER NOT NULL DEFAULT 0 CHECK(personnel >= 0),
    equipment INTEGER NOT NULL DEFAULT 0 CHECK(equipment >= 0),
    inventory_gold INTEGER NOT NULL DEFAULT 0 CHECK(inventory_gold >= 0),
    last_recruit_at INTEGER NOT NULL DEFAULT 0,
    last_action_at INTEGER NOT NULL DEFAULT 0,
    last_collect_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pmc_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pmc_id INTEGER NOT NULL,
    country_id INTEGER NOT NULL,
    request_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected', 'cancelled')),
    anonymous INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    resolved_at INTEGER,
    resolved_by INTEGER
);

CREATE TABLE IF NOT EXISTS pmc_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pmc_id INTEGER NOT NULL,
    country_id INTEGER NOT NULL,
    request_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'cancelled', 'disqualified')),
    created_at INTEGER NOT NULL,
    resolved_at INTEGER
);

CREATE TABLE IF NOT EXISTS pmc_sanctions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pmc_id INTEGER NOT NULL,
    sanction_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pmc_requests_pmc_status ON pmc_requests(pmc_id, status);
CREATE INDEX IF NOT EXISTS idx_pmc_contracts_country_status ON pmc_contracts(country_id, status);
"""

# Колонки, которые могли отсутствовать в базах, созданных до этого обновления.
MIGRATIONS = [
    "ALTER TABLE countries ADD COLUMN last_action_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN stability INTEGER NOT NULL DEFAULT 70",
    "ALTER TABLE countries ADD COLUMN readiness INTEGER NOT NULL DEFAULT 50",
    "ALTER TABLE countries ADD COLUMN war_exhaustion INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE countries ADD COLUMN reputation INTEGER NOT NULL DEFAULT 50",
    "ALTER TABLE countries ADD COLUMN policy TEXT NOT NULL DEFAULT 'development'",
    "ALTER TABLE countries ADD COLUMN labor_focus TEXT NOT NULL DEFAULT 'balanced'",
    "ALTER TABLE countries ADD COLUMN tax_rate INTEGER NOT NULL DEFAULT 10",
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
    "ALTER TABLE countries ADD COLUMN territory INTEGER NOT NULL DEFAULT 100000",
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
    "ALTER TABLE countries ADD COLUMN username TEXT",
    "ALTER TABLE pmcs ADD COLUMN last_action_at INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE pmcs ADD COLUMN last_collect_at INTEGER NOT NULL DEFAULT 0",
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


async def check_integrity() -> bool:
    """Return whether SQLite reports a healthy database."""
    async with _connect() as db:
        cur = await db.execute("PRAGMA integrity_check")
        row = await cur.fetchone()
        return bool(row and row[0] == "ok")


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
        try:
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_countries_username_nocase ON countries(username COLLATE NOCASE) WHERE username IS NOT NULL AND username <> ''")
        except aiosqlite.IntegrityError:
            logger.warning("Не удалось создать уникальный индекс username: в legacy базе есть дубликаты")
        cur = await db.execute("SELECT COUNT(*) FROM world_events")
        if (await cur.fetchone())[0] == 0:
            await db.execute(
                "INSERT INTO world_events (title, description, event_type, game_year, effects_json, active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                ("Новая эпоха", "Мировая система готова к первым решениям государств. Торговля, союзы и конфликты будут менять баланс сил.", "global", None, "{}", int(time.time())),
            )
        await db.commit()


async def create_country(user_id: int, chat_id: int, name: str, territory_tier: str = "medium", profile: dict | None = None, username: str | None = None):
    async with _connect() as db:
        cur = await db.execute("SELECT name FROM countries")
        existing_names = await cur.fetchall()
        if any(str(row[0]).casefold() == str(name).casefold() for row in existing_names):
            return False
        now = int(time.time())
        cur = await db.execute(
            """INSERT OR IGNORE INTO countries
               (user_id, username, chat_id, name, economy, military, population, tech, diplomacy,
                points, gold, resources, manpower, water, food, wood, military_bases, territory_tier,
                created_at, last_action_at, last_collect_at, iso_code, data_year,
                real_population, real_gdp_usd, real_gdp_per_capita_usd, real_life_expectancy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, normalize_username(username), chat_id, name,
                START_STATS["economy"], START_STATS["military"],
                (profile or {}).get("game_population", START_STATS["population"]),
                START_STATS["tech"], START_STATS["diplomacy"],
                START_GOLD, START_RESOURCES, START_MANPOWER, START_WATER, START_FOOD,
                START_WOOD, START_MILITARY_BASES, territory_tier, now,
                (profile or {}).get("iso_code"), (profile or {}).get("selected_year"),
                (profile or {}).get("population"), (profile or {}).get("gdp_usd"),
                (profile or {}).get("gdp_per_capita_usd"), (profile or {}).get("life_expectancy"),
            ),
        )
        await db.commit()
        return cur.rowcount == 1


async def set_tax_rate(user_id: int, tax_rate: int) -> bool:
    from config import TAX_RATE_MIN, TAX_RATE_MAX
    if tax_rate < TAX_RATE_MIN or tax_rate > TAX_RATE_MAX:
        return False
    async with _connect() as db:
        cur = await db.execute("UPDATE countries SET tax_rate = ? WHERE user_id = ?", (tax_rate, user_id))
        await db.commit()
        return cur.rowcount == 1


async def set_labor_focus(user_id: int, focus: str) -> bool:
    if focus not in {"civilian", "balanced", "military"}:
        raise ValueError(f"Недопустимый приоритет труда: {focus!r}")
    async with _connect() as db:
        cur = await db.execute("UPDATE countries SET labor_focus = ? WHERE user_id = ?", (focus, user_id))
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


def normalize_username(username: str | None) -> str | None:
    value = str(username or "").strip().lstrip("@").casefold()
    return value or None


async def update_country_username(user_id: int, username: str | None) -> bool:
    normalized = normalize_username(username)
    if not normalized:
        return False
    async with _connect() as db:
        try:
            cur = await db.execute("UPDATE countries SET username = ? WHERE user_id = ?", (normalized, user_id))
            await db.commit()
            return cur.rowcount == 1
        except aiosqlite.IntegrityError:
            await db.rollback()
            logger.warning("Username %s is already linked to another country", normalized)
            return False


async def get_country_by_username(username: str):
    normalized = normalize_username(username)
    if not normalized:
        return None
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM countries WHERE username = ? COLLATE NOCASE", (normalized,))
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


async def get_premium_balance(user_id: int) -> int:
    async with _connect() as db:
        cur = await db.execute("SELECT balance FROM premium_wallets WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return int(row[0] if row else 0)


async def get_premium_items(user_id: int) -> dict[str, int]:
    now = int(time.time())
    async with _connect() as db:
        cur = await db.execute(
            "SELECT item_key, quantity FROM premium_items WHERE user_id = ? AND (expires_at IS NULL OR expires_at > ?)",
            (user_id, now),
        )
        return {str(row[0]): int(row[1]) for row in await cur.fetchall() if int(row[1]) > 0}


async def grant_premium(user_id: int, amount: int, reason: str, actor_id: int | None = None) -> bool:
    if amount <= 0 or not reason.strip():
        return False
    now = int(time.time())
    async with _connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute("INSERT OR IGNORE INTO premium_wallets(user_id, balance, updated_at) VALUES (?, 0, ?)", (user_id, now))
        await db.execute("UPDATE premium_wallets SET balance = balance + ?, updated_at = ? WHERE user_id = ?", (amount, now, user_id))
        cur = await db.execute("SELECT balance FROM premium_wallets WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        await db.execute("INSERT INTO premium_ledger(user_id, delta, balance_after, reason, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (user_id, amount, int(row[0]), reason.strip(), actor_id, now))
        await db.commit()
        return True


async def purchase_premium(user_id: int, item_key: str, cost: int, reason: str, quantity: int = 1, expires_at: int | None = None) -> bool:
    if cost <= 0 or quantity <= 0 or not item_key or not reason.strip():
        return False
    now = int(time.time())
    async with _connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute("INSERT OR IGNORE INTO premium_wallets(user_id, balance, updated_at) VALUES (?, 0, ?)", (user_id, now))
        cur = await db.execute("UPDATE premium_wallets SET balance = balance - ?, updated_at = ? WHERE user_id = ? AND balance >= ?", (cost, now, user_id, cost))
        if cur.rowcount != 1:
            await db.rollback()
            return False
        if item_key == "territory_expansion":
            await db.execute("UPDATE countries SET territory = territory + 2500 WHERE user_id = ?", (user_id,))
        await db.execute(
            "INSERT INTO premium_items(user_id, item_key, quantity, expires_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, item_key) DO UPDATE SET quantity = quantity + excluded.quantity, expires_at = excluded.expires_at",
            (user_id, item_key, quantity, expires_at),
        )
        cur = await db.execute("SELECT balance FROM premium_wallets WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        await db.execute("INSERT INTO premium_ledger(user_id, delta, balance_after, reason, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (user_id, -cost, int(row[0]), reason.strip(), user_id, now))
        await db.commit()
        return True


async def consume_premium_item(user_id: int, item_key: str, quantity: int = 1) -> bool:
    if quantity <= 0 or not item_key:
        return False
    now = int(time.time())
    async with _connect() as db:
        cur = await db.execute(
            "UPDATE premium_items SET quantity = quantity - ? WHERE user_id = ? AND item_key = ? AND quantity >= ? AND (expires_at IS NULL OR expires_at > ?)",
            (quantity, user_id, item_key, quantity, now),
        )
        await db.commit()
        return cur.rowcount == 1


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


async def get_recent_events_for_user(user_id: int, limit: int = 10):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM events WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        return [dict(r) for r in await cur.fetchall()]


async def create_country_statement(user_id: int, country_name: str, statement: str, game_year: int | None = None, timestamp: int | None = None):
    statement = " ".join(str(statement or "").split())[:1200]
    country_name = " ".join(str(country_name or "").split())[:120]
    if not country_name or not statement or len(statement) < 50:
        return None
    async with _connect() as db:
        cur = await db.execute(
            "INSERT INTO country_statements (user_id, country_name, statement, game_year, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, country_name, statement, game_year, int(timestamp or time.time())),
        )
        await db.commit()
        return int(cur.lastrowid)


async def create_pmc_statement(pmc_id: int, organization_name: str, statement: str, game_year: int | None = None, timestamp: int | None = None):
    from config import STATEMENT_COOLDOWN_SECONDS
    timestamp = int(timestamp or time.time())
    statement = " ".join(str(statement or "").split())[:1000]
    if not statement:
        return None
    async with _connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute("SELECT status FROM pmcs WHERE id = ?", (pmc_id,))
        organization = await cur.fetchone()
        if not organization or organization[0] != "active":
            await db.rollback()
            return None
        cur = await db.execute("SELECT created_at FROM pmc_statements WHERE pmc_id = ? ORDER BY id DESC LIMIT 1", (pmc_id,))
        previous = await cur.fetchone()
        if previous and timestamp - int(previous[0]) < STATEMENT_COOLDOWN_SECONDS:
            await db.rollback()
            return None
        cur = await db.execute("INSERT INTO pmc_statements (pmc_id, organization_name, statement, game_year, created_at) VALUES (?, ?, ?, ?, ?)", (pmc_id, organization_name, statement, game_year, timestamp))
        await db.commit()
        return int(cur.lastrowid)


async def get_pmc_action_cooldown(pmc_id: int, timestamp: int | None = None) -> int:
    from config import PMC_ACTION_COOLDOWN_SECONDS
    timestamp = int(timestamp or time.time())
    async with _connect() as db:
        cur = await db.execute("SELECT last_action_at FROM pmcs WHERE id = ? AND status = 'active'", (pmc_id,))
        row = await cur.fetchone()
    if not row:
        return -1
    last_action_at = int(row[0] or 0)
    if last_action_at <= 0:
        return 0
    return max(0, PMC_ACTION_COOLDOWN_SECONDS - (timestamp - last_action_at))


async def touch_pmc_action(pmc_id: int, owner_id: int, timestamp: int | None = None) -> bool:
    timestamp = int(timestamp or time.time())
    async with _connect() as db:
        cur = await db.execute("UPDATE pmcs SET last_action_at = ? WHERE id = ? AND owner_id = ? AND status = 'active'", (timestamp, pmc_id, owner_id))
        await db.commit()
        return cur.rowcount == 1


async def get_recent_pmc_statements(limit: int = 12):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM pmc_statements ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(int(limit), 50)),))
        return [dict(row) for row in await cur.fetchall()]


async def get_recent_country_statements(limit: int = 12):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, user_id, country_name, statement, game_year, created_at FROM country_statements ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def create_world_event(title: str, description: str, event_type: str = "world", game_year: int | None = None, effects: dict | None = None, expires_at: int | None = None) -> int:
    if not title.strip() or not description.strip():
        raise ValueError("Событие должно иметь заголовок и описание")
    async with _connect() as db:
        cur = await db.execute(
            "INSERT INTO world_events (title, description, event_type, game_year, effects_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title.strip()[:160], description.strip()[:2000], event_type.strip()[:32] or "world", game_year, json.dumps(effects or {}, ensure_ascii=False), int(time.time()), expires_at),
        )
        await db.commit()
        return int(cur.lastrowid)


async def get_latest_world_event_created_at() -> int:
    async with _connect() as db:
        cur = await db.execute("SELECT COALESCE(MAX(created_at), 0) FROM world_events")
        row = await cur.fetchone()
        return int(row[0] or 0)


async def get_world_events(limit: int = 10, active_only: bool = True):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        where = "WHERE active = 1 AND (expires_at IS NULL OR expires_at > ?)" if active_only else ""
        args = (int(time.time()), limit) if active_only else (limit,)
        cur = await db.execute(f"SELECT * FROM world_events {where} ORDER BY id DESC LIMIT ?", args)
        rows = await cur.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["effects"] = json.loads(item.pop("effects_json") or "{}")
            except json.JSONDecodeError:
                item["effects"] = {}
            result.append(item)
        return result


async def deactivate_world_event(event_id: int) -> bool:
    async with _connect() as db:
        cur = await db.execute("UPDATE world_events SET active = 0 WHERE id = ? AND active = 1", (event_id,))
        await db.commit()
        return cur.rowcount == 1


TRADE_RESOURCES = frozenset({"resources", "water", "food", "wood", "iron", "coal", "oil", "uranium"})


async def create_trade_contract(proposer_id: int, target_id: int, resource: str, amount: int, price: int, expires_at: int | None = None):
    if proposer_id == target_id or resource not in TRADE_RESOURCES or amount <= 0 or price < 0:
        return None
    async with _connect() as db:
        cur = await db.execute("SELECT 1 FROM countries WHERE user_id IN (?, ?)", (proposer_id, target_id))
        if len(await cur.fetchall()) != 2:
            return None
        cur = await db.execute(
            "INSERT INTO trade_contracts (proposer_id, target_id, resource, amount, price, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (proposer_id, target_id, resource, amount, price, int(time.time()), expires_at),
        )
        await db.commit()
        return int(cur.lastrowid)


async def get_trade_contract(contract_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM trade_contracts WHERE id = ?", (contract_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_trade_contracts(user_id: int, limit: int = 20):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT t.*, p.name AS proposer_name, q.name AS target_name
               FROM trade_contracts t
               LEFT JOIN countries p ON p.user_id = t.proposer_id
               LEFT JOIN countries q ON q.user_id = t.target_id
               WHERE (t.proposer_id = ? OR t.target_id = ?) AND t.status = 'pending'
               ORDER BY t.id DESC LIMIT ?""",
            (user_id, user_id, limit),
        )
        return [dict(row) for row in await cur.fetchall()]


async def accept_trade_contract(contract_id: int, target_id: int, timestamp: int | None = None) -> bool:
    timestamp = int(timestamp or time.time())
    async with _connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM trade_contracts WHERE id = ? AND target_id = ? AND status = 'pending'", (contract_id, target_id))
        contract = await cur.fetchone()
        if not contract or (contract["expires_at"] is not None and contract["expires_at"] <= timestamp):
            await db.rollback()
            return False
        cur = await db.execute("SELECT * FROM countries WHERE user_id IN (?, ?)", (contract["proposer_id"], contract["target_id"]))
        countries = {row["user_id"]: row for row in await cur.fetchall()}
        proposer, target = countries.get(contract["proposer_id"]), countries.get(contract["target_id"])
        if not proposer or not target or proposer[contract["resource"]] < contract["amount"] or target["gold"] < contract["price"]:
            await db.rollback()
            return False
        resource = contract["resource"]
        await db.execute(f"UPDATE countries SET {resource} = {resource} - ? WHERE user_id = ?", (contract["amount"], contract["proposer_id"]))
        await db.execute(f"UPDATE countries SET {resource} = {resource} + ?, gold = gold - ? WHERE user_id = ?", (contract["amount"], contract["price"], contract["target_id"]))
        await db.execute("UPDATE countries SET gold = gold + ? WHERE user_id = ?", (contract["price"], contract["proposer_id"]))
        await db.execute("UPDATE trade_contracts SET status = 'accepted', resolved_at = ? WHERE id = ?", (timestamp, contract_id))
        await db.commit()
        return True


async def reject_trade_contract(contract_id: int, target_id: int) -> bool:
    async with _connect() as db:
        cur = await db.execute("UPDATE trade_contracts SET status = 'rejected', resolved_at = ? WHERE id = ? AND target_id = ? AND status = 'pending'", (int(time.time()), contract_id, target_id))
        await db.commit()
        return cur.rowcount == 1


async def create_diplomatic_pact(proposer_id: int, target_id: int, pact_type: str, terms: str, duration_days: int, timestamp: int | None = None):
    timestamp = int(timestamp or time.time())
    pact_type = (pact_type or "").strip().lower()
    terms = " ".join(str(terms or "").split())[:1000]
    if proposer_id == target_id or pact_type not in {"non_aggression", "defense", "trade"} or not terms or duration_days < 1 or duration_days > 30:
        return None
    async with _connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute("SELECT 1 FROM countries WHERE user_id IN (?, ?)", (proposer_id, target_id))
        if len(await cur.fetchall()) != 2:
            await db.rollback()
            return None
        cur = await db.execute(
            "SELECT 1 FROM diplomatic_pacts WHERE proposer_id = ? AND target_id = ? AND status IN ('pending', 'active')",
            (proposer_id, target_id),
        )
        if await cur.fetchone():
            await db.rollback()
            return None
        cur = await db.execute(
            "INSERT INTO diplomatic_pacts (proposer_id, target_id, pact_type, terms, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (proposer_id, target_id, pact_type, terms, timestamp, timestamp + duration_days * 86400),
        )
        await db.commit()
        return int(cur.lastrowid)


async def list_diplomatic_pacts(user_id: int, limit: int = 20):
    now = int(time.time())
    async with _connect() as db:
        await db.execute("UPDATE diplomatic_pacts SET status = 'expired', resolved_at = ? WHERE status IN ('pending', 'active') AND expires_at <= ?", (now, now))
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT p.*, a.name AS proposer_name, b.name AS target_name
               FROM diplomatic_pacts p
               LEFT JOIN countries a ON a.user_id = p.proposer_id
               LEFT JOIN countries b ON b.user_id = p.target_id
               WHERE p.proposer_id = ? OR p.target_id = ?
               ORDER BY p.id DESC LIMIT ?""",
            (user_id, user_id, limit),
        )
        return [dict(row) for row in await cur.fetchall()]


async def resolve_diplomatic_pact(pact_id: int, target_id: int, accept: bool, timestamp: int | None = None):
    timestamp = int(timestamp or time.time())
    async with _connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM diplomatic_pacts WHERE id = ? AND target_id = ? AND status = 'pending'", (pact_id, target_id))
        pact = await cur.fetchone()
        if not pact or pact["expires_at"] <= timestamp:
            await db.rollback()
            return None
        status = "active" if accept else "rejected"
        await db.execute("UPDATE diplomatic_pacts SET status = ?, resolved_at = ? WHERE id = ?", (status, timestamp, pact_id))
        await db.commit()
        return {**dict(pact), "status": status}


async def create_country_sanction(issuer_id: int, target_id: int, sanction_type: str, duration_days: int, reason: str, timestamp: int | None = None):
    timestamp = int(timestamp or time.time())
    reason = " ".join(str(reason or "").split())[:500]
    if issuer_id == target_id or sanction_type not in {"economic", "trade", "diplomatic"} or not reason or duration_days < 1 or duration_days > 30:
        return None
    async with _connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT 1 FROM countries WHERE user_id IN (?, ?)", (issuer_id, target_id))
        if len(await cur.fetchall()) != 2:
            await db.rollback()
            return None
        cur = await db.execute("SELECT COUNT(*) FROM country_sanctions WHERE issuer_id = ? AND status = 'active' AND expires_at > ?", (issuer_id, timestamp))
        if (await cur.fetchone())[0] >= 3:
            await db.rollback()
            return None
        cur = await db.execute("SELECT 1 FROM country_sanctions WHERE issuer_id = ? AND target_id = ? AND sanction_type = ? AND status = 'active' AND expires_at > ?", (issuer_id, target_id, sanction_type, timestamp))
        if await cur.fetchone():
            await db.rollback()
            return None
        cur = await db.execute("INSERT INTO country_sanctions (issuer_id, target_id, sanction_type, reason, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)", (issuer_id, target_id, sanction_type, reason, timestamp, timestamp + duration_days * 86400))
        await db.commit()
        return int(cur.lastrowid)


async def get_active_country_sanctions(target_id: int, timestamp: int | None = None):
    timestamp = int(timestamp or time.time())
    async with _connect() as db:
        await db.execute("UPDATE country_sanctions SET status = 'expired' WHERE status = 'active' AND expires_at <= ?", (timestamp,))
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT s.*, c.name AS issuer_name FROM country_sanctions s LEFT JOIN countries c ON c.user_id = s.issuer_id WHERE s.target_id = ? AND s.status = 'active' AND s.expires_at > ? ORDER BY s.id DESC", (target_id, timestamp))
        return [dict(row) for row in await cur.fetchall()]


async def list_country_sanctions(user_id: int, limit: int = 20):
    timestamp = int(time.time())
    async with _connect() as db:
        await db.execute("UPDATE country_sanctions SET status = 'expired' WHERE status = 'active' AND expires_at <= ?", (timestamp,))
        await db.commit()
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT s.*, a.name AS issuer_name, b.name AS target_name FROM country_sanctions s LEFT JOIN countries a ON a.user_id = s.issuer_id LEFT JOIN countries b ON b.user_id = s.target_id WHERE s.issuer_id = ? OR s.target_id = ? ORDER BY s.id DESC LIMIT ?", (user_id, user_id, limit))
        return [dict(row) for row in await cur.fetchall()]


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
        await db.execute("DELETE FROM pending_wars WHERE attacker_id = ? OR defender_id = ?", (user_id, user_id))
        await db.execute("DELETE FROM buildings WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM alliance_members WHERE user_id = ?", (user_id,))
        # A deleted player must not leave pending offers that can later be
        # accepted against a non-existent proposer or target.
        await db.execute(
            "UPDATE trade_contracts SET status = 'cancelled', resolved_at = ? "
            "WHERE status = 'pending' AND (proposer_id = ? OR target_id = ?)",
            (int(time.time()), user_id, user_id),
        )
        cur = await db.execute("DELETE FROM countries WHERE user_id = ?", (user_id,))
        await db.commit()
        return cur.rowcount > 0


async def transfer_country(old_user_id: int, new_user_id: int, new_chat_id: int | None = None, new_username: str | None = None) -> bool:
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
                "UPDATE countries SET user_id = ?, username = ?, chat_id = ? WHERE user_id = ?",
                (new_user_id, normalize_username(new_username), new_chat_id, old_user_id),
            )
        else:
            await db.execute(
                "UPDATE countries SET user_id = ?, username = ? WHERE user_id = ?",
                (new_user_id, normalize_username(new_username), old_user_id),
            )
        await db.execute("UPDATE buildings SET user_id = ? WHERE user_id = ?", (new_user_id, old_user_id))
        await db.execute("UPDATE events SET user_id = ? WHERE user_id = ?", (new_user_id, old_user_id))
        await db.execute(
            "UPDATE wars SET attacker_id = ? WHERE attacker_id = ?", (new_user_id, old_user_id)
        )
        await db.execute(
            "UPDATE wars SET defender_id = ? WHERE defender_id = ?", (new_user_id, old_user_id)
        )
        await db.execute(
            "UPDATE trade_contracts SET proposer_id = ? WHERE proposer_id = ?",
            (new_user_id, old_user_id),
        )
        await db.execute(
            "UPDATE trade_contracts SET target_id = ? WHERE target_id = ?",
            (new_user_id, old_user_id),
        )
        # Preserve the one-alliance-per-player invariant. If the recipient is
        # already in an alliance, discard the old membership rather than leave
        # an orphan row or silently retain the old Telegram user id.
        cur = await db.execute(
            "SELECT 1 FROM alliance_members WHERE user_id = ?", (new_user_id,)
        )
        if await cur.fetchone():
            await db.execute("DELETE FROM alliance_members WHERE user_id = ?", (old_user_id,))
        else:
            await db.execute(
                "UPDATE alliance_members SET user_id = ? WHERE user_id = ?",
                (new_user_id, old_user_id),
            )
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
    elapsed_years = (int(time.time()) - row["started_at"]) // max(1, int(SECONDS_PER_GAME_YEAR))
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


async def create_pending_war(attacker_id: int, attacker_name: str, defender_id: int, defender_name: str, attack_text: str, created_at: int, expires_at: int) -> int | None:
    async with _connect() as db:
        cur = await db.execute(
            "SELECT id FROM pending_wars WHERE attacker_id = ? AND status = 'pending'",
            (attacker_id,),
        )
        if await cur.fetchone():
            return None
        cur = await db.execute(
            "INSERT INTO pending_wars (attacker_id, attacker_name, defender_id, defender_name, attack_text, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (attacker_id, attacker_name, defender_id, defender_name, attack_text, created_at, expires_at),
        )
        await db.commit()
        return cur.lastrowid


async def get_pending_war(war_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM pending_wars WHERE id = ?", (war_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_pending_wars_for_attacker(attacker_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM pending_wars WHERE attacker_id = ? AND status IN ('pending', 'resolving') ORDER BY id DESC",
            (attacker_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def list_pending_wars_for_defender(defender_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM pending_wars WHERE defender_id = ? AND status = 'pending' ORDER BY id DESC",
            (defender_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def claim_pending_war(war_id: int, defender_id: int, defense_text: str, timestamp: int) -> bool:
    async with _connect() as db:
        cur = await db.execute(
            "UPDATE pending_wars SET status = 'resolving', defense_text = ? WHERE id = ? AND defender_id = ? AND status = 'pending'",
            (defense_text, war_id, defender_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def reset_pending_war(war_id: int) -> None:
    async with _connect() as db:
        await db.execute("UPDATE pending_wars SET status = 'pending', defense_text = NULL WHERE id = ? AND status = 'resolving'", (war_id,))
        await db.commit()


async def complete_pending_war(war_id: int) -> None:
    async with _connect() as db:
        await db.execute("UPDATE pending_wars SET status = 'resolved' WHERE id = ? AND status = 'resolving'", (war_id,))
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


async def get_war_history(user_id: int, limit: int = 20):
    """Return wars involving one country, newest first, without exposing hidden turn text."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT id, attacker_id, attacker_name, defender_id, defender_name,
                      outcome, verdict_text, created_at
               FROM wars
               WHERE attacker_id = ? OR defender_id = ?
               ORDER BY id DESC LIMIT ?""",
            (user_id, user_id, limit),
        )
        return [dict(row) for row in await cur.fetchall()]


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


async def create_alliance_invite(inviter_id: int, invitee_id: int, alliance_id: int, timestamp: int | None = None):
    """Create an invite only when the inviter leads the selected alliance."""
    if inviter_id == invitee_id:
        return None
    timestamp = int(timestamp or time.time())
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute("SELECT 1 FROM alliance_members WHERE user_id = ? AND alliance_id = ?", (inviter_id, alliance_id))
        if not await cur.fetchone():
            await db.rollback()
            return None
        cur = await db.execute("SELECT 1 FROM countries WHERE user_id = ?", (invitee_id,))
        if not await cur.fetchone():
            await db.rollback()
            return None
        cur = await db.execute("SELECT 1 FROM alliance_members WHERE user_id = ?", (invitee_id,))
        if await cur.fetchone():
            await db.rollback()
            return None
        cur = await db.execute(
            "SELECT id FROM alliance_invites WHERE alliance_id = ? AND invitee_id = ? AND status = 'pending'",
            (alliance_id, invitee_id),
        )
        if await cur.fetchone():
            await db.rollback()
            return None
        try:
            cur = await db.execute(
                "INSERT INTO alliance_invites (alliance_id, inviter_id, invitee_id, created_at) VALUES (?, ?, ?, ?)",
                (alliance_id, inviter_id, invitee_id, timestamp),
            )
        except aiosqlite.IntegrityError:
            await db.rollback()
            return None
        await db.commit()
        return int(cur.lastrowid)


async def list_alliance_invites(user_id: int):
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT i.id, i.alliance_id, i.inviter_id, i.created_at, a.tag, a.name,
                      c.name AS inviter_name
               FROM alliance_invites i
               JOIN alliances a ON a.id = i.alliance_id
               LEFT JOIN countries c ON c.user_id = i.inviter_id
               WHERE i.invitee_id = ? AND i.status = 'pending'
               ORDER BY i.id DESC""",
            (user_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def resolve_alliance_invite(invite_id: int, invitee_id: int, accept: bool, timestamp: int | None = None):
    timestamp = int(timestamp or time.time())
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute(
            """SELECT i.*, a.tag, a.name FROM alliance_invites i
               JOIN alliances a ON a.id = i.alliance_id
               WHERE i.id = ? AND i.invitee_id = ? AND i.status = 'pending'""",
            (invite_id, invitee_id),
        )
        invite = await cur.fetchone()
        if not invite:
            await db.rollback()
            return None
        if not accept:
            await db.execute("UPDATE alliance_invites SET status = 'rejected', resolved_at = ? WHERE id = ?", (timestamp, invite_id))
            await db.commit()
            return {"accepted": False, **dict(invite)}
        cur = await db.execute("SELECT 1 FROM alliance_members WHERE user_id = ?", (invitee_id,))
        if await cur.fetchone():
            await db.rollback()
            return None
        await db.execute(
            "INSERT INTO alliance_members (user_id, alliance_id, joined_at) VALUES (?, ?, ?)",
            (invitee_id, invite["alliance_id"], timestamp),
        )
        await db.execute(
            "UPDATE countries SET reputation = MIN(100, reputation + 2), stability = MIN(100, stability + 1) WHERE user_id = ?",
            (invitee_id,),
        )
        await db.execute("UPDATE alliance_invites SET status = 'accepted', resolved_at = ? WHERE id = ?", (timestamp, invite_id))
        await db.commit()
        return {"accepted": True, **dict(invite)}


# --- ЧВК и анонимные заказы ---

async def create_pmc(owner_id: int, name: str, org_type: str = "pmc", timestamp: int | None = None):
    name = " ".join(str(name or "").split())[:80]
    if not name or org_type not in {"pmc", "terror"}:
        return None
    timestamp = int(timestamp or time.time())
    async with _connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute("SELECT 1 FROM pmcs WHERE owner_id = ? AND status != 'disqualified'", (owner_id,))
        if await cur.fetchone():
            await conn.rollback()
            return None
        try:
            cur = await conn.execute(
                "INSERT INTO pmcs (owner_id, name, org_type, inventory_gold, created_at) VALUES (?, ?, ?, ?, ?)",
                (owner_id, name, org_type, PMC_STARTING_FUNDS, timestamp),
            )
        except aiosqlite.IntegrityError:
            await conn.rollback()
            return None
        await conn.commit()
        return int(cur.lastrowid)


async def get_pmc(pmc_id: int):
    async with _connect() as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM pmcs WHERE id = ?", (pmc_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_pmc_by_owner(owner_id: int):
    async with _connect() as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM pmcs WHERE owner_id = ? AND status != 'disqualified' ORDER BY id DESC LIMIT 1",
            (owner_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_active_pmcs(limit: int = 30):
    async with _connect() as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT * FROM pmcs WHERE status = 'active' ORDER BY reputation DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def create_pmc_request(pmc_id: int, country_id: int, request_text: str, timestamp: int | None = None):
    request_text = " ".join(str(request_text or "").split())[:1500]
    if not request_text:
        return None
    timestamp = int(timestamp or time.time())
    async with _connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute("SELECT id, status FROM pmcs WHERE id = ? AND status = 'active'", (pmc_id,))
        if not await cur.fetchone():
            await conn.rollback()
            return None
        cur = await conn.execute("SELECT 1 FROM countries WHERE user_id = ?", (country_id,))
        if not await cur.fetchone():
            await conn.rollback()
            return None
        cur = await conn.execute(
            "SELECT 1 FROM pmc_contracts WHERE pmc_id = ? AND country_id = ? AND status = 'active' LIMIT 1",
            (pmc_id, country_id),
        )
        if await cur.fetchone():
            await conn.rollback()
            return None
        cur = await conn.execute(
            "SELECT 1 FROM pmc_requests WHERE pmc_id = ? AND country_id = ? AND status = 'pending' LIMIT 1",
            (pmc_id, country_id),
        )
        if await cur.fetchone():
            await conn.rollback()
            return None
        cur = await conn.execute(
            "SELECT COUNT(DISTINCT pmc_id) FROM pmc_contracts WHERE country_id = ? AND status = 'active'",
            (country_id,),
        )
        if (await cur.fetchone())[0] >= 2:
            await conn.rollback()
            return None
        cur = await conn.execute(
            "INSERT INTO pmc_requests (pmc_id, country_id, request_text, created_at) VALUES (?, ?, ?, ?)",
            (pmc_id, country_id, request_text, timestamp),
        )
        await conn.commit()
        return int(cur.lastrowid)


async def list_pmc_requests(pmc_id: int, limit: int = 20):
    async with _connect() as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id, pmc_id, request_text, status, anonymous, created_at FROM pmc_requests WHERE pmc_id = ? AND status = 'pending' ORDER BY id DESC LIMIT ?",
            (pmc_id, limit),
        )
        return [dict(row) for row in await cur.fetchall()]


async def get_pmc_request(request_id: int):
    async with _connect() as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("SELECT * FROM pmc_requests WHERE id = ?", (request_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def resolve_pmc_request(request_id: int, pmc_owner_id: int, accept: bool, timestamp: int | None = None):
    timestamp = int(timestamp or time.time())
    async with _connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT r.*, p.owner_id, p.status AS pmc_status FROM pmc_requests r JOIN pmcs p ON p.id = r.pmc_id WHERE r.id = ? AND r.status = 'pending'",
            (request_id,),
        )
        request = await cur.fetchone()
        if not request or request["owner_id"] != pmc_owner_id or request["pmc_status"] != "active":
            await conn.rollback()
            return None
        if not accept:
            await conn.execute("UPDATE pmc_requests SET status = 'rejected', resolved_at = ?, resolved_by = ? WHERE id = ?", (timestamp, pmc_owner_id, request_id))
            await conn.commit()
            return {"accepted": False, **dict(request)}
        cur = await conn.execute("SELECT 1 FROM pmc_contracts WHERE pmc_id = ? AND country_id = ? AND status = 'active' LIMIT 1", (request["pmc_id"], request["country_id"]))
        if await cur.fetchone():
            await conn.rollback()
            return None
        cur = await conn.execute("SELECT COUNT(DISTINCT pmc_id) FROM pmc_contracts WHERE country_id = ? AND status = 'active'", (request["country_id"],))
        if (await cur.fetchone())[0] >= 2:
            await conn.rollback()
            return None
        await conn.execute("UPDATE pmc_requests SET status = 'accepted', resolved_at = ?, resolved_by = ? WHERE id = ?", (timestamp, pmc_owner_id, request_id))
        cur = await conn.execute(
            "INSERT INTO pmc_contracts (pmc_id, country_id, request_id, created_at) VALUES (?, ?, ?, ?)",
            (request["pmc_id"], request["country_id"], request_id, timestamp),
        )
        await conn.commit()
        return {"accepted": True, "contract_id": int(cur.lastrowid), **dict(request)}


async def recruit_pmc(pmc_id: int, owner_id: int, amount: int, timestamp: int | None = None):
    from config import PMC_MAX_BATCH_RECRUIT, PMC_MAX_PERSONNEL, PMC_RECRUIT_COOLDOWN_SECONDS, PMC_RECRUIT_COST_PER_PERSON
    timestamp = int(timestamp or time.time())
    if amount <= 0 or amount > PMC_MAX_BATCH_RECRUIT:
        return False, "batch_limit"
    async with _connect() as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute("SELECT * FROM pmcs WHERE id = ? AND owner_id = ? AND status = 'active'", (pmc_id, owner_id))
        pmc = await cur.fetchone()
        if not pmc:
            await conn.rollback()
            return False, "not_owner"
        if pmc["last_recruit_at"] and timestamp - pmc["last_recruit_at"] < PMC_RECRUIT_COOLDOWN_SECONDS:
            await conn.rollback()
            return False, "cooldown"
        if pmc["personnel"] + amount > PMC_MAX_PERSONNEL:
            await conn.rollback()
            return False, "personnel_limit"
        cost = amount * PMC_RECRUIT_COST_PER_PERSON
        if pmc["inventory_gold"] < cost:
            await conn.rollback()
            return False, "funds"
        await conn.execute(
            "UPDATE pmcs SET personnel = personnel + ?, inventory_gold = inventory_gold - ?, last_recruit_at = ? WHERE id = ?",
            (amount, cost, timestamp, pmc_id),
        )
        await conn.commit()
        return True, cost


async def sanction_pmc(pmc_id: int, sanction_type: str, reason: str, actor_id: int, timestamp: int | None = None):
    timestamp = int(timestamp or time.time())
    allowed = {"warn", "inventory_clear", "suspend", "disqualify"}
    if sanction_type not in allowed or not reason.strip():
        return False
    async with _connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute("SELECT id FROM pmcs WHERE id = ?", (pmc_id,))
        if not await cur.fetchone():
            await conn.rollback()
            return False
        if sanction_type == "inventory_clear":
            await conn.execute("UPDATE pmcs SET personnel = 0, equipment = 0, inventory_gold = 0, reputation = MAX(0, reputation - 20) WHERE id = ?", (pmc_id,))
        elif sanction_type == "suspend":
            await conn.execute("UPDATE pmcs SET status = 'suspended', reputation = MAX(0, reputation - 15) WHERE id = ?", (pmc_id,))
        elif sanction_type == "disqualify":
            await conn.execute("UPDATE pmcs SET status = 'disqualified', personnel = 0, equipment = 0, inventory_gold = 0, reputation = 0 WHERE id = ?", (pmc_id,))
            await conn.execute("UPDATE pmc_contracts SET status = 'disqualified', resolved_at = ? WHERE pmc_id = ? AND status = 'active'", (timestamp, pmc_id))
        else:
            await conn.execute("UPDATE pmcs SET reputation = MAX(0, reputation - 5) WHERE id = ?", (pmc_id,))
        await conn.execute("INSERT INTO pmc_sanctions (pmc_id, sanction_type, reason, actor_id, created_at) VALUES (?, ?, ?, ?, ?)", (pmc_id, sanction_type, reason[:500], actor_id, timestamp))
        await conn.commit()
        return True


async def collect_pmc_income(pmc_id: int, owner_id: int, timestamp: int | None = None):
    from config import PMC_BASE_INCOME, PMC_COLLECT_COOLDOWN_SECONDS, PMC_INCOME_PER_1000_PERSONNEL
    timestamp = int(timestamp or time.time())
    async with _connect() as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute(
            "SELECT personnel, last_collect_at FROM pmcs WHERE id = ? AND owner_id = ? AND status = 'active'",
            (pmc_id, owner_id),
        )
        pmc = await cur.fetchone()
        if not pmc:
            await conn.rollback()
            return False, "not_owner"
        last_collect_at = int(pmc["last_collect_at"] or 0)
        remaining = PMC_COLLECT_COOLDOWN_SECONDS - (timestamp - last_collect_at) if last_collect_at else 0
        if remaining > 0:
            await conn.rollback()
            return False, ("cooldown", remaining)
        income = PMC_BASE_INCOME + (int(pmc["personnel"]) // 1000) * PMC_INCOME_PER_1000_PERSONNEL
        await conn.execute(
            "UPDATE pmcs SET inventory_gold = inventory_gold + ?, last_collect_at = ? WHERE id = ? AND owner_id = ? AND status = 'active'",
            (income, timestamp, pmc_id, owner_id),
        )
        await conn.commit()
        return True, income


async def fund_pmc(pmc_id: int, owner_id: int, amount: int, timestamp: int | None = None) -> bool:
    """Move ordinary country money into the owner's PMC inventory atomically."""
    if amount <= 0:
        return False
    timestamp = int(timestamp or time.time())
    async with _connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute("SELECT owner_id, status FROM pmcs WHERE id = ?", (pmc_id,))
        pmc = await cur.fetchone()
        if not pmc or pmc[0] != owner_id or pmc[1] != "active":
            await conn.rollback()
            return False
        cur = await conn.execute("UPDATE countries SET gold = gold - ? WHERE user_id = ? AND gold >= ?", (amount, owner_id, amount))
        if cur.rowcount != 1:
            await conn.rollback()
            return False
        await conn.execute("UPDATE pmcs SET inventory_gold = inventory_gold + ? WHERE id = ?", (amount, pmc_id))
        await conn.commit()
        return True
