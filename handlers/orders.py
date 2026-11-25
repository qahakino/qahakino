"""Kino buyurtma qilish.

Mijoz: «🎬 Kino buyurtma qilish» → nom → til → buyurtma guruhga tushadi.
Xodim (admin): guruhdagi xabar ostida ✅ Qo'shdim (kodni yozadi) yoki ❌ Iloji yo'q (sabab).
Javob mijozga ASOSIY botdan ketadi (mijoz faqat shu bot bilan yozishgan).
"""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS, ORDERS_CHAT_ID
from database import db
from handlers.user import (
    MAX_SEARCH_RESULTS,
    callback_subscribed,
    check_user_subscription,
    send_by_code,
)
from i18n import LANG_NAMES, LANGS, all_variants, t, ulang
from keyboards import search_results_keyboard
from states import OrderStates, UserStates
from utils.search import matches, normalize

router = Router()

MAX_OPEN_ORDERS = 3

# Menyu tugmalari: buyurtma nomi sifatida qabul qilinmasligi kerak
ALL_MENU_BUTTONS = set().union(
    *(all_variants(k) for k in ("btn_code", "btn_name", "btn_voice", "btn_lang", "btn_order"))
)
BTN_ORDER_ALL = all_variants("btn_order")


def esc(x) -> str:
    return html.escape(str(x or ""), quote=False)   # Telegram uchun faqat & < > yetarli


def is_staff(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ============================================================
# MIJOZ TOMONI
# ============================================================

def _my_orders_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "order_my_btn"), callback_data="my_orders")]]
    )


@router.message(F.text.in_(BTN_ORDER_ALL))
async def menu_order(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    lang = await ulang(message.from_user.id)
    open_count = await db.count_open_orders(message.from_user.id)
    if open_count >= MAX_OPEN_ORDERS:
        await state.clear()
        await message.answer(t(lang, "order_limit", n=open_count), reply_markup=_my_orders_keyboard(lang))
        return

    await state.clear()
    await state.set_state(UserStates.waiting_order_title)
    await message.answer(t(lang, "order_prompt"), reply_markup=_my_orders_keyboard(lang))


@router.message(
    StateFilter(UserStates.waiting_order_title),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(ALL_MENU_BUTTONS),
)
async def order_title(message: Message, bot: Bot, state: FSMContext):
    if not await check_user_subscription(message, bot):
        return

    lang = await ulang(message.from_user.id)
    title = " ".join(message.text.split())

    if not 2 <= len(title) <= 120:
        await message.answer(t(lang, "order_title_err"))
        return

    # Adashib kod yozgan bo'lsa — kinoni darrov beramiz
    if await send_by_code(bot, message.chat.id, title):
        await state.clear()
        return

    # Bunday kino allaqachon bormi? Bo'lsa, buyurtma o'rniga o'shani ko'rsatamiz
    movies = [(c, n) for c, n in await db.all_movies_basic() if matches(title, n or "")]
    series = [(i, n) for i, _c, n in await db.all_series() if matches(title, n or "")]
    await state.update_data(order_title=title)

    if movies or series:
        shown_movies = movies[:MAX_SEARCH_RESULTS]
        shown_series = series[: MAX_SEARCH_RESULTS - len(shown_movies)]
        keyboard = search_results_keyboard(shown_movies, shown_series)
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text=t(lang, "order_anyway_btn"), callback_data="order_anyway")]
        )
        await message.answer(t(lang, "order_exists"), reply_markup=keyboard)
        return

    await _ask_order_language(message.answer, state, lang, title)


async def _ask_order_language(answer, state: FSMContext, lang: str, title: str):
    await state.set_state(UserStates.waiting_order_lang)
    builder = InlineKeyboardBuilder()
    for code in LANGS:
        builder.button(text=LANG_NAMES[code], callback_data=f"ordlang:{code}")
    builder.adjust(1)
    await answer(t(lang, "order_ask_lang", title=esc(title)), reply_markup=builder.as_markup())


@router.callback_query(F.data == "order_anyway", StateFilter(UserStates.waiting_order_title))
async def order_anyway(callback: CallbackQuery, state: FSMContext):
    lang = await ulang(callback.from_user.id)
    title = (await state.get_data()).get("order_title")
    if not title:
        await callback.answer(t(lang, "order_stale"), show_alert=True)
        return
    await callback.answer()
    await _ask_order_language(callback.message.answer, state, lang, title)


@router.callback_query(F.data == "order_anyway")
async def order_anyway_stale(callback: CallbackQuery):
    await callback.answer(t(await ulang(callback.from_user.id), "order_stale"), show_alert=True)


