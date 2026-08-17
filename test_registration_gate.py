import asyncio
import os
from datetime import datetime, timezone

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

from aiogram.types import Chat, Message, User

import bot


async def main():
    original_country = bot.db.get_country
    original_pmc = bot.db.get_pmc_by_owner
    original_answer = bot.answer_topic_safe
    calls = []

    async def fake_country(user_id):
        return {"user_id": user_id} if user_id == 200 else None

    async def fake_pmc(user_id):
        return None

    async def fake_answer(message, text, reply_markup=None, owner_id=None):
        calls.append((text, reply_markup, owner_id))

    async def handler(event, data):
        calls.append(("HANDLER", event.text))
        return True

    try:
        bot.db.get_country = fake_country
        bot.db.get_pmc_by_owner = fake_pmc
        bot.answer_topic_safe = fake_answer
        user = User(id=100, is_bot=False, first_name="Test")
        message = Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=1, type="private"),
            from_user=user,
            text="/country",
        )
        await bot.registration_gate(handler, message, {})
        assert calls and calls[-1][0].startswith("🔒")
        assert not any(item[0] == "HANDLER" for item in calls)

        calls.clear()
        start_message = message.model_copy(update={"text": "/start"})
        await bot.registration_gate(handler, start_message, {})
        assert any(item[0] == "HANDLER" for item in calls)

        calls.clear()
        registered_message = message.model_copy(update={"from_user": User(id=200, is_bot=False, first_name="Registered"), "text": "/country"})
        await bot.registration_gate(handler, registered_message, {})
        assert any(item[0] == "HANDLER" for item in calls)
        print("REGISTRATION_GATE_OK")
    finally:
        bot.db.get_country = original_country
        bot.db.get_pmc_by_owner = original_pmc
        bot.answer_topic_safe = original_answer


if __name__ == "__main__":
    asyncio.run(main())
