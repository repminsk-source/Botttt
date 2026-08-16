import asyncio
import html
import logging
import os
import random
import time

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    ErrorEvent,
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
import db
import ai
import countries
import territory
import market
import world_data
from anti_spam import AntiSpamMiddleware

# Объединённый список построек: старые (BUILDINGS) + новые сырьевые (RESOURCE_BUILDINGS).
# Собран в один словарь, чтобы /build, /collect и format_country работали с обоими
# наборами построек одинаковым общим кодом, не дублируя логику.
ALL_BUILDINGS = {**config.BUILDINGS, **config.RESOURCE_BUILDINGS}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gavan")

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
spam_guard = AntiSpamMiddleware()

# One active interface card per player and forum topic. The player is part of
# the key because a group can contain many independent game sessions.
_ACTIVE_INTERFACE_MESSAGES: dict[tuple[int, int, int], int] = {}
_INTERFACE_DELETE_TASKS: dict[tuple[int, int], asyncio.Task] = {}


async def _delete_interface_message_later(chat_id: int, message_id: int) -> None:
    """Delete one bot card after the configured delay, without blocking handlers."""
    key = (chat_id, message_id)
    try:
        delay = config.INTERFACE_MESSAGE_DELETE_SECONDS
        if delay > 0:
            await asyncio.sleep(delay)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
                # The card may already have been deleted manually or by a
                # concurrent cleanup task; this must never affect gameplay.
                logger.debug("Delayed interface deletion skipped for %s: %s", message_id, exc)
    except asyncio.CancelledError:
        raise
    finally:
        _INTERFACE_DELETE_TASKS.pop(key, None)
        for interface_key, active_id in list(_ACTIVE_INTERFACE_MESSAGES.items()):
            if active_id == message_id and interface_key[0] == chat_id:
                _ACTIVE_INTERFACE_MESSAGES.pop(interface_key, None)


def _schedule_interface_deletion(chat_id: int, message_id: int) -> None:
    """Schedule one deletion at most once; zero disables automatic cleanup."""
    if config.INTERFACE_MESSAGE_DELETE_SECONDS <= 0:
        return
    key = (chat_id, message_id)
    existing = _INTERFACE_DELETE_TASKS.get(key)
    if existing and not existing.done():
        return
    _INTERFACE_DELETE_TASKS[key] = asyncio.create_task(
        _delete_interface_message_later(chat_id, message_id)
    )

dp.message.middleware(spam_guard)
dp.callback_query.middleware(spam_guard)


def esc(text) -> str:
    """
    Экранирует текст перед вставкой в HTML-сообщение.
    Используется для ЛЮБОГО текста, пришедшего от игрока (название страны, действие)
    или от ИИ (вердикт) — иначе символы <, >, & ломают HTML-разметку Telegram,
    и message.answer/edit_text падает с ошибкой "can't parse entities".
    """
    return html.escape(str(text), quote=False)


def command_payload(message: Message) -> str:
    """Return arguments after /command or /command@bot in private and group chats."""
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def _interface_key(message: Message, owner_id: int | None = None) -> tuple[int, int, int]:
    """Return the storage key for one player's active card in one chat/topic."""
    return (
        message.chat.id,
        int(owner_id if owner_id is not None else message.from_user.id),
        int(message.message_thread_id or 0),
    )


async def hide_group_command(message: Message) -> None:
    """Remove secret command text from group chats when Telegram permits it."""
    if getattr(message.chat, "type", "private") not in ("group", "supergroup"):
        return
    try:
        await message.delete()
    except Exception:
        logger.info("Не удалось скрыть секретную команду в группе", exc_info=True)


async def answer_topic_safe(
    message: Message,
    text: str,
    reply_markup=None,
    owner_id: int | None = None,
):
    """Send a new active card and remove this player's previous one when possible."""
    try:
        sent = await message.answer(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "TOPIC_CLOSED" not in str(exc):
            raise
        sent = await bot.send_message(
            chat_id=message.chat.id,
            text="⚠️ Эта тема закрыта. Ответ отправлен в общую тему группы. Открой тему или продолжи там.\n\n" + text,
            reply_markup=reply_markup,
        )
    key = _interface_key(message, owner_id)
    _ACTIVE_INTERFACE_MESSAGES[key] = sent.message_id
    # Do not remove the previous card synchronously. Every card gets its own
    # readable lifetime, so action results cannot disappear immediately.
    _schedule_interface_deletion(message.chat.id, sent.message_id)
    return sent


STAT_NAMES_RU = {
    "economy": "Экономика",
    "military": "Армия",
    "population": "Население",
    "tech": "Технологии",
    "diplomacy": "Дипломатия",
}

RESOURCE_NAMES_RU = {
    "gold": "💵 Деньги",
    "resources": "📦 Ресурсы",
    "manpower": "🧑‍🤝‍🧑 Резерв людей",
    "water": "💧 Вода",
    "food": "🌽 Еда",
    **config.RESOURCE_NAMES_RU_EXTRA,
}

# --- Блокировки на пользователя ---
# Защищают от гонки при двойном/быстром повторном нажатии одной и той же команды
# (например /action или /collect отправлены дважды подряд до того, как первый
# вызов успел обновить БД) — без этого можно было обойти кулдаун и получить
# ресурсы/вердикты несколько раз за один интервал.
_user_locks: dict[int, asyncio.Lock] = {}
_ai_inflight: set[int] = set()


def get_user_lock(user_id: int) -> asyncio.Lock:
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[user_id] = lock
    return lock


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Страна"), KeyboardButton(text="📥 Сбор")],
        [KeyboardButton(text="🏗️ Строить"), KeyboardButton(text="⚔️ Армия")],
        [KeyboardButton(text="📈 Прогресс"), KeyboardButton(text="☰ Ещё")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Выберите раздел",
)

MORE_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📰 Новости"), KeyboardButton(text="🌍 Рейтинг")],
        [KeyboardButton(text="🏛️ Политика"), KeyboardButton(text="🤝 Дипломатия")],
        [KeyboardButton(text="🏴 ЧВК"), KeyboardButton(text="📖 Помощь")],
        [KeyboardButton(text="⬅️ Назад")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Выберите раздел",
)

# Inline buttons are the reliable interface in groups: unlike reply-keyboard
# text, callback queries are delivered even when Telegram Privacy Mode is on.
MAIN_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📊 Страна", callback_data="ui:country"), InlineKeyboardButton(text="📥 Сбор", callback_data="ui:collect")],
    [InlineKeyboardButton(text="🏗️ Строить", callback_data="ui:build"), InlineKeyboardButton(text="⚔️ Армия", callback_data="ui:army")],
    [InlineKeyboardButton(text="📈 Прогресс", callback_data="ui:progress"), InlineKeyboardButton(text="☰ Ещё", callback_data="ui:more")],
])

MORE_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📰 Мои новости", callback_data="ui:news"), InlineKeyboardButton(text="🌎 Мир", callback_data="ui:world")],
    [InlineKeyboardButton(text="📜 Торговля", callback_data="ui:trade"), InlineKeyboardButton(text="🌍 Рейтинг", callback_data="ui:top")],
    [InlineKeyboardButton(text="🏛️ Политика", callback_data="ui:policy"), InlineKeyboardButton(text="🤝 Дипломатия", callback_data="ui:diplomacy")],
    [InlineKeyboardButton(text="🏴 ЧВК", callback_data="ui:pmc"), InlineKeyboardButton(text="💎 Магазин", callback_data="ui:premium")],
    [InlineKeyboardButton(text="📖 Помощь", callback_data="ui:guide")],
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="ui:back")],
])

PREMIUM_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⚡ Буст удачи", callback_data="premium:buy:luck_boost")],
    [InlineKeyboardButton(text="🗺️ Территория", callback_data="premium:buy:territory_expansion")],
    [InlineKeyboardButton(text="🛡️ Защита от вайпа", callback_data="premium:buy:wipe_protection")],
    [InlineKeyboardButton(text="🏅 Премиальный статус", callback_data="premium:buy:premium_status")],
    [InlineKeyboardButton(text="⬅️ Ещё", callback_data="ui:more")],
])

BUILD_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🌾 Ферма", callback_data="build:farm"), InlineKeyboardButton(text="⛏️ Шахта", callback_data="build:mine")],
    [InlineKeyboardButton(text="🏪 Рынок", callback_data="build:market"), InlineKeyboardButton(text="💧 Колодец", callback_data="build:well")],
    [InlineKeyboardButton(text="🌽 Амбар", callback_data="build:granary"), InlineKeyboardButton(text="🌲 Лесопилка", callback_data="build:sawmill")],
    [InlineKeyboardButton(text="⛓️ Железо", callback_data="build:iron_mine"), InlineKeyboardButton(text="🪨 Уголь", callback_data="build:coal_mine")],
    [InlineKeyboardButton(text="🛢️ Нефть", callback_data="build:oil_rig"), InlineKeyboardButton(text="☢️ Уран", callback_data="build:uranium_mine")],
    [InlineKeyboardButton(text="🪖 Военная база", callback_data="build:base")],
    [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="ui:back")],
])

COUNTRY_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📊 Сводка", callback_data="ui:country"), InlineKeyboardButton(text="💼 Экономика", callback_data="ui:economy")],
    [InlineKeyboardButton(text="⚔️ Армия", callback_data="ui:army"), InlineKeyboardButton(text="📈 Прогресс", callback_data="ui:progress")],
    [InlineKeyboardButton(text="🏗️ Строить", callback_data="ui:build"), InlineKeyboardButton(text="🏴 ЧВК", callback_data="ui:pmc")],
    [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="ui:back")],
])

ECONOMY_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📥 Собрать ресурсы", callback_data="eco:collect")],
    [InlineKeyboardButton(text="🏗️ Строить", callback_data="ui:build"), InlineKeyboardButton(text="🛒 Рынок", callback_data="eco:market")],
    [InlineKeyboardButton(text="📊 Сводка", callback_data="ui:country"), InlineKeyboardButton(text="⬅️ Главное меню", callback_data="ui:back")],
])

ARMY_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⚔️ Мобилизовать 1", callback_data="army:mobilize:1")],
    [InlineKeyboardButton(text="🪖 Построить базу", callback_data="army:base")],
    [InlineKeyboardButton(text="📊 Сводка", callback_data="ui:country"), InlineKeyboardButton(text="💼 Экономика", callback_data="ui:economy")],
    [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="ui:back")],
])

PROGRESS_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📥 Собрать", callback_data="ui:collect"), InlineKeyboardButton(text="🏗️ Строить", callback_data="ui:build")],
    [InlineKeyboardButton(text="📊 Сводка", callback_data="ui:country"), InlineKeyboardButton(text="⬅️ Главное меню", callback_data="ui:back")],
])

PMC_INLINE = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📊 Профиль", callback_data="pmc:profile"), InlineKeyboardButton(text="📨 Заказы", callback_data="pmc:requests")],
    [InlineKeyboardButton(text="👥 Набор", callback_data="pmc:recruit"), InlineKeyboardButton(text="💰 Бюджет", callback_data="pmc:fund")],
    [InlineKeyboardButton(text="⚔️ Операция", callback_data="pmc:action"), InlineKeyboardButton(text="📰 Новости", callback_data="pmc:news")],
    [InlineKeyboardButton(text="🌐 Организации", callback_data="pmc:list"), InlineKeyboardButton(text="📖 Правила", callback_data="pmc:help")],
        [InlineKeyboardButton(text="🌍 Страна", callback_data="mode:country"), InlineKeyboardButton(text="⬅️ Разделы", callback_data="ui:more")],
])
def callback_message(callback: CallbackQuery, text: str) -> Message:
    """Route a callback action under the clicker's identity, never the card author."""
    return callback.message.model_copy(update={"from_user": callback.from_user, "text": text})


async def finish_callback(callback: CallbackQuery, command: str, handler, markup=MAIN_INLINE):
    """Run a callback command without overwriting its freshly rendered card."""
    await callback.answer()
    owner_id = callback.from_user.id
    key = _interface_key(callback.message, owner_id)
    previous_id = _ACTIVE_INTERFACE_MESSAGES.get(key)
    await handler(callback_message(callback, command))
    current_id = _ACTIVE_INTERFACE_MESSAGES.get(key)
    # Most command handlers now render their own final card. Only append a
    # fallback menu when a handler produced no interface message at all.
    if markup is not None and current_id == previous_id:
        await answer_topic_safe(
            callback.message,
            "Меню разделов:",
            reply_markup=markup,
            owner_id=owner_id,
        )


def progression_snapshot(country: dict, buildings: dict | None = None) -> dict:
    buildings = buildings or {}
    stats_score = sum(int(country.get(stat, 0)) for stat in STAT_NAMES_RU)
    building_levels = sum(max(0, int(level)) for level in buildings.values())
    score = stats_score + building_levels * config.PROGRESS_BUILDING_POINTS
    current_stage = config.PROGRESS_STAGES[0]
    next_stage = None
    for stage in config.PROGRESS_STAGES:
        if score >= stage[0]:
            current_stage = stage
        elif next_stage is None:
            next_stage = stage
    return {
        "score": score,
        "stats_score": stats_score,
        "building_levels": building_levels,
        "stage": current_stage,
        "next_stage": next_stage,
    }


COOLDOWN_FIELDS = {
    "build": "last_build_at",
    "upgrade": "last_upgrade_at",
    "mobilize": "last_mobilize_at",
    "buy": "last_buy_at",
    "base": "last_base_at",
    "collect": "last_collect_at",
    "action": "last_action_at",
    "attack": "last_attack_at",
    "spy": "last_spy_at",
}


def cooldown_remaining(country: dict, action: str, seconds: int, now: int | None = None) -> int:
    if seconds <= 0:
        return 0
    now = int(time.time()) if now is None else now
    field = COOLDOWN_FIELDS[action]
    return max(0, seconds - (now - int(country.get(field, 0) or 0)))