@router.callback_query(F.data.startswith("ordlang:"), StateFilter(UserStates.waiting_order_lang))
async def order_language(callback: CallbackQuery, bot: Bot, state: FSMContext):
    if not await callback_subscribed(callback, bot):
        return

    lang = await ulang(callback.from_user.id)
    movie_lang = callback.data.split(":", 1)[1]
    title = (await state.get_data()).get("order_title")
    if movie_lang not in LANGS or not title:
        await callback.answer(t(lang, "order_stale"), show_alert=True)
        return

    open_count = await db.count_open_orders(callback.from_user.id)
    if open_count >= MAX_OPEN_ORDERS:
        await state.clear()
        await callback.answer()
        await callback.message.answer(t(lang, "order_limit", n=open_count))
        return

    user = callback.from_user
    order_id = await db.create_order(
        user.id, user.username, user.full_name, title, movie_lang, lang
    )
    await state.clear()
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(
        t(lang, "order_ok", id=order_id, title=esc(title), lang=LANG_NAMES[movie_lang]),
        reply_markup=_my_orders_keyboard(lang),
    )
    await notify_staff(bot, order_id)


@router.callback_query(F.data.startswith("ordlang:"))
async def order_language_stale(callback: CallbackQuery):
    await callback.answer(t(await ulang(callback.from_user.id), "order_stale"), show_alert=True)


async def _orders_text(user_id: int) -> str:
    lang = await ulang(user_id)
    orders = await db.user_orders(user_id)
    if not orders:
        return t(lang, "orders_empty")
    lines = [t(lang, "orders_head"), ""]
    for o in orders:
        title = esc(o["title"])
        if o["status"] == "done":
            lines.append(t(lang, "order_line_done", id=o["id"], title=title, code=esc(o["code"])))
        elif o["status"] == "rejected":
            lines.append(t(lang, "order_line_rej", id=o["id"], title=title))
        else:
            lines.append(t(lang, "order_line_pending", id=o["id"], title=title))
    return "\n".join(lines)


@router.message(Command("orders"))
async def cmd_orders(message: Message):
    await message.answer(await _orders_text(message.from_user.id))


@router.callback_query(F.data == "my_orders")
async def cb_my_orders(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(await _orders_text(callback.from_user.id))


# ============================================================
# BUYURTMA XODIMLARGA (GURUHGA) YUBORILADI
# ============================================================

def staff_text(order: dict, same: int = 0) -> str:
    name = esc(order["full_name"]) or "—"
    username = f"@{esc(order['username'])}" if order.get("username") else "—"
    lines = [
        f"🆕 <b>Buyurtma #{order['id']}</b>",
        f"🎬 <b>{esc(order['title'])}</b>",
        f"🌐 Kerakli til: <b>{LANG_NAMES.get(order['movie_lang'], order['movie_lang'])}</b>",
        f"👤 <a href=\"tg://user?id={order['user_id']}\">{name}</a> ({username})",
        f"🆔 <code>{order['user_id']}</code> · mijoz tili: {order.get('user_lang') or '—'}",
    ]
    if same:
        lines.append(f"🔁 Shu nomda yana <b>{same} ta</b> kutilayotgan buyurtma bor")
    return "\n".join(lines)


def staff_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Qo'shdim", callback_data=f"ord_ok:{order_id}"),
        InlineKeyboardButton(text="❌ Iloji yo'q", callback_data=f"ord_no:{order_id}"),
    ]])


def reasons_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Topilmadi", callback_data=f"ord_rs:{order_id}:nf")],
        [InlineKeyboardButton(text="🌐 Shu tilda yo'q", callback_data=f"ord_rs:{order_id}:nl")],
        [InlineKeyboardButton(text="📉 Sifati yomon", callback_data=f"ord_rs:{order_id}:nq")],
        [InlineKeyboardButton(text="✍️ Boshqa sabab", callback_data=f"ord_rs:{order_id}:ot")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"ord_bk:{order_id}")],
    ])


async def notify_staff(bot: Bot, order_id: int):
    order = await db.get_order(order_id)
    if not order:
        return

    key = normalize(order["title"])
    same = sum(
        1 for o in await db.pending_orders()
        if o["id"] != order_id and normalize(o["title"]) == key
    )
    text = staff_text(order, same)
    targets = [ORDERS_CHAT_ID] if ORDERS_CHAT_ID else list(ADMIN_IDS)

    for chat_id in targets:
        try:
            sent = await bot.send_message(chat_id, text, reply_markup=staff_keyboard(order_id))
            await db.add_order_msg(order_id, chat_id, sent.message_id)
        except Exception:
            logging.exception("Buyurtmani %s ga yuborib bo'lmadi", chat_id)


