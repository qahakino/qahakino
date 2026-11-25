import asyncio
import gzip
import html
import json
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import aiosqlite
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageOriginChannel,
    WebAppInfo,
)

from config import ADMIN_IDS, MAX_DOWNLOAD_BYTES, STORAGE_CHANNEL_ID
from database import db
from miniapp import GENRES, WEBAPP_URL, get_info, next_missing_info, parse_info, set_info, set_poster
from keyboards import admin_clips_keyboard, serial_admin_keyboard
from utils.parts import parse_parts
from states import AdminStates


router = Router()


# ============================================================
# ADMIN TEKSHIRISH
# ============================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _miniapp_edit_button(code: str) -> InlineKeyboardMarkup:
    """Mini App'ni shu kinoning «Ma'lumotni tahrirlash» oynasida ochadi."""
    url = f"{WEBAPP_URL}?item={quote(code, safe='')}&edit=1"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Poster, janr, izohni to'ldirish", web_app=WebAppInfo(url=url))
    ]])


# ============================================================
# /ADMIN
# ============================================================

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await state.set_state(AdminStates.waiting_movie_name)

    await message.answer(
        "🎬 <b>Kino qo'shish</b>\n\n"
        "Kino nomini kiriting:"
    )


# ============================================================
# KINO NOMI
# ============================================================

@router.message(
    StateFilter(AdminStates.waiting_movie_name),
    F.text,
    ~F.text.startswith("/")
)
async def process_movie_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    movie_name = message.text.strip()

    if not movie_name:
        await message.answer("❌ Kino nomi bo'sh bo'lishi mumkin emas.")
        return

    await state.update_data(movie_name=movie_name)
    await state.set_state(AdminStates.waiting_movie_code)

    await message.answer(
        f"🎬 Kino: <b>{movie_name}</b>\n\n"
        "🔢 Kino kodini kiriting:"
    )


# ============================================================
# KINO KODI
# ============================================================

@router.message(
    StateFilter(AdminStates.waiting_movie_code),
    F.text,
    ~F.text.startswith("/")
)
async def process_movie_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    code = message.text.strip()

    if not code:
        await message.answer("❌ Kod bo'sh bo'lishi mumkin emas.")
        return

    if await db.code_exists(code):
        await message.answer(
            f"❌ <b>{code}</b> kodi allaqachon ishlatilgan.\n\n"
            "Boshqa kod kiriting:"
        )
        return

    await state.update_data(movie_code=code)
    await state.set_state(AdminStates.waiting_movie_content)

    await message.answer(
        "📹 Endi kino videosini yuboring.\n\n"
        "Videoni shu yerga yuboring yoki Storage kanaldan forward qiling."
    )


# ============================================================
# KINO VIDEOSINI QABUL QILISH
# ============================================================