def cooldown_text(label: str, remaining: int) -> str:
    hours, rest = divmod(max(0, remaining), 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"⏳ {label}: ещё {hours} ч {minutes} мин."
    return f"⏳ {label}: ещё {minutes} мин {seconds} сек."


def format_duration(seconds: int) -> str:
    """Format a remaining cooldown consistently in compact Russian text."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours} ч {minutes} мин {seconds} сек"
    if minutes:
        return f"{minutes} мин {seconds} сек"
    return f"{seconds} сек"


def energy_balance(buildings: dict | None = None, population: int = 0) -> tuple[int, int]:
    buildings = buildings or {}
    supply = 0
    demand = max(0, int(population) // 100)
    for b_type, level in buildings.items():
        info = ALL_BUILDINGS.get(b_type)
        if not info or int(level) <= 0:
            continue
        if info["produces"] == "energy":
            supply += int(level) * info["amount_per_level"]
        elif info["produces"] in {"resources", "wood", "iron", "coal", "oil", "uranium"}:
            demand += int(level) * 100
    return supply, demand


def economic_level_name(economy: int) -> str:
    current = config.ECONOMIC_LEVELS[0][1]
    for threshold, label in config.ECONOMIC_LEVELS:
        if economy >= threshold:
            current = label
    return current


def production_preview(buildings: dict | None = None) -> dict:
    gains = {info["produces"]: 0 for info in ALL_BUILDINGS.values()}
    for b_type, level in (buildings or {}).items():
        info = ALL_BUILDINGS.get(b_type)
        if info and int(level) > 0:
            gains[info["produces"]] += int(level) * info["amount_per_level"]
    return {key: value for key, value in gains.items() if value > 0}


def next_step_hint(country: dict, buildings: dict | None = None) -> str:
    buildings = buildings or {}
    progress = progression_snapshot(country, buildings)
    if not buildings.get("farm"):
        return "🎯 Следующий шаг: этап 1 — построй ферму <code>/build farm</code>, затем выполни <code>/collect</code>."
    if not buildings.get("mine"):
        return "🎯 Следующий шаг: этап 2 — построй шахту <code>/build mine</code>, чтобы получать базовое сырьё."
    if not buildings.get("market"):
        return "🎯 Следующий шаг: этап 3 — построй рынок <code>/build market</code>, чтобы получать деньги."
    if not buildings.get("granary"):
        return "🎯 Следующий шаг: этап 4 — построй амбар <code>/build granary</code>, чтобы накапливать еду и растить население."
    population_required = config.MOBILIZE_POPULATION_PER_POINT
    if country["population"] < population_required:
        return (
            f"🎯 Следующий шаг: развивай население через фермы, амбар и <code>/collect</code>. "
            f"Для первой единицы армии нужно {population_required:,} населения; сейчас {country['population']:,}."
        )
    if country["manpower"] < config.MOBILIZE_MANPOWER_PER_POINT or country["gold"] < config.MOBILIZE_GOLD_PER_POINT:
        return "🎯 Следующий шаг: выполни <code>/collect</code>, чтобы накопить резерв людей и деньги для первой мобилизации."
    base_capacity = country["military_bases"] * config.MILITARY_PER_BASE
    if country["military"] < base_capacity:
        return "🎯 Следующий шаг: мобилизуй армию <code>/mobilize 1</code> — база ещё не заполнена."
    if progress["next_stage"]:
        target, title, _ = progress["next_stage"]
        return f"🎯 Следующий шаг: накопи ресурсы и очки до этапа «{title}» — осталось {max(0, target - progress['score'])} очков. После заполнения базы строй следующую через <code>/build_base</code>."
    return "🎯 Следующий шаг: построй следующую военную базу <code>/build_base</code>, развивай дипломатию и используй <code>/action</code>."


def real_population_millions(country: dict) -> int | None:
    """Return the country's factual population scale in millions, if available."""
    value = country.get("real_population")
    if value is None:
        return None
    try:
        return max(1, round(float(value) / 1_000_000))
    except (TypeError, ValueError):
        return None


def clamp_country_changes(country: dict, changes: dict) -> dict:
    """Clamp AI deltas at zero and cap only military by the country's factual population."""
    result = {}
    for stat in STAT_NAMES_RU:
        try:
            delta = int((changes or {}).get(stat, 0) or 0)
        except (TypeError, ValueError):
            delta = 0
        new_value = max(0, country[stat] + delta)
        if stat == "military":
            population_cap = real_population_millions(country)
            if population_cap is not None:
                new_value = min(population_cap, new_value)
        result[stat] = new_value - country[stat]
    return result


async def animate(message: Message, frames: list[str], delay: float = 0.25):
    sent = await message.answer(frames[0])
    for frame in frames[1:]:
        await asyncio.sleep(delay)
        try:
            await sent.edit_text(frame)
        except TelegramBadRequest:
            break
    # Treat the finished animation as the player's active interface card. The
    # next safe response will replace it just like any other menu.
    _ACTIVE_INTERFACE_MESSAGES[_interface_key(message)] = sent.message_id
    return sent


async def format_country(c: dict) -> str:
    buildings = await db.get_buildings(c["user_id"])
    tier = c.get("territory_tier", "medium")
    factual_cap = int(c["real_population"] * config.MAX_ARMY_POPULATION_SHARE / config.MILITARY_UNIT_SIZE) if c.get("real_population") else None
    base_capacity = c["military_bases"] * config.MILITARY_PER_BASE
    military_cap = min(base_capacity, factual_cap) if factual_cap is not None else base_capacity
    base_cap = max(1, config.TERRITORY_BASE_BONUS.get(tier, 0) + c["military"] // config.MILITARY_PER_BASE)
    alliance = await db.get_user_alliance(c["user_id"])

    text = (
        f"🏳️ <b>{esc(c['name'])}</b> ({territory.TIER_LABEL_RU.get(tier, tier)})\n"
    )
    if alliance:
        text += f"🤝 Альянс: <b>{esc(alliance['tag'])}</b> — {esc(alliance['name'])}\n"
    real_profile = {
        "population": c.get("real_population"),
        "gdp_usd": c.get("real_gdp_usd"),
        "gdp_per_capita_usd": c.get("real_gdp_per_capita_usd"),
        "life_expectancy": c.get("real_life_expectancy"),
        "selected_year": c.get("data_year"),
    }
    if real_profile["population"] is None and real_profile["gdp_usd"] is None:
        real_profile = world_data.get_profile(c["name"], config.START_DATA_YEAR) or real_profile
    if real_profile.get("population") is not None or real_profile.get("gdp_usd") is not None:
        text += (
            f"\n<b>📚 Реальные данные World Bank ({real_profile.get('selected_year') or 'нет года'}):</b>\n"
            f"👥 Население: {world_data.format_population(real_profile.get('population'))}\n"
            f"💵 ВВП: {world_data.format_money(real_profile.get('gdp_usd'))}\n"
            f"📊 ВВП на душу: {world_data.format_money(real_profile.get('gdp_per_capita_usd'))}\n"
            f"❤️ Ожидаемая продолжительность жизни: {world_data.format_life_expectancy(real_profile.get('life_expectancy'))}\n"
            "Это фактический исторический профиль. Игровые ресурсы и таймеры ниже — отдельная стратегия.\n"
        )
    army_limit_text = (
        f" / {military_cap} внутренних единиц ({military_cap * config.MILITARY_UNIT_SIZE:,} военнослужащих)\n"
        if military_cap is not None
        else " (лимит по базам и World Bank не найден)\n"
    )
    text += (
        f"\n<b>Игровые характеристики:</b>\n"
        f"💰 Экономика: {c['economy']}\n"
        f"⚔️ Армия: {c['military']}{army_limit_text}"
        f"👥 Игровое население: {c['population']:,} единиц (без искусственного лимита)\n"
        f"🔬 Технологии: {c['tech']}\n"
        f"🤝 Дипломатия: {c['diplomacy']}\n"
        f"🏛️ Национальный курс: {config.POLICY_DEFINITIONS.get(c.get('policy', 'development'), config.POLICY_DEFINITIONS['development'])['name']}\n"
        f"⚙️ Приоритет производства: { {'civilian': 'гражданский', 'balanced': 'сбалансированный', 'military': 'военный'}.get(c.get('labor_focus', 'balanced'), 'сбалансированный') }\n"
        f"💹 Экономический уровень: {economic_level_name(c['economy'])} · налог: {c.get('tax_rate', config.TAX_RATE_DEFAULT)}%\n"
        f"🛡️ Стабильность: {c['stability']} / 100\n"
        f"🚨 Готовность армии: {c['readiness']} / 100\n"
        f"📉 Военная усталость: {c['war_exhaustion']} / 100\n"
        f"🌐 Репутация: {c['reputation']} / 100\n\n"
        f"<b>Ресурсы:</b>\n"
        f"💰 Деньги: {c['gold']}\n"
        f"📦 Ресурсы: {c['resources']}\n"
        f"🧑‍🤝‍🧑 Резерв людей: {c['manpower']}\n"
        f"💧 Вода: {c['water']}\n"
        f"🌽 Еда: {c['food']}\n"
        f"🌲 Дерево: {c['wood']}\n"
        f"⛓️ Железо: {c['iron']}\n"
        f"🪨 Уголь: {c['coal']}\n"
        f"🛢️ Нефть: {c['oil']}\n"
        f"☢️ Уран: {c['uranium']}\n"
        f"⭐ Очки развития: {c['points']}\n\n"
        f"🪖 Военные базы: {c['military_bases']} / {base_cap}\n\n"
        f"<b>Постройки:</b>\n"
    )
    if not buildings:
        text += "пока ничего не построено — см. /build\n"
    else:
        for b_type, level in buildings.items():
            info = ALL_BUILDINGS.get(b_type)
            if not info:
                continue
            text += f"{info['emoji']} {info['name']}: ур. {level}\n"
    progress = progression_snapshot(c, buildings)
    _, stage_name, stage_goal = progress["stage"]
    text += (
        f"\n<b>📈 Развитие страны</b>\n"
        f"Этап: <b>{esc(stage_name)}</b>\n"
        f"Игровой счёт развития: <b>{progress['score']}</b> "
        f"(характеристики {progress['stats_score']} + постройки {progress['building_levels']}×{config.PROGRESS_BUILDING_POINTS})\n"
        f"Смысл этапа: {esc(stage_goal)}\n"
        f"🛡️ Стабильность: {c['stability']}/100 · 🚨 Готовность: {c['readiness']}/100\n"
        f"📉 Военная усталость: {c['war_exhaustion']}/100 · 🌐 Репутация: {c['reputation']}/100\n"
    )
    if not c.get("last_collect_at", 0):
        text += "🎁 Следующая ключевая цель: первый сбор даст одноразовый бонус +14 000 000 денег.\n"

    if progress["next_stage"]:
        target, next_name, _ = progress["next_stage"]
        text += f"До этапа «{esc(next_name)}»: ещё <b>{target - progress['score']}</b> очков.\n"
    else:
        text += "Достигнут максимальный этап текущей шкалы.\n"
    timer_specs = [
        ("collect", config.COLLECT_COOLDOWN_SECONDS, "Сбор ресурсов"),
        ("build", config.BUILD_COOLDOWN_SECONDS, "Строительство"),
        ("upgrade", config.UPGRADE_COOLDOWN_SECONDS, "Улучшение"),
        ("mobilize", config.MOBILIZE_COOLDOWN_SECONDS, "Мобилизация"),
        ("action", config.ACTION_COOLDOWN_SECONDS, "Политическое действие"),
        ("attack", config.ATTACK_COOLDOWN_SECONDS, "Атака"),
        ("buy", config.BUY_COOLDOWN_SECONDS, "Покупка сырья"),
        ("base", config.BASE_COOLDOWN_SECONDS, "Военная база"),
        ("spy", config.SPY_COOLDOWN_SECONDS, "Разведка"),
    ]
    active_timers = [
        cooldown_text(label, cooldown_remaining(c, action, seconds))
        for action, seconds, label in timer_specs
        if cooldown_remaining(c, action, seconds)
    ]
    if active_timers:
        text += "\n<b>⏱️ Активные ограничения:</b>\n" + "\n".join(active_timers) + "\n"
    preview = production_preview(buildings)
    if preview:
        text += "\n<b>Доход за один доступный /collect:</b>\n"
        for resource, amount in preview.items():
            text += f"{RESOURCE_NAMES_RU.get(resource, resource)}: +{amount}\n"
    else:
        text += "\n<b>Доход:</b> пока 0 — сначала построй производство.\n"
    text += "\n" + next_step_hint(c, buildings)
    return text


async def format_country_summary(c: dict) -> str:
    buildings = await db.get_buildings(c["user_id"])
    progress = progression_snapshot(c, buildings)
    stage_name = progress["stage"][1]
    next_step = next_step_hint(c, buildings)
    alliance = await db.get_user_alliance(c["user_id"])
    alliance_line = f" · 🤝 {esc(alliance['tag'])}" if alliance else ""
    premium_items = await db.get_premium_items(c["user_id"])
    premium_line = ""
    if premium_items.get("premium_status", 0):
        premium_line += "\n🏅 Премиальный статус активен"
    if premium_items.get("wipe_protection", 0):
        premium_line += f"\n🛡️ Заряды защиты от вайпа: {premium_items['wipe_protection']}"
    return (
        f"🏳️ <b>{esc(c['name'])}</b>{alliance_line}{premium_line}\n"
        f"Этап: <b>{esc(stage_name)}</b> · очки: <b>{progress['score']}</b>\n\n"
        f"💰 <b>{c['gold']:,}</b> денег  ·  📦 <b>{c['resources']:,}</b> ресурсов\n"
        f"👥 <b>{c['population']:,}</b> населения  ·  ⚔️ <b>{c['military']:,}</b> армии\n"
        f"🛡️ Стабильность: <b>{c['stability']}/100</b>  ·  🌐 Репутация: <b>{c['reputation']}/100</b>\n\n"
        f"<b>Следующий шаг</b>\n{next_step}"
    )


async def format_country_economy(c: dict) -> str:
    buildings = await db.get_buildings(c["user_id"])
    preview = production_preview(buildings)
    produced = ", ".join(f"{RESOURCE_NAMES_RU.get(k, k)} +{v:,}" for k, v in preview.items()) if preview else "пока нет"
    return (
        f"💼 <b>Экономика {esc(c['name'])}</b>\n\n"
        f"💰 Деньги: <b>{c['gold']:,}</b>\n"
        f"📦 Основные ресурсы: <b>{c['resources']:,}</b>\n"
        f"🌲 Дерево: <b>{c['wood']:,}</b> · 🌽 Еда: <b>{c['food']:,}</b>\n"
        f"⛓️ Железо: <b>{c['iron']:,}</b> · 💧 Вода: <b>{c['water']:,}</b>\n\n"
        f"🏗️ Уровни построек: <b>{sum(max(0, int(v)) for v in buildings.values())}</b>\n"
        f"📥 За один сбор: <b>{produced}</b>\n\n"
        "Выбери действие ниже."
    )


@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    existing = await db.get_country(user_id)
    pmc = await db.get_pmc_by_owner(user_id)
    if pmc:
        await animate(message, ["🏴 Загружаю профиль организации…", "✅ Центр ЧВК готов!"])
        await render_pmc_dashboard(message, owner_id=user_id)
        return
    if existing:
        await animate(message, ["🌍 Загружаю твою державу…", "✅ С возвращением в ВПИ ГАВАНЬ!"])
        await answer_topic_safe(message, "С возвращением. Открой «📊 Моя страна» — там уже показана одна конкретная следующая цель, а не список из десятков команд.", reply_markup=MAIN_INLINE)
        return
    await animate(message, ["🌍 Добро пожаловать в ВПИ ГАВАНЬ…", "🗺️ Здесь ты строишь страну, развиваешь армию и влияешь на мир."])
    await answer_topic_safe(message,
        "<b>Начинаем с одного шага:</b> выбери свой путь.\n\n"
        "<b>🌍 Игра за страну</b>\n"
        "Выбери реальную страну: <code>/founding Бразилия</code>. После этого открой страну, собери ресурсы и построй первый объект. Остальные разделы можно изучать постепенно через меню и <code>/help</code>.\n\n"
        "<b>🏴 Игра за ЧВК</b>\n"
        "ЧВК регистрируется отдельно и не требует страны: <code>/pmc_create Название</code>. Затем открой <code>/pmc_profile</code>, найми сотрудников через <code>/pmc_recruit количество</code> и получай заказы от стран.\n"
        "Финансирование от своей страны необязательно: если она есть, можно добровольно перевести средства через <code>/pmc_fund сумма</code>. Для военной операции используй <code>/pmc_action описание</code>, для публикации — <code>/pmc_news текст</code>.",
        reply_markup=MAIN_INLINE,
    )


@dp.message(F.new_chat_members)
async def welcome_new_members(message: Message):
    """Explain the two game paths when users enter a group."""
    if message.chat.type not in {"group", "supergroup"}:
        return
    members = [member for member in (message.new_chat_members or []) if not member.is_bot]
    if not members:
        return
    mentions = ", ".join(
        f'<a href="tg://user?id={member.id}">{esc(member.full_name)}</a>'
        for member in members
    )
    await message.answer(
        f"👋 Добро пожаловать, {mentions}!\n\n"
        "Это <b>ВПИ ГАВАНЬ</b> — геополитическая RP-игра. Здесь можно развивать государство или управлять отдельной ЧВК.\n\n"
        "<b>🌍 Хочешь играть за страну?</b>\n"
        "Выбери реальную страну командой: <code>/founding Название</code>.\n\n"
        "<b>🏴 Хочешь играть за ЧВК?</b>\n"
        "Страна не нужна. Создай самостоятельную организацию: <code>/pmc_create Название</code>. После регистрации бот сам откроет Центр ЧВК при команде <code>/start</code>.\n\n"
        "<b>С чего начать:</b> отправь <code>/start</code>, выбери один путь и следуй подсказке «Что делать сейчас». Правила и команды: <code>/help</code>."
    )


_founding_lock = asyncio.Lock()  # общий лок, чтобы два игрока не заняли одну страну одновременно


@dp.message(Command("founding"))
async def cmd_founding(message: Message):
    name = command_payload(message)
    # Схлопываем переносы строк/табы, чтобы название не разрывало сообщения
    # в несколько "строк" интерфейса и не пряталось за счёт \n внутри <b>...</b>.
    name = " ".join(name.split())
    if not name:
        await answer_topic_safe(message,
            "Играть можно только за реально существующую страну мира.\n"
            "Укажи название: <code>/founding Бразилия</code>"
        )
        return
    if len(name) > 64:
        await answer_topic_safe(message, "Слишком длинное название страны (макс 64 символа).")
        return

    canonical = countries.match_country(name)
    if canonical is None:
        await answer_topic_safe(message,
            f"«{esc(name)}» не похоже на название реальной страны.\n"
            "В этой игре можно основать только существующую страну мира — например: "
            "<code>/founding Бразилия</code>, <code>/founding Египет</code>, <code>/founding Индонезия</code>."
        )
        return

    async with get_user_lock(message.from_user.id):
        existing = await db.get_country(message.from_user.id)
        if existing:
            await answer_topic_safe(message, "У тебя уже есть страна. Используй /country чтобы посмотреть её.")
            return

    async with _founding_lock:
        taken = await db.get_country_by_name(canonical)
        if taken:
            await answer_topic_safe(message, f"«{esc(canonical)}» уже занята другим игроком. Выбери другую страну.")
            return
        tier = territory.get_tier(canonical)
        profile = world_data.get_profile(canonical, config.START_DATA_YEAR)
        # Фактическое население хранится отдельно; игровое население начинается с нуля.
        created = await db.create_country(message.from_user.id, message.chat.id, canonical, tier, profile)
        if not created:
            await answer_topic_safe(message, f"«{esc(canonical)}» уже занята другим игроком. Выбери другую страну.")
            return
        country = await db.get_country(message.from_user.id)
        if not country:
            await answer_topic_safe(message, "Не удалось сохранить страну. Повтори попытку позже.")
            return

    await answer_topic_safe(message,
        f"Страна основана! 🎉\n\n{await format_country_summary(country)}\n\n<b>Порядок первого хода:</b> 1) открой «📊 Страна»; 2) нажми «📥 Сбор»; 3) построй ферму через «🏗️ Строить». Не нужно искать другие команды.\n\n<b>🏴 Как зарегистрироваться за ЧВК</b>\n1. Создай организацию: <code>/pmc_create Название</code>.\n2. Проверь профиль: <code>/pmc_profile</code>.\n3. Набери сотрудников: <code>/pmc_recruit количество</code> — максимум 2 500 за набор, КД 6 часов.\n4. Найди заказ: <code>/pmc_list</code>.\n5. Если у тебя есть страна, она может добровольно профинансировать ЧВК: <code>/pmc_fund сумма</code>.\n6. Отправь анонимное предложение: <code>/pmc_request ID описание</code>.\n\nСтрана-заказчик скрыта от обычных игроков. Для принятия заказа ЧВК использует <code>/pmc_requests</code> и <code>/pmc_accept номер</code>.",
        reply_markup=MAIN_INLINE,
    )


@dp.message(Command("policy"))
async def cmd_policy(message: Message):
    """Показать или сменить национальную доктрину."""
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала основи страну: <code>/founding Бразилия</code>")
        return
    parts = message.text.split()
    if len(parts) == 1:
        current = config.POLICY_DEFINITIONS.get(country.get("policy", "development"), config.POLICY_DEFINITIONS["development"])
        lines = [f"<b>🏛️ Национальная политика</b>\nТекущий курс: <b>{current['name']}</b>", current["description"], "", "Сменить курс можно раз в 30 минут:"]
        for key, policy in config.POLICY_DEFINITIONS.items():
            lines.append(f"<code>/policy {key}</code> — {policy['name']}: {policy['description']}")
        await answer_topic_safe(message, "\n".join(lines))
        return
    policy_key = parts[1].lower()
    policy = config.POLICY_DEFINITIONS.get(policy_key)
    if not policy:
        await answer_topic_safe(message, "Неизвестный курс. Используй <code>/policy</code>, чтобы увидеть доступные варианты.")
        return
    now = int(time.time())
    async with get_user_lock(message.from_user.id):
        changed = await db.set_policy(message.from_user.id, policy_key, now, config.POLICY_COOLDOWN_SECONDS)
    if not changed:
        await answer_topic_safe(message, "Политику можно менять не чаще одного раза в 30 минут.")
        return
    await answer_topic_safe(message, f"🏛️ Новый национальный курс: <b>{policy['name']}</b>\n{policy['description']}")


@dp.message(Command("priority"))
async def cmd_priority(message: Message):
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала основи страну: <code>/founding Бразилия</code>")
        return
    labels = {
        "civilian": "Гражданское производство (+15% денег, ресурсов, еды и воды; −15% резерва)",
        "balanced": "Сбалансированный режим (без модификаторов)",
        "military": "Военная подготовка (+25% резерва; −5% остальных доходов)",
    }
    parts = message.text.split()
    if len(parts) == 1:
        current = country.get("labor_focus", "balanced")
        await answer_topic_safe(message, f"⚙️ <b>Приоритет населения</b>\nТекущий режим: <b>{labels[current]}</b>\n\nВыбери: <code>/priority civilian</code>, <code>/priority balanced</code> или <code>/priority military</code>. Режим влияет на следующий сбор и не ограничивает общий размер населения.")
        return
    focus = parts[1].lower()
    if focus not in labels:
        await answer_topic_safe(message, "Неизвестный режим. Используй <code>/priority</code>.")
        return
    async with get_user_lock(message.from_user.id):
        changed = await db.set_labor_focus(message.from_user.id, focus)
    await answer_topic_safe(message, f"⚙️ Приоритет изменён: <b>{labels[focus]}</b>" if changed else "Не удалось изменить приоритет.")


@dp.message(Command("tax"))
async def cmd_tax(message: Message):
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала основи страну: <code>/founding Бразилия</code>")
        return
    parts = message.text.split()
    if len(parts) == 1:
        await answer_topic_safe(message, f"🏛️ Налоговая ставка: <b>{country.get('tax_rate', config.TAX_RATE_DEFAULT)}%</b>\nДопустимый диапазон: {config.TAX_RATE_MIN}–{config.TAX_RATE_MAX}%. Налоги начисляются при <code>/collect</code> и зависят от игрового населения.")
        return
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/tax 1–30</code>")
        return
    rate = int(parts[1])
    changed = await db.set_tax_rate(message.from_user.id, rate)
    await answer_topic_safe(message, f"🏛️ Налоговая ставка изменена на <b>{rate}%</b>." if changed else f"Ставка должна быть от {config.TAX_RATE_MIN}% до {config.TAX_RATE_MAX}%.")


@dp.message(Command("history"))
async def cmd_history(message: Message):
    requested = " ".join(command_payload(message).split())
    if requested:
        canonical = countries.match_country(requested)
    else:
        own = await db.get_country(message.from_user.id)
        canonical = own.get("name") if own else None
    if not canonical:
        await answer_topic_safe(message, "Укажи страну или сначала основи свою: <code>/history Россия</code>.")
        return
    history = world_data.get_history(canonical)
    if not history:
        await answer_topic_safe(message, "Исторические данные для этой страны пока не найдены.")
        return
    by_year = {int(row["year"]): row for row in history}
    years = [year for year in (1990, 2000, 2010, 2020) if year in by_year]
    lines = [f"<b>📚 История: {esc(canonical)}</b>", "Источник: World Bank Indicators API", ""]
    for year in years:
        row = by_year[year]
        lines.append(
            f"<b>{year}</b>: население {world_data.format_population(row.get('population'))}; "
            f"ВВП {world_data.format_money(row.get('gdp_usd'))}; "
            f"ВВП/чел. {world_data.format_money(row.get('gdp_per_capita_usd'))}; "
            f"продолжительность жизни {world_data.format_life_expectancy(row.get('life_expectancy'))}"
        )
    lines.append("\nДанные относятся к фактической стране. Игровые ресурсы, здания и таймеры не являются реальными бюджетами страны.")
    await answer_topic_safe(message, "\n".join(lines), reply_markup=MAIN_INLINE)


@dp.message(Command("country"))
async def cmd_country(message: Message):
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "У тебя ещё нет страны. Создай через /founding Название")
        return
    await answer_topic_safe(message, await format_country_summary(country), reply_markup=COUNTRY_INLINE)


@dp.message(Command("progress"))
async def cmd_progress(message: Message):
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала основи страну: <code>/founding Бразилия</code>")
        return
    buildings = await db.get_buildings(message.from_user.id)
    progress = progression_snapshot(country, buildings)
    _, stage_name, stage_goal = progress["stage"]
    military_cap = real_population_millions(country)
    real_population_text = world_data.format_population(country.get("real_population"))
    army_limit_text = (
        f"{military_cap} млн игровых единиц"
        if military_cap is not None
        else "не определён: нет профиля World Bank"
    )
    lines = [
        f"📈 <b>Прогресс {esc(country['name'])}</b>",
        f"Этап: <b>{esc(stage_name)}</b> · очки: <b>{progress['score']}</b>",
        f"Цель: <b>{esc(stage_goal)}</b>",
        f"Реальное население: <b>{esc(real_population_text)}</b> · предел армии: <b>{esc(army_limit_text)}</b>",
    ]
    if progress["next_stage"]:
        target, next_name, _ = progress["next_stage"]
        lines.append(f"До «{esc(next_name)}»: <b>{target - progress['score']}</b> очков")
    else:
        lines.append("Верхний этап достигнут — развивай влияние через мир и войну.")
    active_timers = [
        cooldown_text(label, cooldown_remaining(country, action, seconds))
        for action, seconds, label in [
            ("collect", config.COLLECT_COOLDOWN_SECONDS, "Сбор"),
            ("build", config.BUILD_COOLDOWN_SECONDS, "Строительство"),
            ("action", config.ACTION_COOLDOWN_SECONDS, "Действие"),
        ]
        if cooldown_remaining(country, action, seconds)
    ]
    if active_timers:
        lines += ["", "⏱️ " + " · ".join(active_timers)]
    lines += ["", next_step_hint(country, buildings)]
    await answer_topic_safe(message, "\n".join(lines), reply_markup=PROGRESS_INLINE)


@dp.message(Command("top"))
async def cmd_top(message: Message):
    countries = await db.get_all_countries()
    if not countries:
        await answer_topic_safe(message, "Пока никто не зарегистрировал страну.")
        return
    scored = []
    for c in countries:
        buildings = await db.get_buildings(c["user_id"])
        scored.append((progression_snapshot(c, buildings).get("score", 0), c))
    scored.sort(key=lambda item: item[0], reverse=True)
    lines = ["🏆 <b>Рейтинг стран</b>\n"]
    for i, (total, c) in enumerate(scored[:15], start=1):
        lines.append(f"{i}. {esc(c['name'])} — {total} очков развития")
    await answer_topic_safe(message, "\n".join(lines), reply_markup=MAIN_INLINE)


def _economy_upgrade_cost(current_level: int, amount: int) -> int:
    """Прогрессивная цена: каждый следующий пункт экономики дороже предыдущего."""
    total = 0
    for i in range(amount):
        total += config.ECONOMY_BASE_COST + (current_level + i) * config.ECONOMY_COST_STEP
    return total


@dp.message(Command("upgrade"))
async def cmd_upgrade(message: Message):
    """/upgrade характеристика количество — прокачка за очки развития"""
    parts = message.text.split()
    if len(parts) != 3:
        await answer_topic_safe(message,
            "Формат: <code>/upgrade характеристика количество</code>\n"
            "Характеристики: economy, military, population, tech, diplomacy\n"
            "Пример: <code>/upgrade tech 3</code>\n\n"
            "⚠️ Армия качается не отсюда, а через /mobilize (нужны резерв людей и деньги)."
        )
        return

    _, stat, amount_str = parts
    stat = stat.lower()
    if stat not in STAT_NAMES_RU:
        await answer_topic_safe(message, "Неизвестная характеристика. Доступно: economy, military, population, tech, diplomacy")
        return
    if stat == "military":
        await answer_topic_safe(message, "Армия качается через /mobilize количество — нужны резерв людей и деньги.")
        return
    if not amount_str.isdigit() or int(amount_str) <= 0:
        await answer_topic_safe(message, "Количество должно быть положительным числом.")
        return
    amount = int(amount_str)
    if amount > config.MAX_UPGRADE_PER_ACTION:
        await answer_topic_safe(message, f"За одну команду можно улучшить максимум на {config.MAX_UPGRADE_PER_ACTION}. Повтори позже.")
        return

    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await answer_topic_safe(message, "Сначала создай страну: /founding Название")
            return
        remaining = cooldown_remaining(country, "upgrade", config.UPGRADE_COOLDOWN_SECONDS)
        if remaining:
            await answer_topic_safe(message, cooldown_text("Следующее улучшение доступно", remaining))
            return

        if stat == "economy":
            cost = _economy_upgrade_cost(country["economy"], amount)
        else:
            cost = amount * config.UPGRADE_COST

        if country["points"] < cost:
            await answer_topic_safe(message, f"Недостаточно очков развития. Нужно {cost}, у тебя {country['points']}.")
            return

        applied = await db.apply_upgrade(message.from_user.id, stat, amount, cost)
        if not applied:
            await answer_topic_safe(message, "Очки развития изменились во время операции. Повтори команду.")
            return
        await db.touch_cooldown(message.from_user.id, "upgrade", int(time.time()))

        updated = await db.get_country(message.from_user.id)

    await answer_topic_safe(message,
        f"✅ {STAT_NAMES_RU[stat]} увеличена на {amount} (потрачено {cost} очков).\n\n{await format_country_summary(updated)}"
    )


@dp.message(Command("build"))
async def cmd_build(message: Message):
    """/build тип — построить или улучшить одну из построек."""
    parts = message.text.split()
    if len(parts) != 2 or parts[1].lower() not in ALL_BUILDINGS:
        options = ", ".join(f"{k} ({v['name']})" for k, v in ALL_BUILDINGS.items())
        await answer_topic_safe(message, f"Формат: <code>/build тип</code>\nДоступно: {options}")
        return
    b_type = parts[1].lower()
    info = ALL_BUILDINGS[b_type]

    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await answer_topic_safe(message, "Сначала создай страну: /founding Название")
            return
        remaining = cooldown_remaining(country, "build", config.BUILD_COOLDOWN_SECONDS)
        if remaining:
            await answer_topic_safe(message, cooldown_text("Следующее строительство доступно", remaining))
            return

        required_tech = config.TECH_GATE_BUILDINGS.get(b_type, 0)
        if country["tech"] < required_tech:
            await answer_topic_safe(message,
                f"🔬 Для постройки {info['name']} нужен уровень технологий {required_tech}. "
                f"Сейчас: {country['tech']}. Используй <code>/upgrade tech 1</code>."
            )
            return

        level = await db.get_building_level(message.from_user.id, b_type)
        tier = country.get("territory_tier", "medium")
        level_cap = config.TERRITORY_BUILDING_LEVEL_CAP.get(tier, config.TERRITORY_BUILDING_LEVEL_CAP["medium"])
        if level + 1 > level_cap:
            await answer_topic_safe(message,
                f"Территория страны не позволяет строить {info['name']} выше уровня {level_cap} "
                f"({territory.TIER_LABEL_RU.get(tier, tier)})."
            )
            return

        cost_gold = info["cost_gold"] * (level + 1)
        cost_resources = info["cost_resources"] * (level + 1)
        if country["gold"] < cost_gold or country["resources"] < cost_resources:
            await answer_topic_safe(message,
                f"Недостаточно ресурсов для улучшения {info['name']} до ур. {level + 1}.\n"
                f"Нужно: 💰{cost_gold} денег, 📦{cost_resources} ресурсов.\n"
                f"У тебя: 💰{country['gold']}, 📦{country['resources']}."
            )
            return

        applied = await db.apply_building_upgrade(
            message.from_user.id, b_type, cost_gold, cost_resources
        )
        if not applied:
            await answer_topic_safe(message, "Ресурсы изменились во время операции. Повтори команду.")
            return
        await db.touch_cooldown(message.from_user.id, "build", int(time.time()))

    await answer_topic_safe(message,
        f"🏗️ {info['emoji']} {info['name']} улучшена до уровня {level + 1}!\n"
        f"Даёт {info['produces_name']} при каждом /collect."
    )


@dp.message(Command("collect"))
async def cmd_collect(message: Message):
    """Сбор ресурсов с построек, раз в COLLECT_COOLDOWN_SECONDS"""
    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await answer_topic_safe(message, "Сначала создай страну: /founding Название")
            return

        remaining = cooldown_remaining(country, "collect", config.COLLECT_COOLDOWN_SECONDS)
        if remaining:
            await answer_topic_safe(message, cooldown_text("Следующий сбор доступен", remaining))
            return

        is_first_collect = int(country.get("last_collect_at", 0) or 0) == 0
        buildings = await db.get_buildings(message.from_user.id)
        gains = production_preview(buildings)
        housing_population = gains.pop("population", 0)
        energy_supply, energy_demand = energy_balance(buildings, country.get("population", 0))
        energy_shortage = energy_demand > energy_supply
        if "energy" in gains:
            gains.pop("energy", None)
        policy = config.POLICY_DEFINITIONS.get(country.get("policy", "development"), config.POLICY_DEFINITIONS["development"])
        policy_multiplier = policy["production_multiplier"]
        gains = {resource: max(1, int(amount * policy_multiplier)) for resource, amount in gains.items()}
        active_sanctions = await db.get_active_country_sanctions(message.from_user.id)
        economic_sanctions = sum(1 for item in active_sanctions if item["sanction_type"] == "economic")
        trade_sanctions = sum(1 for item in active_sanctions if item["sanction_type"] == "trade")
        if economic_sanctions:
            gains = {resource: max(1, int(amount * (0.75 ** economic_sanctions))) if resource in {"gold", "resources"} else amount for resource, amount in gains.items()}
        if trade_sanctions:
            gains = {resource: max(1, int(amount * (0.80 ** trade_sanctions))) if resource in {"wood", "iron", "coal", "oil", "uranium", "resources"} else amount for resource, amount in gains.items()}
        if energy_shortage:
            gains = {resource: max(1, int(amount * config.ENERGY_SHORTAGE_MULTIPLIER)) if resource in {"resources", "wood", "iron", "coal", "oil", "uranium"} else amount for resource, amount in gains.items()}
        tax_gain = min(500_000, int(country.get("population", 0) * config.TAX_PER_POPULATION * country.get("tax_rate", config.TAX_RATE_DEFAULT) / 10))
        if tax_gain > 0:
            gains["gold"] = gains.get("gold", 0) + tax_gain
        labor_focus = country.get("labor_focus", "balanced")
        if labor_focus == "civilian":
            gains = {resource: max(1, int(amount * (1.15 if resource in {"gold", "resources", "food", "water"} else 0.85))) for resource, amount in gains.items()}
        elif labor_focus == "military":
            gains = {resource: max(1, int(amount * (1.25 if resource == "manpower" else 0.95))) for resource, amount in gains.items()}
        premium_items = await db.get_premium_items(message.from_user.id)
        luck_boost_used = premium_items.get("luck_boost", 0) > 0
        if luck_boost_used:
            gains = {resource: max(1, int(amount * 1.25)) for resource, amount in gains.items()}
        if country.get("policy") == "welfare":
            for resource in ("food", "water"):
                if resource in gains:
                    gains[resource] = int(gains[resource] * 1.25)
        elif country.get("policy") == "militarism" and "manpower" in gains:
            gains["manpower"] = int(gains["manpower"] * 1.25)

        # Постепенный прирост экономики от развитых построек (шахта + рынок)
        mine_level = buildings.get("mine", 0)
        market_level = buildings.get("market", 0)
        economy_growth = (mine_level + market_level) // config.ECONOMY_GROWTH_DIVISOR

        # Накопленная еда сверх порога уходит на рост населения — делает еду
        # не просто ещё одним числом, а ресурсом с игровым эффектом.
        # Рост определяется накопленной едой; территориального потолка населения нет.
        population_growth = 0
        food_population_growth = 0
        food_spend = 0
        current_food = country["food"] + gains.get("food", 0)
        if current_food >= config.FOOD_GROWTH_THRESHOLD:
            possible_growth = current_food // config.FOOD_GROWTH_THRESHOLD
            # Население не ограничивается территориальным потолком; рост зависит от еды.
            food_population_growth = min(possible_growth, config.MAX_POPULATION_GROWTH_PER_COLLECT)
            food_spend = food_population_growth * config.FOOD_GROWTH_THRESHOLD
        population_growth = food_population_growth + max(0, int(housing_population))

        stability_delta = policy["stability_delta"]
        if current_food >= config.FOOD_GROWTH_THRESHOLD * 2 and country["water"] >= 100:
            stability_delta += 1
        elif current_food == 0 and country["water"] == 0:
            stability_delta -= 1
        applied = await db.apply_collect(
            message.from_user.id,
            gains,
            economy_growth,
            food_spend,
            population_growth,
            config.POINTS_PER_COLLECT,
            int(time.time()),
            stability_delta,
        )
        if not applied:
            await answer_topic_safe(message, "Состояние страны изменилось во время сбора. Повтори команду.")
            return
        if luck_boost_used:
            await db.consume_premium_item(message.from_user.id, "luck_boost")

    lines = ["📥 <b>Сбор ресурсов</b>\n"]
    any_gain = False
    for resource, amount in gains.items():
        if amount > 0:
            any_gain = True
            lines.append(f"{RESOURCE_NAMES_RU[resource]}: +{amount}")
    if not any_gain:
        lines.append("Построек пока нет — используй /build чтобы начать что-то производить.")
    if is_first_collect:
        lines.append(f"🎁 Стартовый сбор: +{config.FIRST_COLLECT_GOLD_BONUS:,} денег")
    if luck_boost_used:
        lines.append("⚡ Буст удачи применён: этот сбор увеличен на 25%.")
    if active_sanctions:
        lines.append(f"⚠️ Активные санкции: {len(active_sanctions)}. Экономические и торговые доходы снижены.")
    if tax_gain > 0:
        lines.append(f"🏛️ Налоги населения: +{tax_gain:,} денег при ставке {country.get('tax_rate', config.TAX_RATE_DEFAULT)}%.")
    if housing_population > 0:
        lines.append(f"🏡 Жильё: +{housing_population:,} населения.")
    if energy_shortage:
        lines.append(f"⚡ Дефицит энергии: добыча снижена до {int(config.ENERGY_SHORTAGE_MULTIPLIER * 100)}%.")
    if economy_growth > 0:
        lines.append(f"💰 Экономика: +{economy_growth} (от развития построек)")
    if population_growth > 0:
        lines.append(f"👥 Население: +{population_growth} (от накопленной еды)")

    await answer_topic_safe(message, "\n".join(lines))


@dp.message(Command("mobilize"))
async def cmd_mobilize(message: Message):
    """/mobilize количество — прокачать армию за резерв людей + деньги"""
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
        await answer_topic_safe(message,
            f"Формат: <code>/mobilize количество</code>\n"
            f"Стоимость 1 пункта армии: {config.MOBILIZE_MANPOWER_PER_POINT} резерва людей + {config.MOBILIZE_GOLD_PER_POINT} денег."
        )
        return
    amount = int(parts[1])
    if amount > config.MAX_MOBILIZE_PER_ACTION:
        await answer_topic_safe(message, f"За одну мобилизацию можно добавить максимум {config.MAX_MOBILIZE_PER_ACTION} пунктов армии.")
        return

    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await answer_topic_safe(message, "Сначала создай страну: /founding Название")
            return
        remaining = cooldown_remaining(country, "mobilize", config.MOBILIZE_COOLDOWN_SECONDS)
        if remaining:
            await answer_topic_safe(message, cooldown_text("Следующая мобилизация доступна", remaining))
            return

        base_capacity = country["military_bases"] * config.MILITARY_PER_BASE
        if country["military"] + amount > base_capacity:
            await answer_topic_safe(message,
                f"Недостаточно военных баз. Текущая вместимость: {base_capacity * config.MILITARY_UNIT_SIZE:,} военнослужащих.\n"
                f"Построй дополнительные базы через /build_base."
            )
            return
        population_required = amount * config.MOBILIZE_POPULATION_PER_POINT
        if country["population"] < population_required:
            await answer_topic_safe(message,
                f"Недостаточно игрового населения для мобилизации. Нужно: {population_required:,}.\n"
                f"У тебя: {country['population']:,}. Развивай фермы, амбары и население через /collect."
            )
            return
        factual_capacity = None
        if country.get("real_population"):
            factual_capacity = int(country["real_population"] * config.MAX_ARMY_POPULATION_SHARE / config.MILITARY_UNIT_SIZE)
        if factual_capacity is not None and country["military"] + amount > factual_capacity:
            await answer_topic_safe(message,
                f"Достигнут демографический предел армии: {factual_capacity:,} внутренних единиц."
            )
            return
        cost_manpower = amount * config.MOBILIZE_MANPOWER_PER_POINT
        cost_gold = amount * config.MOBILIZE_GOLD_PER_POINT

        if country["manpower"] < cost_manpower or country["gold"] < cost_gold:
            await answer_topic_safe(message,
                f"Недостаточно ресурсов для мобилизации +{amount} к армии.\n"
                f"Нужно: 🧑‍🤝‍🧑{cost_manpower} резерва, 💰{cost_gold} денег.\n"
                f"У тебя: 🧑‍🤝‍🧑{country['manpower']}, 💰{country['gold']}."
            )
            return

        applied = await db.apply_mobilization(
            message.from_user.id, cost_manpower, cost_gold, amount, int(time.time())
        )
        if not applied:
            await answer_topic_safe(message, "Ресурсы изменились во время операции. Повтори команду.")
            return

    await answer_topic_safe(message, f"⚔️ Армия усилена на {amount}! Потрачено: 🧑‍🤝‍🧑{cost_manpower}, 💰{cost_gold}.")


@dp.message(Command("market"))
async def cmd_market(message: Message):
    """/market — текущие (динамические) цены на сырьё"""
    prices = market.get_all_prices()
    remaining = market.seconds_until_next_tick()
    mins = remaining // 60
    lines = ["📈 <b>Рынок сырья</b>\n"]
    for resource, price in prices.items():
        base = config.RESOURCE_BUY_PRICE_GOLD[resource]
        arrow = "📈" if price > base else ("📉" if price < base else "➖")
        lines.append(f"{RESOURCE_NAMES_RU[resource]}: 💰{price}/ед. {arrow}")
    lines.append(f"\n⏳ Цены обновятся через ~{mins} мин.")
    lines.append("Купить: <code>/buy ресурс количество</code>")
    await answer_topic_safe(message, "\n".join(lines), reply_markup=ECONOMY_INLINE)


@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    """/buy ресурс количество — купить сырьё (wood/iron/coal/oil/uranium) по текущей рыночной цене"""
    parts = message.text.split()
    if (
        len(parts) != 3
        or parts[1].lower() not in config.RESOURCE_BUY_PRICE_GOLD
        or not parts[2].isdigit()
        or int(parts[2]) <= 0
    ):
        options = ", ".join(config.RESOURCE_BUY_PRICE_GOLD.keys())
        await answer_topic_safe(message,
            f"Формат: <code>/buy ресурс количество</code>\nДоступно: {options}\nТекущие цены — /market"
        )
        return

    resource = parts[1].lower()
    amount = int(parts[2])
    if amount > config.MAX_BUY_PER_ORDER:
        await answer_topic_safe(message, f"Максимум за одну покупку: {config.MAX_BUY_PER_ORDER}.")
        return

    # Цену фиксируем один раз до входа в лок — рынок общий для всех, отдельно
    # блокировать его не нужно, а лёгкая гонка "цена сменилась между чтением и списанием
    # денег" тут не критична (окно — доли секунды, тик — минуты).
    price_per_unit = market.get_price(resource)
    price = price_per_unit * amount

    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await answer_topic_safe(message, "Сначала создай страну: /founding Название")
            return
        remaining = cooldown_remaining(country, "buy", config.BUY_COOLDOWN_SECONDS)
        if remaining:
            await answer_topic_safe(message, cooldown_text("Следующая покупка доступна", remaining))
            return
        if country["gold"] < price:
            await answer_topic_safe(message, f"Недостаточно денег. Нужно 💰{price} (цена {price_per_unit}/ед.), у тебя 💰{country['gold']}.")
            return
        applied = await db.apply_purchase(message.from_user.id, resource, amount, price)
        if not applied:
            await answer_topic_safe(message, "Деньги изменилось во время операции. Повтори покупку.")
            return
        await db.touch_cooldown(message.from_user.id, "buy", int(time.time()))

    await answer_topic_safe(message,
        f"🛒 Куплено {RESOURCE_NAMES_RU[resource]}: +{amount} по 💰{price_per_unit}/ед. (итого 💰{price})."
    )


@dp.message(Command("build_base"))
async def cmd_build_base(message: Message):
    """/build_base — построить военную базу (лимит зависит от территории и армии)"""
    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await answer_topic_safe(message, "Сначала создай страну: /founding Название")
            return
        remaining = cooldown_remaining(country, "base", config.BASE_COOLDOWN_SECONDS)
        if remaining:
            await answer_topic_safe(message, cooldown_text("Следующая военная база доступна", remaining))
            return

        tier = country.get("territory_tier", "medium")
        base_cap = config.TERRITORY_BASE_BONUS.get(tier, 0) + country["military"] // config.MILITARY_PER_BASE
        if country["military_bases"] >= base_cap:
            await answer_topic_safe(message,
                f"Лимит военных баз исчерпан: {country['military_bases']}/{base_cap}.\n"
                f"Увеличь армию (/mobilize) — лимит растёт вместе с ней."
            )
            return

        next_count = country["military_bases"] + 1
        required_military = (next_count - 1) * config.MILITARY_PER_BASE
        if country["military"] < required_military:
            await answer_topic_safe(message,
                f"Для базы №{next_count} сначала нужна армия не менее {required_military} внутренних единиц "
                f"({required_military * config.MILITARY_UNIT_SIZE:,} военнослужащих)."
            )
            return
        cost_gold = config.BASE_COST_GOLD * next_count
        cost_resources = config.BASE_COST_RESOURCES * next_count
        if country["gold"] < cost_gold or country["resources"] < cost_resources:
            await answer_topic_safe(message,
                f"Недостаточно ресурсов для базы №{next_count}.\n"
                f"Нужно: 💰{cost_gold}, 📦{cost_resources}.\n"
                f"У тебя: 💰{country['gold']}, 📦{country['resources']}."
            )
            return

        applied = await db.apply_base(message.from_user.id, cost_gold, cost_resources, required_military)
        if not applied:
            await answer_topic_safe(message, "Ресурсы изменились во время строительства. Повтори команду.")
            return
        await db.touch_cooldown(message.from_user.id, "base", int(time.time()))

    await answer_topic_safe(message, f"🪖 Военная база построена! Теперь их {next_count}/{base_cap}.")


@dp.message(Command("spy"))
async def cmd_spy(message: Message):
    """/spy user_id — скрытная разведка чужой страны. Цель никогда не уведомляется."""
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message,
            "Формат: <code>/spy user_id</code>\n"
            f"Стоимость: 💰{config.SPY_COST_GOLD}. Кулдаун: {config.SPY_COOLDOWN_SECONDS // 60} мин.\n"
            "Операция полностью скрытная — цель никогда не узнает, ни при успехе, ни при провале."
        )
        return

    target_id = int(parts[1])
    spy_id = message.from_user.id
    if target_id == spy_id:
        await answer_topic_safe(message, "Шпионить за самим собой бессмысленно.")
        return

    async with get_user_lock(spy_id):
        spy_country = await db.get_country(spy_id)
        if not spy_country:
            await answer_topic_safe(message, "Сначала создай страну: /founding Название")
            return
        target = await db.get_country(target_id)
        if not target:
            await answer_topic_safe(message, "У этого user_id нет страны.")
            return

        elapsed = int(time.time()) - spy_country.get("last_spy_at", 0)
        remaining = config.SPY_COOLDOWN_SECONDS - elapsed
        if remaining > 0:
            mins, secs = remaining // 60, remaining % 60
            await answer_topic_safe(message, f"⏳ Следующую операцию можно провести через {mins} мин {secs} сек.")
            return
        if spy_country["gold"] < config.SPY_COST_GOLD:
            await answer_topic_safe(message, f"Недостаточно денег. Нужно 💰{config.SPY_COST_GOLD}.")
            return

        # Момент операции и стоимость фиксируем сразу — сама операция скрытная,
        # цель ни в коем случае не получает уведомления, независимо от исхода.
        applied = await db.apply_spy_operation(spy_id, config.SPY_COST_GOLD, int(time.time()))
        if not applied:
            await answer_topic_safe(message, "Деньги изменилось во время операции. Повтори попытку.")
            return

        # Шанс успеха растёт вместе с разницей tech/diplomacy шпиона и цели.
        edge = (spy_country["tech"] - target["tech"]) + (spy_country["diplomacy"] - target["diplomacy"])
        chance = max(10, min(90, config.SPY_BASE_SUCCESS_CHANCE + edge))
        success = random.randint(1, 100) <= chance

    if not success:
        await answer_topic_safe(message, "🕵️ Операция провалилась — агент не смог добыть достоверные данные. Цель ничего не заметила.")
        return

    await answer_topic_safe(message,
        f"🕵️ Разведданные по «{esc(target['name'])}» (операция прошла незаметно):\n\n"
        f"💰 Экономика: {target['economy']}\n"
        f"⚔️ Армия: {target['military']}\n"
        f"👥 Население: {target['population']}\n"
        f"🔬 Технологии: {target['tech']}\n"
        f"🤝 Дипломатия: {target['diplomacy']}\n"
        f"🪖 Военные базы: {target['military_bases']}\n"
    )


