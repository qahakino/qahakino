import asyncio
import time

from aiogram import Bot

# Obuna bo'lgan foydalanuvchi qisqa muddat qayta tekshirilmaydi: har bir xabarda
# Telegram'ga murojaat qilish botni sekinlashtirardi.
SUBSCRIBED_TTL = 120  # soniya
_subscribed_until: dict[int, float] = {}


async def is_subscribed(bot: Bot, user_id: int, chat_id) -> bool:
    """Foydalanuvchi berilgan kanalga obuna bo'lganini tekshiradi.

    Bot shu kanalda ADMIN bo'lishi shart, aks holda get_chat_member
    xatolik qaytaradi va biz xavfsizlik uchun "obuna emas" deb hisoblaymiz.
    """
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False


async def get_unsubscribed_channels(
    bot: Bot, user_id: int, channels: list[dict]
) -> list[dict]:
    """Foydalanuvchi hali obuna bo'lmagan kanallarni qaytaradi."""
    if _subscribed_until.get(user_id, 0) > time.monotonic():
        return []

    # Kanallar ketma-ket emas, bir vaqtda tekshiriladi
    results = await asyncio.gather(
        *(is_subscribed(bot, user_id, ch["id"]) for ch in channels)
    )
    missing = [ch for ch, ok in zip(channels, results) if not ok]

    if missing:
        _subscribed_until.pop(user_id, None)
    else:
        if len(_subscribed_until) > 50_000:
            _subscribed_until.clear()
        _subscribed_until[user_id] = time.monotonic() + SUBSCRIBED_TTL
    return missing