@router.message(
    StateFilter(AdminStates.waiting_movie_content),
    F.video
)
async def process_movie_content(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()

    movie_name = data.get("movie_name")
    movie_code = data.get("movie_code")

    if not movie_name or not movie_code:
        await state.clear()
        await message.answer(
            "❌ Ma'lumotlar yo'qolgan. /admin orqali qaytadan boshlang."
        )
        return

    try:
        chat_id, message_id = await save_to_storage(message, bot)

        await db.add_movie(
            code=movie_code,
            name=movie_name,
            chat_id=chat_id,
            message_id=message_id,
        )

        await state.clear()

        await message.answer(
            "✅ <b>Kino qo'shildi!</b>\n\n"
            f"🎬 {html.escape(movie_name)}\n"
            f"🔑 Kod: <code>{html.escape(movie_code)}</code>\n\n"
            "Poster, janr va izohni Mini App'da to'ldiring 👇",
            reply_markup=_miniapp_edit_button(movie_code),
        )

    except Exception as e:
        await state.clear()
        await message.answer(
            "❌ Kino qo'shishda xatolik yuz berdi.\n\n"
            f"<code>{html.escape(str(e))}</code>"
        )


# ============================================================
# STORAGE'GA SAQLASH
# ============================================================

async def save_to_storage(
    message: Message,
    bot: Bot,
):
    """
    Video/foto/xabarni private Storage kanalga saqlaydi.

    Agar xabar forward qilingan bo'lsa va original
    channel message mavjud bo'lsa, original message'ni
    ishlatishga harakat qiladi.

    Aks holda copy_message ishlatiladi.
    """

    # Forward qilingan Storage kanal xabarini aniqlash
    if isinstance(message.forward_origin, MessageOriginChannel):
        origin = message.forward_origin

        if origin.chat.id == STORAGE_CHANNEL_ID:
            return origin.chat.id, origin.message_id

    # Oddiy yuborilgan xabarni Storage kanalga nusxalash
    copied = await bot.copy_message(
        chat_id=STORAGE_CHANNEL_ID,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )

    return STORAGE_CHANNEL_ID, copied.message_id


# ============================================================
# IZOH / YIL / JANR (kino qo'shgandan keyin va /info)
# ============================================================

INFO_HELP = (
    "Qisqa <b>izoh</b> yozing — Mini App'da kino sahifasida ko'rinadi.\n\n"
    "Yil, janr va davomiylikni ham kiritish uchun <b>birinchi qatorga</b> shunday yozing:\n"
    "<code>2024 | Komediya, Drama | 120</code>\n"
    "<i>(yil | janrlar | daqiqa — hammasi ixtiyoriy)</i>\n"
    "Izoh keyingi qatordan boshlanadi.\n\n"
    f"Janrlar: {', '.join(GENRES)}\n\n"
    "O'tkazib yuborish: /skip"
)


def _info_summary(info: dict) -> str:
    parts = []
    if info.get("year"):
        parts.append(f"📅 {info['year']}")
    if info.get("genres"):
        parts.append("🎭 " + ", ".join(info["genres"]))
    if info.get("duration"):
        parts.append(f"⏱ {info['duration']} daq")
    if info.get("description"):
        parts.append(f"📝 {len(info['description'])} belgi")
    return " · ".join(parts)


async def _prompt_info(message: Message, state: FSMContext, code: str, queue: bool, skipped: list):
    item = await get_info(code)
    if not item:
        await state.clear()
        await message.answer(f"❌ <code>{html.escape(code)}</code> kodi bilan kino ham, serial ham topilmadi.")
        return
    await state.set_state(AdminStates.waiting_info_text)
    await state.update_data(info_code=code, info_queue=queue, info_skipped=skipped)

    current = _info_summary({
        "year": item["year"], "duration": item["duration"],
        "genres": [g for g in (item["genres"] or "").split(",") if g],
        "description": item["description"],
    }) or "hali hech narsa yo'q"
    await message.answer(
        f"{'📺' if item['kind'] == 'series' else '🎬'} <b>{html.escape(item['name'] or '')}</b> "
        f"(kod: <code>{html.escape(code)}</code>)\n"
        f"Hozir: {current}\n\n" + INFO_HELP
    )


@router.message(Command("info"))
async def cmd_info(message: Message, state: FSMContext, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    code = (command.args or "").strip()
    if code:  # /info 101 — bitta kino
        await _prompt_info(message, state, code, queue=False, skipped=[])
        return
    # /info — izohi/janri yo'q kinolarni birin-ketin to'ldirish
    nxt = await next_missing_info()
    if not nxt:
        await message.answer("✅ Hamma kino va seriallarda izoh va janr bor.")
        return
    await message.answer("📝 Ma'lumoti yetishmaydigan kinolarni birin-ketin to'ldiramiz. Tugatish: /cancel")
    await _prompt_info(message, state, nxt, queue=True, skipped=[])


async def _next_in_queue(message: Message, state: FSMContext, skipped: list):
    nxt = await next_missing_info(skipped)
    if not nxt:
        await state.clear()
        await message.answer("🎉 Tayyor! Ma'lumoti yetishmaydigan kino qolmadi.")
        return
    await _prompt_info(message, state, nxt, queue=True, skipped=skipped)


@router.message(
    StateFilter(AdminStates.waiting_info_text),
    F.text,
    ~F.text.startswith("/"),
)
async def process_info_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    code = data.get("info_code")
    if not code:
        await state.clear()
        await message.answer("❌ Ma'lumot yo'qolgan. /info orqali qaytadan boshlang.")
        return

    info = parse_info(message.text)
    if not any(info[k] is not None for k in ("description", "year", "genres", "duration")):
        await message.answer("❌ Hech narsa tanib bo'lmadi. Izoh yozing yoki /skip.")
        return

    await set_info(
        code, description=info["description"], year=info["year"],
        genres=info["genres"], duration=info["duration"],
    )
    text = "✅ Saqlandi: " + _info_summary(info)
    if info["unknown"]:
        text += (
            f"\n\n⚠️ Noma'lum janr: <b>{html.escape(', '.join(info['unknown']))}</b> — qo'shilmadi.\n"
            f"Mavjud janrlar: {', '.join(GENRES)}"
        )
    await message.answer(text)

    if data.get("info_queue"):
        await _next_in_queue(message, state, list(data.get("info_skipped") or []))
    else:
        await state.clear()


@router.message(StateFilter(AdminStates.waiting_info_text), Command("skip"))
async def skip_info(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    if data.get("info_queue"):
        skipped = list(data.get("info_skipped") or []) + [data.get("info_code")]
        await message.answer("⏭ O'tkazib yuborildi.")
        await _next_in_queue(message, state, skipped)
        return
    await state.clear()
    await message.answer("👌 Izoh qo'shilmadi. Keyin /info yoki Mini App orqali qo'shishingiz mumkin.")


@router.message(
    StateFilter(AdminStates.waiting_info_text),
    ~F.text.startswith("/"),
)
async def info_wrong_type(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("❌ Matn yuboring (izoh yozing) yoki /skip.")


# ============================================================
# /POSTER — ESKI KINO YOKI SERIALGA POSTER ULASH
# ============================================================

async def _ask_poster_photo(message: Message, state: FSMContext, code: str):
    if not await db.code_exists(code):
        await state.set_state(AdminStates.waiting_poster_code)
        await message.answer(
            "❌ Bunday kodli kino yoki serial topilmadi.\n"
            "Kodni qayta kiriting yoki /cancel:"
        )
        return
    await state.update_data(poster_code=code)
    await state.set_state(AdminStates.waiting_poster_photo)
    await message.answer(
        f"🔑 Kod: <b>{html.escape(code)}</b>\n\n"
        "🖼 Endi poster rasmini (photo) yuboring:"
    )


@router.message(Command("poster"))
async def cmd_poster(message: Message, state: FSMContext, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    code = (command.args or "").strip()
    if code:  # /poster 101
        await _ask_poster_photo(message, state, code)
        return
    await state.set_state(AdminStates.waiting_poster_code)
    await message.answer(
        "🖼 <b>Poster ulash</b>\n\n"
        "Kino yoki serial kodini kiriting:"
    )


@router.message(
    StateFilter(AdminStates.waiting_poster_code),
    F.text,
    ~F.text.startswith("/"),
)
async def process_poster_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await _ask_poster_photo(message, state, message.text.strip())


@router.message(StateFilter(AdminStates.waiting_poster_photo), F.photo)
async def process_poster_photo(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    code = (await state.get_data()).get("poster_code")
    if not code:
        await state.clear()
        await message.answer("❌ Ma'lumot yo'qolgan. /poster orqali qaytadan boshlang.")
        return
    await set_poster(code, message.photo[-1].file_id)
    # Eski kinolar ko'p bo'lsa qulay: keyingi kodni darrov so'raymiz
    await state.set_state(AdminStates.waiting_poster_code)
    await message.answer(
        f"✅ <b>{html.escape(code)}</b> uchun poster saqlandi.\n\n"
        "Keyingi kino kodini yuboring yoki tugatish uchun /cancel:"
    )


@router.message(
    StateFilter(AdminStates.waiting_poster_photo),
    ~F.text.startswith("/"),
)
async def poster_wrong_type(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("❌ Rasm (photo) yuboring yoki /cancel.")


# ============================================================
# /CANCEL
# ============================================================

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()

    await message.answer(
        "❌ Amal bekor qilindi."
    )


# ============================================================
# /DELETE
# ============================================================

@router.message(Command("delete"))
async def cmd_delete(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)

    # /delete 1001
    if len(parts) >= 2 and parts[1].strip():
        code = parts[1].strip()

        await delete_content_by_code(
            message=message,
            code=code,
            bot=bot,
        )
        return

    # Faqat /delete
    await state.set_state(AdminStates.waiting_delete_movie_code)

    await message.answer(
        "🗑 <b>Kino yoki serial kodini kiriting:</b>\n\n"
        "Masalan:\n"
        "• <code>1001</code> — kino\n"
        "• <code>2001</code> — serial"
    )


# ============================================================
# DELETE KODINI QABUL QILISH
# ============================================================

@router.message(
    StateFilter(AdminStates.waiting_delete_movie_code),
    F.text,
    ~F.text.startswith("/")
)
async def process_delete_movie_code(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    if not is_admin(message.from_user.id):
        return

    code = message.text.strip()

    await delete_content_by_code(
        message=message,
        code=code,
        bot=bot,
    )

    await state.clear()


# ============================================================
# KINO YOKI SERIALNI O'CHIRISH
# ============================================================

async def delete_content_by_code(
    message: Message,
    code: str,
    bot: Bot,
):
    # ========================================================
    # 1. AVVAL KINO QIDIRAMIZ
    # ========================================================

    movie = await db.get_movie(code)

    if movie:
        _, name, chat_id, message_id = movie

        channel_deleted = False
        delete_error = None

        try:
            await bot.delete_message(
                chat_id=chat_id,
                message_id=message_id,
            )
            channel_deleted = True

        except Exception as e:
            delete_error = str(e)

        deleted_from_db = await db.delete_movie(code)

        if not deleted_from_db:
            await message.answer(
                "⚠️ Kino topildi, lekin bazadan o'chirishda muammo yuz berdi."
            )
            return

        if channel_deleted:
            await message.answer(
                "🗑 <b>Kino o'chirildi!</b>\n\n"
                f"🎬 Nomi: <b>{name}</b>\n"
                f"🔑 Kodi: <code>{code}</code>\n\n"
                "✅ Database'dan o'chirildi\n"
                "✅ Storage kanaldan o'chirildi"
            )
        else:
            await message.answer(
                "⚠️ <b>Kino Database'dan o'chirildi.</b>\n\n"
                f"🎬 Nomi: <b>{name}</b>\n"
                f"🔑 Kodi: <code>{code}</code>\n\n"
                "❌ Storage kanaldan o'chirilmadi.\n\n"
                f"Telegram xatosi:\n<code>{delete_error}</code>"
            )

        return

    # ========================================================
    # 2. KINO TOPILMASA — SERIAL QIDIRAMIZ
    # ========================================================

    series = await db.get_series_by_code(code)

    if not series:
        await message.answer(
            f"❌ <code>{code}</code> kodi bilan "
            "kino ham, serial ham topilmadi."
        )
        return

    (
        series_id,
        series_code,
        series_name,
        poster_chat_id,
        poster_message_id,
    ) = series

    # ========================================================
    # 3. SERIALNING BARCHA QISMLARINI OLAMIZ
    # ========================================================

    episodes = await db.get_episodes(series_id)

    deleted_from_storage = 0
    failed_deletes = 0

    # ========================================================
    # 4. POSTERNI O'CHIRAMIZ
    # ========================================================

    try:
        await bot.delete_message(
            chat_id=poster_chat_id,
            message_id=poster_message_id,
        )

        deleted_from_storage += 1

    except Exception:
        failed_deletes += 1

    # ========================================================
    # 5. BARCHA QISMLARNI STORAGE'DAN O'CHIRAMIZ
    # ========================================================

    for episode in episodes:
        (
            episode_id,
            episode_number,
            chat_id,
            message_id,
        ) = episode

        try:
            await bot.delete_message(
                chat_id=chat_id,
                message_id=message_id,
            )

            deleted_from_storage += 1

        except Exception:
            failed_deletes += 1

    # ========================================================
    # 6. SERIALNI DATABASE'DAN O'CHIRAMIZ
    # ========================================================

    deleted_series = await db.delete_series(code)

    if not deleted_series:
        await message.answer(
            "❌ Serial Storage'dan o'chirishga harakat qilindi, "
            "lekin bazadan topilmadi."
        )
        return

    # ========================================================
    # 7. NATIJA
    # ========================================================

    await message.answer(
        "🗑 <b>Serial o'chirildi!</b>\n\n"
        f"📺 Nomi: <b>{series_name}</b>\n"
        f"🔑 Kodi: <code>{series_code}</code>\n"
        f"🎬 Qismlar: <b>{len(episodes)} ta</b>\n\n"
        f"🗑 Storage'dan o'chirilgan: "
        f"<b>{deleted_from_storage} ta</b>\n"
        f"⚠️ O'chmay qolgan: "
        f"<b>{failed_deletes} ta</b>\n\n"
        "✅ Database'dan serial va uning qismlari o'chirildi."
    )


# ============================================================
# /BACKUP — BAZANI YUKLAB OLISH (boshqa serverga ko'chirish uchun)
# ============================================================

TELEGRAM_FILE_LIMIT = 49 * 1024 * 1024  # bot orqali fayl yuborish chegarasi ~50 MB


def _gzip_file(src: Path, dst: Path):
    with open(src, "rb") as f_in, gzip.open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


@router.message(Command("backup"))
async def cmd_backup(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    status = await message.answer("⏳ Baza nusxasi tayyorlanmoqda...")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
            snapshot = Path(tmp) / f"qaxakino_{stamp}.db"

            # VACUUM INTO — bot ishlab turgan paytda ham butun va buzilmagan nusxa beradi
            async with aiosqlite.connect(db.path) as conn:
                await conn.execute("VACUUM INTO ?", (str(snapshot),))

            send_path = snapshot
            if snapshot.stat().st_size > TELEGRAM_FILE_LIMIT:
                send_path = Path(str(snapshot) + ".gz")
                await asyncio.to_thread(_gzip_file, snapshot, send_path)

            if send_path.stat().st_size > TELEGRAM_FILE_LIMIT:
                await status.edit_text(
                    "❌ Baza Telegram orqali yuborish uchun juda katta (50 MB dan oshdi).\n"
                    "Uni Railway Volume'dan yuklab oling."
                )
                return

            size_mb = send_path.stat().st_size / (1024 * 1024)
            await message.answer_document(
                FSInputFile(send_path),
                caption=(
                    "💾 <b>Baza nusxasi</b>\n\n"
                    f"👥 Foydalanuvchilar: <b>{await db.users_count()}</b>\n"
                    f"🎬 Kinolar: <b>{await db.movies_count()}</b>\n"
                    f"📺 Seriallar: <b>{await db.series_count()}</b>\n"
                    f"📦 Hajmi: <b>{size_mb:.2f} MB</b>\n\n"
                    "⚠️ Faylda foydalanuvchi ma'lumotlari bor — begonalarga bermang."
                ),
            )
        await status.delete()

    except Exception as e:
        logging.exception("Backup xatosi")
        await status.edit_text(
            "❌ Baza nusxasini olishda xatolik yuz berdi.\n\n"
            f"<code>{html.escape(str(e))}</code>"
        )


# ============================================================
# /STATS
# ============================================================

def _natural_key(code: str):
    """Raqamli kodlar songa qarab (9 < 10 < 101), harfli kodlar oxirida alifbo bo'yicha."""
    return (0, int(code), code) if code.isdigit() else (1, 0, code.lower())


def _ranges(nums: list[int]) -> str:
    runs, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            runs.append((start, prev))
            start = prev = n
    if start is not None:
        runs.append((start, prev))
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in runs)


@router.message(Command("kodlar", "kodlarni_korish"))
async def cmd_codes(message: Message):
    """Band kodlar ro'yxati (kichikdan kattaga) + keyingi bo'sh kod. Faqat adminlar uchun."""
    if not is_admin(message.from_user.id):
        return

    items = sorted(await db.all_codes(), key=lambda x: _natural_key(x[0]))
    if not items:
        await message.answer("📋 Hozircha kino yo'q. Birinchi kod: <code>1</code>")
        return

    esc = lambda x: html.escape(str(x or ""), quote=False)
    movies = sum(1 for it in items if it[1] == "movie")
    head = [f"📋 <b>Kodlar</b> — jami {len(items)} ta (🎬 {movies} kino, 📺 {len(items) - movies} serial)"]

    numeric = sorted({int(c) for c, *_ in items if c.isdigit()})
    if numeric:
        head.append(f"➕ Keyingi kod: <code>{numeric[-1] + 1}</code>")
        if numeric[-1] - numeric[0] <= 100_000:
            used = set(numeric)
            gaps = [n for n in range(numeric[0], numeric[-1] + 1) if n not in used]
            if gaps:
                text = _ranges(gaps)
                if len(text) > 300:
                    text = text[:300].rsplit(",", 1)[0] + ", …"
                head.append(f"🕳 Bo'sh kodlar: {text}")

    lines = []
    for code, kind, name, episodes in items:
        icon = "📺" if kind == "series" else "🎬"
        extra = f" ({episodes} qism)" if kind == "series" else ""
        lines.append(f"<code>{esc(code)}</code> {icon} {esc((name or '')[:60])}{extra}")

    # Telegram xabari 4096 belgidan oshmasligi uchun bo'laklarga bo'lamiz
    chunks, current = [], "\n".join(head) + "\n\n"
    for line in lines:
        if len(current) + len(line) + 1 > 3800:
            chunks.append(current.rstrip())
            current = ""
        current += line + "\n"
    chunks.append(current.rstrip())
    for chunk in chunks:
        await message.answer(chunk)


@router.message(Command("chatid"))
async def cmd_chatid(message: Message):
    """Guruh ID sini bilish uchun: botni guruhga qo'shib, guruhda /chatid yozing."""
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        f"🆔 Chat ID: <code>{message.chat.id}</code>\n\n"
        "Buyurtmalar shu guruhga kelishi uchun, Railway'da "
        f"<code>ORDERS_CHAT_ID={message.chat.id}</code> o'zgaruvchisini qo'shing."
    )


@router.message(
    StateFilter(None),
    F.from_user.id.in_(set(ADMIN_IDS)),
    F.forward_origin.func(lambda origin: isinstance(origin, MessageOriginChannel)),
)
async def forwarded_channel_id(message: Message):
    """Kanal ID sini bilish uchun: kanaldan istalgan xabarni botga forward qiling."""
    chat = message.forward_origin.chat
    await message.answer(
        f"📢 Kanal: <b>{html.escape(chat.title or '')}</b>\n"
        f"🆔 ID: <code>{chat.id}</code>\n\n"
        f"Buyurtmalar shu kanalga kelishi uchun Railway'da:\n"
        f"<code>ORDERS_CHAT_ID={chat.id}</code>"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    users_count = await db.users_count()
    movies_count = await db.movies_count()
    series_count = await db.series_count()
    clips_count = await db.clips_count()
    pending_orders = await db.pending_orders_count()

    await message.answer(
        "📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users_count}</b>\n"
        f"🎬 Kinolar: <b>{movies_count}</b>\n"
        f"📺 Seriallar: <b>{series_count}</b>\n"
        f"🎙 Ovozli parchalar: <b>{clips_count}</b>\n"
        f"📨 Kutilayotgan buyurtmalar: <b>{pending_orders}</b>"
    )


# ============================================================
# /SERIAL
# ============================================================

@router.message(Command("serial"))
async def cmd_serial(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    await state.clear()

    series = await db.all_series()

    if series:
        await message.answer(
            "📺 <b>Serial boshqaruvi</b>\n\n"
            "Mavjud seriallardan birini tanlang "
            "yoki yangi serial qo'shing:",
            reply_markup=serial_admin_keyboard(series),
        )
    else:
        await message.answer(
            "📺 <b>Serial qo'shish</b>\n\n"
            "Hozircha seriallar yo'q.\n"
            "Yangi serial qo'shish tugmasini bosing.",
            reply_markup=serial_admin_keyboard([]),
        )


# ============================================================
# YANGI SERIAL
# ============================================================

@router.callback_query(F.data == "admin_new_series")
async def admin_new_series(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    await state.clear()
    await state.set_state(AdminStates.waiting_series_name)

    await callback.message.answer(
        "📺 <b>Yangi serial</b>\n\n"
        "Serial nomini kiriting:"
    )

    await callback.answer()


# ============================================================
# MAVJUD SERIALNI TANLASH
# ============================================================

@router.callback_query(F.data.startswith("admin_series:"))
async def admin_select_series(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        series_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer(
            "❌ Noto'g'ri serial.",
            show_alert=True,
        )
        return

    series = await db.get_series(series_id)

    if not series:
        await callback.answer(
            "❌ Serial topilmadi.",
            show_alert=True,
        )
        return

    _, code, name, _, _ = series

    await state.clear()
    await state.update_data(
        series_id=series_id,
        series_code=code,
        series_name=name,
    )

    await state.set_state(AdminStates.waiting_series_episode_number)

    await callback.message.answer(
        f"📺 Serial: <b>{name}</b>\n"
        f"🔑 Kod: <code>{code}</code>\n\n"
        "🎬 Qism raqamini kiriting:"
    )

    await callback.answer()


# ============================================================
# YANGI SERIAL NOMI
# ============================================================

@router.message(
    StateFilter(AdminStates.waiting_series_name),
    F.text,
    ~F.text.startswith("/")
)
async def process_series_name(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    series_name = message.text.strip()

    if not series_name:
        await message.answer(
            "❌ Serial nomi bo'sh bo'lishi mumkin emas."
        )
        return

    await state.update_data(
        series_name=series_name
    )

    await state.set_state(
        AdminStates.waiting_series_code
    )

    await message.answer(
        f"📺 Serial: <b>{series_name}</b>\n\n"
        "🔑 Serial kodini kiriting:"
    )


# ============================================================
# YANGI SERIAL KODI
# ============================================================

@router.message(
    StateFilter(AdminStates.waiting_series_code),
    F.text,
    ~F.text.startswith("/")
)
async def process_series_code(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    code = message.text.strip()

    if not code:
        await message.answer(
            "❌ Kod bo'sh bo'lishi mumkin emas."
        )
        return

    if await db.code_exists(code):
        await message.answer(
            f"❌ <code>{code}</code> kodi allaqachon ishlatilgan.\n\n"
            "Boshqa kod kiriting:"
        )
        return

    await state.update_data(
        series_code=code
    )

    await state.set_state(
        AdminStates.waiting_series_poster
    )

    await message.answer(
        "🖼 Endi serial uchun poster rasmini yuboring:"
    )


# ============================================================
# SERIAL POSTERI
# ============================================================

@router.message(
    StateFilter(AdminStates.waiting_series_poster),
    F.photo
)
async def process_series_poster(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()

    series_name = data.get("series_name")
    series_code = data.get("series_code")

    if not series_name or not series_code:
        await state.clear()

        await message.answer(
            "❌ Ma'lumotlar yo'qolgan. "
            "/serial orqali qaytadan boshlang."
        )
        return

    try:
        poster_chat_id, poster_message_id = await save_to_storage(
            message,
            bot,
        )

        await state.update_data(
            poster_chat_id=poster_chat_id,
            poster_message_id=poster_message_id,
            poster_file_id=message.photo[-1].file_id,
        )

        await state.set_state(
            AdminStates.waiting_series_episode_number
        )

        await message.answer(
            "✅ Poster saqlandi.\n\n"
            "🎬 Birinchi qism raqamini kiriting:"
        )

    except Exception as e:
        await message.answer(
            "❌ Posterni saqlashda xatolik yuz berdi.\n\n"
            f"<code>{e}</code>"
        )


# ============================================================
# QISM RAQAMI
# ============================================================

@router.message(
    StateFilter(AdminStates.waiting_series_episode_number),
    F.text,
    ~F.text.startswith("/")
)
async def process_episode_number(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    try:
        episode_number = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Qism raqami faqat son bo'lishi kerak.\n\n"
            "Masalan: <code>1</code>"
        )
        return

    if episode_number <= 0:
        await message.answer(
            "❌ Qism raqami 1 yoki undan katta bo'lishi kerak."
        )
        return

    data = await state.get_data()

    series_id = data.get("series_id")

    # ========================================================
    # MAVJUD SERIAL
    # ========================================================

    if series_id:
        existing_episode = await db.get_episode_by_number(
            series_id,
            episode_number,
        )

        if existing_episode:
            await message.answer(
                f"❌ <b>{episode_number}-qism</b> allaqachon mavjud.\n\n"
                "Boshqa qism raqamini kiriting:"
            )
            return

        await state.update_data(
            episode_number=episode_number
        )

        await state.set_state(
            AdminStates.waiting_series_episode_content
        )

        await message.answer(
            f"🎬 <b>{episode_number}-qism</b>\n\n"
            "📹 Endi video yuboring:"
        )

        return

    # ========================================================
    # YANGI SERIAL
    # ========================================================

    series_name = data.get("series_name")
    series_code = data.get("series_code")
    poster_chat_id = data.get("poster_chat_id")
    poster_message_id = data.get("poster_message_id")

    if not all(
        [
            series_name,
            series_code,
            poster_chat_id,
            poster_message_id,
        ]
    ):
        await state.clear()

        await message.answer(
            "❌ Serial ma'lumotlari to'liq emas.\n\n"
            "/serial orqali qaytadan boshlang."
        )
        return

    await state.update_data(
        episode_number=episode_number
    )

    await state.set_state(
        AdminStates.waiting_series_episode_content
    )

    await message.answer(
        f"📺 Serial: <b>{series_name}</b>\n"
        f"🔑 Kod: <code>{series_code}</code>\n"
        f"🎬 Qism: <b>{episode_number}</b>\n\n"
        "📹 Endi birinchi qism videosini yuboring:"
    )


# ============================================================
# QISM VIDEOSINI QABUL QILISH
# ============================================================

@router.message(
    StateFilter(AdminStates.waiting_series_episode_content),
    F.video
)
async def process_episode_video(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()

    episode_number = data.get("episode_number")

    if not episode_number:
        await state.clear()

        await message.answer(
            "❌ Qism raqami topilmadi. "
            "/serial orqali qaytadan boshlang."
        )
        return

    # ========================================================
    # MAVJUD SERIALGA QISM QO'SHISH
    # ========================================================

    series_id = data.get("series_id")

    if series_id:
        series = await db.get_series(series_id)

        if not series:
            await state.clear()

            await message.answer(
                "❌ Serial topilmadi."
            )
            return

        _, series_code, series_name, _, _ = series

        try:
            chat_id, message_id = await save_to_storage(
                message,
                bot,
            )

            added = await db.add_episode(
                series_id=series_id,
                episode_number=episode_number,
                chat_id=chat_id,
                message_id=message_id,
            )

            if not added:
                # Storage'ga saqlanib qolgan bo'lishi mumkin.
                # Shu sababli message'ni o'chirishga harakat qilamiz.
                try:
                    await bot.delete_message(
                        chat_id=chat_id,
                        message_id=message_id,
                    )
                except Exception:
                    pass

                await message.answer(
                    f"❌ <b>{episode_number}-qism</b>ni "
                    "qo'shib bo'lmadi.\n\n"
                    "Bu qism allaqachon mavjud bo'lishi mumkin."
                )

                await state.clear()
                return

            await message.answer(
                "✅ <b>Qism qo'shildi!</b>\n\n"
                f"📺 Serial: <b>{series_name}</b>\n"
                f"🔑 Kod: <code>{series_code}</code>\n"
                f"🎬 Qism: <b>{episode_number}</b>"
            )

        except Exception as e:
            await message.answer(
                "❌ Qismni qo'shishda xatolik yuz berdi.\n\n"
                f"<code>{e}</code>"
            )

        finally:
            await state.clear()

        return

    # ========================================================
    # YANGI SERIALNI YARATISH
    # ========================================================

    series_name = data.get("series_name")
    series_code = data.get("series_code")
    poster_chat_id = data.get("poster_chat_id")
    poster_message_id = data.get("poster_message_id")

    if not all(
        [
            series_name,
            series_code,
            poster_chat_id,
            poster_message_id,
        ]
    ):
        await state.clear()

        await message.answer(
            "❌ Serial ma'lumotlari to'liq emas.\n\n"
            "/serial orqali qaytadan boshlang."
        )
        return

    try:
        # Serialni yaratamiz
        series_id = await db.add_series(
            code=series_code,
            name=series_name,
            poster_chat_id=poster_chat_id,
            poster_message_id=poster_message_id,
        )
        if data.get("poster_file_id"):
            await set_poster(series_code, data["poster_file_id"])

        # Birinchi qismni Storage'ga saqlaymiz
        chat_id, message_id = await save_to_storage(
            message,
            bot,
        )

        # Birinchi qismni DB'ga qo'shamiz
        added = await db.add_episode(
            series_id=series_id,
            episode_number=episode_number,
            chat_id=chat_id,
            message_id=message_id,
        )

        if not added:
            await message.answer(
                "⚠️ Serial yaratildi, lekin birinchi qismni "
                "qo'shishda muammo yuz berdi."
            )

            await state.clear()
            return

        await message.answer(
            "🎉 <b>Yangi serial muvaffaqiyatli yaratildi!</b>\n\n"
            f"📺 Nomi: <b>{series_name}</b>\n"
            f"🔑 Kodi: <code>{series_code}</code>\n"
            f"🎬 Birinchi qism: <b>{episode_number}</b>\n\n"
            "Endi boshqa qismlarni qo'shish uchun:\n"
            "<code>/serial</code> → serialni tanlang → qism raqami → video"
        )

    except Exception as e:
        await message.answer(
            "❌ Serial yaratishda xatolik yuz berdi.\n\n"
            f"<code>{e}</code>"
        )

    finally:
        await state.clear()


# ============================================================
# OVOZLI PARCHALAR (/clip, /clips)
# Tartib: nom -> asl video -> orqa fonli video -> vaqt belgili matn qismlari
# ============================================================

@router.message(Command("clip"))
async def cmd_clip(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await state.set_state(AdminStates.waiting_clip_title)

    await message.answer(
        "🎙 <b>Ovozli parcha qo'shish</b>\n\n"
        "Parcha nomini kiriting (masalan: <i>Temir odam — mashhur monolog</i>):"
    )


@router.message(
    StateFilter(AdminStates.waiting_clip_title),
    F.text,
    ~F.text.startswith("/"),
)
async def process_clip_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    title = message.text.strip()
    if not title:
        await message.answer("❌ Nom bo'sh bo'lishi mumkin emas.")
        return

    await state.update_data(clip_title=title)
    await state.set_state(AdminStates.waiting_clip_video)

    await message.answer(
        f"🎞 Parcha: <b>{html.escape(title)}</b>\n\n"
        "1️⃣ Endi <b>asl videoni</b> yuboring (foydalanuvchiga ko'rsatiladi, "
        "o'z ovozi bilan). Video sifatida yuboring."
    )


@router.message(StateFilter(AdminStates.waiting_clip_video), F.video)
async def process_clip_video(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    video = message.video

    # Zaxira sifatida storage kanalga nusxalaymiz (bo'lmasa ham ishlayveradi)
    storage_chat_id = storage_message_id = None
    try:
        storage_chat_id, storage_message_id = await save_to_storage(message, bot)
    except Exception:
        logging.warning("Parchani storage kanalga saqlab bo'lmadi", exc_info=True)

    await state.update_data(
        clip_video_file_id=video.file_id,
        clip_duration=video.duration,
        clip_storage_chat_id=storage_chat_id,
        clip_storage_message_id=storage_message_id,
    )
    await state.set_state(AdminStates.waiting_clip_bg)

    await message.answer(
        f"✅ Asl video qabul qilindi ({video.duration or '?'} soniya).\n\n"
        "2️⃣ Endi <b>faqat orqa fonli videoni</b> yuboring (gaplar olib tashlangan, "
        "musiqa va fon qolgan; asl bilan bir xil uzunlikda).\n\n"
        "⚠️ Bu videoning hajmi <b>20 MB dan oshmasin</b> — bot uni yuklab olib "
        "ovozlarni ustiga qo'yadi."
    )


@router.message(StateFilter(AdminStates.waiting_clip_bg), F.video)
async def process_clip_bg(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    video = message.video

    if video.file_size and video.file_size > MAX_DOWNLOAD_BYTES:
        size_mb = video.file_size / (1024 * 1024)
        await message.answer(
            f"❌ Video juda katta ({size_mb:.1f} MB). "
            "20 MB dan kichikroq qilib siqib yuboring."
        )
        return

    data = await state.get_data()
    warning = ""
    orig = data.get("clip_duration")
    if orig and video.duration and abs(orig - video.duration) > 2:
        warning = (
            f"\n\n⚠️ Diqqat: orqa fonli video ({video.duration} s) asl videodan "
            f"({orig} s) farq qiladi. Vaqtlar mos kelmasligi mumkin."
        )

    await state.update_data(
        clip_bg_file_id=video.file_id,
        clip_bg_duration=video.duration,
    )
    await state.set_state(AdminStates.waiting_clip_parts)

    await message.answer(
        "✅ Orqa fonli video qabul qilindi."
        f"{warning}\n\n"
        "3️⃣ Endi matnni <b>qismlarga bo'lib</b> yuboring. Har bir qism alohida "
        "qatorda, shu ko'rinishda:\n\n"
        "<code>00:05-00:12 | Salom, men keldim</code>\n"
        "<code>00:13-00:20 | Qayerdan keldingiz?</code>\n\n"
        "Vaqt — shu gap videoda qachon eshitilishi (daqiqa:soniya). "
        "Qismlar bir-biriga kesishmasin. Hammasini bitta xabarda yuboring."
    )


@router.message(
    StateFilter(AdminStates.waiting_clip_parts),
    F.text,
    ~F.text.startswith("/"),
)
async def process_clip_parts(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    max_duration = data.get("clip_bg_duration") or data.get("clip_duration")

    parts, errors = parse_parts(message.text, max_duration=max_duration)

    if errors:
        shown = "\n".join(f"• {html.escape(e)}" for e in errors[:8])
        await message.answer(
            "❌ Quyidagi xatolarni to'g'rilab, matnni qaytadan yuboring:\n\n"
            f"{shown}"
        )
        return

    title = data.get("clip_title")
    video_file_id = data.get("clip_video_file_id")
    bg_file_id = data.get("clip_bg_file_id")

    if not (title and video_file_id and bg_file_id):
        await state.clear()
        await message.answer("❌ Ma'lumotlar yo'qolgan. /clip orqali qaytadan boshlang.")
        return

    try:
        clip_id = await db.add_clip(
            title=title,
            script="\n".join(part["text"] for part in parts),
            video_file_id=video_file_id,
            duration=data.get("clip_duration"),
            storage_chat_id=data.get("clip_storage_chat_id"),
            storage_message_id=data.get("clip_storage_message_id"),
            bg_file_id=bg_file_id,
            parts_json=json.dumps(parts, ensure_ascii=False),
        )
    except Exception as e:
        logging.exception("Parcha qo'shishda xatolik")
        await message.answer(
            "❌ Parcha qo'shishda xatolik yuz berdi.\n\n"
            f"<code>{html.escape(str(e))}</code>"
        )
        return
    finally:
        await state.clear()

    await message.answer(
        "✅ <b>Ovozli parcha qo'shildi!</b>\n\n"
        f"🎞 Nomi: <b>{html.escape(title)}</b>\n"
        f"🧩 Qismlar: <b>{len(parts)} ta</b>\n"
        f"⏱ Davomiyligi: <b>{data.get('clip_duration') or '?'} soniya</b>\n"
        f"🆔 ID: <code>{clip_id}</code>\n\n"
        "Foydalanuvchilar «🎙 Ovozli kino» tugmasida ko'radi.\n"
        "Ro'yxat va o'chirish: /clips"
    )


@router.message(Command("clips"))
async def cmd_clips(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    clips = await db.all_clips()

    if not clips:
        await message.answer(
            "🎙 Hozircha ovozli parchalar yo'q.\n"
            "Qo'shish uchun: /clip"
        )
        return

    await message.answer(
        "🎙 <b>Ovozli parchalar</b>\n\n"
        "O'chirish uchun parchani bosing:",
        reply_markup=admin_clips_keyboard(clips),
    )


@router.callback_query(F.data.startswith("admin_del_clip:"))
async def admin_delete_clip(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        clip_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Noto'g'ri parcha.", show_alert=True)
        return

    deleted = await db.delete_clip(clip_id)
    if not deleted:
        await callback.answer("❌ Parcha topilmadi.", show_alert=True)
        return

    # Storage kanaldagi nusxasini ham o'chirishga harakat qilamiz
    if deleted["storage_chat_id"] and deleted["storage_message_id"]:
        try:
            await bot.delete_message(
                chat_id=deleted["storage_chat_id"],
                message_id=deleted["storage_message_id"],
            )
        except Exception:
            pass

    await callback.answer(f"🗑 O'chirildi: {deleted['title']}", show_alert=False)

    # Ro'yxatni yangilaymiz
    clips = await db.all_clips()
    if clips:
        await callback.message.edit_reply_markup(
            reply_markup=admin_clips_keyboard(clips)
        )
    else:
        await callback.message.edit_text("🎙 Parchalar qolmadi. Qo'shish uchun: /clip")
