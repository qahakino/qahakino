import asyncio
import html
import logging
import tempfile
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
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
    clips_keyboard,
    lang_keyboard,
    main_menu_keyboard,
    part_redo_keyboard,
    search_results_keyboard,
    series_episodes_keyboard,
    series_main_keyboard,
    subscription_keyboard,
)
from i18n import LANGS, all_variants, get_lang, set_lang, t, ulang
from states import UserStates
from utils.media import MediaError, ffmpeg_available, mix_parts, replace_audio
from utils.parts import fmt_time
from utils.search import matches, normalize
from utils.subscription import get_unsubscribed_channels

router = Router()

# Menyu tugmalari uchala tilda taniladi
BTN_CODE_ALL = all_variants("btn_code")
BTN_NAME_ALL = all_variants("btn_name")
BTN_VOICE_ALL = all_variants("btn_voice")
BTN_LANG_ALL = all_variants("btn_lang")

MAX_SEARCH_RESULTS = 10

# Bir vaqtda ko'pi bilan 2 ta video yig'iladi (server qotib qolmasligi uchun)
_JOB_SEM = asyncio.Semaphore(2)
# Fon vazifalari "yig'ishtirib yuborilmasligi" uchun havolasini saqlab turamiz
_BACKGROUND_TASKS: set[asyncio.Task] = set()


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================

async def send_subscription_prompt(message: Message, channels: list[dict]):
    lang = await ulang(message.from_user.id)
    await message.answer(t(lang, "subscribe"), reply_markup=subscription_keyboard(channels, lang))


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
        lang = await ulang(callback.from_user.id)
        await callback.answer(t(lang, "need_all_channels"), show_alert=True)
        return False
    return True


async def welcome(bot: Bot, user_id: int, chat_id: int, name: str, lang: str):
    """Obunani tekshiradi, so'ng salomlashib asosiy menyuni chiqaradi."""
    if REQUIRED_CHANNELS:
        unsubscribed = await get_unsubscribed_channels(bot, user_id, REQUIRED_CHANNELS)
        if unsubscribed:
            await bot.send_message(
                chat_id, t(lang, "subscribe"),
                reply_markup=subscription_keyboard(unsubscribed, lang),
            )
            return

    await bot.send_message(
        chat_id,
        t(lang, "hello", name=html.escape(name)) + "\n\n" + t(lang, "ask_code"),
        reply_markup=main_menu_keyboard(lang),
    )


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
        await bot.send_message(chat_id, t(await ulang(chat_id), "movie_send_err"))


async def send_series_poster(bot: Bot, chat_id: int, series: tuple):
    series_id, _, name, poster_chat_id, poster_message_id = series
    lang = await ulang(chat_id)
    try:
        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=poster_chat_id,
            message_id=poster_message_id,
            caption=f"📺 <b>{html.escape(name)}</b>",
            reply_markup=series_main_keyboard(series_id, lang),
        )
    except Exception:
        await bot.send_message(chat_id, t(lang, "poster_send_err"))


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

    lang = await get_lang(message.from_user.id)
    if lang is None:
        # Birinchi marta kirdi — avval tilni tanlaydi
        await message.answer(t("uz", "choose_lang"), reply_markup=lang_keyboard())
        return

    await welcome(
        bot, message.from_user.id, message.chat.id, message.from_user.full_name, lang
    )


@router.message(Command("lang"))
async def cmd_lang(message: Message):
    await message.answer(t("uz", "choose_lang"), reply_markup=lang_keyboard())


