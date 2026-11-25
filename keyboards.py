from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from i18n import LANG_NAMES, LANGS, t


# ============================================================
# ASOSIY MENYU (klaviatura o'rnida chiqadigan tugmalar)
# ============================================================

def main_menu_keyboard(lang: str = "uz") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, "btn_code")), KeyboardButton(text=t(lang, "btn_name"))],
            [KeyboardButton(text=t(lang, "btn_voice")), KeyboardButton(text=t(lang, "btn_order"))],
            [KeyboardButton(text=t(lang, "btn_lang"))],
        ],
        resize_keyboard=True,
        input_field_placeholder=t(lang, "input_ph"),
    )


def lang_keyboard() -> InlineKeyboardMarkup:
    """Til tanlash tugmalari (🇺🇿 / 🇷🇺 / 🇬🇧)."""
    builder = InlineKeyboardBuilder()
    for code in LANGS:
        builder.button(text=LANG_NAMES[code], callback_data=f"setlang:{code}")
    builder.adjust(1)
    return builder.as_markup()


def _short(text: str, limit: int = 55) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def search_results_keyboard(
    movies: list[tuple], series: list[tuple]
) -> InlineKeyboardMarkup:
    """Nom bo'yicha qidiruv natijalari: movies=(code, name), series=(id, name)."""
    builder = InlineKeyboardBuilder()
    for code, name in movies:
        builder.button(text=f"🎬 {_short(name)}", callback_data=f"open_movie:{code}")
    for series_id, name in series:
        builder.button(text=f"📺 {_short(name)}", callback_data=f"open_series:{series_id}")
    builder.adjust(1)
    return builder.as_markup()


def _fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    return f" ({int(seconds) // 60}:{int(seconds) % 60:02d})"


def clips_keyboard(clips: list[tuple]) -> InlineKeyboardMarkup:
    """Foydalanuvchi uchun ovozli parchalar: (id, title, duration)."""
    builder = InlineKeyboardBuilder()
    for clip_id, title, duration in clips:
        builder.button(
            text=f"🎞 {_short(title, 45)}{_fmt_duration(duration)}",
            callback_data=f"clip:{clip_id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def part_redo_keyboard(idx: int, lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t(lang, "part_redo_btn"),
        callback_data=f"part_redo:{idx}",
    )
    return builder.as_markup()


def admin_clips_keyboard(clips: list[tuple]) -> InlineKeyboardMarkup:
    """Admin uchun o'chirish tugmalari: (id, title, duration)."""
    builder = InlineKeyboardBuilder()
    for clip_id, title, duration in clips:
        builder.button(
            text=f"🗑 {_short(title, 45)}",
            callback_data=f"admin_del_clip:{clip_id}",
        )
    builder.adjust(1)
    return builder.as_markup()


# ============================================================
# OBUNA / SERIAL (avvalgidek)
# ============================================================

def subscription_keyboard(channels: list[dict], lang: str = "uz") -> InlineKeyboardMarkup:
    """Obuna bo'linmagan kanallar ro'yxati + tekshirish tugmasi."""
    builder = InlineKeyboardBuilder()
    for i, ch in enumerate(channels, start=1):
        builder.button(text=t(lang, "sub_btn_channel", i=i), url=ch["link"])
    builder.button(text=t(lang, "sub_btn_done"), callback_data="check_subscription")
    builder.adjust(1)
    return builder.as_markup()


def serial_admin_keyboard(series: list[tuple]) -> InlineKeyboardMarkup:
    """Admin uchun mavjud seriallar + yangi serial tugmasi."""
    builder = InlineKeyboardBuilder()
    for series_id, code, name in series:
        builder.button(text=f"📺 {name}", callback_data=f"admin_series:{series_id}")
    builder.button(text="➕ Yangi serial", callback_data="admin_new_series")
    builder.adjust(1)
    return builder.as_markup()


def series_main_keyboard(series_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t(lang, "series_btn_eps"), callback_data=f"series_episodes:{series_id}")
    return builder.as_markup()


EPISODES_PER_PAGE = 30


def series_episodes_keyboard(
    episodes: list[tuple],
    series_id: int | None = None,
    current: int | None = None,
    page: int | None = None,
    lang: str = "uz",
) -> InlineKeyboardMarkup:
    """Qismlar tugmalari: qatorda 5 tadan, 30 tadan sahifalanadi.

    current — hozir ko'rilayotgan qism raqami (▶ bilan belgilanadi va pastda
    «oldingi / keyingi qism» tugmalari chiqadi).
    """
    pages = max(1, -(-len(episodes) // EPISODES_PER_PAGE))
    if page is None:
        index = next((i for i, e in enumerate(episodes) if e[1] == current), 0)
        page = index // EPISODES_PER_PAGE
    page = min(max(page, 0), pages - 1)

    chunk = episodes[page * EPISODES_PER_PAGE:(page + 1) * EPISODES_PER_PAGE]
    buttons = [
        InlineKeyboardButton(
            text=f"▶ {number}" if number == current else str(number),
            callback_data=f"series_episode:{episode_id}",
        )
        for episode_id, number, *_ in chunk
    ]
    rows = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]

    if pages > 1 and series_id is not None:
        cur = current or 0
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                text="◀️", callback_data=f"series_page:{series_id}:{page - 1}:{cur}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="series_noop"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(
                text="▶️", callback_data=f"series_page:{series_id}:{page + 1}:{cur}"))
        rows.append(nav)

    if current is not None:
        pos = next((i for i, e in enumerate(episodes) if e[1] == current), None)
        if pos is not None:
            step = []
            if pos > 0:
                prev = episodes[pos - 1]
                step.append(InlineKeyboardButton(
                    text=t(lang, "ep_prev", n=prev[1]), callback_data=f"series_episode:{prev[0]}"))
            if pos < len(episodes) - 1:
                nxt = episodes[pos + 1]
                step.append(InlineKeyboardButton(
                    text=t(lang, "ep_next", n=nxt[1]), callback_data=f"series_episode:{nxt[0]}"))
            if step:
                rows.append(step)

    return InlineKeyboardMarkup(inline_keyboard=rows)
