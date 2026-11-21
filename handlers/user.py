import asyncio
import html
import logging
import tempfile
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from config import (
    MAX_DOWNLOAD_BYTES,
    PART_EXTRA_SECONDS,
    REQUIRED_CHANNELS,
    VOICE_EXTRA_SECONDS,
)
from database import db
from keyboards import (
    BTN_CODE,
    BTN_NAME,
    BTN_VOICE,
    clips_keyboard,
    main_menu_keyboard,
    part_redo_keyboard,
    search_results_keyboard,
    series_episodes_keyboard,
    series_main_keyboard,
    subscription_keyboard,
)
from states import UserStates
from utils.media import MediaError, ffmpeg_available, mix_parts, replace_audio
from utils.parts import fmt_time
from utils.search import matches, normalize
from utils.subscription import get_unsubscribed_channels

router = Router()

SUBSCRIBE_TEXT = (
    "📢 Botdan foydalanish uchun avval quyidagi kanal(lar)ga obuna bo'ling.\n\n"
    "Obuna bo'lgach, \"✅ Obuna bo'ldim\" tugmasini bosing."
)

ASK_CODE_TEXT = (
    "🎬 Kino yoki serial kodini kiriting, men sizga topib beraman.\n"
    "Yoki pastdagi tugmalardan foydalaning."
)

MAX_SEARCH_RESULTS = 10

# Bir vaqtda ko'pi bilan 2 ta video yig'iladi (server qotib qolmasligi uchun)
_JOB_SEM = asyncio.Semaphore(2)
# Fon vazifalari "yig'ishtirib yuborilmasligi" uchun havolasini saqlab turamiz
_BACKGROUND_TASKS: set[asyncio.Task] = set()


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

async def send_subscription_prompt(message: Message, channels: list[dict]):
    await message.answer(SUBSCRIBE_TEXT, reply_markup=subscription_keyboard(channels))


async def check_user_subscription(message: Message, bot: Bot) -> bool:
    if not REQUIRED_CHANNELS:
        return True

    unsubscribed = await get_unsubscribed_channels(
        bot, message.from_user.id, REQUIRED_CHANNELS
    )
    if unsubscribed:
        await send_subscription_prompt(message, unsubscribed)
        return False
    return True


async def callback_subscribed(callback: CallbackQuery, bot: Bot) -> bool:
    """Tugma bosilganda obunani tekshiradi (obuna bo'lmasa ogohlantiradi)."""
    if not REQUIRED_CHANNELS:
        return True

    unsubscribed = await get_unsubscribed_channels(
        bot, callback.from_user.id, REQUIRED_CHANNELS
    )
    if unsubscribed:
        await callback.answer(
            "❌ Avval barcha kanallarga obuna bo'ling.", show_alert=True
        )
        return False
    return True


def fmt_duration(seconds: int | float | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


async def send_movie(bot: Bot, chat_id: int, movie: tuple):
    _, _name, from_chat_id, from_message_id = movie
    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=from_message_id,
        )
    except Exception:
        await bot.send_message(
            chat_id,
            "⚠️ Kinoni yuborishda xatolik yuz berdi. Birozdan so'ng qaytadan urinib ko'ring.",
        )


async def send_series_poster(bot: Bot, chat_id: int, series: tuple):
    series_id, _, name, poster_chat_id, poster_message_id = series
    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=poster_chat_id,
            message_id=poster_message_id,
            caption=f"📺 <b>{html.escape(name)}</b>",
            reply_markup=series_main_keyboard(series_id),
        )
    except Exception:
        await bot.send_message(
            chat_id,
            "⚠️ Serial posterini yuborishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.",
        )


async def send_by_code(bot: Bot, chat_id: int, code: str) -> bool:
    """Kod bo'yicha kino yoki serialni yuboradi. Topilsa True."""
    movie = await db.get_movie(code)
    if movie:
        await send_movie(bot, chat_id, movie)
        return True

    series = await db.get_series_by_code(code)
    if series:
        await send_series_poster(bot, chat_id, series)
        return True

    return False


