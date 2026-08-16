import time
from collections import defaultdict, deque

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

import config


class AntiSpamMiddleware(BaseMiddleware):
    """Throttle noisy users without changing per-command gameplay cooldowns."""

    def __init__(self):
        self._last_event: dict[int, float] = {}
        self._last_key: dict[int, tuple[str, float]] = {}
        self._burst: dict[int, deque[float]] = defaultdict(deque)
        self._last_notice: dict[int, float] = {}
        self._chat_burst: dict[int, deque[tuple[float, int]]] = defaultdict(deque)
        self._chat_lockdown_until: dict[int, float] = {}
        self._admin_cache: dict[tuple[int, int], tuple[float, bool]] = {}

    @staticmethod
    def _event_key(event) -> str:
        if isinstance(event, CallbackQuery):
            return f"callback:{event.data or ''}"
        if isinstance(event, Message):
            return f"message:{' '.join((event.text or '').split())}"
        return type(event).__name__

    async def _delete_blocked_message(self, event) -> None:
        """Remove blocked group messages when the bot has Telegram permission."""
        chat = getattr(event, "chat", None)
        if getattr(chat, "type", None) not in {"group", "supergroup"}:
            return
        delete = getattr(event, "delete", None)
        if delete is None:
            return
        try:
            await delete()
        except Exception:
            # Missing admin rights or an already deleted message must not
            # disable the middleware or affect legitimate gameplay.
            return

    @staticmethod
    def _chat_from_event(event):
        chat = getattr(event, "chat", None)
        if chat is not None:
            return chat
        message = getattr(event, "message", None)
        return getattr(message, "chat", None)

    async def _is_group_admin(self, event, data) -> bool:
        chat = self._chat_from_event(event)
        user = getattr(event, "from_user", None)
        if not chat or getattr(chat, "type", None) not in {"group", "supergroup"} or not user:
            return False
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            return False
        key = (chat_id, user.id)
        now = time.monotonic()
        cached = self._admin_cache.get(key)
        if cached and now - cached[0] < config.GROUP_RAID_ADMIN_CACHE_SECONDS:
            return cached[1]
        bot = data.get("bot")
        if bot is None:
            return False
        try:
            member = await bot.get_chat_member(chat_id, user.id)
            allowed = getattr(member, "status", "") in {"creator", "administrator"}
        except Exception:
            # A failed admin lookup must fail closed during lockdown.
            allowed = False
        self._admin_cache[key] = (now, allowed)
        return allowed

    async def _group_raid_gate(self, event, data, user_id: int) -> bool:
        """Return True when the event may continue to a gameplay handler."""
        chat = self._chat_from_event(event)
        if not chat or getattr(chat, "type", None) not in {"group", "supergroup"}:
            return True
        chat_id = getattr(chat, "id", None)
        # Telegram always supplies an ID, but partial test/update objects may not.
        # Do not let moderation metadata break the underlying gameplay handler.
        if chat_id is None:
            return True
        now = time.monotonic()
        if await self._is_group_admin(event, data):
            return True

        burst = self._chat_burst[chat_id]
        while burst and now - burst[0][0] > config.GROUP_RAID_WINDOW_SECONDS:
            burst.popleft()
        burst.append((now, user_id))
        unique_users = {uid for _, uid in burst}
        lockdown_until = self._chat_lockdown_until.get(chat_id, 0.0)
        if lockdown_until <= now and len(unique_users) >= config.GROUP_RAID_UNIQUE_USERS:
            lockdown_until = now + config.GROUP_RAID_LOCKDOWN_SECONDS
            self._chat_lockdown_until[chat_id] = lockdown_until

        if lockdown_until > now:
            await self._delete_blocked_message(event)
            return False
        return True

    async def _notify(self, event, remaining: float) -> None:
        user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)
        if user_id is None:
            return
        now = time.monotonic()
        # Do not answer every rejected packet; that would create another spam loop.
        if now - self._last_notice.get(user_id, 0.0) < config.GLOBAL_MESSAGE_COOLDOWN_SECONDS:
            return
        self._last_notice[user_id] = now
        text = f"⏳ Не спеши. Повтори через {max(1, int(remaining + 0.99))} сек."
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=False)
        elif isinstance(event, Message):
            await event.answer(text)

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)
        if user_id is None:
            return await handler(event, data)

        now = time.monotonic()
        if not await self._group_raid_gate(event, data, user_id):
            return
        key = self._event_key(event)
        last_event = self._last_event.get(user_id, 0.0)
        last_key, last_key_at = self._last_key.get(user_id, (None, 0.0))
        burst = self._burst[user_id]
        while burst and now - burst[0] > config.SPAM_BURST_WINDOW_SECONDS:
            burst.popleft()

        if now - last_event < config.GLOBAL_MESSAGE_COOLDOWN_SECONDS:
            await self._delete_blocked_message(event)
            await self._notify(event, config.GLOBAL_MESSAGE_COOLDOWN_SECONDS - (now - last_event))
            return
        if key == last_key and now - last_key_at < config.DUPLICATE_MESSAGE_WINDOW_SECONDS:
            await self._delete_blocked_message(event)
            await self._notify(event, config.DUPLICATE_MESSAGE_WINDOW_SECONDS - (now - last_key_at))
            return
        if len(burst) >= config.SPAM_BURST_LIMIT:
            await self._delete_blocked_message(event)
            await self._notify(event, config.SPAM_BURST_WINDOW_SECONDS - (now - burst[0]))
            return

        self._last_event[user_id] = now
        self._last_key[user_id] = (key, now)
        burst.append(now)
        return await handler(event, data)