_FORBIDDEN_WAR_TERMS = (
    "космонавт", "единорог", "мопед", "бабуш", "хомяк", "такс", "утюг",
    "детск", "пластиков", "бамбук", "блогер", "велосипед", "попугай",
    "сомнамбул", "без скафандр", "мкс", "игрушеч", "кошк", "котят",
)
_REALISTIC_WAR_TERMS = (
    "арм", "войск", "удар", "оборон", "наступ", "десант", "артил", "танк",
    "ракет", "флот", "авиац", "развед", "мобилиз", "гарнизон", "рубеж",
    "снабж", "диверс", "пехот", "брон", "позици", "огонь", "склад",
)


def is_realistic_war_scenario(text: str) -> bool:
    normalized = text.casefold()
    return not any(term in normalized for term in _FORBIDDEN_WAR_TERMS) and any(
        term in normalized for term in _REALISTIC_WAR_TERMS
    )


def build_anti_raid_context(attacker: dict, defender: dict) -> str:
    """Pass preparedness to the referee without exposing hidden player moves."""
    readiness = max(0, min(100, int(defender.get("readiness", 0) or 0)))
    bases = max(0, int(defender.get("military_bases", 0) or 0))
    tech = max(0, int(defender.get("tech", 0) or 0))
    defense_index = readiness + bases * 2 + tech
    if defense_index >= 80:
        posture = "высокая готовность: внезапный рейд быстро обнаруживается и получает ограниченный эффект"
    elif defense_index >= 40:
        posture = "средняя готовность: часть удара может застать гарнизоны врасплох, но полного разгрома быть не должно"
    else:
        posture = "низкая готовность: внезапный рейд получает преимущество, но не может автоматически уничтожить страну"
    return (
        f"Анти-рейд: готовность обороны {readiness}/100, военные базы {bases}, технологии {tech}, "
        f"индекс подготовки {defense_index}. Положение: {posture}. "
        "Ущерб обычного рейда должен быть поэтапным и ограниченным; не обнуляй страну одним ударом."
    )