@router.message(F.text.in_(BTN_LANG_ALL))
async def menu_language(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(t("uz", "choose_lang"), reply_markup=lang_keyboard())


@router.callback_query(F.data.startswith("setlang:"))
async def set_language(callback: CallbackQuery, bot: Bot, state: FSMContext):
    lang = callback.data.split(":", 1)[1]
    if lang not in LANGS:
        await callback.answer()
        return

    await state.clear()
    await set_lang(callback.from_user.id, lang)
    await callback.answer(t(lang, "lang_set"))
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Menyu tugmalari yangi tilda chiqishi uchun salomlashishni qayta yuboramiz
    await welcome(
        bot, callback.from_user.id, callback.message.chat.id,
        callback.from_user.full_name, lang,
    )


@router.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery, bot: Bot):
    lang = await ulang(callback.from_user.id)
    unsubscribed = await get_unsubscribed_channels(
        bot, callback.from_user.id, REQUIRED_CHANNELS
    )
    if unsubscribed:
        await callback.answer(t(lang, "not_all_subscribed"), show_alert=True)
        await callback.message.edit_reply_markup(
            reply_markup=subscription_keyboard(unsubscribed, lang)
        )
        return

    await callback.answer(t(lang, "sub_ok"))
    await callback.message.edit_text(t(lang, "thanks"))
    # Klaviaturani (menyu tugmalarini) chiqarish uchun alohida xabar kerak
    await callback.message.answer(t(lang, "ask_code"), reply_markup=main_menu_keyboard(lang))


# ============================================================
# MENYU TUGMALARI
# ============================================================

