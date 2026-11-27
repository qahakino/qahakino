"""Baza zaxira nusxasi: qo'lda (/backup) va har kuni avtomatik."""
import asyncio
import contextlib
import gzip
import logging
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
from aiogram import Bot
from aiogram.types import FSInputFile

from config import ADMIN_IDS, BACKUP_CHAT_ID, BACKUP_HOUR
from database import db

TASHKENT = timezone(timedelta(hours=5))      # O'zbekiston vaqti (yozgi/qishki vaqt yo'q)
TELEGRAM_FILE_LIMIT = 49 * 1024 * 1024       # bot orqali fayl yuborish chegarasi ~50 MB


class BackupTooLarge(Exception):
    pass


def next_run(now: datetime, hour: int) -> datetime:
    """Keyingi zaxira vaqti: bugun soat `hour`:00, o'tib ketgan bo'lsa — ertaga."""
    run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


def _gzip_file(src: Path, dst: Path):
    with open(src, "rb") as f_in, gzip.open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


@contextlib.asynccontextmanager
async def backup_file():
    """Bazaning butun va buzilmagan nusxasini vaqtinchalik fayl sifatida beradi.

    VACUUM INTO bot ishlab turgan paytda ham izchil nusxa oladi. 50 MB dan oshsa siqiladi.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stamp = datetime.now(TASHKENT).strftime("%Y-%m-%d_%H%M")
        snapshot = Path(tmp) / f"qaxakino_{stamp}.db"

        async with aiosqlite.connect(db.path) as conn:
            await conn.execute("VACUUM INTO ?", (str(snapshot),))

        path = snapshot
        if snapshot.stat().st_size > TELEGRAM_FILE_LIMIT:
            path = Path(str(snapshot) + ".gz")
            await asyncio.to_thread(_gzip_file, snapshot, path)
        if path.stat().st_size > TELEGRAM_FILE_LIMIT:
            raise BackupTooLarge()
        yield path


async def backup_caption(path: Path, title: str = "💾 <b>Baza nusxasi</b>") -> str:
    return (
        f"{title}\n\n"
        f"👥 Foydalanuvchilar: <b>{await db.users_count()}</b>\n"
        f"🎬 Kinolar: <b>{await db.movies_count()}</b>\n"
        f"📺 Seriallar: <b>{await db.series_count()}</b>\n"
        f"📦 Hajmi: <b>{path.stat().st_size / (1024 * 1024):.2f} MB</b>\n\n"
        "⚠️ Faylda foydalanuvchi ma'lumotlari bor — begonalarga bermang."
    )


async def _alert_admins(bot: Bot, text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logging.warning("Adminga (%s) ogohlantirish yetmadi", admin_id)


async def run_scheduled_backup(bot: Bot) -> bool:
    """Zaxira nusxani BACKUP_CHAT_ID ga (bo'sh bo'lsa — hamma adminga) yuboradi.
    Muvaffaqiyatsiz bo'lsa adminlarga xabar beradi."""
    targets = [BACKUP_CHAT_ID] if BACKUP_CHAT_ID else list(ADMIN_IDS)
    if not targets:
        logging.warning("Zaxira nusxa: yuboriladigan joy yo'q (ADMIN_IDS bo'sh)")
        return False
    try:
        async with backup_file() as path:
            caption = await backup_caption(
                path, f"💾 <b>Avtomatik zaxira nusxa</b> — {datetime.now(TASHKENT):%Y-%m-%d %H:%M}"
            )
            failed = []
            for chat_id in targets:
                try:
                    await bot.send_document(chat_id, FSInputFile(path), caption=caption)
                except Exception:
                    logging.exception("Zaxira nusxani %s ga yuborib bo'lmadi", chat_id)
                    failed.append(chat_id)
    except BackupTooLarge:
        await _alert_admins(bot, "❌ Avtomatik zaxira: baza Telegram orqali yuborish uchun juda katta (50 MB+). "
                                 "Uni Railway Volume'dan yuklab oling.")
        return False
    except Exception as e:
        logging.exception("Avtomatik zaxira xatosi")
        await _alert_admins(bot, f"❌ Avtomatik zaxira nusxa olinmadi:\n<code>{e}</code>")
        return False

    if failed:
        await _alert_admins(bot, f"⚠️ Zaxira nusxani {len(failed)} ta joyga yuborib bo'lmadi: "
                                 + ", ".join(str(c) for c in failed))
    return len(failed) < len(targets)


async def backup_loop(bot: Bot, hour: int = BACKUP_HOUR):
    """Har kuni Toshkent vaqti bilan soat `hour`:00 da zaxira nusxa yuboradi (-1 = o'chirilgan)."""
    if hour < 0:
        logging.info("Avtomatik zaxira o'chirilgan (BACKUP_HOUR=-1)")
        return
    while True:
        now = datetime.now(TASHKENT)
        run = next_run(now, hour)
        logging.info("Keyingi avtomatik zaxira: %s", run.isoformat(timespec="minutes"))
        await asyncio.sleep((run - now).total_seconds())
        await run_scheduled_backup(bot)