@dp.message(Command("raid_status"))
async def cmd_raid_status(message: Message):
    """Show the player's current in-game anti-raid posture."""
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала создай страну: /founding Название")
        return
    readiness = max(0, min(100, int(country.get("readiness", 0) or 0)))
    bases = int(country.get("military_bases", 0) or 0)
    tech = int(country.get("tech", 0) or 0)
    defense_index = readiness + bases * 2 + tech
    posture = "высокая" if defense_index >= 80 else "средняя" if defense_index >= 40 else "низкая"
    await answer_topic_safe(
        message,
        f"🛡️ <b>Анти-рейд: {esc(country['name'])}</b>\n"
        f"Готовность: <b>{readiness}/100</b>\n"
        f"Военные базы: <b>{bases}</b> · технологии: <b>{tech}</b>\n"
        f"Индекс подготовки: <b>{defense_index}</b> · позиция: <b>{posture}</b>\n\n"
        "Повышай готовность, строй базы и развивай технологии. Это уменьшает эффект внезапной атаки, "
        "но не делает страну полностью неуязвимой."
    )


@dp.message(Command("attack"))
async def cmd_attack(message: Message):
    """/attack user_id описание атаки — война между двумя игроками, вердикт от ИИ"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await answer_topic_safe(message,
            "Формат: <code>/attack user_id описание атаки</code>\n"
            "user_id соперника можно узнать через /top (или он сам скажет через /myid).\n"
            "Пример: <code>/attack 123456789 Наношу внезапный удар по приграничным гарнизонам</code>"
        )
        return

    defender_id = int(parts[1])
    action_text = parts[2].strip()
    if len(action_text) < config.MIN_NARRATIVE_LEN:
        await answer_topic_safe(message, f"Описание атаки должно содержать минимум {config.MIN_NARRATIVE_LEN} символов.")
        return
    if not is_realistic_war_scenario(action_text):
        await answer_topic_safe(message, "Опиши реалистичную военную операцию: силы, цель, направление и способ действий. Фантастические и шуточные сценарии не принимаются.")
        return
    if len(action_text) > config.MAX_ACTION_LEN:
        await answer_topic_safe(message, f"Слишком длинное описание (макс {config.MAX_ACTION_LEN} символов).")
        return

    attacker_id = message.from_user.id
    if defender_id == attacker_id:
        await answer_topic_safe(message, "Нельзя напасть на самого себя.")
        return

    current_year = await db.get_current_year()
    if current_year is None:
        await answer_topic_safe(message,
            "⚠️ Год мира ещё не задан. Администратор должен сначала выполнить "
            "<code>/set_year год</code>, прежде чем атаки станут доступны."
        )
        return
    # Блокировки берём в фиксированном порядке (по возрастанию user_id) вне зависимости
    # от того, кто атакующий — иначе две одновременные встречные атаки могут взаимно
    # заблокироваться (deadlock), ожидая лок друг друга в обратном порядке.
    lock_a, lock_b = sorted([attacker_id, defender_id])
    first_lock, second_lock = get_user_lock(lock_a), get_user_lock(lock_b)

    async with first_lock:
        async with second_lock:
            attacker = await db.get_country(attacker_id)
            if not attacker:
                await answer_topic_safe(message, "Сначала создай страну: /founding Название")
                return
            defender = await db.get_country(defender_id)
            if not defender:
                await answer_topic_safe(message, "У этого user_id нет страны — атаковать некого.")
                return

            if config.ATTACK_COOLDOWN_SECONDS > 0:
                elapsed = int(time.time()) - attacker.get("last_attack_at", 0)
                remaining = config.ATTACK_COOLDOWN_SECONDS - elapsed
                if remaining > 0:
                    mins, secs = remaining // 60, remaining % 60
                    await answer_topic_safe(message, f"⏳ Следующую атаку можно совершить через {mins} мин {secs} сек.")
                    return
            pending_id = await db.create_pending_war(
                attacker_id, attacker["name"], defender_id, defender["name"],
                action_text, int(time.time()), int(time.time()) + config.WAR_DEFENSE_WINDOW_SECONDS,
            )
            if not pending_id:
                await answer_topic_safe(message, "У тебя уже есть незавершённая война. Дождись ответа защитника.")
                return
            await db.touch_last_attack(attacker_id, int(time.time()))
            await hide_group_command(message)
            await answer_topic_safe(
                message,
                f"⚔️ Атака #{pending_id} объявлена против «{esc(defender['name'])}».\n"
                "Война не завершена. Защитник должен ответить командой "
                f"<code>/defend {pending_id} описание обороны</code>.",
            )
            try:
                await bot.send_message(
                    defender["chat_id"],
                    f"🛡️ На твою страну объявлена атака #{pending_id}.\n"
                    f"Атакующий: <b>{esc(attacker['name'])}</b>\n"
                    f"Ответь: <code>/defend {pending_id} описание обороны</code>",
                )
            except Exception:
                logger.info("Не удалось уведомить защитника о войне %s", pending_id, exc_info=True)
            return

@dp.message(Command("defend"))
async def cmd_defend(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/defend номер_войны описание обороны</code>")
        return
    defense_text = parts[2].strip()
    if len(defense_text) < config.MIN_NARRATIVE_LEN:
        await answer_topic_safe(message, f"Описание обороны должно содержать минимум {config.MIN_NARRATIVE_LEN} символов.")
        return
    if not is_realistic_war_scenario(defense_text):
        await answer_topic_safe(message, "Опиши реалистичную оборону: силы, рубежи, снабжение и способ отражения атаки.")
        return
    war_id = int(parts[1])
    pending = await db.get_pending_war(war_id)
    if not pending or pending["defender_id"] != message.from_user.id or pending["status"] != "pending":
        await answer_topic_safe(message, "Такая ожидающая война не найдена или ты не являешься защитником.")
        return
    attacker = await db.get_country(pending["attacker_id"])
    defender = await db.get_country(pending["defender_id"])
    if not attacker or not defender:
        await answer_topic_safe(message, "Одна из стран больше не существует. Война отменена без вердикта.")
        return
    if not await db.claim_pending_war(war_id, message.from_user.id, defense_text, int(time.time())):
        await answer_topic_safe(message, "На эту войну уже ответили или она обрабатывается.")
        return
    await hide_group_command(message)
    current_year = await db.get_current_year()
    combined_text = f"Атака: {pending['attack_text']}\nОборона: {defense_text}"
    raid_context = build_anti_raid_context(attacker, defender)
    thinking_msg = await message.answer("⚔️ Ведущий рассматривает действия атакующей и обороняющейся стороны...")
    try:
        verdict = await ai.get_war_verdict(
            attacker,
            defender,
            combined_text,
            world_context=f"Текущий год мира: {current_year}.\n{raid_context}",
        )
        outcome = verdict.get("outcome", "error")
        if outcome == "error":
            await db.reset_pending_war(war_id)
            await thinking_msg.edit_text(esc(verdict.get("verdict_text", "ИИ временно недоступен. Ответ можно отправить снова.")))
            return
        attacker_changes = clamp_country_changes(attacker, verdict.get("attacker_stat_changes", {}))
        defender_changes = clamp_country_changes(defender, verdict.get("defender_stat_changes", {}))
        loot_gold = loot_resources = 0
        if outcome == "attacker_win":
            loot_gold = defender["gold"] * config.WAR_LOOT_PERCENT // 100
            loot_resources = defender["resources"] * config.WAR_LOOT_PERCENT // 100
        elif outcome == "defender_win":
            loot_gold = -(attacker["gold"] * config.WAR_LOOT_PERCENT // 100)
            loot_resources = -(attacker["resources"] * config.WAR_LOOT_PERCENT // 100)
        lock_a, lock_b = sorted([pending["attacker_id"], pending["defender_id"]])
        async with get_user_lock(lock_a):
            async with get_user_lock(lock_b):
                if outcome not in ("attacker_win", "defender_win", "draw"):
                    await db.reset_pending_war(war_id)
                    await thinking_msg.edit_text("⚠️ Вердикт не содержит допустимого исхода. Война остаётся ожидающей ответа.")
                    return
                await db.apply_war_result(pending["attacker_id"], pending["defender_id"], attacker_changes, defender_changes, loot_gold, loot_resources)
                await db.log_war(pending["attacker_id"], attacker["name"], pending["defender_id"], defender["name"], combined_text, outcome, verdict["verdict_text"])
                await db.complete_pending_war(war_id)
        labels = {"attacker_win": f"🏆 Победа {esc(attacker['name'])}!", "defender_win": f"🛡️ {esc(defender['name'])} отстояла свои границы!", "draw": "🤝 Ничья — обе стороны понесли потери."}
        await thinking_msg.edit_text(f"{labels.get(outcome, 'Исход неясен.')}\n\n{verdict['verdict_text']}\n\nВойна #{war_id} завершена после ответа обороны.")
    except Exception:
        await db.reset_pending_war(war_id)
        raise


@dp.message(Command("war_history"))
async def cmd_war_history(message: Message):
    """Show completed wars involving the player without revealing secret turn text."""
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала основи страну: <code>/founding Бразилия</code>")
        return
    history = await db.get_war_history(message.from_user.id, 20)
    if not history:
        await answer_topic_safe(message, "📚 У твоей страны пока нет завершённых войн.")
        return
    lines = [
        f"📚 <b>Военная история {esc(country['name'])}</b>",
        "Секретные тексты атаки и обороны здесь не показываются.",
        "",
    ]
    for item in history:
        if item["attacker_id"] == message.from_user.id:
            opponent = item["defender_name"]
            role = "Атака"
            result = {"attacker_win": "победа", "defender_win": "поражение", "draw": "ничья"}.get(item["outcome"], "завершено")
        else:
            opponent = item["attacker_name"]
            role = "Оборона"
            result = {"defender_win": "победа", "attacker_win": "поражение", "draw": "ничья"}.get(item["outcome"], "завершено")
        lines.append(f"• Война #{item['id']} · {role} против <b>{esc(opponent)}</b> · <b>{result}</b>")
    await answer_topic_safe(message, "\n".join(lines), reply_markup=MAIN_INLINE)


@dp.message(Command("wars"))
async def cmd_wars(message: Message):
    """/wars — ожидающие обороны и последние военные столкновения."""
    pending_defense = await db.list_pending_wars_for_defender(message.from_user.id)
    pending_attack = await db.list_pending_wars_for_attacker(message.from_user.id)
    wars = await db.get_recent_wars(10)
    lines = []
    if pending_attack:
        lines.append("⚔️ <b>Твои незавершённые войны</b>")
        for item in pending_attack:
            state = "защитник готовит ответ" if item["status"] == "pending" else "ведущий готовит итог"
            lines.append(f"Война #{item['id']} против <b>{esc(item['defender_name'])}</b> — {state}.")
        lines.append("")
    if pending_defense:
        lines.append("🛡️ <b>Войны, ожидающие твоей обороны</b>")
        for item in pending_defense:
            lines.append(
                f"Атака #{item['id']} от <b>{esc(item['attacker_name'])}</b>\n"
                f"Ответь: <code>/defend {item['id']} описание обороны</code>"
            )
        lines.append("")
    if not wars:
        if lines:
            await answer_topic_safe(message, "\n".join(lines))
        else:
            await answer_topic_safe(message, "Войн пока не было.")
        return
    lines.append("⚔️ <b>Последние столкновения</b>\n")
    for w in wars:
        arrow = {
            "attacker_win": "победил(а)",
            "defender_win": "отбилась от",
            "draw": "сразилась вничью с",
        }.get(w["outcome"], "напал(а) на")
        lines.append(f"• <b>{esc(w['attacker_name'])}</b> {arrow} <b>{esc(w['defender_name'])}</b>")
    await answer_topic_safe(message, "\n".join(lines))


@dp.message(Command("action"))
async def cmd_action(message: Message):
    action_text = command_payload(message)
    if not action_text:
        await answer_topic_safe(message,
            "Опиши действие своей страны после команды.\n"
            "Пример: <code>/action Объявляю мобилизацию и готовлю вторжение в соседнее государство</code>"
        )
        return
    if len(action_text) > config.MAX_ACTION_LEN:
        await answer_topic_safe(message, f"Слишком длинное описание (макс {config.MAX_ACTION_LEN} символов).")
        return

    # Без заданного года мира ИИ не сможет корректно учитывать контекст эпохи в вердикте —
    # админ должен один раз задать год через /set_year, дальше он растёт сам.
    current_year = await db.get_current_year()
    if current_year is None:
        await answer_topic_safe(message,
            "⚠️ Год мира ещё не задан. Администратор должен сначала выполнить "
            "<code>/set_year год</code>, прежде чем действия станут доступны."
        )
        return

    user_id = message.from_user.id
    lock = get_user_lock(user_id)
    async with lock:
        if user_id in _ai_inflight:
            await answer_topic_safe(message, "⏳ Предыдущее действие ещё обрабатывается ведущим. Дождись результата.")
            return
        country = await db.get_country(message.from_user.id)
        if not country:
            await answer_topic_safe(message, "Сначала создай страну: /founding Название")
            return

        if config.ACTION_COOLDOWN_SECONDS > 0:
            elapsed = int(time.time()) - country.get("last_action_at", 0)
            remaining = config.ACTION_COOLDOWN_SECONDS - elapsed
            if remaining > 0:
                mins, secs = remaining // 60, remaining % 60
                await answer_topic_safe(message, f"⏳ Следующее действие можно совершить через {mins} мин {secs} сек.")
                return
        _ai_inflight.add(user_id)

    # Запрос к ИИ намеренно вне лока — чтобы не держать блокировку пользователя
    # на десятки секунд и не блокировать другие его команды (/country и т.п.).
    thinking_msg = await message.answer("🤔 Ведущий обдумывает вердикт...")
    world_context = f"Текущий год мира: {current_year}."
    try:
        verdict = await ai.get_verdict(country, action_text, world_context=world_context)
    except Exception:
        _ai_inflight.discard(user_id)
        raise
    if verdict.get("success") == "error":
        _ai_inflight.discard(user_id)
        await thinking_msg.edit_text(esc(verdict.get("verdict_text", "⚠️ Не удалось получить вердикт от ИИ.")))
        return

    try:
        async with lock:
            current_country = await db.get_country(message.from_user.id)
            if not current_country:
                await thinking_msg.edit_text("⚠️ Пока ведущий готовил вердикт, страна была удалена. Результат не применён.")
                return
            country = current_country
            changes = clamp_country_changes(country, verdict.get("stat_changes", {}))
            await db.apply_action_result(
                message.from_user.id,
                changes,
                country["name"],
                action_text,
                verdict["verdict_text"],
            )
            await db.touch_last_action(user_id, int(time.time()))
    finally:
        _ai_inflight.discard(user_id)


    changes_lines = []
    for stat, delta in changes.items():
        if delta != 0:
            sign = "+" if delta > 0 else ""
            changes_lines.append(f"{STAT_NAMES_RU[stat]}: {sign}{delta}")
    changes_text = "\n".join(changes_lines) if changes_lines else "без изменений характеристик"

    result_text = (
        f"📜 <b>Вердикт по действию {esc(country['name'])}</b> ({current_year} год)\n\n"
        f"{verdict['verdict_text']}\n\n"
        f"<b>Изменения:</b>\n{changes_text}"
    )
    await thinking_msg.edit_text(result_text)


@dp.message(Command("year"))
async def cmd_year(message: Message):
    """/year — показать текущий год мира"""
    year = await db.get_current_year()
    if year is None:
        await answer_topic_safe(message,
            "Год мира ещё не задан. Администратор должен выполнить <code>/set_year год</code>."
        )
        return
    await answer_topic_safe(message, f"📅 Текущий год мира: <b>{year}</b>")


@dp.message(Command("news"))
async def cmd_news(message: Message):
    events = await db.get_recent_events_for_user(message.from_user.id, 8)
    if not events:
        await answer_topic_safe(message, "📰 <b>Мои новости</b>\n\nЛичных действий пока не было. Глобальная лента находится в разделе «🌎 Мир».", reply_markup=MORE_INLINE)
        return
    lines = ["📰 <b>Мои новости</b>", "", "Здесь только решения и последствия твоей страны.", ""]
    for e in events:
        lines.append(f"• {esc(e['verdict_text'][:240])}")
    lines += ["", "Глобальные события: открой «🌎 Мир»." ]
    await answer_topic_safe(message, "\n\n".join(lines), reply_markup=MORE_INLINE)


@dp.message(Command("statement"))
async def cmd_statement(message: Message):
    """Publish a country statement to the public world feed."""
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала основи страну: <code>/founding Бразилия</code>")
        return
    statement = command_payload(message)
    if len(statement) < config.MIN_NARRATIVE_LEN:
        await answer_topic_safe(message, f"Заявление должно содержать минимум {config.MIN_NARRATIVE_LEN} символов: позицию страны, цель или решение.")
        return
    recent = await db.get_recent_country_statements(50)
    last = next((item for item in recent if item["user_id"] == message.from_user.id), None)
    remaining = 0
    if last:
        remaining = max(0, config.STATEMENT_COOLDOWN_SECONDS - (int(time.time()) - int(last["created_at"])))
    if remaining:
        await answer_topic_safe(message, f"Официальное заявление можно публиковать ещё через <b>{format_duration(remaining)}</b>.")
        return
    year = await db.get_current_year()
    statement_id = await db.create_country_statement(message.from_user.id, country["name"], statement, year)
    if not statement_id:
        await answer_topic_safe(message, "Не удалось опубликовать заявление. Проверь текст и повтори позже.")
        return
    await answer_topic_safe(message, f"📣 Заявление страны <b>{esc(country['name'])}</b> опубликовано в мировой ленте под номером <b>#{statement_id}</b>.", reply_markup=MORE_INLINE)


@dp.message(Command("statements"))
async def cmd_statements(message: Message):
    statements = await db.get_recent_country_statements(12)
    if not statements:
        await answer_topic_safe(message, "📣 Официальных заявлений пока нет.", reply_markup=MORE_INLINE)
        return
    lines = ["📣 <b>Официальные заявления стран</b>", ""]
    for item in statements:
        year = f" · {item['game_year']} год" if item.get("game_year") else ""
        lines.append(f"• <b>{esc(item['country_name'])}</b>{year}\n{esc(item['statement'][:500])}")
    await answer_topic_safe(message, "\n\n".join(lines), reply_markup=MORE_INLINE)


@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    await answer_topic_safe(message, f"Твой telegram user_id: <code>{message.from_user.id}</code>")


BEGINNER_GUIDE = (
    "<b>🧭 Как играть без путаницы</b>\n\n"
    "<b>Первые 10 минут</b>\n"
    "1. Создай государство: <code>/founding Название</code>.\n"
    "2. Открой «📊 Страна» и посмотри только строку «Следующий шаг».\n"
    "3. Нажми «📥 Сбор», затем «🏗️ Строить» и начни с фермы.\n"
    "4. Повтори сбор после таймера — производство превращается в деньги, ресурсы, еду и резерв людей.\n\n"
    "<b>Что прокачивать дальше</b>\n"
    "Экономика даёт деньги и ресурсы. Население и резерв людей позволяют мобилизовать армию. Военные базы определяют вместимость армии. Дипломатия, торговля и альянсы помогают не воевать в одиночку.\n\n"
    "<b>Война</b>\n"
    "Атака создаётся через <code>/attack user_id описание</code>, но вердикт не появляется сразу: защитник получает отдельное право на ответ через <code>/defend ID описание обороны</code>. В группе тексты ходов скрываются.\n\n"
    "<b>Главное правило</b>\n"
    "Не нужно запоминать команды. Открывай «📊 Страна», «📈 Прогресс» и «☰ Ещё»: каждый экран показывает один ближайший шаг. Таймер означает, что действие нужно повторить позже, а не что страна сломалась."
)


@dp.message(Command("guide"))
async def cmd_guide(message: Message):
    await answer_topic_safe(message, BEGINNER_GUIDE, reply_markup=MAIN_INLINE)


@dp.message(F.text.in_({"📊 Моя страна", "📊 Страна"}))
async def menu_country(message: Message):
    await cmd_country(message)


@dp.message(F.text.in_({"📖 Что делать?", "📖 Помощь"}))
async def menu_guide(message: Message):
    await cmd_guide(message)


@dp.message(F.text.in_({"📥 Собрать ресурсы", "📥 Сбор"}))
async def menu_collect(message: Message):
    await cmd_collect(message)


@dp.message(F.text == "📈 Прогресс")
async def menu_progress(message: Message):
    await cmd_progress(message)


@dp.message(F.text == "🌍 Рейтинг")
async def menu_top(message: Message):
    await cmd_top(message)


@dp.message(F.text.in_({"🏗️ Построить", "🏗️ Строить"}))
async def menu_build(message: Message):
    await answer_topic_safe(
        message,
        "<b>🏗️ Развитие инфраструктуры</b>\n\n"
        "Выбери один объект. После строительства сбор ресурсов покажет новый эффект.",
        reply_markup=BUILD_INLINE,
    )


@dp.message(F.text == "🏛️ Политика")
async def menu_policy(message: Message):
    await cmd_policy(message)

@dp.message(F.text == "🤝 Дипломатия")
async def menu_diplomacy(message: Message):
    await cmd_alliances(message)

@dp.message(F.text == "📰 Новости")
async def menu_news(message: Message):
    await cmd_news(message)

@dp.message(F.text == "⚔️ Армия")
async def menu_army(message: Message):
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала основи страну: <code>/founding Бразилия</code>")
        return
    base_capacity = country["military_bases"] * config.MILITARY_PER_BASE
    factual_capacity = int(country["real_population"] * config.MAX_ARMY_POPULATION_SHARE / config.MILITARY_UNIT_SIZE) if country.get("real_population") else None
    demographic_text = f"\nДемографический предел: {factual_capacity:,}" if factual_capacity is not None else ""
    free_capacity = max(0, base_capacity - country['military'])
    await answer_topic_safe(
        message,
        f"⚔️ <b>Армия {esc(country['name'])}</b>\n\n"
        f"Сила: <b>{country['military']:,}/{base_capacity:,}</b> · свободно <b>{free_capacity:,}</b>\n"
        f"Базы: <b>{country['military_bases']}</b> · резерв: <b>{country['manpower']:,}</b>\n"
        f"Деньги: <b>{country['gold']:,}</b> · население: <b>{country['population']:,}</b>{esc(demographic_text)}\n\n"
        "Выбери одно действие ниже.",
        reply_markup=ARMY_INLINE,
    )


@dp.message(F.text == "☰ Ещё")
async def menu_more(message: Message):
    await answer_topic_safe(
        message,
        "<b>Ещё разделы</b>\nНовости, рейтинг, политика, дипломатия, ЧВК и помощь.",
        reply_markup=MORE_INLINE,
    )


async def render_pmc_dashboard(message: Message, owner_id: int | None = None):
    pmc = await db.get_pmc_by_owner(message.from_user.id)
    if not pmc:
        text = (
            "🏴 <b>Центр ЧВК</b>\n\n"
            "Здесь управляется самостоятельная организация, а не страна. ЧВК имеет собственные деньги, личный состав, репутацию, заказы и операции.\n\n"
            "<b>Начни так:</b>\n"
            "1. Создай организацию: <code>/pmc_create Название</code>\n"
            "2. Открой профиль и проверь стартовый бюджет.\n"
            "3. После создания используй кнопки ниже — в каждой карточке будет объяснено, что делать дальше.\n\n"
            "Страна для регистрации ЧВК не нужна."
        )
    else:
        label = "Террористическая организация" if pmc["org_type"] == "terror" else "ЧВК"
        pending_requests = await db.list_pmc_requests(pmc["id"], 20) if pmc["status"] == "active" else []
        personnel = int(pmc.get("personnel", 0) or 0)
        funds = int(pmc.get("inventory_gold", 0) or 0)
        if pmc["status"] != "active":
            next_step = "Организация временно недоступна. Обратись к куратору для уточнения статуса."
        elif pending_requests:
            next_step = f"📨 У тебя есть необработанные заказы: <b>{len(pending_requests)}</b>. Открой «Заказы» и прими или отклони их."
        elif personnel <= 0:
            next_step = "👥 Следующий шаг: набери первый личный состав командой <code>/pmc_recruit 2500</code>."
        elif personnel < 2500:
            next_step = "👥 Следующий шаг: доведи первый набор до 2 500 сотрудников, если хватает бюджета."
        else:
            next_step = "⚔️ Следующий шаг: подготовь реалистичную операцию через <code>/pmc_action описание</code> или опубликуй новость через <code>/pmc_news текст</code>."
        text = (
            f"🏴 <b>Центр {label}</b>\n\n"
            f"<b>{esc(pmc['name'])}</b> · ID <code>{pmc['id']}</code>\n"
            f"Статус: <b>{esc(pmc['status'])}</b> · репутация: <b>{pmc['reputation']}/100</b>\n"
            f"👥 Личный состав: <b>{personnel:,}</b>\n"
            f"💰 Бюджет ЧВК: <b>{funds:,}</b>\n"
            f"📨 Ожидающие заказы: <b>{len(pending_requests)}</b>\n\n"
            f"🧭 <b>Что делать сейчас</b>\n{next_step}\n\n"
            "<b>Разделы меню:</b> профиль показывает состояние организации; бюджет и набор развивают ресурсы; заказы дают работу; операция нужна для военного RP; новости формируют публичную историю.\n\n"
            "Статистика ЧВК и страны хранится отдельно. Для перехода к стране нажми «🌍 Страна»."
        )
    await answer_topic_safe(message, text, reply_markup=PMC_INLINE, owner_id=owner_id)


@dp.message(F.text == "🏴 ЧВК")
async def menu_pmc(message: Message):
    await render_pmc_dashboard(message)


@dp.callback_query(F.data == "mode:country")
async def callback_mode_country(callback: CallbackQuery):
    await callback.answer()
    country = await db.get_country(callback.from_user.id)
    if not country:
        await answer_topic_safe(callback.message, "Страна ещё не создана. Используй <code>/founding Название</code>.", reply_markup=PMC_INLINE, owner_id=callback.from_user.id)
        return
    await answer_topic_safe(callback.message, await format_country_summary(country), reply_markup=COUNTRY_INLINE, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "ui:pmc")
async def callback_pmc(callback: CallbackQuery):
    await callback.answer()
    await render_pmc_dashboard(callback.message.model_copy(update={"from_user": callback.from_user}), owner_id=callback.from_user.id)


@dp.callback_query(F.data == "pmc:profile")
async def callback_pmc_profile(callback: CallbackQuery):
    await finish_callback(callback, "/pmc_profile", cmd_pmc_profile, PMC_INLINE)


@dp.callback_query(F.data == "pmc:requests")
async def callback_pmc_requests(callback: CallbackQuery):
    await finish_callback(callback, "/pmc_requests", cmd_pmc_requests, PMC_INLINE)


@dp.callback_query(F.data == "pmc:list")
async def callback_pmc_list(callback: CallbackQuery):
    await finish_callback(callback, "/pmc_list", cmd_pmc_list, PMC_INLINE)


@dp.callback_query(F.data == "pmc:help")
async def callback_pmc_help(callback: CallbackQuery):
    await finish_callback(callback, "/pmc_help", cmd_pmc_help, PMC_INLINE)


@dp.callback_query(F.data.in_({"pmc:recruit", "pmc:fund", "pmc:action", "pmc:news"}))
async def callback_pmc_command_hint(callback: CallbackQuery):
    await callback.answer()
    hints = {
        "pmc:recruit": "👥 <b>Набор сотрудников</b>\n\nВведи команду отдельным сообщением:\n<code>/pmc_recruit количество</code>\n\nКД — 6 часов, максимум за один набор — 2 500 человек.",
        "pmc:fund": "💰 <b>Бюджет ЧВК</b>\n\nФинансирование от страны необязательно. Для добровольного перевода введи:\n<code>/pmc_fund сумма</code>",
        "pmc:action": "⚔️ <b>Военная операция</b>\n\nОпиши реалистичную операцию минимум 50 символами:\n<code>/pmc_action описание</code>\n\nКД — 10 минут. Статистика страны не изменяется.",
        "pmc:news": "📰 <b>Новость ЧВК</b>\n\nОпубликуй официальное сообщение минимум 50 символами:\n<code>/pmc_news текст</code>\n\nЛента новостей открывается кнопкой «Новости» после публикации.",
    }
    await answer_topic_safe(callback.message, hints[callback.data], reply_markup=PMC_INLINE, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "ui:more")
async def callback_more(callback: CallbackQuery):
    await callback.answer()
    await answer_topic_safe(callback.message, "<b>Ещё разделы</b>", reply_markup=MORE_INLINE, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "ui:back")
async def callback_back(callback: CallbackQuery):
    await callback.answer()
    await answer_topic_safe(callback.message, "<b>Главное меню</b>", reply_markup=MAIN_INLINE, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "ui:country")
async def callback_country(callback: CallbackQuery):
    await callback.answer()
    country = await db.get_country(callback.from_user.id)
    if not country:
        await answer_topic_safe(callback.message, "Сначала основи страну: <code>/founding Бразилия</code>", reply_markup=MAIN_INLINE, owner_id=callback.from_user.id)
        return
    await answer_topic_safe(callback.message, await format_country_summary(country), reply_markup=COUNTRY_INLINE, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "ui:economy")
async def callback_economy(callback: CallbackQuery):
    await callback.answer()
    country = await db.get_country(callback.from_user.id)
    if not country:
        await answer_topic_safe(callback.message, "Сначала основи страну: <code>/founding Бразилия</code>", reply_markup=MAIN_INLINE, owner_id=callback.from_user.id)
        return
    await answer_topic_safe(callback.message, await format_country_economy(country), reply_markup=ECONOMY_INLINE, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "eco:collect")
async def callback_economy_collect(callback: CallbackQuery):
    await finish_callback(callback, "/collect", cmd_collect, ECONOMY_INLINE)


@dp.callback_query(F.data == "eco:market")
async def callback_economy_market(callback: CallbackQuery):
    # cmd_market renders the final card itself; do not append a second menu
    # afterward, because active-message cleanup would immediately remove it.
    await finish_callback(callback, "/market", cmd_market, None)


@dp.callback_query(F.data == "army:mobilize:1")
async def callback_army_mobilize(callback: CallbackQuery):
    await finish_callback(callback, "/mobilize 1", cmd_mobilize, ARMY_INLINE)


@dp.callback_query(F.data == "army:base")
async def callback_army_base(callback: CallbackQuery):
    await finish_callback(callback, "/build_base", cmd_build_base, ARMY_INLINE)


@dp.callback_query(F.data == "ui:collect")
async def callback_collect(callback: CallbackQuery):
    await finish_callback(callback, "/collect", cmd_collect)


@dp.callback_query(F.data == "ui:build")
async def callback_build(callback: CallbackQuery):
    await callback.answer()
    await menu_build(callback_message(callback, "/build"))


@dp.callback_query(F.data.startswith("build:"))
async def callback_build_type(callback: CallbackQuery):
    await callback.answer()
    building = callback.data.split(":", 1)[1]
    if building == "base":
        await cmd_build_base(callback_message(callback, "/build_base"))
    elif building in ALL_BUILDINGS:
        await cmd_build(callback_message(callback, f"/build {building}"))
    else:
        await answer_topic_safe(callback.message, "Неизвестный тип постройки. Открой строительство заново.", owner_id=callback.from_user.id)
        return
    await answer_topic_safe(callback.message, "Меню разделов:", reply_markup=MAIN_INLINE, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "ui:army")
async def callback_army(callback: CallbackQuery):
    await finish_callback(callback, "/mobilize", menu_army)


@dp.callback_query(F.data == "ui:progress")
async def callback_progress(callback: CallbackQuery):
    await finish_callback(callback, "/progress", cmd_progress)


@dp.callback_query(F.data == "ui:news")
async def callback_news(callback: CallbackQuery):
    await finish_callback(callback, "/news", cmd_news)


@dp.callback_query(F.data == "ui:top")
async def callback_top(callback: CallbackQuery):
    await finish_callback(callback, "/top", cmd_top)


async def render_premium_shop(message: Message, owner_id: int | None = None):
    balance = await db.get_premium_balance(owner_id or message.from_user.id)
    items = await db.get_premium_items(owner_id or message.from_user.id)
    lines = [f"💎 <b>Магазин за {config.PREMIUM_CURRENCY_NAME}</b>", "", f"Баланс: <b>{balance:,} {config.PREMIUM_CURRENCY_SHORT}</b>", "", "Покупки дают игровые эффекты и списываются атомарно.", ""]
    for key, item in config.PREMIUM_SHOP.items():
        owned = items.get(key, 0)
        lines.append(f"{item['name']} — <b>{item['cost']} {config.PREMIUM_CURRENCY_SHORT}</b>\n{item['description']} · у тебя: {owned}")
    await answer_topic_safe(message, "\n".join(lines), reply_markup=PREMIUM_INLINE, owner_id=owner_id)


@dp.callback_query(F.data == "ui:premium")
async def callback_premium(callback: CallbackQuery):
    await callback.answer()
    await render_premium_shop(callback.message, owner_id=callback.from_user.id)


@dp.callback_query(F.data.startswith("premium:buy:"))
async def callback_premium_buy(callback: CallbackQuery):
    await callback.answer()
    item_key = callback.data.split(":", 2)[2]
    item = config.PREMIUM_SHOP.get(item_key)
    if not item:
        await answer_topic_safe(callback.message, "Товар больше недоступен.", reply_markup=PREMIUM_INLINE, owner_id=callback.from_user.id)
        return
    expires_at = int(time.time()) + 7 * 86400 if item_key == "premium_status" else None
    ok = await db.purchase_premium(callback.from_user.id, item_key, item["cost"], f"Покупка: {item['name']}", item.get("quantity", 1), expires_at)
    if not ok:
        await answer_topic_safe(callback.message, f"Недостаточно {config.PREMIUM_CURRENCY_NAME} или страна не зарегистрирована.", reply_markup=PREMIUM_INLINE, owner_id=callback.from_user.id)
        return
    await answer_topic_safe(callback.message, f"✅ Куплено: <b>{item['name']}</b>. Эффект: {item['description']}", reply_markup=PREMIUM_INLINE, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "ui:world")
async def callback_world(callback: CallbackQuery):
    await callback.answer()
    await render_world_events(callback.message, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "ui:trade")
async def callback_trade(callback: CallbackQuery):
    await callback.answer()
    await answer_topic_safe(callback.message, await _trade_list_text(callback.from_user.id), reply_markup=MORE_INLINE, owner_id=callback.from_user.id)


@dp.callback_query(F.data == "ui:policy")
async def callback_policy(callback: CallbackQuery):
    await finish_callback(callback, "/policy", cmd_policy)


@dp.callback_query(F.data == "ui:diplomacy")
async def callback_diplomacy(callback: CallbackQuery):
    await finish_callback(callback, "/alliances", cmd_alliances, MORE_INLINE)


@dp.callback_query(F.data == "ui:guide")
async def callback_guide(callback: CallbackQuery):
    await finish_callback(callback, "/guide", cmd_guide, MAIN_INLINE)


@dp.message(F.text == "⬅️ Назад")
async def menu_back(message: Message):
    await answer_topic_safe(message, "Главное меню", reply_markup=MAIN_INLINE)

# --- Альянсы ---

@dp.message(Command("alliances"))
async def cmd_alliances(message: Message):
    items = await db.list_alliances()
    if not items:
        await answer_topic_safe(message, "Альянсов пока нет. Основать: /alliance_create ТЕГ Название")
        return
    lines = ["🤝 <b>Альянсы</b>\n"]
    for a in items:
        lines.append(f"<b>{esc(a['tag'])}</b> — {esc(a['name'])} ({a['member_count']} стран)")
    await answer_topic_safe(message, "\n".join(lines))


@dp.message(Command("alliance_create"))
async def cmd_alliance_create(message: Message):
    """/alliance_create ТЕГ Название альянса"""
    parts = message.text.split(maxsplit=2)
    if len(parts) != 3:
        await answer_topic_safe(message, "Формат: <code>/alliance_create ТЕГ Название альянса</code>\nПример: <code>/alliance_create BRICS БРИКС</code>")
        return
    tag, name = parts[1].strip(), " ".join(parts[2].split())
    if len(tag) > config.MAX_ALLIANCE_TAG_LEN or len(name) > config.MAX_ALLIANCE_NAME_LEN:
        await answer_topic_safe(message,
            f"Тег до {config.MAX_ALLIANCE_TAG_LEN} символов, название до {config.MAX_ALLIANCE_NAME_LEN}."
        )
        return

    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала создай страну: /founding Название")
        return

    ok = await db.create_alliance(tag, name)
    if not ok:
        await answer_topic_safe(message, f"Тег «{esc(tag)}» уже занят. Выбери другой.")
        return

    alliance = await db.get_alliance_by_tag(tag)
    await db.join_alliance(message.from_user.id, alliance["id"])
    await answer_topic_safe(message, f"🤝 Альянс <b>{esc(tag)}</b> — {esc(name)} создан, ты в нём первый участник.")


@dp.message(Command("alliance_join"))
async def cmd_alliance_join(message: Message):
    """/alliance_join ТЕГ"""
    parts = message.text.split()
    if len(parts) != 2:
        await answer_topic_safe(message, "Формат: <code>/alliance_join ТЕГ</code>\nСписок — /alliances")
        return
    country = await db.get_country(message.from_user.id)
    if not country:
        await answer_topic_safe(message, "Сначала создай страну: /founding Название")
        return
    alliance = await db.get_alliance_by_tag(parts[1])
    if not alliance:
        await answer_topic_safe(message, "Такого альянса нет. Список — /alliances")
        return
    await db.join_alliance(message.from_user.id, alliance["id"])
    await answer_topic_safe(message, f"✅ «{esc(country['name'])}» вступила в <b>{esc(alliance['tag'])}</b> — {esc(alliance['name'])}.")


@dp.message(Command("alliance_leave"))
async def cmd_alliance_leave(message: Message):
    ok = await db.leave_alliance(message.from_user.id)
    if ok:
        await answer_topic_safe(message, "Вышли из альянса.")
    else:
        await answer_topic_safe(message, "Ты не состоишь ни в одном альянсе.")


@dp.message(Command("alliance_info"))
async def cmd_alliance_info(message: Message):
    parts = message.text.split()
    if len(parts) == 2:
        alliance = await db.get_alliance_by_tag(parts[1])
        if not alliance:
            await answer_topic_safe(message, "Такого альянса нет.")
            return
    else:
        alliance = await db.get_user_alliance(message.from_user.id)
        if not alliance:
            await answer_topic_safe(message, "Ты не в альянсе. Укажи тег: <code>/alliance_info ТЕГ</code>")
            return

    members = await db.get_alliance_members(alliance["id"])
    lines = [f"🤝 <b>{esc(alliance['tag'])}</b> — {esc(alliance['name'])}\n"]
    if not members:
        lines.append("Участников пока нет.")
    else:
        for m in members:
            lines.append(f"• {esc(m['name'])}")
    await answer_topic_safe(message, "\n".join(lines))


TRADE_ALIASES = {
    "ресурсы": "resources", "resource": "resources", "resources": "resources",
    "вода": "water", "water": "water", "еда": "food", "food": "food",
    "дерево": "wood", "wood": "wood", "железо": "iron", "iron": "iron",
    "уголь": "coal", "coal": "coal", "нефть": "oil", "oil": "oil",
    "уран": "uranium", "uranium": "uranium",
}


async def _trade_list_text(user_id: int) -> str:
    contracts = await db.list_trade_contracts(user_id)
    if not contracts:
        return "📜 <b>Торговые договоры</b>\n\nАктивных предложений нет.\n\nСоздать: <code>/trade_offer user_id ресурс количество цена</code>"
    lines = ["📜 <b>Торговые договоры</b>", ""]
    for item in contracts:
        role = "тебе предлагают" if item["target_id"] == user_id else "ты предложил"
        name = item["proposer_name"] if item["target_id"] == user_id else item["target_name"]
        lines.append(f"#{item['id']} · {role} стране <b>{esc(name or str(item['target_id']))}</b>")
        lines.append(f"{RESOURCE_NAMES_RU.get(item['resource'], item['resource'])}: {item['amount']:,} за 💰{item['price']:,}")
        if item["target_id"] == user_id:
            lines.append(f"Принять: <code>/trade_accept {item['id']}</code> · Отклонить: <code>/trade_reject {item['id']}</code>")
    return "\n".join(lines)


@dp.message(Command("sanction"))
async def cmd_sanction(message: Message):
    parts = message.text.split(maxsplit=4)
    if len(parts) < 5 or not parts[1].isdigit() or not parts[3].isdigit():
        await answer_topic_safe(message, "Формат: <code>/sanction user_id economic|trade|diplomatic дни причина</code>")
        return
    sanction_id = await db.create_country_sanction(message.from_user.id, int(parts[1]), parts[2].lower(), int(parts[3]), parts[4])
    if not sanction_id:
        await answer_topic_safe(message, "Не удалось наложить санкции. Проверь страну, тип, срок 1–30 дней, лимит в 3 активные санкции и отсутствие такого же действующего ограничения.")
        return
    await answer_topic_safe(message, f"⚠️ Санкции #{sanction_id} введены на {parts[3]} дн. Условия будут видны в <code>/sanctions</code>.")


@dp.message(Command("sanctions"))
async def cmd_sanctions(message: Message):
    items = await db.list_country_sanctions(message.from_user.id)
    if not items:
        await answer_topic_safe(message, "⚠️ У страны нет активных или недавних санкций.")
        return
    labels = {"economic": "экономические", "trade": "торговые", "diplomatic": "дипломатические"}
    lines = ["⚠️ <b>Санкции страны</b>", ""]
    for item in items:
        if item["issuer_id"] == message.from_user.id:
            other, role = item.get("target_name") or str(item["target_id"]), "введены против"
        else:
            other, role = item.get("issuer_name") or str(item["issuer_id"]), "наложены страной"
        lines.append(f"• #{item['id']} · {labels[item['sanction_type']]} · {role} <b>{esc(other)}</b> · <b>{item['status']}</b>\n  Причина: {esc(item['reason'])}")
    await answer_topic_safe(message, "\n\n".join(lines))


@dp.message(Command("pact_offer"))
async def cmd_pact_offer(message: Message):
    parts = message.text.split(maxsplit=4)
    if len(parts) < 5 or not parts[1].isdigit() or not parts[3].isdigit():
        await answer_topic_safe(message, "Формат: <code>/pact_offer user_id non_aggression|defense|trade дни условия</code>")
        return
    if int(parts[1]) == message.from_user.id:
        await answer_topic_safe(message, "Нельзя заключить пакт со своей страной.")
        return
    pact_id = await db.create_diplomatic_pact(message.from_user.id, int(parts[1]), parts[2], parts[4], int(parts[3]))
    if not pact_id:
        await answer_topic_safe(message, "Не удалось создать предложение. Проверь user_id, тип, срок от 1 до 30 дней и отсутствие действующего пакта с этой страной.")
        return
    await answer_topic_safe(message, f"🤝 Предложение пакта <b>#{pact_id}</b> создано. Страна получателя увидит его в <code>/pacts</code>.")


@dp.message(Command("pacts"))
async def cmd_pacts(message: Message):
    pacts = await db.list_diplomatic_pacts(message.from_user.id, 20)
    if not pacts:
        await answer_topic_safe(message, "🤝 У твоей страны пока нет дипломатических пактов.")
        return
    labels = {"non_aggression": "ненападение", "defense": "оборонный", "trade": "торговый"}
    lines = ["🤝 <b>Дипломатические пакты</b>", ""]
    for pact in pacts:
        if pact["proposer_id"] == message.from_user.id:
            other = pact.get("target_name") or str(pact["target_id"])
            direction = "ты предложил"
        else:
            other = pact.get("proposer_name") or str(pact["proposer_id"])
            direction = "тебе предложили"
        action = ""
        if pact["status"] == "pending" and pact["target_id"] == message.from_user.id:
            action = f" · принять: <code>/pact_accept {pact['id']}</code> или отклонить: <code>/pact_reject {pact['id']}</code>"
        lines.append(f"• Пакт #{pact['id']} · {labels.get(pact['pact_type'], pact['pact_type'])} · {direction} страна <b>{esc(other)}</b> · статус: <b>{pact['status']}</b>{action}\n  Условия: {esc(pact['terms'][:260])}")
    await answer_topic_safe(message, "\n\n".join(lines), reply_markup=MORE_INLINE)


@dp.message(Command("pact_accept"))
async def cmd_pact_accept(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/pact_accept ID</code>")
        return
    result = await db.resolve_diplomatic_pact(int(parts[1]), message.from_user.id, True)
    await answer_topic_safe(message, "✅ Пакт принят и действует до указанной даты." if result else "Пакт не найден, уже обработан или истёк.")


@dp.message(Command("pact_reject"))
async def cmd_pact_reject(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/pact_reject ID</code>")
        return
    result = await db.resolve_diplomatic_pact(int(parts[1]), message.from_user.id, False)
    await answer_topic_safe(message, "Пакт отклонён." if result else "Пакт не найден, уже обработан или истёк.")


@dp.message(Command("trade"))
async def cmd_trade(message: Message):
    await answer_topic_safe(message, await _trade_list_text(message.from_user.id), reply_markup=MORE_INLINE)


@dp.message(Command("trade_offer"))
async def cmd_trade_offer(message: Message):
    parts = message.text.split()
    if len(parts) != 5 or not parts[1].isdigit() or not parts[3].isdigit() or not parts[4].isdigit():
        await answer_topic_safe(message, "Формат: <code>/trade_offer user_id ресурс количество цена</code>\nПример: <code>/trade_offer 123456 wood 1000 500</code>")
        return
    target_id, amount, price = int(parts[1]), int(parts[3]), int(parts[4])
    resource = TRADE_ALIASES.get(parts[2].casefold())
    country = await db.get_country(message.from_user.id)
    target = await db.get_country(target_id)
    if not country or not target:
        await answer_topic_safe(message, "Обе страны должны быть зарегистрированы.")
        return
    if resource is None or amount <= 0 or price < 0:
        await answer_topic_safe(message, "Ресурс или количество указаны неверно. Доступны: resources, water, food, wood, iron, coal, oil, uranium.")
        return
    if country[resource] < amount:
        await answer_topic_safe(message, f"Недостаточно {RESOURCE_NAMES_RU.get(resource, resource)} для предложения.")
        return
    contract_id = await db.create_trade_contract(message.from_user.id, target_id, resource, amount, price, int(time.time()) + 7 * 86400)
    if not contract_id:
        await answer_topic_safe(message, "Не удалось создать договор. Проверь данные и попробуй снова.")
        return
    await answer_topic_safe(message, f"📜 Предложение #{contract_id} создано для страны <b>{esc(target['name'])}</b>. Ресурсы списываются только после принятия.", reply_markup=MORE_INLINE)
    try:
        await bot.send_message(target["chat_id"], f"📜 Страна <b>{esc(country['name'])}</b> предлагает договор #{contract_id}: {RESOURCE_NAMES_RU.get(resource, resource)} {amount:,} за 💰{price:,}.\nПринять: <code>/trade_accept {contract_id}</code>")
    except Exception:
        logger.info("Не удалось уведомить получателя торгового договора %s", contract_id, exc_info=True)


@dp.message(Command("trade_accept"))
async def cmd_trade_accept(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/trade_accept номер_договора</code>")
        return
    ok = await db.accept_trade_contract(int(parts[1]), message.from_user.id)
    await answer_topic_safe(message, "✅ Договор принят: ресурсы и деньги переведены атомарно." if ok else "❌ Договор нельзя принять: он уже закрыт, истёк или одной из сторон не хватает средств.", reply_markup=MORE_INLINE)


@dp.message(Command("trade_reject"))
async def cmd_trade_reject(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/trade_reject номер_договора</code>")
        return
    ok = await db.reject_trade_contract(int(parts[1]), message.from_user.id)
    await answer_topic_safe(message, "Договор отклонён." if ok else "Договор не найден или уже закрыт.", reply_markup=MORE_INLINE)


def _compact_rank_value(value: float) -> str:
    value = int(max(0, value))
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f} млрд"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} млн"
    return f"{value:,}".replace(",", " ")


async def build_world_rankings() -> list[str]:
    countries = await db.get_all_countries()
    if not countries:
        return []

    # Wealth is a transparent game score: capital is primary, economy and
    # productive reserves provide the strategic depth behind the balance.
    richest = sorted(
        countries,
        key=lambda c: (
            c.get("gold", 0) + c.get("economy", 0) * 1_000_000
            + c.get("resources", 0) * 2 + c.get("food", 0) + c.get("water", 0),
            c.get("gold", 0),
        ),
        reverse=True,
    )[:5]
    # Intimidation reflects actual military capacity, readiness and bases,
    # with technology and reputation as secondary factors.
    intimidating = sorted(
        countries,
        key=lambda c: (
            c.get("military", 0) + c.get("military_bases", 0) * 10
            + c.get("readiness", 0) * 2 + c.get("tech", 0) * 0.5
            + c.get("reputation", 0) * 0.25 - c.get("war_exhaustion", 0) * 0.5,
            c.get("military", 0),
        ),
        reverse=True,
    )[:5]

    rich_lines = ["💰 <b>САМЫЕ БОГАТЫЕ СТРАНЫ</b>", "", "Рейтинг капитала и экономической мощи мира:"]
    for index, country in enumerate(richest, 1):
        wealth = country.get("gold", 0) + country.get("economy", 0) * 1_000_000
        rich_lines.append(
            f"{index}. <b>{esc(country['name'])}</b> — капитал {_compact_rank_value(country.get('gold', 0))}; "
            f"экономика {country.get('economy', 0)} · общий индекс {_compact_rank_value(wealth)}"
        )

    fear_lines = ["🛡️ <b>САМЫЕ УСТРАШАЮЩИЕ СТРАНЫ МИРА</b>", "", "Рейтинг военной силы, готовности и способности вести войну:"]
    for index, country in enumerate(intimidating, 1):
        threat = country.get("military", 0) + country.get("military_bases", 0) * 10 + country.get("readiness", 0) * 2
        fear_lines.append(
            f"{index}. <b>{esc(country['name'])}</b> — армия {country.get('military', 0):,}; "
            f"базы {country.get('military_bases', 0)} · готовность {country.get('readiness', 0)} · индекс угрозы {int(threat)}"
        )
    return ["\n".join(rich_lines), "\n".join(fear_lines)]


async def render_world_events(message: Message, owner_id: int | None = None):
    events = await db.get_world_events(8)
    ranking_articles = await build_world_rankings()
    if not events and not ranking_articles:

        await answer_topic_safe(
            message,
            "🌎 <b>Мировая лента</b>\n\nАктивных глобальных событий пока нет.",
            reply_markup=MORE_INLINE,
            owner_id=owner_id,
        )
        return
    lines = ["🌎 <b>Мировая лента</b>", ""]
    for article in ranking_articles:
        lines.append(f"<i>📰 Газета · {time.strftime('%H:%M')}</i>\n{article}")
        lines.append("")
    for event in events:
        year = f" · {event['game_year']} год" if event.get("game_year") else ""
        lines.append(f"<b>{esc(event['title'])}</b>{year}\n{esc(event['description'])}")
    await answer_topic_safe(message, "\n\n".join(lines), reply_markup=MORE_INLINE, owner_id=owner_id)


@dp.message(Command("world"))
async def cmd_world(message: Message):
    await render_world_events(message)


@dp.message(Command("world_event"))
async def cmd_world_event(message: Message):
    if not is_admin(message.from_user.id):
        await answer_topic_safe(message, "Команда только для админов.")
        return
    payload = message.text.partition(" ")[2]
    parts = [part.strip() for part in payload.split("|", 2)]
    if len(parts) != 3 or not all(parts):
        await answer_topic_safe(message, "Формат: <code>/world_event тип | заголовок | описание</code>")
        return
    if len(parts[2]) < config.MIN_NARRATIVE_LEN:
        await answer_topic_safe(message, f"Описание новости должно содержать минимум {config.MIN_NARRATIVE_LEN} символов.")
        return
    latest_event_at = await db.get_latest_world_event_created_at()
    remaining = config.WORLD_EVENT_COOLDOWN_SECONDS - (int(time.time()) - latest_event_at)
    if remaining > 0:
        minutes, seconds = divmod(remaining, 60)
        await answer_topic_safe(message, f"⏳ Следующую мировую новость можно опубликовать через {minutes} мин {seconds} сек.")
        return
    year = await db.get_current_year()
    event_id = await db.create_world_event(parts[1], parts[2], parts[0], year)
    await answer_topic_safe(message, f"🌎 Глобальное событие #{event_id} опубликовано.")


# --- Админ-команды ---

@dp.message(Command("set_year"))
async def cmd_set_year(message: Message):
    """/set_year год — задать (или переустановить) текущий год мира. Дальше растёт сам."""
    if not is_admin(message.from_user.id):
        await answer_topic_safe(message, "Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await answer_topic_safe(message, "Формат: <code>/set_year год</code>\nПример: <code>/set_year 2140</code>")
        return
    year = int(parts[1])
    await db.set_world_year(year)
    await answer_topic_safe(message,
        f"📅 Год мира установлен: <b>{year}</b>.\n"
        f"Дальше он будет расти автоматически: 1 реальные сутки = 1 игровой год."
    )


@dp.message(Command("seed_alliances"))
async def cmd_seed_alliances(message: Message):
    """/seed_alliances — создать канонические альянсы (НАТО, ОДКБ и т.д.), обычно сразу после вайпа."""
    if not is_admin(message.from_user.id):
        await answer_topic_safe(message, "Команда только для админов.")
        return
    created, skipped = [], []
    for a in config.CANONICAL_ALLIANCES:
        ok = await db.create_alliance(a["tag"], a["name"])
        (created if ok else skipped).append(a["tag"])
    text = ""
    if created:
        text += f"✅ Созданы: {', '.join(created)}\n"
    if skipped:
        text += f"⏭️ Уже существовали: {', '.join(skipped)}\n"
    await answer_topic_safe(message, text or "Список канонических альянсов пуст.")


@dp.message(Command("premium_grant"))
async def cmd_premium_grant(message: Message):
    """Выдать Гаванские кредиты: /premium_grant user_id количество причина"""
    if not is_admin(message.from_user.id):
        await answer_topic_safe(message, "Команда только для админов.")
        return
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit() or int(parts[2]) <= 0:
        await answer_topic_safe(message, "Формат: <code>/premium_grant user_id количество причина</code>")
        return
    user_id, amount = int(parts[1]), int(parts[2])
    if not await db.get_country(user_id):
        await answer_topic_safe(message, "У этого user_id нет страны.")
        return
    reason = parts[3].strip() if len(parts) == 4 else "Административная выдача"
    await db.grant_premium(user_id, amount, reason, message.from_user.id)
    balance = await db.get_premium_balance(user_id)
    await answer_topic_safe(message, f"✅ Игроку {user_id} выдано {amount} {config.PREMIUM_CURRENCY_SHORT}. Баланс: {balance}.")


@dp.message(Command("premium"))
async def cmd_premium(message: Message):
    await render_premium_shop(message, owner_id=message.from_user.id)


@dp.message(Command("give_points"))
async def cmd_give_points(message: Message):
    """/give_points количество — всем; /give_points user_id количество — одному"""
    if not is_admin(message.from_user.id):
        await answer_topic_safe(message, "Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) == 2 and parts[1].isdigit():
        amount = int(parts[1])
        await db.set_points_all(amount)
        await answer_topic_safe(message, f"Всем странам начислено по {amount} очков развития.")
    elif len(parts) == 3 and parts[1].isdigit() and parts[2].lstrip("-").isdigit():
        user_id, amount = int(parts[1]), int(parts[2])
        target_country = await db.get_country(user_id)
        if not target_country:
            await answer_topic_safe(message, "У этого user_id нет страны.")
            return
        await db.update_stat(user_id, "points", amount)
        await answer_topic_safe(message, f"Игроку {user_id} начислено {amount} очков.")
    else:
        await answer_topic_safe(message,
            "Формат:\n<code>/give_points количество</code> — всем\n"
            "<code>/give_points user_id количество</code> — одному игроку"
        )


@dp.message(Command("set_stat"))
async def cmd_set_stat(message: Message):
    """/set_stat user_id характеристика значение — ручная правка"""
    if not is_admin(message.from_user.id):
        await answer_topic_safe(message, "Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) != 4 or not parts[1].isdigit() or parts[2] not in STAT_NAMES_RU:
        await answer_topic_safe(message, "Формат: <code>/set_stat user_id характеристика новое_значение</code>")
        return
    user_id, stat, value = int(parts[1]), parts[2], parts[3]
    if not value.lstrip("-").isdigit():
        await answer_topic_safe(message, "Значение должно быть числом.")
        return
    country = await db.get_country(user_id)
    if not country:
        await answer_topic_safe(message, "Такой страны нет.")
        return
    delta = int(value) - country[stat]
    await db.update_stat(user_id, stat, delta)
    await answer_topic_safe(message, f"Готово. {STAT_NAMES_RU[stat]} игрока {user_id} теперь {value}.")


@dp.message(Command("kick"))
async def cmd_kick(message: Message):
    """/kick user_id — убрать игрока со страны"""
    if not is_admin(message.from_user.id):
        await answer_topic_safe(message, "Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/kick user_id</code>")
        return
    user_id = int(parts[1])
    country = await db.get_country(user_id)
    if not country:
        await answer_topic_safe(message, "У этого игрока нет страны.")
        return
    ok = await db.delete_country(user_id)
    if ok:
        await answer_topic_safe(message, f"❌ Игрок {user_id} снят со страны «{esc(country['name'])}». Страна удалена.")
    else:
        await answer_topic_safe(message, "Не получилось удалить — попробуй ещё раз.")


@dp.message(Command("transfer"))
async def cmd_transfer(message: Message):
    """/transfer старый_id новый_id — передать страну другому игроку"""
    if not is_admin(message.from_user.id):
        await answer_topic_safe(message, "Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await answer_topic_safe(message, "Формат: <code>/transfer старый_user_id новый_user_id</code>")
        return
    old_id, new_id = int(parts[1]), int(parts[2])
    old_country = await db.get_country(old_id)
    if not old_country:
        await answer_topic_safe(message, "У старого user_id нет страны.")
        return
    ok = await db.transfer_country(old_id, new_id)
    if ok:
        await answer_topic_safe(message, f"✅ Страна «{esc(old_country['name'])}» передана от {old_id} к {new_id}.")
    else:
        await answer_topic_safe(message, "Не удалось передать: либо у нового user_id уже есть страна, либо старая не найдена.")


@dp.message(Command("pmc_create"))
async def cmd_pmc_create(message: Message):
    """Create one PMC or terrorist organization per owner."""
    payload = command_payload(message)
    parts = payload.split(maxsplit=1)
    org_type = "pmc"
    if parts and parts[0].casefold() in {"terror", "террор", "terrorist"}:
        org_type = "terror"
        parts = parts[1:]
    name = parts[0] if parts else ""
    if not name:
        await answer_topic_safe(message, "Формат: <code>/pmc_create Название</code> или <code>/pmc_create terror Название</code>")
        return
    pmc_id = await db.create_pmc(message.from_user.id, name, org_type)
    if not pmc_id:
        await answer_topic_safe(message, "Не удалось создать организацию. У владельца уже есть организация или это название занято.")
        return
    label = "террористическая организация" if org_type == "terror" else "ЧВК"
    await answer_topic_safe(message, f"✅ Создана отдельная организация: {label} <b>{esc(name)}</b> (ID: <code>{pmc_id}</code>).\nСтартовый бюджет организации: <b>{config.PMC_STARTING_FUNDS:,}</b>.\nПрофиль: <code>/pmc_profile</code>\nСтрана для создания не требуется; финансирование от страны — только добровольное спонсорство через <code>/pmc_fund</code>.", reply_markup=PMC_INLINE)


@dp.message(Command("pmc_help"))
async def cmd_pmc_help(message: Message):
    await answer_topic_safe(
        message,
        "🏴 <b>Как зарегистрироваться и играть за ЧВК</b>\n\n"
        "ЧВК — это отдельная ветка игры, а не продолжение развития страны. Страна для создания не нужна.\n\n"
        "<b>Шаг 1. Создай самостоятельную организацию</b>\n"
        "Введи: <code>/pmc_create Название ЧВК</code>. Организация получает собственный стартовый бюджет и профиль через <code>/pmc_profile</code>.\n\n"
        "<b>Шаг 2. Управляй инвентарём ЧВК</b>\n"
        "Личный состав, техника, репутация и средства ЧВК хранятся отдельно от страны. Если у владельца есть страна, она может добровольно спонсировать организацию через <code>/pmc_fund сумма</code>, но это не является обязательным.\n\n"
        "<b>Шаг 3. Набирай сотрудников</b>\n"
        "Команда: <code>/pmc_recruit количество</code>. За один набор — максимум 2 500 человек, между наборами действует КД 6 часов, общий предел — 250 000 сотрудников.\n\n"
        "<b>Шаг 4. Получай контракты от стран</b>\n"
        "Список организаций: <code>/pmc_list</code>. Страна может отправить тебе скрытый запрос: <code>/pmc_request ID описание</code>. Ты увидишь описание, но обычные игроки не увидят страну-заказчика.\n\n"
        "<b>Шаг 5. Решай по заказам</b>\n"
        "Проверь входящие запросы: <code>/pmc_requests</code>. Принять: <code>/pmc_accept номер</code>, отклонить: <code>/pmc_reject номер</code>.\n\n"
        "<b>Важно</b>\n"
        "Стране разрешено иметь максимум 2 активных договора с ЧВК. Анонимный заказ должен иметь понятную RP-причину. При нарушениях куратор может вынести предупреждение, очистить инвентарь, приостановить или дисквалифицировать организацию. Для террористической организации официальный набор и обычные анонимные заказы запрещены.",
        reply_markup=PMC_INLINE,
    )


@dp.message(Command("pmc_profile"))
async def cmd_pmc_profile(message: Message):
    pmc = await db.get_pmc_by_owner(message.from_user.id)
    if not pmc:
        await answer_topic_safe(message, "У тебя нет организации. Создай её через <code>/pmc_create Название</code>.")
        return
    label = "Террористическая организация" if pmc["org_type"] == "terror" else "ЧВК"
    await answer_topic_safe(
        message,
        f"🏴 <b>{label}: {esc(pmc['name'])}</b>\n"
        f"ID: <code>{pmc['id']}</code> · статус: <b>{pmc['status']}</b>\n"
        f"Репутация: <b>{pmc['reputation']}/100</b>\n"
        f"Личный состав: <b>{pmc['personnel']:,}/250 000</b>\n"
        f"Техника: <b>{pmc['equipment']:,}</b> · средства: <b>{pmc['inventory_gold']:,}</b>\n\n"
        "Запросы заказчиков: <code>/pmc_requests</code>\n"
        "Набор: <code>/pmc_recruit количество</code>",
        reply_markup=PMC_INLINE,
    )


@dp.message(Command("pmc_list"))
async def cmd_pmc_list(message: Message):
    items = await db.list_active_pmcs()
    if not items:
        await answer_topic_safe(message, "Активных организаций пока нет.")
        return
    lines = ["🏴 <b>Активные организации</b>", "", "Для анонимного запроса: <code>/pmc_request ID описание</code>", ""]
    for pmc in items:
        label = "Террор" if pmc["org_type"] == "terror" else "ЧВК"
        lines.append(f"<code>{pmc['id']}</code> · {label} <b>{esc(pmc['name'])}</b> · репутация {pmc['reputation']}/100")
    await answer_topic_safe(message, "\n".join(lines), reply_markup=PMC_INLINE)


@dp.message(Command("pmc_request"))
async def cmd_pmc_request(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit() or len(parts[2].strip()) < 30:
        await answer_topic_safe(message, "Формат: <code>/pmc_request ID описание</code>. Описание заказа — минимум 30 символов.")
        return
    country = await db.get_country(message.from_user.id)
    pmc = await db.get_pmc(int(parts[1]))
    if not country or not pmc or pmc["status"] != "active":
        await answer_topic_safe(message, "Страна или активная организация не найдена.")
        return
    if pmc["org_type"] == "terror":
        await answer_topic_safe(message, "Официальный анонимный заказ в террористическую организацию запрещён. Для неё действует отдельная скрытая RP-процедура куратора.")
        return
    request_id = await db.create_pmc_request(pmc["id"], message.from_user.id, parts[2].strip())
    if not request_id:
        await answer_topic_safe(message, "Нельзя создать запрос: у страны уже максимум 2 активных договора или организация недоступна.")
        return
    await hide_group_command(message)
    await answer_topic_safe(message, f"✅ Анонимный запрос #{request_id} отправлен в «{esc(pmc['name'])}».\nОбычные игроки не увидят страну-заказчика.")
    try:
        await bot.send_message(
            (await db.get_country(pmc["owner_id"]))["chat_id"] if await db.get_country(pmc["owner_id"]) else pmc["owner_id"],
            f"📨 Новый анонимный заказ #{request_id} для «{esc(pmc['name'])}».\n"
            f"Описание: {esc(parts[2].strip())}\n"
            f"Принять: <code>/pmc_accept {request_id}</code> · отклонить: <code>/pmc_reject {request_id}</code>",
        )
    except Exception:
        logger.info("Не удалось уведомить владельца ЧВК о запросе %s", request_id, exc_info=True)


@dp.message(Command("pmc_requests"))
async def cmd_pmc_requests(message: Message):
    pmc = await db.get_pmc_by_owner(message.from_user.id)
    if not pmc:
        await answer_topic_safe(message, "У тебя нет организации.")
        return
    if pmc.get("status") != "active":
        await answer_topic_safe(message, f"Организация «{esc(pmc['name'])}» сейчас имеет статус <b>{esc(pmc['status'])}</b> и не может принимать заказы.")
        return
    requests = await db.list_pmc_requests(pmc["id"])
    if not requests:
        await answer_topic_safe(message, "Новых анонимных запросов нет.")
        return
    lines = [f"📨 <b>Запросы «{esc(pmc['name'])}»</b>", ""]
    for item in requests:
        lines.append(f"#{item['id']} — {esc(item['request_text'])}\nПринять: <code>/pmc_accept {item['id']}</code> · отклонить: <code>/pmc_reject {item['id']}</code>")
    await answer_topic_safe(message, "\n".join(lines), reply_markup=PMC_INLINE)


@dp.message(Command("pmc_accept"))
async def cmd_pmc_accept(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/pmc_accept номер_запроса</code>")
        return
    result = await db.resolve_pmc_request(int(parts[1]), message.from_user.id, True)
    if not result:
        await answer_topic_safe(message, "Запрос не найден, уже обработан или лимит страны достигнут.")
        return
    await answer_topic_safe(message, f"✅ Анонимный запрос принят. Контракт: <code>{result['contract_id']}</code>.")
    requester = await db.get_country(result["country_id"])
    if requester:
        try:
            await bot.send_message(requester["chat_id"], f"✅ ЧВК приняла твой анонимный запрос #{result['id']}. Контракт: <code>{result['contract_id']}</code>.")
        except Exception:
            logger.info("Не удалось уведомить страну о принятии PMC-запроса", exc_info=True)


@dp.message(Command("pmc_reject"))
async def cmd_pmc_reject(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/pmc_reject номер_запроса</code>")
        return
    result = await db.resolve_pmc_request(int(parts[1]), message.from_user.id, False)
    await answer_topic_safe(message, "Запрос отклонён." if result else "Запрос не найден или уже обработан.", reply_markup=PMC_INLINE)


@dp.message(Command("pmc_action"))
async def cmd_pmc_action(message: Message):
    user_id = message.from_user.id
    action_text = command_payload(message)
    if len(action_text) < config.MIN_NARRATIVE_LEN:
        await answer_topic_safe(message, f"Описание операции должно содержать минимум {config.MIN_NARRATIVE_LEN} символов.")
        return
    pmc = await db.get_pmc_by_owner(user_id)
    if not pmc or pmc.get("status") != "active":
        await answer_topic_safe(message, "Сначала создай активную ЧВК: <code>/pmc_create Название</code>")
        return
    if pmc.get("org_type") == "terror":
        await answer_topic_safe(message, "Публичный военный вердикт для террористической организации запрещён. Нужна отдельная RP-процедура куратора.")
        return
    current_year = await db.get_current_year()
    if current_year is None:
        await answer_topic_safe(message, "Администратор ещё не задал год мира через <code>/set_year год</code>.")
        return
    lock = get_user_lock(user_id)
    async with lock:
        if user_id in _ai_inflight:
            await answer_topic_safe(message, "⏳ Предыдущая операция ЧВК ещё обрабатывается. Дождись результата.")
            return
        remaining = await db.get_pmc_action_cooldown(pmc["id"])
        if remaining > 0:
            await answer_topic_safe(message, f"⏳ Следующий военный вердикт ЧВК можно запросить через <b>{format_duration(remaining)}</b>.")
            return
        _ai_inflight.add(user_id)
    actor = {"name": pmc["name"], "economy": 0, "military": pmc.get("personnel", 0), "military_bases": 0, "tech": 0, "diplomacy": pmc.get("reputation", 0), "stability": pmc.get("reputation", 50), "readiness": 50, "war_exhaustion": 0, "reputation": pmc.get("reputation", 50)}
    thinking = await message.answer("⚔️ Куратор оценивает операцию ЧВК...")
    try:
        verdict = await ai.get_verdict(actor, action_text, world_context=f"Текущий год мира: {current_year}. Это самостоятельная операция легальной ЧВК. Не меняй характеристики страны и не считай ЧВК государством.")
        if verdict.get("success") == "error":
            await thinking.edit_text(esc(verdict.get("verdict_text", "⚠️ Не удалось получить вердикт.")))
            return
        await db.touch_pmc_action(pmc["id"], user_id)
        await thinking.edit_text(f"📜 <b>Военный вердикт ЧВК «{esc(pmc['name'])}»</b> ({current_year} год)\n\n{verdict['verdict_text']}\n\n<i>Вердикт не изменяет статистику страны автоматически.</i>", reply_markup=PMC_INLINE)
    finally:
        _ai_inflight.discard(user_id)


@dp.message(Command("pmc_news"))
async def cmd_pmc_news(message: Message):
    pmc = await db.get_pmc_by_owner(message.from_user.id)
    if not pmc or pmc.get("status") != "active":
        await answer_topic_safe(message, "Сначала создай активную ЧВК.")
        return
    if pmc.get("org_type") == "terror":
        await answer_topic_safe(message, "Террористическая организация не может публиковать официальные новости. Для скрытой RP-подачи нужен куратор.")
        return
    statement = command_payload(message)
    if len(statement) < config.MIN_NARRATIVE_LEN:
        await answer_topic_safe(message, f"Новость ЧВК должна содержать минимум {config.MIN_NARRATIVE_LEN} символов.")
        return
    recent = await db.get_recent_pmc_statements(50)
    last = next((item for item in recent if item["pmc_id"] == pmc["id"]), None)
    if last and int(time.time()) - int(last["created_at"]) < config.STATEMENT_COOLDOWN_SECONDS:
        await answer_topic_safe(message, f"Следующую новость ЧВК можно опубликовать через <b>{format_duration(config.STATEMENT_COOLDOWN_SECONDS - (int(time.time()) - int(last['created_at'])))}</b>.")
        return
    year = await db.get_current_year()
    statement_id = await db.create_pmc_statement(pmc["id"], pmc["name"], statement, year)
    if not statement_id:
        await answer_topic_safe(message, "Новость не опубликована: кулдаун уже действует или организация недоступна.")
        return
    await answer_topic_safe(message, f"📰 Новость ЧВК «{esc(pmc['name'])}» опубликована под номером <b>#{statement_id}</b>.", reply_markup=PMC_INLINE)


@dp.message(Command("pmc_news_feed"))
async def cmd_pmc_news_feed(message: Message):
    statements = await db.get_recent_pmc_statements(12)
    if not statements:
        await answer_topic_safe(message, "📰 Публичных новостей ЧВК пока нет.", reply_markup=PMC_INLINE)
        return
    lines = ["📰 <b>Новости ЧВК</b>", ""]
    for item in statements:
        year = f" · {item['game_year']} год" if item.get("game_year") else ""
        lines.append(f"• <b>{esc(item['organization_name'])}</b>{year}\n{esc(item['statement'][:500])}")
    await answer_topic_safe(message, "\n\n".join(lines), reply_markup=PMC_INLINE)
@dp.message(Command("pmc_fund"))
async def cmd_pmc_fund(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
        await answer_topic_safe(message, "Формат: <code>/pmc_fund сумма</code>")
        return
    pmc = await db.get_pmc_by_owner(message.from_user.id)
    if not pmc:
        await answer_topic_safe(message, "Сначала создай организацию.")
        return
    amount = int(parts[1])
    ok = await db.fund_pmc(pmc["id"], message.from_user.id, amount)
    await answer_topic_safe(message, f"✅ В инвентарь организации внесено 💰{amount:,}." if ok else "❌ Недостаточно денег страны или организация недоступна.", reply_markup=PMC_INLINE)


@dp.message(Command("pmc_recruit"))
async def cmd_pmc_recruit(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/pmc_recruit количество</code>. Максимум за набор — 2 500 человек.")
        return
    pmc = await db.get_pmc_by_owner(message.from_user.id)
    if not pmc:
        await answer_topic_safe(message, "Сначала создай организацию.")
        return
    if pmc["org_type"] == "terror":
        await answer_topic_safe(message, "Официальный набор террористической организации запрещён. Нужна отдельная скрытая RP-отыгровка и решение куратора.")
        return
    ok, detail = await db.recruit_pmc(pmc["id"], message.from_user.id, int(parts[1]))
    errors = {"batch_limit": "За один набор можно принять максимум 2 500 человек.", "cooldown": "КД набора ещё не закончился — он составляет 6 часов.", "personnel_limit": "Достигнут предел 250 000 служащих.", "funds": "Недостаточно средств в инвентаре ЧВК.", "not_owner": "Организация недоступна или ты не её владелец."}
    await answer_topic_safe(message, f"✅ Набор завершён. Затрачено средств: {detail:,}." if ok else f"❌ {errors.get(detail, 'Набор отклонён.')}" , reply_markup=PMC_INLINE)


@dp.message(Command("pmc_sanction"))
async def cmd_pmc_sanction(message: Message):
    if not is_admin(message.from_user.id):
        await answer_topic_safe(message, "Команда только для куратора/администратора.")
        return
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4 or not parts[1].isdigit():
        await answer_topic_safe(message, "Формат: <code>/pmc_sanction ID warn|inventory_clear|suspend|disqualify причина</code>")
        return
    ok = await db.sanction_pmc(int(parts[1]), parts[2], parts[3], message.from_user.id)
    await answer_topic_safe(message, "✅ Санкция применена и записана в журнал." if ok else "❌ Организация не найдена или тип санкции указан неверно.")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = BEGINNER_GUIDE
    if message.chat.type in ("group", "supergroup"):
        text += (
            "\n\n<b>👥 В группе</b>\n"
            "Если бот не видит команду, используй <code>/help@имя_бота</code> "
            "или отключи Privacy Mode через BotFather."
        )
    text += (
        "\n\n<b>🏴 ЧВК и анонимные заказы</b>\n"
        "<code>/pmc_create Название</code> — создать ЧВК\n"
        "<code>/pmc_create terror Название</code> — создать террористическую организацию\n"
        "<code>/pmc_list</code> — список организаций\n"
        "<code>/pmc_request ID описание</code> — анонимно предложить заказ\n"
        "<code>/pmc_profile</code> — профиль своей организации\n"
        "<code>/pmc_requests</code> — входящие заказы ЧВК\n"
        "<code>/pmc_fund сумма</code> — перевести деньги страны в инвентарь\n"
        "<code>/pmc_recruit количество</code> — набор (КД 6 часов)\n"
        "<code>/pmc_action описание</code> — военный вердикт самостоятельной операции ЧВК (КД 10 минут)\n"
        "<code>/pmc_news текст</code> — официальная новость ЧВК\n"
        "<code>/pmc_news_feed</code> — публичная лента новостей ЧВК\n"
        "<code>/pmc_help</code> — подробная инструкция по регистрации и работе ЧВК\n"
        "<code>/war_history</code> — история завершённых войн своей страны\n"
        "<code>/statement текст</code> — официальное заявление страны (КД 30 минут)\n"
        "<code>/statements</code> — публичная лента заявлений стран\n"
        "<code>/pact_offer ID тип дни условия</code> — предложить дипломатический пакт\n"
        "<code>/pacts</code> — свои предложения и действующие пакты\n"
        "<code>/pact_accept ID</code> / <code>/pact_reject ID</code> — ответить на предложение\n"
        "<code>/sanction ID тип дни причина</code> — наложить санкции на страну\n"
        "<code>/sanctions</code> — действующие и недавние санкции\n"
        "<code>/priority</code> — приоритет гражданского производства или армии\n"
        "<code>/tax</code> — налоговая ставка и налоги населения\n"
    )
    if is_admin(message.from_user.id):
        text += "\n<b>🔐 Панель администратора</b>\n<code>/pmc_sanction ID тип причина</code> — санкция ЧВК."

    await answer_topic_safe(message, text, reply_markup=MAIN_INLINE)


@dp.message(F.text.regexp(r"^/"))
async def unknown_group_command(message: Message):
    if message.chat.type in ("group", "supergroup"):
        await answer_topic_safe(
            message,
            "Не понял эту команду. Открой подсказку: <code>/help</code> или <code>/help@имя_бота</code>.",
            reply_markup=MAIN_INLINE,
        )


# Reply keyboards send ordinary text messages. If Telegram still has an older
# keyboard cached, or a user sends a label with a minor text mismatch, do not
# silently ignore it: explain the available route and restore the menu.
@dp.message(F.text)
async def unhandled_text(message: Message):
    text = (message.text or "").strip()
    if not text:
        return
    await answer_topic_safe(
        message,
        "Я не распознал этот пункт меню. Используй кнопки ниже или открой <b>📖 Помощь</b>.",
        reply_markup=MAIN_INLINE,
    )


@dp.error()
async def on_error(event: ErrorEvent):
    """
    Общий обработчик ошибок хендлеров. Без него необработанное исключение в одной
    команде (например TelegramBadRequest из-за неэкранированного HTML, сетевой сбой,
    и т.п.) просто тихо логируется aiogram и пользователь остаётся без ответа —
    здесь мы дополнительно логируем с трейсбеком и, если возможно, сообщаем
    пользователю, что что-то пошло не так, вместо молчания.
    """
    logger.exception("Необработанная ошибка при обработке апдейта: %s", event.exception)
    update = event.update
    message = update.message if update else None
    if message is not None:
        try:
            await answer_topic_safe(message, "⚠️ Что-то пошло не так при обработке команды. Попробуй ещё раз чуть позже.")
        except TelegramBadRequest:
            pass


async def _run_healthcheck_server():
    """Нужен только если сервис на Render запущен как Web Service (не Background Worker)."""
    from aiohttp import web

    async def health(request):
        return web.Response(text="ВПИ ГАВАНЬ бот жив")

    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


async def main():
    await db.init_db()
    if not await db.check_integrity():
        raise RuntimeError("SQLite integrity check failed; refusing to start with a corrupted database")
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
        if not os.path.isabs(config.DB_PATH):
            logger.warning("DB_PATH=%s is relative on Render; use a Persistent Disk path or external database to prevent data loss after redeploy", config.DB_PATH)
    if os.getenv("RENDER_WEB_SERVICE") == "1":
        await _run_healthcheck_server()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