async def refresh_staff(bot: Bot, order: dict, status_line: str):
    """Guruhdagi (yoki adminlardagi) buyurtma xabarini yangilab, tugmalarni olib tashlaydi."""
    text = staff_text(order) + "\n\n" + status_line
    for chat_id, message_id in await db.order_msgs(order["id"]):
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=None)
        except Exception:
            logging.warning("Buyurtma xabarini yangilab bo'lmadi: %s/%s", chat_id, message_id)


async def _notify_customer(bot: Bot, order: dict, text: str, markup=None) -> bool:
    try:
        await bot.send_message(order["user_id"], text, reply_markup=markup)
        return True
    except Exception:
        logging.warning("Mijozga (%s) xabar yetmadi", order["user_id"])
        return False


async def _open_markup(code: str, lang: str) -> InlineKeyboardMarkup | None:
    if await db.get_movie(code):
        data = f"open_movie:{code}"
    else:
        series = await db.get_series_by_code(code)
        if not series:
            return None
        data = f"open_series:{series[0]}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "order_open_btn"), callback_data=data)]]
    )


def _who(user) -> str:
    return f"@{user.username}" if getattr(user, "username", None) else esc(user.full_name)


async def complete_order(bot: Bot, order_id: int, code: str, admin) -> tuple[list[dict], int]:
    """Buyurtmani «bajarildi» qiladi va mijozga kodni yuboradi.

    Shu nom va shu tildagi boshqa kutilayotgan buyurtmalar ham avtomatik bajariladi.
    Qaytaradi: (bajarilgan buyurtmalar, xabar yetmaganlar soni).
    """
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        return [], 0

    batch = [order] + [
        o for o in await db.pending_orders()
        if o["id"] != order_id
        and normalize(o["title"]) == normalize(order["title"])
        and o["movie_lang"] == order["movie_lang"]
    ]

    done, unreachable = [], 0
    for o in batch:
        if not await db.finish_order(o["id"], "done", code=code, handled_by=admin.id):
            continue  # boshqa admin ulgurgan
        o = {**o, "status": "done", "code": code}
        done.append(o)
        lang = o["user_lang"] or "uz"
        sent = await _notify_customer(
            bot, o, t(lang, "order_done", title=esc(o["title"]), code=esc(code)),
            await _open_markup(code, lang),
        )
        unreachable += 0 if sent else 1
        await refresh_staff(bot, o, f"✅ Bajarildi — kod: <code>{esc(code)}</code> · {_who(admin)}")
    return done, unreachable


async def reject_order(bot: Bot, order_id: int, kind: str, admin, custom: str | None = None) -> bool | None:
    """Buyurtmani rad etadi. True — mijozga yetdi, False — yetmadi, None — allaqachon bajarilgan."""
    order = await db.get_order(order_id)
    if not order or order["status"] != "pending":
        return None

    lang = order["user_lang"] or "uz"
    if custom:
        reason = t(lang, "reason_custom", reason=esc(custom))
        stored = custom
    else:
        reason = t(lang, f"reason_{kind}", lang=LANG_NAMES.get(order["movie_lang"], ""))
        stored = kind
    if not await db.finish_order(order_id, "rejected", reason=stored, handled_by=admin.id):
        return None

    order = {**order, "status": "rejected"}
    sent = await _notify_customer(
        bot, order, t(lang, "order_rej", title=esc(order["title"]), reason=reason)
    )
    labels = {"nf": "topilmadi", "nl": "shu tilda yo'q", "nq": "sifati yomon"}
    await refresh_staff(
        bot, order, f"❌ Rad etildi — {esc(custom) if custom else labels.get(kind, kind)} · {_who(admin)}"
    )
    return sent


# ============================================================
# XODIM TUGMALARI (guruhda)
# ============================================================

async def _staff_guard(callback: CallbackQuery) -> dict | None:
    """Faqat adminlar; buyurtma hali kutilayotgan bo'lishi kerak."""
    if not is_staff(callback.from_user.id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return None
    order = await db.get_order(int(callback.data.split(":")[1]))
    if not order:
        await callback.answer("❌ Buyurtma topilmadi.", show_alert=True)
        return None
    if order["status"] != "pending":
        await callback.answer("Bu buyurtma allaqachon ko'rib chiqilgan.", show_alert=True)
        return None
    return order


async def _ask_admin_input(callback: CallbackQuery, bot: Bot, state: FSMContext, order: dict, kind: str):
    """Kod yoki sababni admin SHAXSIY chatda yozadi (guruhdagi maxfiylik rejimiga bog'liq emas)."""
    uid = callback.from_user.id
    if kind == "code":
        prompt = (
            f"🔑 <b>#{order['id']} — {esc(order['title'])}</b> "
            f"({LANG_NAMES.get(order['movie_lang'], '')})\n\n"
            "Kinoni botga qo'shgan bo'lsangiz, uning <b>kodini</b> yuboring.\n"
            "Bekor qilish: /cancel"
        )
        wait_state = OrderStates.waiting_code
    else:
        prompt = (
            f"✍️ <b>#{order['id']} — {esc(order['title'])}</b>\n\n"
            "Mijozga ko'rsatiladigan <b>sababni</b> yozing.\nBekor qilish: /cancel"
        )
        wait_state = OrderStates.waiting_reason

    try:
        await bot.send_message(uid, prompt)
    except Exception:
        await callback.answer("❗ Avval botga o'tib /start bosing, so'ng qayta bosing.", show_alert=True)
        return

    private = FSMContext(storage=state.storage, key=StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid))
    await private.set_state(wait_state)
    await private.update_data(order_id=order["id"])
    await callback.answer("📩 Botdan shaxsiy xabar keldi" if callback.message.chat.id != uid else "")


