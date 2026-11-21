import asyncio
import logging
import os

from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Update,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    ErrorEvent,
    MenuButtonWebApp,
    WebAppInfo,
)
from aiogram.fsm.storage.memory import MemoryStorage


from config import BOT_TOKEN, ADMIN_IDS, WEBHOOK_SECRET
from database import db
from handlers import admin, user
from utils.media import ffmpeg_available
from miniapp import WEBAPP_URL, migrate, setup_miniapp


WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = "https://qahakino-production.up.railway.app/webhook"


async def health(request):
    return web.Response(text="OK")


async def webhook(request):
    # WEBHOOK_SECRET berilgan bo'lsa, faqat Telegramdan kelgan so'rovlar qabul qilinadi
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if token != WEBHOOK_SECRET:
            return web.Response(status=403, text="Forbidden")

    bot = request.app["bot"]
    dp = request.app["dp"]

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})

    try:
        await dp.feed_update(bot, update)
    except Exception:
        logging.exception("Update qayta ishlashda xatolik")

    return web.Response(text="OK")


async def start_web_server(bot: Bot, dp: Dispatcher):
    app = web.Application()

    app["bot"] = bot
    app["dp"] = dp
    setup_miniapp(app, bot)

    app.router.add_get("/health", health)
    app.router.add_post(WEBHOOK_PATH, webhook)

    port = int(os.environ.get("PORT", 10000))

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=port,
    )

    await site.start()

    logging.info(f"Web server ishga tushdi: port {port}")
    logging.info(f"Webhook URL: {WEBHOOK_URL}")


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi.")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    await db.init()
    await migrate()

    async def on_error(event: ErrorEvent):
        logging.error(
            "Handlerda xatolik: %s", event.exception, exc_info=event.exception
        )
        message = event.update.message
        if message is None and event.update.callback_query:
            message = event.update.callback_query.message
        if message is not None:
            try:
                await message.answer(
                    "⚠️ Kutilmagan xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring."
                )
            except Exception:
                pass
        return True

    dp.errors.register(on_error)

    dp.include_router(admin.router)
    dp.include_router(user.router)

    # Oddiy foydalanuvchilar uchun commandlar
    await bot.set_my_commands(
        [
            BotCommand(
                command="start",
                description="Botni ishga tushirish"
            ),
        ],
        scope=BotCommandScopeDefault(),
    )
    for admin_id in ADMIN_IDS:
        await bot.set_my_commands(
            [
                BotCommand(
                    command="start",
                    description="Botni ishga tushirish"
                ),
                BotCommand(
                    command="admin",
                    description="Kino qo‘shish"
                ),
                BotCommand(
                    command="stats",
                    description="Statistika"
                ),
                BotCommand(
                    command="delete",
                    description="Kino o‘chirish"
                ),
                BotCommand(
                    command="serial",
                    description="Serial qo‘shish"
                ),
                BotCommand(
                    command="clip",
                    description="Ovozli parcha qo‘shish"
                ),
                BotCommand(
                    command="clips",
                    description="Ovozli parchalar ro‘yxati"
                ),
                BotCommand(
                    command="poster",
                    description="Kinoga poster ulash"
                ),
                BotCommand(
                    command="cancel",
                    description="Amalni bekor qilish"
                ),
            ],
            scope=BotCommandScopeChat(chat_id=admin_id),
        )

    # Eski webhookni tozalab, yangisini o'rnatamiz
    await bot.delete_webhook(drop_pending_updates=True)

    await bot.set_webhook(
        url=WEBHOOK_URL,
        drop_pending_updates=True,
        secret_token=WEBHOOK_SECRET or None,
    )

    # Mini App tugmasi (chatdagi "menu" tugmasi)
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="🎬 Kinolar", web_app=WebAppInfo(url=WEBAPP_URL))
        )
    except Exception:
        logging.exception("Menu tugmasini o'rnatib bo'lmadi")

    if not ffmpeg_available():
        logging.warning(
            "ffmpeg/ffprobe topilmadi — «Ovozli kino» funksiyasi ishlamaydi. "
            "Railway'da RAILPACK_DEPLOY_APT_PACKAGES=ffmpeg o'zgaruvchisini qo'shing."
        )

    await start_web_server(bot, dp)

    logging.info("Bot webhook rejimida ishga tushdi...")

    try:
        await asyncio.Event().wait()
    finally:
        await bot.delete_webhook()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())