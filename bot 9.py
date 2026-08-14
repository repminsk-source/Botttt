import asyncio
import html
import logging
import os
import random
import time

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import ErrorEvent, Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
import db
import ai
import countries
import territory
import market

# Объединённый список построек: старые (BUILDINGS) + новые сырьевые (RESOURCE_BUILDINGS).
# Собран в один словарь, чтобы /build, /collect и format_country работали с обоими
# наборами построек одинаковым общим кодом, не дублируя логику.
ALL_BUILDINGS = {**config.BUILDINGS, **config.RESOURCE_BUILDINGS}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gavan")

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def esc(text) -> str:
    """
    Экранирует текст перед вставкой в HTML-сообщение.
    Используется для ЛЮБОГО текста, пришедшего от игрока (название страны, действие)
    или от ИИ (вердикт) — иначе символы <, >, & ломают HTML-разметку Telegram,
    и message.answer/edit_text падает с ошибкой "can't parse entities".
    """
    return html.escape(str(text), quote=False)

STAT_NAMES_RU = {
    "economy": "Экономика",
    "military": "Армия",
    "population": "Население",
    "tech": "Технологии",
    "diplomacy": "Дипломатия",
}

RESOURCE_NAMES_RU = {
    "gold": "💰 Золото",
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
        [KeyboardButton(text="📊 Моя страна"), KeyboardButton(text="📖 Что делать?")],
        [KeyboardButton(text="📥 Собрать ресурсы"), KeyboardButton(text="🏗️ Построить")],
        [KeyboardButton(text="⚔️ Армия"), KeyboardButton(text="🌍 Рейтинг")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие или введи команду",
)


def next_step_hint(country: dict, buildings: dict | None = None) -> str:
    if buildings is None:
        buildings = {}
    if not buildings:
        return "🎯 Следующий шаг: построй ферму — <code>/build farm</code>, затем собери доход через <code>/collect</code>."
    if not buildings.get("mine"):
        return "🎯 Следующий шаг: построй шахту — <code>/build mine</code>, чтобы получать ресурсы для новых построек."
    if not buildings.get("market"):
        return "🎯 Следующий шаг: построй рынок — <code>/build market</code>, чтобы получать золото."
    if country["manpower"] >= config.MOBILIZE_MANPOWER_PER_POINT and country["gold"] >= config.MOBILIZE_GOLD_PER_POINT:
        return "🎯 Следующий шаг: мобилизуй армию — <code>/mobilize 1</code>."
    return "🎯 Следующий шаг: используй <code>/collect</code>, накопи ресурсы и затем мобилизуй армию."


def clamp_country_changes(country: dict, changes: dict) -> dict:
    """Clamp AI deltas so stats stay non-negative and population stays within territory."""
    result = {}
    for stat in STAT_NAMES_RU:
        try:
            delta = int((changes or {}).get(stat, 0) or 0)
        except (TypeError, ValueError):
            delta = 0
        new_value = max(0, country[stat] + delta)
        if stat == "population":
            tier = country.get("territory_tier", "medium")
            cap = config.TERRITORY_POPULATION_CAP.get(tier, config.TERRITORY_POPULATION_CAP["medium"])
            new_value = min(cap, new_value)
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
    return sent


async def format_country(c: dict) -> str:
    buildings = await db.get_buildings(c["user_id"])
    tier = c.get("territory_tier", "medium")
    pop_cap = config.TERRITORY_POPULATION_CAP.get(tier, config.TERRITORY_POPULATION_CAP["medium"])
    base_cap = config.TERRITORY_BASE_BONUS.get(tier, 0) + c["military"] // config.MILITARY_PER_BASE
    alliance = await db.get_user_alliance(c["user_id"])

    text = (
        f"🏳️ <b>{esc(c['name'])}</b> ({territory.TIER_LABEL_RU.get(tier, tier)})\n"
    )
    if alliance:
        text += f"🤝 Альянс: <b>{esc(alliance['tag'])}</b> — {esc(alliance['name'])}\n"
    text += (
        f"\n<b>Характеристики:</b>\n"
        f"💰 Экономика: {c['economy']}\n"
        f"⚔️ Армия: {c['military']}\n"
        f"👥 Население: {c['population']} / {pop_cap}\n"
        f"🔬 Технологии: {c['tech']}\n"
        f"🤝 Дипломатия: {c['diplomacy']}\n\n"
        f"<b>Ресурсы:</b>\n"
        f"💰 Золото: {c['gold']}\n"
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
    text += "\n" + next_step_hint(c, buildings)
    return text


@dp.message(CommandStart())
async def cmd_start(message: Message):
    existing = await db.get_country(message.from_user.id)
    if existing:
        await animate(message, ["🌍 Загружаю твою державу…", "✅ С возвращением в ВПИ ГАВАНЬ!"])
        await message.answer("Начни с кнопки «📊 Моя страна». Я буду подсказывать следующий шаг.", reply_markup=MAIN_KEYBOARD)
        return
    await animate(message, ["🌍 Добро пожаловать в ВПИ ГАВАНЬ…", "🗺️ Здесь ты строишь страну, развиваешь армию и влияешь на мир."])
    await message.answer(
        "<b>Начинаем с одного шага:</b> напиши название реальной страны.\n\n"
        "Пример: <code>/founding Бразилия</code>\n\n"
        "После основания я покажу, что делать дальше.",
        reply_markup=MAIN_KEYBOARD,
    )


_founding_lock = asyncio.Lock()  # общий лок, чтобы два игрока не заняли одну страну одновременно


@dp.message(Command("founding"))
async def cmd_founding(message: Message):
    name = message.text.replace("/founding", "", 1).strip()
    # Схлопываем переносы строк/табы, чтобы название не разрывало сообщения
    # в несколько "строк" интерфейса и не пряталось за счёт \n внутри <b>...</b>.
    name = " ".join(name.split())
    if not name:
        await message.answer(
            "Играть можно только за реально существующую страну мира.\n"
            "Укажи название: <code>/founding Бразилия</code>"
        )
        return
    if len(name) > 64:
        await message.answer("Слишком длинное название страны (макс 64 символа).")
        return

    canonical = countries.match_country(name)
    if canonical is None:
        await message.answer(
            f"«{esc(name)}» не похоже на название реальной страны.\n"
            "В этой игре можно основать только существующую страну мира — например: "
            "<code>/founding Бразилия</code>, <code>/founding Египет</code>, <code>/founding Индонезия</code>."
        )
        return

    async with get_user_lock(message.from_user.id):
        existing = await db.get_country(message.from_user.id)
        if existing:
            await message.answer("У тебя уже есть страна. Используй /country чтобы посмотреть её.")
            return

    async with _founding_lock:
        taken = await db.get_country_by_name(canonical)
        if taken:
            await message.answer(f"«{esc(canonical)}» уже занята другим игроком. Выбери другую страну.")
            return
        tier = territory.get_tier(canonical)
        created = await db.create_country(message.from_user.id, message.chat.id, canonical, tier)
        if not created:
            await message.answer(f"«{esc(canonical)}» уже занята другим игроком. Выбери другую страну.")
            return
        country = await db.get_country(message.from_user.id)
        if not country:
            await message.answer("Не удалось сохранить страну. Повтори попытку позже.")
            return

    await message.answer(f"Страна основана! 🎉\n\n{await format_country(country)}")


@dp.message(Command("country"))
async def cmd_country(message: Message):
    country = await db.get_country(message.from_user.id)
    if not country:
        await message.answer("У тебя ещё нет страны. Создай через /founding Название")
        return
    await message.answer(await format_country(country))


@dp.message(Command("top"))
async def cmd_top(message: Message):
    countries = await db.get_all_countries()
    if not countries:
        await message.answer("Пока никто не зарегистрировал страну.")
        return
    lines = ["🏆 <b>Рейтинг стран</b>\n"]
    for i, c in enumerate(countries[:15], start=1):
        total = c["economy"] + c["military"] + c["population"] + c["tech"] + c["diplomacy"]
        lines.append(f"{i}. {esc(c['name'])} — {total} очков силы")
    await message.answer("\n".join(lines))


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
        await message.answer(
            "Формат: <code>/upgrade характеристика количество</code>\n"
            "Характеристики: economy, military, population, tech, diplomacy\n"
            "Пример: <code>/upgrade tech 3</code>\n\n"
            "⚠️ Армия качается не отсюда, а через /mobilize (нужны резерв людей и золото)."
        )
        return

    _, stat, amount_str = parts
    stat = stat.lower()
    if stat not in STAT_NAMES_RU:
        await message.answer("Неизвестная характеристика. Доступно: economy, military, population, tech, diplomacy")
        return
    if stat == "military":
        await message.answer("Армия качается через /mobilize количество — нужны резерв людей и золото.")
        return
    if not amount_str.isdigit() or int(amount_str) <= 0:
        await message.answer("Количество должно быть положительным числом.")
        return
    amount = int(amount_str)

    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await message.answer("Сначала создай страну: /founding Название")
            return

        if stat == "economy":
            cost = _economy_upgrade_cost(country["economy"], amount)
        else:
            cost = amount * config.UPGRADE_COST

        if stat == "population":
            tier = country.get("territory_tier", "medium")
            pop_cap = config.TERRITORY_POPULATION_CAP.get(tier, config.TERRITORY_POPULATION_CAP["medium"])
            if country["population"] + amount > pop_cap:
                await message.answer(
                    f"Население ограничено территорией страны: максимум {pop_cap} "
                    f"({territory.TIER_LABEL_RU.get(tier, tier)}). Сейчас: {country['population']}."
                )
                return

        if country["points"] < cost:
            await message.answer(f"Недостаточно очков развития. Нужно {cost}, у тебя {country['points']}.")
            return

        applied = await db.apply_upgrade(message.from_user.id, stat, amount, cost)
        if not applied:
            await message.answer("Очки развития изменились во время операции. Повтори команду.")
            return

        updated = await db.get_country(message.from_user.id)

    await message.answer(
        f"✅ {STAT_NAMES_RU[stat]} увеличена на {amount} (потрачено {cost} очков).\n\n{await format_country(updated)}"
    )


@dp.message(Command("build"))
async def cmd_build(message: Message):
    """/build тип — построить или улучшить одну из построек."""
    parts = message.text.split()
    if len(parts) != 2 or parts[1].lower() not in ALL_BUILDINGS:
        options = ", ".join(f"{k} ({v['name']})" for k, v in ALL_BUILDINGS.items())
        await message.answer(f"Формат: <code>/build тип</code>\nДоступно: {options}")
        return
    b_type = parts[1].lower()
    info = ALL_BUILDINGS[b_type]

    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await message.answer("Сначала создай страну: /founding Название")
            return

        required_tech = config.TECH_GATE_BUILDINGS.get(b_type, 0)
        if country["tech"] < required_tech:
            await message.answer(
                f"🔬 Для постройки {info['name']} нужен уровень технологий {required_tech}. "
                f"Сейчас: {country['tech']}. Используй <code>/upgrade tech 1</code>."
            )
            return

        level = await db.get_building_level(message.from_user.id, b_type)
        tier = country.get("territory_tier", "medium")
        level_cap = config.TERRITORY_BUILDING_LEVEL_CAP.get(tier, config.TERRITORY_BUILDING_LEVEL_CAP["medium"])
        if level + 1 > level_cap:
            await message.answer(
                f"Территория страны не позволяет строить {info['name']} выше уровня {level_cap} "
                f"({territory.TIER_LABEL_RU.get(tier, tier)})."
            )
            return

        cost_gold = info["cost_gold"] * (level + 1)
        cost_resources = info["cost_resources"] * (level + 1)
        if country["gold"] < cost_gold or country["resources"] < cost_resources:
            await message.answer(
                f"Недостаточно ресурсов для улучшения {info['name']} до ур. {level + 1}.\n"
                f"Нужно: 💰{cost_gold} золота, 📦{cost_resources} ресурсов.\n"
                f"У тебя: 💰{country['gold']}, 📦{country['resources']}."
            )
            return

        applied = await db.apply_building_upgrade(
            message.from_user.id, b_type, cost_gold, cost_resources
        )
        if not applied:
            await message.answer("Ресурсы изменились во время операции. Повтори команду.")
            return

    await message.answer(
        f"🏗️ {info['emoji']} {info['name']} улучшена до уровня {level + 1}!\n"
        f"Даёт {info['produces_name']} при каждом /collect."
    )


@dp.message(Command("collect"))
async def cmd_collect(message: Message):
    """Сбор ресурсов с построек, раз в COLLECT_COOLDOWN_SECONDS"""
    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await message.answer("Сначала создай страну: /founding Название")
            return

        elapsed = int(time.time()) - country.get("last_collect_at", 0)
        remaining = config.COLLECT_COOLDOWN_SECONDS - elapsed
        if remaining > 0:
            mins, secs = remaining // 60, remaining % 60
            await message.answer(f"⏳ Собирать ресурсы можно раз в {config.COLLECT_COOLDOWN_SECONDS // 60} мин. Осталось: {mins} мин {secs} сек.")
            return

        buildings = await db.get_buildings(message.from_user.id)
        # Список ресурсов берём из ALL_BUILDINGS, а не хардкодим — так добавление
        # новой постройки/ресурса в config.py не требует правки этого места.
        gains = {info["produces"]: 0 for info in ALL_BUILDINGS.values()}
        for b_type, level in buildings.items():
            info = ALL_BUILDINGS.get(b_type)
            if not info or level <= 0:
                continue
            gains[info["produces"]] += level * info["amount_per_level"]

        # Постепенный прирост экономики от развитых построек (шахта + рынок)
        mine_level = buildings.get("mine", 0)
        market_level = buildings.get("market", 0)
        economy_growth = (mine_level + market_level) // config.ECONOMY_GROWTH_DIVISOR

        # Накопленная еда сверх порога уходит на рост населения — делает еду
        # не просто ещё одним числом, а ресурсом с игровым эффектом.
        # Рост ограничен потолком населения по территории страны.
        population_growth = 0
        food_spend = 0
        current_food = country["food"] + gains.get("food", 0)
        if current_food >= config.FOOD_GROWTH_THRESHOLD:
            tier = country.get("territory_tier", "medium")
            pop_cap = config.TERRITORY_POPULATION_CAP.get(tier, config.TERRITORY_POPULATION_CAP["medium"])
            possible_growth = current_food // config.FOOD_GROWTH_THRESHOLD
            population_growth = min(possible_growth, max(0, pop_cap - country["population"]))
            if population_growth > 0:
                food_spend = population_growth * config.FOOD_GROWTH_THRESHOLD
            else:
                food_spend = 0

        applied = await db.apply_collect(
            message.from_user.id,
            gains,
            economy_growth,
            food_spend,
            population_growth,
            int(time.time()),
        )
        if not applied:
            await message.answer("Состояние страны изменилось во время сбора. Повтори команду.")
            return

    lines = ["📥 <b>Сбор ресурсов</b>\n"]
    any_gain = False
    for resource, amount in gains.items():
        if amount > 0:
            any_gain = True
            lines.append(f"{RESOURCE_NAMES_RU[resource]}: +{amount}")
    if not any_gain:
        lines.append("Построек пока нет — используй /build чтобы начать что-то производить.")
    if economy_growth > 0:
        lines.append(f"💰 Экономика: +{economy_growth} (от развития построек)")
    if population_growth > 0:
        lines.append(f"👥 Население: +{population_growth} (от накопленной еды)")

    await message.answer("\n".join(lines))


@dp.message(Command("mobilize"))
async def cmd_mobilize(message: Message):
    """/mobilize количество — прокачать армию за резерв людей + золото"""
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
        await message.answer(
            f"Формат: <code>/mobilize количество</code>\n"
            f"Стоимость 1 пункта армии: {config.MOBILIZE_MANPOWER_PER_POINT} резерва людей + {config.MOBILIZE_GOLD_PER_POINT} золота."
        )
        return
    amount = int(parts[1])

    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await message.answer("Сначала создай страну: /founding Название")
            return

        cost_manpower = amount * config.MOBILIZE_MANPOWER_PER_POINT
        cost_gold = amount * config.MOBILIZE_GOLD_PER_POINT

        if country["manpower"] < cost_manpower or country["gold"] < cost_gold:
            await message.answer(
                f"Недостаточно ресурсов для мобилизации +{amount} к армии.\n"
                f"Нужно: 🧑‍🤝‍🧑{cost_manpower} резерва, 💰{cost_gold} золота.\n"
                f"У тебя: 🧑‍🤝‍🧑{country['manpower']}, 💰{country['gold']}."
            )
            return

        applied = await db.apply_mobilization(
            message.from_user.id, cost_manpower, cost_gold, amount
        )
        if not applied:
            await message.answer("Ресурсы изменились во время операции. Повтори команду.")
            return

    await message.answer(f"⚔️ Армия усилена на {amount}! Потрачено: 🧑‍🤝‍🧑{cost_manpower}, 💰{cost_gold}.")


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
    await message.answer("\n".join(lines))


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
        await message.answer(
            f"Формат: <code>/buy ресурс количество</code>\nДоступно: {options}\nТекущие цены — /market"
        )
        return

    resource = parts[1].lower()
    amount = int(parts[2])
    if amount > config.MAX_BUY_PER_ORDER:
        await message.answer(f"Максимум за одну покупку: {config.MAX_BUY_PER_ORDER}.")
        return

    # Цену фиксируем один раз до входа в лок — рынок общий для всех, отдельно
    # блокировать его не нужно, а лёгкая гонка "цена сменилась между чтением и списанием
    # золота" тут не критична (окно — доли секунды, тик — минуты).
    price_per_unit = market.get_price(resource)
    price = price_per_unit * amount

    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await message.answer("Сначала создай страну: /founding Название")
            return
        if country["gold"] < price:
            await message.answer(f"Недостаточно золота. Нужно 💰{price} (цена {price_per_unit}/ед.), у тебя 💰{country['gold']}.")
            return
        applied = await db.apply_purchase(message.from_user.id, resource, amount, price)
        if not applied:
            await message.answer("Золото изменилось во время операции. Повтори покупку.")
            return

    await message.answer(
        f"🛒 Куплено {RESOURCE_NAMES_RU[resource]}: +{amount} по 💰{price_per_unit}/ед. (итого 💰{price})."
    )


@dp.message(Command("build_base"))
async def cmd_build_base(message: Message):
    """/build_base — построить военную базу (лимит зависит от территории и армии)"""
    async with get_user_lock(message.from_user.id):
        country = await db.get_country(message.from_user.id)
        if not country:
            await message.answer("Сначала создай страну: /founding Название")
            return

        tier = country.get("territory_tier", "medium")
        base_cap = config.TERRITORY_BASE_BONUS.get(tier, 0) + country["military"] // config.MILITARY_PER_BASE
        if country["military_bases"] >= base_cap:
            await message.answer(
                f"Лимит военных баз исчерпан: {country['military_bases']}/{base_cap}.\n"
                f"Увеличь армию (/mobilize) — лимит растёт вместе с ней."
            )
            return

        next_count = country["military_bases"] + 1
        cost_gold = config.BASE_COST_GOLD * next_count
        cost_resources = config.BASE_COST_RESOURCES * next_count
        if country["gold"] < cost_gold or country["resources"] < cost_resources:
            await message.answer(
                f"Недостаточно ресурсов для базы №{next_count}.\n"
                f"Нужно: 💰{cost_gold}, 📦{cost_resources}.\n"
                f"У тебя: 💰{country['gold']}, 📦{country['resources']}."
            )
            return

        applied = await db.apply_base(message.from_user.id, cost_gold, cost_resources)
        if not applied:
            await message.answer("Ресурсы изменились во время строительства. Повтори команду.")
            return

    await message.answer(f"🪖 Военная база построена! Теперь их {next_count}/{base_cap}.")


@dp.message(Command("spy"))
async def cmd_spy(message: Message):
    """/spy user_id — скрытная разведка чужой страны. Цель никогда не уведомляется."""
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "Формат: <code>/spy user_id</code>\n"
            f"Стоимость: 💰{config.SPY_COST_GOLD}. Кулдаун: {config.SPY_COOLDOWN_SECONDS // 60} мин.\n"
            "Операция полностью скрытная — цель никогда не узнает, ни при успехе, ни при провале."
        )
        return

    target_id = int(parts[1])
    spy_id = message.from_user.id
    if target_id == spy_id:
        await message.answer("Шпионить за самим собой бессмысленно.")
        return

    async with get_user_lock(spy_id):
        spy_country = await db.get_country(spy_id)
        if not spy_country:
            await message.answer("Сначала создай страну: /founding Название")
            return
        target = await db.get_country(target_id)
        if not target:
            await message.answer("У этого user_id нет страны.")
            return

        elapsed = int(time.time()) - spy_country.get("last_spy_at", 0)
        remaining = config.SPY_COOLDOWN_SECONDS - elapsed
        if remaining > 0:
            mins, secs = remaining // 60, remaining % 60
            await message.answer(f"⏳ Следующую операцию можно провести через {mins} мин {secs} сек.")
            return
        if spy_country["gold"] < config.SPY_COST_GOLD:
            await message.answer(f"Недостаточно золота. Нужно 💰{config.SPY_COST_GOLD}.")
            return

        # Момент операции и стоимость фиксируем сразу — сама операция скрытная,
        # цель ни в коем случае не получает уведомления, независимо от исхода.
        applied = await db.apply_spy_operation(spy_id, config.SPY_COST_GOLD, int(time.time()))
        if not applied:
            await message.answer("Золото изменилось во время операции. Повтори попытку.")
            return

        # Шанс успеха растёт вместе с разницей tech/diplomacy шпиона и цели.
        edge = (spy_country["tech"] - target["tech"]) + (spy_country["diplomacy"] - target["diplomacy"])
        chance = max(10, min(90, config.SPY_BASE_SUCCESS_CHANCE + edge))
        success = random.randint(1, 100) <= chance

    if not success:
        await message.answer("🕵️ Операция провалилась — агент не смог добыть достоверные данные. Цель ничего не заметила.")
        return

    await message.answer(
        f"🕵️ Разведданные по «{esc(target['name'])}» (операция прошла незаметно):\n\n"
        f"💰 Экономика: {target['economy']}\n"
        f"⚔️ Армия: {target['military']}\n"
        f"👥 Население: {target['population']}\n"
        f"🔬 Технологии: {target['tech']}\n"
        f"🤝 Дипломатия: {target['diplomacy']}\n"
        f"🪖 Военные базы: {target['military_bases']}\n"
    )


@dp.message(Command("attack"))
async def cmd_attack(message: Message):
    """/attack user_id описание атаки — война между двумя игроками, вердикт от ИИ"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer(
            "Формат: <code>/attack user_id описание атаки</code>\n"
            "user_id соперника можно узнать через /top (или он сам скажет через /myid).\n"
            "Пример: <code>/attack 123456789 Наношу внезапный удар по приграничным гарнизонам</code>"
        )
        return

    defender_id = int(parts[1])
    action_text = parts[2].strip()
    if not action_text:
        await message.answer("Опиши атаку после user_id соперника.")
        return
    if len(action_text) > config.MAX_ACTION_LEN:
        await message.answer(f"Слишком длинное описание (макс {config.MAX_ACTION_LEN} символов).")
        return

    attacker_id = message.from_user.id
    if defender_id == attacker_id:
        await message.answer("Нельзя напасть на самого себя.")
        return

    current_year = await db.get_current_year()
    if current_year is None:
        await message.answer(
            "⚠️ Год мира ещё не задан. Администратор должен сначала выполнить "
            "<code>/set_year год</code>, прежде чем атаки станут доступны."
        )
        return
    world_context = f"Текущий год мира: {current_year}."

    # Блокировки берём в фиксированном порядке (по возрастанию user_id) вне зависимости
    # от того, кто атакующий — иначе две одновременные встречные атаки могут взаимно
    # заблокироваться (deadlock), ожидая лок друг друга в обратном порядке.
    lock_a, lock_b = sorted([attacker_id, defender_id])
    first_lock, second_lock = get_user_lock(lock_a), get_user_lock(lock_b)

    async with first_lock:
        async with second_lock:
            attacker = await db.get_country(attacker_id)
            if not attacker:
                await message.answer("Сначала создай страну: /founding Название")
                return
            defender = await db.get_country(defender_id)
            if not defender:
                await message.answer("У этого user_id нет страны — атаковать некого.")
                return

            if config.ATTACK_COOLDOWN_SECONDS > 0:
                elapsed = int(time.time()) - attacker.get("last_attack_at", 0)
                remaining = config.ATTACK_COOLDOWN_SECONDS - elapsed
                if remaining > 0:
                    mins, secs = remaining // 60, remaining % 60
                    await message.answer(f"⏳ Следующую атаку можно совершить через {mins} мин {secs} сек.")
                    return

            # Фиксируем момент атаки сразу, до (долгого) запроса к ИИ.
            await db.touch_last_attack(attacker_id, int(time.time()))

    # Запрос к ИИ намеренно вне локов — чтобы не держать блокировку обоих игроков
    # на десятки секунд, пока ждём ответ модели.
    thinking_msg = await message.answer(
        f"⚔️ Ведущий обдумывает исход столкновения с «{esc(defender['name'])}»..."
    )
    verdict = await ai.get_war_verdict(attacker, defender, action_text, world_context=world_context)
    outcome = verdict.get("outcome", "error")

    async with first_lock:
        async with second_lock:
            current_attacker = await db.get_country(attacker_id)
            current_defender = await db.get_country(defender_id)
            if not current_attacker or not current_defender:
                await thinking_msg.edit_text("⚠️ Пока ведущий готовил вердикт, одна из стран была удалена. Результат не применён.")
                return
            attacker, defender = current_attacker, current_defender
            attacker_changes = clamp_country_changes(
                attacker, verdict.get("attacker_stat_changes", {})
            )
            defender_changes = clamp_country_changes(
                defender, verdict.get("defender_stat_changes", {})
            )

            loot_gold = loot_resources = 0
            if outcome == "attacker_win":
                loot_gold = defender["gold"] * config.WAR_LOOT_PERCENT // 100
                loot_resources = defender["resources"] * config.WAR_LOOT_PERCENT // 100
            elif outcome == "defender_win":
                loot_gold = -(attacker["gold"] * config.WAR_LOOT_PERCENT // 100)
                loot_resources = -(attacker["resources"] * config.WAR_LOOT_PERCENT // 100)

            if outcome in ("attacker_win", "defender_win", "draw"):
                await db.apply_war_result(
                    attacker_id, defender_id,
                    attacker_changes, defender_changes,
                    loot_gold=loot_gold, loot_resources=loot_resources,
                )

            if outcome in ("attacker_win", "defender_win", "draw"):
                await db.log_war(
                    attacker_id, attacker["name"], defender_id, defender["name"],
                    action_text, outcome, verdict["verdict_text"],
                )

    outcome_text = {
        "attacker_win": f"🏆 Победа {esc(attacker['name'])}!",
        "defender_win": f"🛡️ {esc(defender['name'])} отстояла свои границы!",
        "draw": "🤝 Ничья — обе стороны понесли потери, но не добились перевеса.",
        "error": "⚠️ Не удалось получить вердикт от ИИ.",
    }.get(outcome, "Исход неясен.")

    def _fmt_changes(country_name: str, changes: dict) -> str:
        lines = [f"<b>{esc(country_name)}:</b>"]
        any_change = False
        for stat, delta in changes.items():
            if delta:
                any_change = True
                sign = "+" if delta > 0 else ""
                lines.append(f"  {STAT_NAMES_RU.get(stat, stat)}: {sign}{delta}")
        if not any_change:
            lines.append("  без изменений")
        return "\n".join(lines)

    result_text = (
        f"{outcome_text}\n\n"
        f"{esc(verdict['verdict_text'])}\n\n"
        f"<b>Изменения:</b>\n"
        f"{_fmt_changes(attacker['name'], attacker_changes)}\n"
        f"{_fmt_changes(defender['name'], defender_changes)}"
    )
    if loot_gold > 0 or loot_resources > 0:
        result_text += f"\n\n💰 Трофеи {esc(attacker['name'])}: +{loot_gold} золота, +{loot_resources} ресурсов."
    elif loot_gold < 0 or loot_resources < 0:
        result_text += f"\n\n💰 Трофеи {esc(defender['name'])}: +{-loot_gold} золота, +{-loot_resources} ресурсов."

    await thinking_msg.edit_text(result_text)


@dp.message(Command("wars"))
async def cmd_wars(message: Message):
    """/wars — последние военные столкновения между игроками"""
    wars = await db.get_recent_wars(10)
    if not wars:
        await message.answer("Войн пока не было.")
        return
    lines = ["⚔️ <b>Последние столкновения</b>\n"]
    for w in wars:
        arrow = {
            "attacker_win": "победил(а)",
            "defender_win": "отбилась от",
            "draw": "сразилась вничью с",
        }.get(w["outcome"], "напал(а) на")
        lines.append(f"• <b>{esc(w['attacker_name'])}</b> {arrow} <b>{esc(w['defender_name'])}</b>")
    await message.answer("\n".join(lines))


@dp.message(Command("action"))
async def cmd_action(message: Message):
    action_text = message.text.replace("/action", "", 1).strip()
    if not action_text:
        await message.answer(
            "Опиши действие своей страны после команды.\n"
            "Пример: <code>/action Объявляю мобилизацию и готовлю вторжение в соседнее государство</code>"
        )
        return
    if len(action_text) > config.MAX_ACTION_LEN:
        await message.answer(f"Слишком длинное описание (макс {config.MAX_ACTION_LEN} символов).")
        return

    # Без заданного года мира ИИ не сможет корректно учитывать контекст эпохи в вердикте —
    # админ должен один раз задать год через /set_year, дальше он растёт сам.
    current_year = await db.get_current_year()
    if current_year is None:
        await message.answer(
            "⚠️ Год мира ещё не задан. Администратор должен сначала выполнить "
            "<code>/set_year год</code>, прежде чем действия станут доступны."
        )
        return

    lock = get_user_lock(message.from_user.id)
    async with lock:
        country = await db.get_country(message.from_user.id)
        if not country:
            await message.answer("Сначала создай страну: /founding Название")
            return

        if config.ACTION_COOLDOWN_SECONDS > 0:
            elapsed = int(time.time()) - country.get("last_action_at", 0)
            remaining = config.ACTION_COOLDOWN_SECONDS - elapsed
            if remaining > 0:
                mins, secs = remaining // 60, remaining % 60
                await message.answer(f"⏳ Следующее действие можно совершить через {mins} мин {secs} сек.")
                return

        # Фиксируем момент действия сразу — до (долгого) запроса к ИИ. Иначе повторный
        # /action, отправленный, пока первый ещё ждёт ответ модели, обходит кулдаун.
        await db.touch_last_action(message.from_user.id, int(time.time()))

    # Запрос к ИИ намеренно вне лока — чтобы не держать блокировку пользователя
    # на десятки секунд и не блокировать другие его команды (/country и т.п.).
    thinking_msg = await message.answer("🤔 Ведущий обдумывает вердикт...")
    world_context = f"Текущий год мира: {current_year}."
    verdict = await ai.get_verdict(country, action_text, world_context=world_context)

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

    changes_lines = []
    for stat, delta in changes.items():
        if delta != 0:
            sign = "+" if delta > 0 else ""
            changes_lines.append(f"{STAT_NAMES_RU[stat]}: {sign}{delta}")
    changes_text = "\n".join(changes_lines) if changes_lines else "без изменений характеристик"

    result_text = (
        f"📜 <b>Вердикт по действию {esc(country['name'])}</b> ({current_year} год)\n\n"
        f"{esc(verdict['verdict_text'])}\n\n"
        f"<b>Изменения:</b>\n{changes_text}"
    )
    await thinking_msg.edit_text(result_text)


@dp.message(Command("year"))
async def cmd_year(message: Message):
    """/year — показать текущий год мира"""
    year = await db.get_current_year()
    if year is None:
        await message.answer(
            "Год мира ещё не задан. Администратор должен выполнить <code>/set_year год</code>."
        )
        return
    await message.answer(f"📅 Текущий год мира: <b>{year}</b>")


@dp.message(Command("news"))
async def cmd_news(message: Message):
    events = await db.get_recent_events(10)
    if not events:
        await message.answer("Событий пока не было.")
        return
    lines = ["📰 <b>Последние события мира</b>\n"]
    for e in events:
        lines.append(f"• <b>{esc(e['country_name'])}</b>: {esc(e['verdict_text'][:200])}")
    await message.answer("\n\n".join(lines))


@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"Твой telegram user_id: <code>{message.from_user.id}</code>")


BEGINNER_GUIDE = (
    "<b>🧭 Как играть — короткий маршрут</b>\n\n"
    "<b>1. Оснуй страну</b>\n<code>/founding Бразилия</code>\n\n"
    "<b>2. Построй экономику</b>\n"
    "Начни с фермы, шахты и рынка:\n"
    "<code>/build farm</code> → <code>/build mine</code> → <code>/build market</code>\n\n"
    "<b>3. Забери доход</b>\n<code>/collect</code> — доступно раз в несколько минут.\n\n"
    "<b>4. Усиль армию</b>\nКогда накопишь людей и золото: <code>/mobilize 1</code>.\n\n"
    "<b>5. Развивай страну</b>\nОчки развития трать через <code>/upgrade tech 1</code> или другие характеристики.\n\n"
    "<b>6. Взаимодействуй с миром</b>\nДля действия используй <code>/action описание</code>, для войны — <code>/attack user_id описание</code>.\n\n"
    "Не нужно запоминать все команды: нажимай кнопки меню, а в разделе «Моя страна» всегда смотри подсказку следующего шага."
)


@dp.message(Command("guide"))
async def cmd_guide(message: Message):
    await message.answer(BEGINNER_GUIDE, reply_markup=MAIN_KEYBOARD)


@dp.message(F.text == "📊 Моя страна")
async def menu_country(message: Message):
    await cmd_country(message)


@dp.message(F.text == "📖 Что делать?")
async def menu_guide(message: Message):
    await cmd_guide(message)


@dp.message(F.text == "📥 Собрать ресурсы")
async def menu_collect(message: Message):
    await cmd_collect(message)


@dp.message(F.text == "🌍 Рейтинг")
async def menu_top(message: Message):
    await cmd_top(message)


@dp.message(F.text == "🏗️ Построить")
async def menu_build(message: Message):
    await message.answer(
        "<b>🏗️ Что строить сначала</b>\n\n"
        "🌾 Ферма — резерв людей\n"
        "⛏️ Шахта — обычные ресурсы\n"
        "🏪 Рынок — золото\n"
        "💧 Колодец — вода\n"
        "🌽 Амбар — еда\n\n"
        "Начни с: <code>/build farm</code>"
    )


@dp.message(F.text == "⚔️ Армия")
async def menu_army(message: Message):
    country = await db.get_country(message.from_user.id)
    if not country:
        await message.answer("Сначала основи страну: <code>/founding Бразилия</code>")
        return
    await message.answer(
        f"<b>⚔️ Армия</b>\n\nТекущая сила: {country['military']}\n"
        f"Резерв людей: {country['manpower']}\nЗолото: {country['gold']}\n\n"
        f"Стоимость +1 армии: {config.MOBILIZE_MANPOWER_PER_POINT} резерва + {config.MOBILIZE_GOLD_PER_POINT} золота.\n"
        "Команда: <code>/mobilize 1</code>"
    )


# --- Альянсы ---

@dp.message(Command("alliances"))
async def cmd_alliances(message: Message):
    items = await db.list_alliances()
    if not items:
        await message.answer("Альянсов пока нет. Основать: /alliance_create ТЕГ Название")
        return
    lines = ["🤝 <b>Альянсы</b>\n"]
    for a in items:
        lines.append(f"<b>{esc(a['tag'])}</b> — {esc(a['name'])} ({a['member_count']} стран)")
    await message.answer("\n".join(lines))


@dp.message(Command("alliance_create"))
async def cmd_alliance_create(message: Message):
    """/alliance_create ТЕГ Название альянса"""
    parts = message.text.split(maxsplit=2)
    if len(parts) != 3:
        await message.answer("Формат: <code>/alliance_create ТЕГ Название альянса</code>\nПример: <code>/alliance_create BRICS БРИКС</code>")
        return
    tag, name = parts[1].strip(), " ".join(parts[2].split())
    if len(tag) > config.MAX_ALLIANCE_TAG_LEN or len(name) > config.MAX_ALLIANCE_NAME_LEN:
        await message.answer(
            f"Тег до {config.MAX_ALLIANCE_TAG_LEN} символов, название до {config.MAX_ALLIANCE_NAME_LEN}."
        )
        return

    country = await db.get_country(message.from_user.id)
    if not country:
        await message.answer("Сначала создай страну: /founding Название")
        return

    ok = await db.create_alliance(tag, name)
    if not ok:
        await message.answer(f"Тег «{esc(tag)}» уже занят. Выбери другой.")
        return

    alliance = await db.get_alliance_by_tag(tag)
    await db.join_alliance(message.from_user.id, alliance["id"])
    await message.answer(f"🤝 Альянс <b>{esc(tag)}</b> — {esc(name)} создан, ты в нём первый участник.")


@dp.message(Command("alliance_join"))
async def cmd_alliance_join(message: Message):
    """/alliance_join ТЕГ"""
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: <code>/alliance_join ТЕГ</code>\nСписок — /alliances")
        return
    country = await db.get_country(message.from_user.id)
    if not country:
        await message.answer("Сначала создай страну: /founding Название")
        return
    alliance = await db.get_alliance_by_tag(parts[1])
    if not alliance:
        await message.answer("Такого альянса нет. Список — /alliances")
        return
    await db.join_alliance(message.from_user.id, alliance["id"])
    await message.answer(f"✅ «{esc(country['name'])}» вступила в <b>{esc(alliance['tag'])}</b> — {esc(alliance['name'])}.")


@dp.message(Command("alliance_leave"))
async def cmd_alliance_leave(message: Message):
    ok = await db.leave_alliance(message.from_user.id)
    if ok:
        await message.answer("Вышли из альянса.")
    else:
        await message.answer("Ты не состоишь ни в одном альянсе.")


@dp.message(Command("alliance_info"))
async def cmd_alliance_info(message: Message):
    parts = message.text.split()
    if len(parts) == 2:
        alliance = await db.get_alliance_by_tag(parts[1])
        if not alliance:
            await message.answer("Такого альянса нет.")
            return
    else:
        alliance = await db.get_user_alliance(message.from_user.id)
        if not alliance:
            await message.answer("Ты не в альянсе. Укажи тег: <code>/alliance_info ТЕГ</code>")
            return

    members = await db.get_alliance_members(alliance["id"])
    lines = [f"🤝 <b>{esc(alliance['tag'])}</b> — {esc(alliance['name'])}\n"]
    if not members:
        lines.append("Участников пока нет.")
    else:
        for m in members:
            lines.append(f"• {esc(m['name'])}")
    await message.answer("\n".join(lines))


# --- Админ-команды ---

@dp.message(Command("set_year"))
async def cmd_set_year(message: Message):
    """/set_year год — задать (или переустановить) текущий год мира. Дальше растёт сам."""
    if not is_admin(message.from_user.id):
        await message.answer("Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Формат: <code>/set_year год</code>\nПример: <code>/set_year 2140</code>")
        return
    year = int(parts[1])
    await db.set_world_year(year)
    await message.answer(
        f"📅 Год мира установлен: <b>{year}</b>.\n"
        f"Дальше он будет расти автоматически: 1 реальные сутки = 1 игровой год."
    )


@dp.message(Command("seed_alliances"))
async def cmd_seed_alliances(message: Message):
    """/seed_alliances — создать канонические альянсы (НАТО, ОДКБ и т.д.), обычно сразу после вайпа."""
    if not is_admin(message.from_user.id):
        await message.answer("Команда только для админов.")
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
    await message.answer(text or "Список канонических альянсов пуст.")


@dp.message(Command("give_points"))
async def cmd_give_points(message: Message):
    """/give_points количество — всем; /give_points user_id количество — одному"""
    if not is_admin(message.from_user.id):
        await message.answer("Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) == 2 and parts[1].isdigit():
        amount = int(parts[1])
        await db.set_points_all(amount)
        await message.answer(f"Всем странам начислено по {amount} очков развития.")
    elif len(parts) == 3 and parts[1].isdigit() and parts[2].lstrip("-").isdigit():
        user_id, amount = int(parts[1]), int(parts[2])
        target_country = await db.get_country(user_id)
        if not target_country:
            await message.answer("У этого user_id нет страны.")
            return
        await db.update_stat(user_id, "points", amount)
        await message.answer(f"Игроку {user_id} начислено {amount} очков.")
    else:
        await message.answer(
            "Формат:\n<code>/give_points количество</code> — всем\n"
            "<code>/give_points user_id количество</code> — одному игроку"
        )


@dp.message(Command("set_stat"))
async def cmd_set_stat(message: Message):
    """/set_stat user_id характеристика значение — ручная правка"""
    if not is_admin(message.from_user.id):
        await message.answer("Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) != 4 or not parts[1].isdigit() or parts[2] not in STAT_NAMES_RU:
        await message.answer("Формат: <code>/set_stat user_id характеристика новое_значение</code>")
        return
    user_id, stat, value = int(parts[1]), parts[2], parts[3]
    if not value.lstrip("-").isdigit():
        await message.answer("Значение должно быть числом.")
        return
    country = await db.get_country(user_id)
    if not country:
        await message.answer("Такой страны нет.")
        return
    delta = int(value) - country[stat]
    await db.update_stat(user_id, stat, delta)
    await message.answer(f"Готово. {STAT_NAMES_RU[stat]} игрока {user_id} теперь {value}.")


@dp.message(Command("kick"))
async def cmd_kick(message: Message):
    """/kick user_id — убрать игрока со страны"""
    if not is_admin(message.from_user.id):
        await message.answer("Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: <code>/kick user_id</code>")
        return
    user_id = int(parts[1])
    country = await db.get_country(user_id)
    if not country:
        await message.answer("У этого игрока нет страны.")
        return
    ok = await db.delete_country(user_id)
    if ok:
        await message.answer(f"❌ Игрок {user_id} снят со страны «{esc(country['name'])}». Страна удалена.")
    else:
        await message.answer("Не получилось удалить — попробуй ещё раз.")


@dp.message(Command("transfer"))
async def cmd_transfer(message: Message):
    """/transfer старый_id новый_id — передать страну другому игроку"""
    if not is_admin(message.from_user.id):
        await message.answer("Команда только для админов.")
        return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Формат: <code>/transfer старый_user_id новый_user_id</code>")
        return
    old_id, new_id = int(parts[1]), int(parts[2])
    old_country = await db.get_country(old_id)
    if not old_country:
        await message.answer("У старого user_id нет страны.")
        return
    ok = await db.transfer_country(old_id, new_id)
    if ok:
        await message.answer(f"✅ Страна «{esc(old_country['name'])}» передана от {old_id} к {new_id}.")
    else:
        await message.answer("Не удалось передать: либо у нового user_id уже есть страна, либо старая не найдена.")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = BEGINNER_GUIDE
    text += "\n\n<b>🔧 Дополнительные возможности</b>\n"
    text += "<code>/market</code> — цены сырья\n<code>/buy ресурс количество</code> — покупка сырья\n"
    text += "<code>/spy user_id</code> — скрытая разведка\n<code>/wars</code> — история войн\n"
    text += "<code>/alliances</code> — альянсы\n<code>/year</code> — игровой год\n<code>/news</code> — события мира\n"
    if is_admin(message.from_user.id):
        text += "\n<b>🔐 Администраторские команды</b>\n<code>/set_year год</code>, <code>/give_points количество</code>, <code>/set_stat user_id характеристика значение</code>, <code>/kick user_id</code>, <code>/transfer старый_id новый_id</code>"
    await message.answer(text, reply_markup=MAIN_KEYBOARD)


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
            await message.answer("⚠️ Что-то пошло не так при обработке команды. Попробуй ещё раз чуть позже.")
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
    if os.getenv("RENDER_WEB_SERVICE") == "1":
        await _run_healthcheck_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
