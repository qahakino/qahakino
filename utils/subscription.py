from aiogram import Bot


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
    result = []
    for ch in channels:
        subscribed = await is_subscribed(bot, user_id, ch["id"])
        if not subscribed:
            result.append(ch)
    return result