@router.callback_query(F.data.startswith("ord_ok:"))
async def staff_ok(callback: CallbackQuery, bot: Bot, state: FSMContext):
    order = await _staff_guard(callback)
    if order:
        await _ask_admin_input(callback, bot, state, order, "code")


@router.callback_query(F.data.startswith("ord_no:"))
async def staff_no(callback: CallbackQuery):
    order = await _staff_guard(callback)
    if order:
        await callback.answer()
        await callback.message.edit_reply_markup(reply_markup=reasons_keyboard(order["id"]))


@router.callback_query(F.data.startswith("ord_bk:"))
async def staff_back(callback: CallbackQuery):
    order = await _staff_guard(callback)
    if order:
        await callback.answer()
        await callback.message.edit_reply_markup(reply_markup=staff_keyboard(order["id"]))


@router.callback_query(F.data.startswith("ord_rs:"))
async def staff_reason(callback: CallbackQuery, bot: Bot, state: FSMContext):
    order = await _staff_guard(callback)
    if not order:
        return
    kind = callback.data.split(":")[2]
    if kind == "ot":
        await _ask_admin_input(callback, bot, state, order, "reason")
        return
    if kind not in ("nf", "nl", "nq"):
        await callback.answer()
        return

    sent = await reject_order(bot, order["id"], kind, callback.from_user)
    if sent is None:
        await callback.answer("Bu buyurtma allaqachon ko'rib chiqilgan.", show_alert=True)
    else:
        await callback.answer("❌ Rad etildi" + ("" if sent else " (mijozga xabar yetmadi)"))


# ============================================================
# ADMIN SHAXSIY CHATDA KOD / SABAB YOZADI
# ============================================================

@router.message(StateFilter(OrderStates.waiting_code), F.text, ~F.text.startswith("/"))
async def admin_order_code(message: Message, bot: Bot, state: FSMContext):
    if not is_staff(message.from_user.id):
        return
    order_id = (await state.get_data()).get("order_id")
    code = message.text.strip()

    if not await db.code_exists(code):
        await message.answer(
            f"❌ <code>{esc(code)}</code> kodli kino yoki serial topilmadi.\n"
            "Avval kinoni /admin orqali qo'shing, so'ng kodini yuboring. Bekor qilish: /cancel"
        )
        return

    done, unreachable = await complete_order(bot, order_id, code, message.from_user)
    await state.clear()
    if not done:
        await message.answer("⚠️ Bu buyurtma allaqachon ko'rib chiqilgan.")
        return

    text = f"✅ Bajarildi: mijozga kod yuborildi (#{done[0]['id']})."
    if len(done) > 1:
        ids = ", ".join(f"#{o['id']}" for o in done[1:])
        text += f"\n🔁 Shu nom va tildagi yana {len(done) - 1} ta buyurtma ham bajarildi: {ids}"
    if unreachable:
        text += f"\n⚠️ {unreachable} ta mijozga xabar yetmadi (botni bloklagan bo'lishi mumkin)."
    await message.answer(text)


@router.message(StateFilter(OrderStates.waiting_reason), F.text, ~F.text.startswith("/"))
async def admin_order_reason(message: Message, bot: Bot, state: FSMContext):
    if not is_staff(message.from_user.id):
        return
    order_id = (await state.get_data()).get("order_id")
    reason = message.text.strip()[:500]
    sent = await reject_order(bot, order_id, "ot", message.from_user, custom=reason)
    await state.clear()
    if sent is None:
        await message.answer("⚠️ Bu buyurtma allaqachon ko'rib chiqilgan.")
    else:
        await message.answer("❌ Rad etildi, sabab mijozga yuborildi." if sent else "❌ Rad etildi, lekin mijozga xabar yetmadi.")