# ============================================================
# /START VA OBUNA
# ============================================================

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot, state: FSMContext):
    await state.clear()

    await db.add_user(
        message.from_user.id,
        message.from_user.full_name,
        message.from_user.username,
    )

    if not await check_user_subscription(message, bot):
        return

    await message.answer(
        f"👋 Assalomu alaykum, {html.escape(message.from_user.full_name)}!\n\n{ASK_CODE_TEXT}",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery, bot: Bot):
    unsubscribed = await get_unsubscribed_channels(
        bot, callback.from_user.id, REQUIRED_CHANNELS
    )
    if unsubscribed:
        await callback.answer(
            "❌ Siz hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True
        )
        await callback.message.edit_reply_markup(
            reply_markup=subscription_keyboard(unsubscribed)
        )
        return

    await callback.answer("✅ Obuna tasdiqlandi!")
    await callback.message.edit_text("✅ Rahmat!")
    # Klaviaturani (menyu tugmalarini) chiqarish uchun alohida xabar kerak
    await callback.message.answer(ASK_CODE_TEXT, reply_markup=main_menu_keyboard())


# ============================================================
# MENYU TUGMALARI
# ============================================================

@router.message(F.text == BTN_CODE)
async def menu_search_by_code(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    await state.clear()
    await message.answer(
        "🔢 Kino yoki serial <b>kodini</b> yuboring:",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == BTN_NAME)
async def menu_search_by_name(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    await state.set_state(UserStates.waiting_name)
    await message.answer(
        "🔎 Kino yoki serial <b>nomini</b> yozing.\n"
        "Nomning bir qismi ham yetarli, masalan: <i>temir</i>",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == BTN_VOICE)
async def menu_voice(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    await state.clear()
    clips = await db.all_clips()

    if not clips:
        await message.answer(
            "🎙 Hozircha ovozli parchalar yo'q. Tez orada qo'shiladi!",
            reply_markup=main_menu_keyboard(),
        )
        return

    await message.answer(
        "🎙 <b>Ovozli kino</b>\n\n"
        "Kinodan mashhur parchani tanlang. Men sizga videoni va uning matnini "
        "yuboraman. Matnni o'qib, <b>ovozli xabar</b> yuborsangiz, videoga "
        "sizning ovozingizni qo'yib beraman.",
        reply_markup=clips_keyboard(clips),
    )


# ============================================================
# NOM BO'YICHA QIDIRUV
# ============================================================

@router.message(
    StateFilter(UserStates.waiting_name),
    F.text,
    ~F.text.startswith("/"),
)
async def handle_name_search(message: Message, bot: Bot):
    if not await check_user_subscription(message, bot):
        return

    query = message.text.strip()

    # Foydalanuvchi adashib kod yozgan bo'lsa ham topib beramiz
    if await send_by_code(bot, message.chat.id, query):
        return

    if len(normalize(query)) < 2:
        await message.answer("❌ Kamida 2 ta harf yozing.")
        return

    movies = [
        (code, name)
        for code, name in await db.all_movies_basic()
        if matches(query, name or "")
    ]
    series = [
        (series_id, name)
        for series_id, _code, name in await db.all_series()
        if matches(query, name or "")
    ]

    total = len(movies) + len(series)

    if total == 0:
        await message.answer(
            "❌ Bunday nomli kino yoki serial topilmadi.\n"
            "Nomini boshqacha yozib ko'ring yoki kod orqali qidiring."
        )
        return

    # Bitta natija bo'lsa — to'g'ridan-to'g'ri yuboramiz
    if total == 1:
        if movies:
            movie = await db.get_movie(movies[0][0])
            if movie:
                await send_movie(bot, message.chat.id, movie)
        else:
            found = await db.get_series(series[0][0])
            if found:
                await send_series_poster(bot, message.chat.id, found)
        return

    shown_movies = movies[:MAX_SEARCH_RESULTS]
    shown_series = series[: MAX_SEARCH_RESULTS - len(shown_movies)]

    text = f"🔎 Topildi: <b>{total} ta</b>. Keraklisini tanlang:"
    if total > MAX_SEARCH_RESULTS:
        text += f"\n(Dastlabki {MAX_SEARCH_RESULTS} tasi ko'rsatildi, aniqroq yozsangiz yaxshi.)"

    await message.answer(
        text,
        reply_markup=search_results_keyboard(shown_movies, shown_series),
    )


@router.callback_query(F.data.startswith("open_movie:"))
async def open_movie(callback: CallbackQuery, bot: Bot):
    if not await callback_subscribed(callback, bot):
        return

    code = callback.data.split(":", 1)[1]
    movie = await db.get_movie(code)
    if not movie:
        await callback.answer("❌ Kino topilmadi.", show_alert=True)
        return

    await callback.answer("🎬 Yuborilmoqda...")
    await send_movie(bot, callback.message.chat.id, movie)


@router.callback_query(F.data.startswith("open_series:"))
async def open_series(callback: CallbackQuery, bot: Bot):
    if not await callback_subscribed(callback, bot):
        return

    try:
        series_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("❌ Noto'g'ri serial.", show_alert=True)
        return

    series = await db.get_series(series_id)
    if not series:
        await callback.answer("❌ Serial topilmadi.", show_alert=True)
        return

    await callback.answer()
    await send_series_poster(bot, callback.message.chat.id, series)


# ============================================================
# OVOZLI KINO
# ============================================================

# ---------- Qismli (yangi) usul ----------

async def send_part_prompt(bot: Bot, chat_id: int, clip: dict, idx: int):
    parts = clip["parts"]
    part = parts[idx]
    window = part["end"] - part["start"]

    text = (
        f"🎙 <b>{idx + 1}/{len(parts)}-qism</b>  "
        f"⏱ {fmt_time(part['start'])}–{fmt_time(part['end'])} "
        f"(~{int(round(window))} soniya)\n\n"
        f"{html.escape(part['text'])}\n\n"
        "Shu qismni o'qib, <b>ovozli xabar</b> yuboring."
    )
    await bot.send_message(
        chat_id,
        text,
        reply_markup=part_redo_keyboard(idx) if idx > 0 else None,
    )


async def start_parts_flow(bot: Bot, chat_id: int, state: FSMContext, clip: dict):
    await state.set_state(UserStates.waiting_part)
    await state.set_data({"clip_id": clip["id"], "idx": 0, "voices": []})

    await bot.send_message(
        chat_id,
        f"🧩 Bu parcha <b>{len(clip['parts'])} qismdan</b> iborat. "
        "Har bir qism uchun alohida ovozli xabar yozasiz, oxirida men hammasini "
        "videoga joylab beraman.\n"
        "Bekor qilish uchun /start bosing.",
    )
    await send_part_prompt(bot, chat_id, clip, 0)


@router.message(StateFilter(UserStates.waiting_part), F.voice | F.audio)
async def receive_part(message: Message, bot: Bot, state: FSMContext):
    logging.info("Qism ovozi qabul qilindi: user_id=%s", message.from_user.id)
    try:
        await _receive_part(message, bot, state)
    except Exception:
        logging.exception("receive_part ichida xatolik")
        await message.answer(
            "⚠️ Ovozni qayta ishlashda xatolik yuz berdi. "
            "Qaytadan urinib ko'ring: «🎙 Ovozli kino» tugmasi."
        )


async def _receive_part(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    data = await state.get_data()
    clip = await db.get_clip_full(data.get("clip_id") or 0)
    idx = int(data.get("idx", 0))
    voices = list(data.get("voices", []))

    if not clip or not clip["parts"] or idx >= len(clip["parts"]):
        await state.clear()
        await message.answer(
            "❌ Parcha topilmadi. «🎙 Ovozli kino» tugmasidan qaytadan tanlang.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if not ffmpeg_available():
        logging.error("ffmpeg/ffprobe serverda o'rnatilmagan!")
        await message.answer(
            "⚠️ Hozircha video yig'ish ishlamayapti (server sozlanmoqda). "
            "Keyinroq urinib ko'ring."
        )
        return

    media = message.voice or message.audio
    parts = clip["parts"]
    window = parts[idx]["end"] - parts[idx]["start"]

    if media.file_size and media.file_size > MAX_DOWNLOAD_BYTES:
        await message.answer("❌ Ovoz fayli juda katta. Qisqaroq ovoz yuboring.")
        return

    if media.duration is not None and media.duration < 1:
        await message.answer("❌ Ovoz juda qisqa. Matnni o'qib, qayta yuboring.")
        return

    if media.duration and media.duration > window + PART_EXTRA_SECONDS:
        await message.answer(
            f"❌ Ovozingiz {media.duration} soniya, bu qism uchun esa "
            f"~{int(round(window))} soniyadan oshmasligi kerak.\n"
            "Biroz tezroq o'qib, qayta yuboring."
        )
        return

    voices.append(media.file_id)
    idx += 1

    if idx < len(parts):
        await state.update_data(idx=idx, voices=voices)
        await send_part_prompt(bot, message.chat.id, clip, idx)
        return

    # Hamma qism yig'ildi
    await state.clear()
    status = await message.answer(
        "✅ Barcha qismlar qabul qilindi.\n"
        "⏳ Videongiz tayyorlanmoqda, 1-2 daqiqa ketishi mumkin..."
    )

    task = asyncio.create_task(
        build_parts_video(
            bot=bot,
            chat_id=message.chat.id,
            voice_ids=voices,
            clip=clip,
            status=status,
        )
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


@router.callback_query(StateFilter(UserStates.waiting_part), F.data.startswith("part_redo:"))
async def part_redo(callback: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    idx = int(data.get("idx", 0))
    voices = list(data.get("voices", []))

    try:
        pressed_idx = int(callback.data.split(":", 1)[1])
    except ValueError:
        pressed_idx = -1

    if pressed_idx != idx:
        await callback.answer("Bu tugma eskirgan.", show_alert=True)
        return

    if idx <= 0 or not voices:
        await callback.answer("Qayta yoziladigan oldingi qism yo'q.", show_alert=True)
        return

    clip = await db.get_clip_full(data.get("clip_id") or 0)
    if not clip:
        await callback.answer("❌ Parcha topilmadi.", show_alert=True)
        return

    idx -= 1
    voices.pop()
    await state.update_data(idx=idx, voices=voices)

    await callback.answer("↩️ Qayta yozing")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await send_part_prompt(bot, callback.message.chat.id, clip, idx)


async def build_parts_video(
    bot: Bot,
    chat_id: int,
    voice_ids: list[str],
    clip: dict,
    status: Message,
):
    try:
        async with _JOB_SEM:
            with tempfile.TemporaryDirectory(prefix="voiceparts_") as tmp:
                tmp_dir = Path(tmp)
                bg_path = tmp_dir / "bg.mp4"
                out_path = tmp_dir / "result.mp4"

                await _set_status(status, "⬇️ 1/3 — Material yuklanmoqda...")
                await bot.download(clip["bg_file_id"], destination=bg_path, timeout=120)

                voices: list[tuple[Path, float]] = []
                for i, (file_id, part) in enumerate(zip(voice_ids, clip["parts"])):
                    voice_path = tmp_dir / f"voice_{i}.ogg"
                    await bot.download(file_id, destination=voice_path, timeout=120)
                    voices.append((voice_path, part["start"]))

                await _set_status(status, "🎬 2/3 — Ovozlar videoga joylanmoqda...")
                await mix_parts(bg_path, voices, out_path)

                await _set_status(status, "📤 3/3 — Tayyor video yuborilmoqda...")
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(out_path, filename="ovozli_kino.mp4"),
                    caption=(
                        f"🎬 <b>{html.escape(clip['title'])}</b>\n"
                        "🎙 Sizning ovozingiz bilan!"
                    ),
                    supports_streaming=True,
                )

        try:
            await status.delete()
        except Exception:
            pass

    except MediaError:
        logging.exception("Qismli video yig'ishda ffmpeg xatosi")
        await _fail_status(status)
    except Exception:
        logging.exception("Qismli video yaratishda xatolik")
        await _fail_status(status)


@router.message(StateFilter(UserStates.waiting_part))
async def waiting_part_wrong_type(message: Message):
    await message.answer(
        "🎙 Iltimos, <b>ovozli xabar</b> (voice) yuboring — "
        "mikrofon tugmasini bosib turib matnni o'qing.\n"
        "Bekor qilish uchun /start bosing."
    )


@router.callback_query(F.data.startswith("clip:"))
async def pick_clip(callback: CallbackQuery, bot: Bot, state: FSMContext):
    if not await callback_subscribed(callback, bot):
        return

    try:
        clip_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("❌ Noto'g'ri parcha.", show_alert=True)
        return

    clip = await db.get_clip(clip_id)
    if not clip:
        await callback.answer("❌ Parcha topilmadi.", show_alert=True)
        return

    _, title, script, video_file_id, duration = clip
    chat_id = callback.message.chat.id

    await callback.answer()

    try:
        await bot.send_video(
            chat_id=chat_id,
            video=video_file_id,
            caption=f"🎬 <b>{html.escape(title)}</b>",
            supports_streaming=True,
        )
    except Exception:
        logging.exception("Parcha videosini yuborib bo'lmadi (clip_id=%s)", clip_id)
        await bot.send_message(
            chat_id,
            "⚠️ Videoni yuborishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.",
        )
        return

    # Yangi usul: parcha qismlarga bo'lingan va orqa fonli video bor
    full = await db.get_clip_full(clip_id)
    if full and full["parts"] and full["bg_file_id"]:
        await start_parts_flow(bot, chat_id, state, full)
        return

    # Eski usul (qismsiz parchalar): bitta ovoz bilan butun videoni almashtirish
    await state.set_state(UserStates.waiting_voice)
    await state.update_data(clip_id=clip_id)

    length_hint = f" Videoning davomiyligi: <b>{fmt_duration(duration)}</b>." if duration else ""
    await bot.send_message(
        chat_id,
        f"📜 <b>Matn:</b>\n\n{html.escape(script)}\n\n"
        "🎙 Endi shu matnni o'qib, <b>ovozli xabar</b> (voice) yuboring."
        f"{length_hint}\n"
        "Bekor qilish uchun /start bosing.",
    )


@router.message(StateFilter(UserStates.waiting_voice), F.voice | F.audio)
async def receive_voice(message: Message, bot: Bot, state: FSMContext):
    logging.info("Ovoz qabul qilindi: user_id=%s", message.from_user.id)
    try:
        await _receive_voice(message, bot, state)
    except Exception:
        logging.exception("receive_voice ichida xatolik")
        await message.answer(
            "⚠️ Ovozni qayta ishlashda xatolik yuz berdi. "
            "Qaytadan urinib ko'ring: «🎙 Ovozli kino» tugmasi."
        )


async def _receive_voice(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    data = await state.get_data()
    clip_id = data.get("clip_id")
    clip = await db.get_clip(clip_id) if clip_id else None

    if not clip:
        await state.clear()
        await message.answer(
            "❌ Parcha topilmadi. «🎙 Ovozli kino» tugmasidan qaytadan tanlang.",
            reply_markup=main_menu_keyboard(),
        )
        return

    if not ffmpeg_available():
        logging.error("ffmpeg/ffprobe serverda o'rnatilmagan!")
        await message.answer(
            "⚠️ Hozircha video yig'ish ishlamayapti (server sozlanmoqda). "
            "Keyinroq urinib ko'ring."
        )
        return

    media = message.voice or message.audio
    clip_duration = clip[4]

    if media.file_size and media.file_size > MAX_DOWNLOAD_BYTES:
        await message.answer("❌ Ovoz fayli juda katta. Qisqaroq ovoz yuboring.")
        return

    if media.duration is not None and media.duration < 2:
        await message.answer("❌ Ovoz juda qisqa. Matnni to'liq o'qib, qayta yuboring.")
        return

    if (
        clip_duration
        and media.duration
        and media.duration > clip_duration + VOICE_EXTRA_SECONDS
    ):
        await message.answer(
            f"❌ Ovozingiz ({fmt_duration(media.duration)}) videodan "
            f"({fmt_duration(clip_duration)}) uzun.\n"
            "Biroz tezroq o'qib, qayta yuboring."
        )
        return

    await state.clear()
    status = await message.answer(
        "✅ Ovozingiz qabul qilindi.\n⏳ Videongiz tayyorlanmoqda, "
        "1 daqiqagacha vaqt ketishi mumkin..."
    )

    # Handler tezda qaytadi, og'ir ish fonda bajariladi (webhook kutib qolmasligi uchun)
    task = asyncio.create_task(
        build_and_send_video(
            bot=bot,
            chat_id=message.chat.id,
            voice_file_id=media.file_id,
            clip=clip,
            status=status,
        )
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _set_status(status: Message, text: str):
    try:
        await status.edit_text(text)
    except Exception:
        pass  # masalan, matn o'zgarmagan bo'lsa


async def build_and_send_video(
    bot: Bot,
    chat_id: int,
    voice_file_id: str,
    clip: tuple,
    status: Message,
):
    _, title, _script, video_file_id, _duration = clip

    try:
        async with _JOB_SEM:
            with tempfile.TemporaryDirectory(prefix="voiceclip_") as tmp:
                tmp_dir = Path(tmp)
                video_path = tmp_dir / "clip.mp4"
                voice_path = tmp_dir / "voice.ogg"
                out_path = tmp_dir / "result.mp4"

                await _set_status(status, "⬇️ 1/3 — Material yuklanmoqda...")
                await bot.download(video_file_id, destination=video_path, timeout=120)
                await bot.download(voice_file_id, destination=voice_path, timeout=120)

                await _set_status(status, "🎬 2/3 — Ovoz videoga qo'yilmoqda...")
                await replace_audio(video_path, voice_path, out_path)

                await _set_status(status, "📤 3/3 — Tayyor video yuborilmoqda...")
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(out_path, filename="ovozli_kino.mp4"),
                    caption=f"🎬 <b>{html.escape(title)}</b>\n🎙 Sizning ovozingiz bilan!",
                    supports_streaming=True,
                )

        # Tayyor video yuborildi — jarayon xabarini o'chiramiz
        try:
            await status.delete()
        except Exception:
            pass

    except MediaError:
        logging.exception("Video yig'ishda ffmpeg xatosi")
        await _fail_status(status)
    except Exception:
        logging.exception("Ovozli video yaratishda xatolik")
        await _fail_status(status)


async def _fail_status(status: Message):
    text = "⚠️ Video yaratishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring."
    try:
        await status.edit_text(text)
    except Exception:
        await status.answer(text)


@router.message(StateFilter(UserStates.waiting_voice))
async def waiting_voice_wrong_type(message: Message):
    await message.answer(
        "🎙 Iltimos, <b>ovozli xabar</b> (voice) yuboring — "
        "mikrofon tugmasini bosib turib matnni o'qing.\n"
        "Bekor qilish uchun /start bosing."
    )


# ============================================================
# KOD ORQALI QIDIRUV (oddiy matn — avvalgidek ishlaydi)
# ============================================================

@router.message(F.text & ~F.text.startswith("/"))
async def handle_code(message: Message, bot: Bot):
    if not await check_user_subscription(message, bot):
        return

    code = message.text.strip()

    if await send_by_code(bot, message.chat.id, code):
        return

    await message.answer(
        "❌ Bunday kodli kino yoki serial topilmadi.\n"
        "Kodni tekshirib, qaytadan yuboring yoki «🔎 Nomi orqali qidirish» tugmasini bosing.",
        reply_markup=main_menu_keyboard(),
    )


# ============================================================
# SERIAL QISMLARI (avvalgidek)
# ============================================================

@router.callback_query(F.data.startswith("series_episodes:"))
async def show_series_episodes(callback: CallbackQuery, bot: Bot):
    if not await callback_subscribed(callback, bot):
        return

    series_id = int(callback.data.split(":", 1)[1])
    series = await db.get_series(series_id)
    if not series:
        await callback.answer("❌ Serial topilmadi.", show_alert=True)
        return

    episodes = await db.get_episodes(series_id)
    if not episodes:
        await callback.answer("❌ Hozircha qismlar yo'q.", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer(
        f"📺 <b>{html.escape(series[2])}</b>\n\nQismni tanlang:",
        reply_markup=series_episodes_keyboard(episodes),
    )


@router.callback_query(F.data.startswith("series_episode:"))
async def send_series_episode(callback: CallbackQuery, bot: Bot):
    if not await callback_subscribed(callback, bot):
        return

    episode_id = int(callback.data.split(":", 1)[1])
    episode = await db.get_episode(episode_id)
    if not episode:
        await callback.answer("❌ Bu qism topilmadi.", show_alert=True)
        return

    _, _series_id, episode_number, chat_id, message_id = episode

    await callback.answer(f"▶️ {episode_number}-qism yuborilmoqda...")
    try:
        await bot.copy_message(
            chat_id=callback.message.chat.id,
            from_chat_id=chat_id,
            message_id=message_id,
        )
    except Exception:
        await callback.message.answer(
            "⚠️ Qismni yuborishda xatolik yuz berdi. Birozdan so'ng qaytadan urinib ko'ring."
        )


# ============================================================
# HOLATSIZ KELGAN OVOZ (masalan, bot qayta ishga tushgan bo'lsa)
# ============================================================

@router.message(F.voice | F.audio)
async def voice_without_state(message: Message):
    await message.answer(
        "🎙 Avval «🎙 Ovozli kino» tugmasidan parcha tanlang, "
        "keyin matnni o'qib ovozli xabar yuboring.",
        reply_markup=main_menu_keyboard(),
    )