@router.message(F.text.in_(BTN_CODE_ALL))
async def menu_search_by_code(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    lang = await ulang(message.from_user.id)
    await state.clear()
    await message.answer(t(lang, "send_code"), reply_markup=main_menu_keyboard(lang))


@router.message(F.text.in_(BTN_NAME_ALL))
async def menu_search_by_name(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    lang = await ulang(message.from_user.id)
    await state.set_state(UserStates.waiting_name)
    await message.answer(t(lang, "send_name"), reply_markup=main_menu_keyboard(lang))


@router.message(F.text.in_(BTN_VOICE_ALL))
async def menu_voice(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    lang = await ulang(message.from_user.id)
    await state.clear()
    clips = await db.all_clips()

    if not clips:
        await message.answer(t(lang, "no_clips"), reply_markup=main_menu_keyboard(lang))
        return

    await message.answer(t(lang, "voice_intro"), reply_markup=clips_keyboard(clips))


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

    lang = await ulang(message.from_user.id)
    if len(normalize(query)) < 2:
        await message.answer(t(lang, "min2"))
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
        await message.answer(t(lang, "name_nf"))
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

    text = t(lang, "found_n", n=total)
    if total > MAX_SEARCH_RESULTS:
        text += t(lang, "first_n", m=MAX_SEARCH_RESULTS)

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
        await callback.answer(t(await ulang(callback.from_user.id), "movie_nf"), show_alert=True)
        return

    await callback.answer(t(await ulang(callback.from_user.id), "sending"))
    await send_movie(bot, callback.message.chat.id, movie)


@router.callback_query(F.data.startswith("open_series:"))
async def open_series(callback: CallbackQuery, bot: Bot):
    if not await callback_subscribed(callback, bot):
        return

    try:
        series_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t(await ulang(callback.from_user.id), "bad_series"), show_alert=True)
        return

    series = await db.get_series(series_id)
    if not series:
        await callback.answer(t(await ulang(callback.from_user.id), "series_nf"), show_alert=True)
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

    lang = await ulang(chat_id)
    text = t(
        lang, "part_prompt",
        i=idx + 1, n=len(parts),
        a=fmt_time(part["start"]), b=fmt_time(part["end"]),
        sec=int(round(window)), text=html.escape(part["text"]),
    )
    await bot.send_message(
        chat_id,
        text,
        reply_markup=part_redo_keyboard(idx, lang) if idx > 0 else None,
    )


async def start_parts_flow(bot: Bot, chat_id: int, state: FSMContext, clip: dict):
    await state.set_state(UserStates.waiting_part)
    await state.set_data({"clip_id": clip["id"], "idx": 0, "voices": []})

    await bot.send_message(
        chat_id, t(await ulang(chat_id), "parts_intro", n=len(clip["parts"]))
    )
    await send_part_prompt(bot, chat_id, clip, 0)


@router.message(StateFilter(UserStates.waiting_part), F.voice | F.audio)
async def receive_part(message: Message, bot: Bot, state: FSMContext):
    logging.info("Qism ovozi qabul qilindi: user_id=%s", message.from_user.id)
    try:
        await _receive_part(message, bot, state)
    except Exception:
        logging.exception("receive_part ichida xatolik")
        lang = await ulang(message.from_user.id)
        await message.answer(t(lang, "voice_proc_err", btn=t(lang, "btn_voice")))


async def _receive_part(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    lang = await ulang(message.from_user.id)

    data = await state.get_data()
    clip = await db.get_clip_full(data.get("clip_id") or 0)
    idx = int(data.get("idx", 0))
    voices = list(data.get("voices", []))

    if not clip or not clip["parts"] or idx >= len(clip["parts"]):
        await state.clear()
        await message.answer(
            t(lang, "clip_nf_retry", btn=t(lang, "btn_voice")),
            reply_markup=main_menu_keyboard(lang),
        )
        return

    if not ffmpeg_available():
        logging.error("ffmpeg/ffprobe serverda o'rnatilmagan!")
        await message.answer(t(lang, "ffmpeg_off"))
        return

    media = message.voice or message.audio
    parts = clip["parts"]
    window = parts[idx]["end"] - parts[idx]["start"]

    if media.file_size and media.file_size > MAX_DOWNLOAD_BYTES:
        await message.answer(t(lang, "voice_too_big"))
        return

    if media.duration is not None and media.duration < 1:
        await message.answer(t(lang, "voice_short"))
        return

    if media.duration and media.duration > window + PART_EXTRA_SECONDS:
        await message.answer(
            t(lang, "part_too_long", d=media.duration, w=int(round(window)))
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
    status = await message.answer(t(lang, "all_parts_ok"))

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
    lang = await ulang(callback.from_user.id)
    data = await state.get_data()
    idx = int(data.get("idx", 0))
    voices = list(data.get("voices", []))

    try:
        pressed_idx = int(callback.data.split(":", 1)[1])
    except ValueError:
        pressed_idx = -1

    if pressed_idx != idx:
        await callback.answer(t(lang, "stale_btn"), show_alert=True)
        return

    if idx <= 0 or not voices:
        await callback.answer(t(lang, "no_prev_part"), show_alert=True)
        return

    clip = await db.get_clip_full(data.get("clip_id") or 0)
    if not clip:
        await callback.answer(t(lang, "clip_nf"), show_alert=True)
        return

    idx -= 1
    voices.pop()
    await state.update_data(idx=idx, voices=voices)

    await callback.answer(t(lang, "rewrite"))
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
    lang = await ulang(chat_id)
    try:
        async with _JOB_SEM:
            with tempfile.TemporaryDirectory(prefix="voiceparts_") as tmp:
                tmp_dir = Path(tmp)
                bg_path = tmp_dir / "bg.mp4"
                out_path = tmp_dir / "result.mp4"

                await _set_status(status, t(lang, "st_1"))
                await bot.download(clip["bg_file_id"], destination=bg_path, timeout=120)

                voices: list[tuple[Path, float]] = []
                for i, (file_id, part) in enumerate(zip(voice_ids, clip["parts"])):
                    voice_path = tmp_dir / f"voice_{i}.ogg"
                    await bot.download(file_id, destination=voice_path, timeout=120)
                    voices.append((voice_path, part["start"]))

                await _set_status(status, t(lang, "st_2_parts"))
                await mix_parts(bg_path, voices, out_path)

                await _set_status(status, t(lang, "st_3"))
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(out_path, filename="ovozli_kino.mp4"),
                    caption=(
                        f"🎬 <b>{html.escape(clip['title'])}</b>\n"
                        + t(lang, "cap_voice")
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
    await message.answer(t(await ulang(message.from_user.id), "wrong_type"))


@router.callback_query(F.data.startswith("clip:"))
async def pick_clip(callback: CallbackQuery, bot: Bot, state: FSMContext):
    if not await callback_subscribed(callback, bot):
        return

    lang = await ulang(callback.from_user.id)

    try:
        clip_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer(t(lang, "bad_clip"), show_alert=True)
        return

    clip = await db.get_clip(clip_id)
    if not clip:
        await callback.answer(t(lang, "clip_nf"), show_alert=True)
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
        await bot.send_message(chat_id, t(lang, "video_send_err"))
        return

    # Yangi usul: parcha qismlarga bo'lingan va orqa fonli video bor
    full = await db.get_clip_full(clip_id)
    if full and full["parts"] and full["bg_file_id"]:
        await start_parts_flow(bot, chat_id, state, full)
        return

    # Eski usul (qismsiz parchalar): bitta ovoz bilan butun videoni almashtirish
    await state.set_state(UserStates.waiting_voice)
    await state.update_data(clip_id=clip_id)

    length_hint = t(lang, "length_hint", d=fmt_duration(duration)) if duration else ""
    await bot.send_message(
        chat_id,
        t(lang, "script_prompt", script=html.escape(script), hint=length_hint),
    )


@router.message(StateFilter(UserStates.waiting_voice), F.voice | F.audio)
async def receive_voice(message: Message, bot: Bot, state: FSMContext):
    logging.info("Ovoz qabul qilindi: user_id=%s", message.from_user.id)
    try:
        await _receive_voice(message, bot, state)
    except Exception:
        logging.exception("receive_voice ichida xatolik")
        lang = await ulang(message.from_user.id)
        await message.answer(t(lang, "voice_proc_err", btn=t(lang, "btn_voice")))


async def _receive_voice(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    lang = await ulang(message.from_user.id)

    data = await state.get_data()
    clip_id = data.get("clip_id")
    clip = await db.get_clip(clip_id) if clip_id else None

    if not clip:
        await state.clear()
        await message.answer(
            t(lang, "clip_nf_retry", btn=t(lang, "btn_voice")),
            reply_markup=main_menu_keyboard(lang),
        )
        return

    if not ffmpeg_available():
        logging.error("ffmpeg/ffprobe serverda o'rnatilmagan!")
        await message.answer(t(lang, "ffmpeg_off"))
        return

    media = message.voice or message.audio
    clip_duration = clip[4]

    if media.file_size and media.file_size > MAX_DOWNLOAD_BYTES:
        await message.answer(t(lang, "voice_too_big"))
        return

    if media.duration is not None and media.duration < 2:
        await message.answer(t(lang, "voice_short_full"))
        return

    if (
        clip_duration
        and media.duration
        and media.duration > clip_duration + VOICE_EXTRA_SECONDS
    ):
        await message.answer(
            t(lang, "voice_longer", a=fmt_duration(media.duration), b=fmt_duration(clip_duration))
        )
        return

    await state.clear()
    status = await message.answer(t(lang, "voice_ok"))

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
    lang = await ulang(chat_id)

    try:
        async with _JOB_SEM:
            with tempfile.TemporaryDirectory(prefix="voiceclip_") as tmp:
                tmp_dir = Path(tmp)
                video_path = tmp_dir / "clip.mp4"
                voice_path = tmp_dir / "voice.ogg"
                out_path = tmp_dir / "result.mp4"

                await _set_status(status, t(lang, "st_1"))
                await bot.download(video_file_id, destination=video_path, timeout=120)
                await bot.download(voice_file_id, destination=voice_path, timeout=120)

                await _set_status(status, t(lang, "st_2_one"))
                await replace_audio(video_path, voice_path, out_path)

                await _set_status(status, t(lang, "st_3"))
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(out_path, filename="ovozli_kino.mp4"),
                    caption=f"🎬 <b>{html.escape(title)}</b>\n" + t(lang, "cap_voice"),
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
    text = t(await ulang(status.chat.id), "video_fail")
    try:
        await status.edit_text(text)
    except Exception:
        await status.answer(text)


@router.message(StateFilter(UserStates.waiting_voice))
async def waiting_voice_wrong_type(message: Message):
    await message.answer(t(await ulang(message.from_user.id), "wrong_type"))


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

    lang = await ulang(message.from_user.id)
    await message.answer(
        t(lang, "code_nf", btn=t(lang, "btn_name")),
        reply_markup=main_menu_keyboard(lang),
    )


# ============================================================
# SERIAL QISMLARI (avvalgidek)
# ============================================================

@router.callback_query(F.data.startswith("series_episodes:"))
async def show_series_episodes(callback: CallbackQuery, bot: Bot):
    if not await callback_subscribed(callback, bot):
        return

    lang = await ulang(callback.from_user.id)
    series_id = int(callback.data.split(":", 1)[1])
    series = await db.get_series(series_id)
    if not series:
        await callback.answer(t(lang, "series_nf"), show_alert=True)
        return

    episodes = await db.get_episodes(series_id)
    if not episodes:
        await callback.answer(t(lang, "ep_none"), show_alert=True)
        return

    await callback.answer()
    keyboard = series_episodes_keyboard(episodes, series_id=series_id, lang=lang)
    try:
        # Poster xabarining o'zida qismlar tugmalari chiqadi (yangi xabar ochilmaydi)
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        await callback.message.answer(
            t(lang, "choose_ep", name=html.escape(series[2])),
            reply_markup=keyboard,
        )


@router.callback_query(F.data.startswith("series_episode:"))
async def send_series_episode(callback: CallbackQuery, bot: Bot):
    if not await callback_subscribed(callback, bot):
        return

    lang = await ulang(callback.from_user.id)
    episode_id = int(callback.data.split(":", 1)[1])
    episode = await db.get_episode(episode_id)
    if not episode:
        await callback.answer(t(lang, "ep_nf"), show_alert=True)
        return

    _, series_id, episode_number, chat_id, message_id = episode
    episodes = await db.get_episodes(series_id)

    await callback.answer(t(lang, "ep_sending", n=episode_number))
    try:
        # Tugmalar yuborilgan qismning O'ZIGA ulanadi: keyingi qismni
        # darrov shu videoning ostidan tanlab ketish mumkin.
        await bot.copy_message(
            chat_id=callback.message.chat.id,
            from_chat_id=chat_id,
            message_id=message_id,
            reply_markup=series_episodes_keyboard(
                episodes, series_id=series_id, current=episode_number, lang=lang
            ),
        )
    except Exception:
        await callback.message.answer(t(lang, "ep_send_err"))
        return

    # Yuqoridagi (eski) xabardagi tugmalar yo'qoladi
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.callback_query(F.data.startswith("series_page:"))
async def series_episodes_page(callback: CallbackQuery):
    """Qismlar ro'yxatini sahifalash (◀️ 2/4 ▶️)."""
    try:
        _, series_id, page, current = callback.data.split(":")
        series_id, page, current = int(series_id), int(page), int(current)
    except ValueError:
        await callback.answer()
        return

    episodes = await db.get_episodes(series_id)
    lang = await ulang(callback.from_user.id)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=series_episodes_keyboard(
                episodes, series_id=series_id, current=current or None, page=page, lang=lang
            )
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "series_noop")
async def series_noop(callback: CallbackQuery):
    await callback.answer()


# ============================================================
# HOLATSIZ KELGAN OVOZ (masalan, bot qayta ishga tushgan bo'lsa)
# ============================================================

@router.message(F.voice | F.audio)
async def voice_without_state(message: Message):
    lang = await ulang(message.from_user.id)
    await message.answer(
        t(lang, "voice_no_state", btn=t(lang, "btn_voice")),
        reply_markup=main_menu_keyboard(lang),
    )
