"""Ko'p tillilik: O'zbekcha (uz), Ruscha (ru), Inglizcha (en).

Har bir matn (uz, ru, en) tartibida. Foydalanuvchi tili `users.lang` ustunida
saqlanadi va bot bilan Mini App uchun umumiy.
"""
import aiosqlite

from database import db

LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "uz"
LANG_NAMES = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}

_PICK = "🌐 Tilni tanlang / Выберите язык / Choose your language"

TEXTS: dict[str, tuple[str, str, str]] = {
    # ---------- til tanlash ----------
    "choose_lang": (_PICK, _PICK, _PICK),
    "lang_set": ("✅ Til: O'zbekcha", "✅ Язык: Русский", "✅ Language: English"),

    # ---------- start / obuna ----------
    "hello": ("👋 Assalomu alaykum, {name}!", "👋 Здравствуйте, {name}!", "👋 Hello, {name}!"),
    "ask_code": (
        "🎬 Kino yoki serial kodini kiriting, men sizga topib beraman.\nYoki pastdagi tugmalardan foydalaning.",
        "🎬 Введите код фильма или сериала, и я найду его для вас.\nИли воспользуйтесь кнопками внизу.",
        "🎬 Send me a movie or series code and I'll find it for you.\nOr use the buttons below.",
    ),
    "subscribe": (
        "📢 Botdan foydalanish uchun avval quyidagi kanal(lar)ga obuna bo'ling.\n\nObuna bo'lgach, \"✅ Obuna bo'ldim\" tugmasini bosing.",
        "📢 Чтобы пользоваться ботом, сначала подпишитесь на канал(ы) ниже.\n\nПосле подписки нажмите «✅ Я подписался».",
        "📢 To use the bot, please subscribe to the channel(s) below first.\n\nThen press “✅ I've subscribed”.",
    ),
    "sub_btn_channel": ("📢 {i}-kanalga o'tish", "📢 Перейти в канал {i}", "📢 Go to channel {i}"),
    "sub_btn_done": ("✅ Obuna bo'ldim", "✅ Я подписался", "✅ I've subscribed"),
    "need_all_channels": (
        "❌ Avval barcha kanallarga obuna bo'ling.",
        "❌ Сначала подпишитесь на все каналы.",
        "❌ Please subscribe to all channels first.",
    ),
    "not_all_subscribed": (
        "❌ Siz hali barcha kanallarga obuna bo'lmadingiz!",
        "❌ Вы ещё не подписались на все каналы!",
        "❌ You haven't subscribed to all channels yet!",
    ),
    "sub_ok": ("✅ Obuna tasdiqlandi!", "✅ Подписка подтверждена!", "✅ Subscription confirmed!"),
    "thanks": ("✅ Rahmat!", "✅ Спасибо!", "✅ Thank you!"),

    # ---------- menyu ----------
    "btn_code": ("🔢 Kod orqali qidirish", "🔢 Поиск по коду", "🔢 Search by code"),
    "btn_name": ("🔎 Nomi orqali qidirish", "🔎 Поиск по названию", "🔎 Search by title"),
    "btn_voice": ("🎙 Ovozli kino", "🎙 Озвучь фильм", "🎙 Voice a movie"),
    "btn_lang": ("🌐 Til", "🌐 Язык", "🌐 Language"),
    "input_ph": (
        "Kod yoki kino nomini yozing...",
        "Введите код или название...",
        "Type a code or a title...",
    ),
    "send_code": (
        "🔢 Kino yoki serial <b>kodini</b> yuboring:",
        "🔢 Отправьте <b>код</b> фильма или сериала:",
        "🔢 Send the <b>code</b> of a movie or series:",
    ),
    "send_name": (
        "🔎 Kino yoki serial <b>nomini</b> yozing.\nNomning bir qismi ham yetarli, masalan: <i>temir</i>",
        "🔎 Напишите <b>название</b> фильма или сериала.\nДостаточно части названия, например: <i>железн</i>",
        "🔎 Type the <b>title</b> of a movie or series.\nPart of the title is enough, for example: <i>iron</i>",
    ),
    "no_clips": (
        "🎙 Hozircha ovozli parchalar yo'q. Tez orada qo'shiladi!",
        "🎙 Пока нет фрагментов для озвучки. Скоро добавим!",
        "🎙 There are no voice clips yet. They will be added soon!",
    ),
    "voice_intro": (
        "🎙 <b>Ovozli kino</b>\n\nKinodan mashhur parchani tanlang. Men sizga videoni va uning matnini "
        "yuboraman. Matnni o'qib, <b>ovozli xabar</b> yuborsangiz, videoga sizning ovozingizni qo'yib beraman.",
        "🎙 <b>Озвучь фильм</b>\n\nВыберите известный фрагмент из фильма. Я пришлю видео и его текст. "
        "Прочитайте текст и отправьте <b>голосовое сообщение</b>, и я наложу ваш голос на видео.",
        "🎙 <b>Voice a movie</b>\n\nPick a famous scene. I'll send you the video and its script. "
        "Read the script aloud and send a <b>voice message</b>, and I'll lay your voice over the video.",
    ),

    # ---------- qidiruv ----------
    "min2": ("❌ Kamida 2 ta harf yozing.", "❌ Введите не меньше 2 букв.", "❌ Type at least 2 letters."),
    "name_nf": (
        "❌ Bunday nomli kino yoki serial topilmadi.\nNomini boshqacha yozib ko'ring yoki kod orqali qidiring.",
        "❌ Фильм или сериал с таким названием не найден.\nПопробуйте написать иначе или поищите по коду.",
        "❌ No movie or series with that title was found.\nTry a different spelling or search by code.",
    ),
    "found_n": (
        "🔎 Topildi: <b>{n} ta</b>. Keraklisini tanlang:",
        "🔎 Найдено: <b>{n}</b>. Выберите нужное:",
        "🔎 Found: <b>{n}</b>. Pick the one you want:",
    ),
    "first_n": (
        "\n(Dastlabki {m} tasi ko'rsatildi, aniqroq yozsangiz yaxshi.)",
        "\n(Показаны первые {m}, уточните запрос для лучшего результата.)",
        "\n(Showing the first {m}. Be more specific for better results.)",
    ),
    "code_nf": (
        "❌ Bunday kodli kino yoki serial topilmadi.\nKodni tekshirib, qaytadan yuboring yoki «{btn}» tugmasini bosing.",
        "❌ Фильм или сериал с таким кодом не найден.\nПроверьте код и отправьте снова или нажмите «{btn}».",
        "❌ No movie or series with that code was found.\nCheck the code and send it again, or press “{btn}”.",
    ),
    "movie_nf": ("❌ Kino topilmadi.", "❌ Фильм не найден.", "❌ Movie not found."),
    "sending": ("🎬 Yuborilmoqda...", "🎬 Отправляю...", "🎬 Sending..."),
    "bad_series": ("❌ Noto'g'ri serial.", "❌ Неверный сериал.", "❌ Invalid series."),
    "series_nf": ("❌ Serial topilmadi.", "❌ Сериал не найден.", "❌ Series not found."),
    "movie_send_err": (
        "⚠️ Kinoni yuborishda xatolik yuz berdi. Birozdan so'ng qaytadan urinib ko'ring.",
        "⚠️ Не удалось отправить фильм. Попробуйте ещё раз чуть позже.",
        "⚠️ Couldn't send the movie. Please try again in a moment.",
    ),
    "poster_send_err": (
        "⚠️ Serial posterini yuborishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.",
        "⚠️ Не удалось отправить постер сериала. Попробуйте ещё раз чуть позже.",
        "⚠️ Couldn't send the series poster. Please try again in a moment.",
    ),

    # ---------- serial ----------
    "series_btn_eps": ("📺 Qismlarni ko'rish", "📺 Смотреть серии", "📺 Show episodes"),
    "ep_prev": ("⏮ {n}-qism", "⏮ Серия {n}", "⏮ Episode {n}"),
    "ep_next": ("{n}-qism ⏭", "Серия {n} ⏭", "Episode {n} ⏭"),
    "choose_ep": (
        "📺 <b>{name}</b>\n\nQismni tanlang:",
        "📺 <b>{name}</b>\n\nВыберите серию:",
        "📺 <b>{name}</b>\n\nChoose an episode:",
    ),
    "ep_none": ("❌ Hozircha qismlar yo'q.", "❌ Серий пока нет.", "❌ No episodes yet."),
    "ep_nf": ("❌ Bu qism topilmadi.", "❌ Эта серия не найдена.", "❌ Episode not found."),
    "ep_sending": ("▶️ {n}-qism yuborilmoqda...", "▶️ Отправляю серию {n}...", "▶️ Sending episode {n}..."),
    "ep_send_err": (
        "⚠️ Qismni yuborishda xatolik yuz berdi. Birozdan so'ng qaytadan urinib ko'ring.",
        "⚠️ Не удалось отправить серию. Попробуйте ещё раз чуть позже.",
        "⚠️ Couldn't send the episode. Please try again in a moment.",
    ),

    # ---------- ovozli kino ----------
    "part_prompt": (
        "🎙 <b>{i}/{n}-qism</b>  ⏱ {a}–{b} (~{sec} soniya)\n\n{text}\n\nShu qismni o'qib, <b>ovozli xabar</b> yuboring.",
        "🎙 <b>Часть {i}/{n}</b>  ⏱ {a}–{b} (~{sec} сек)\n\n{text}\n\nПрочитайте эту часть и отправьте <b>голосовое сообщение</b>.",
        "🎙 <b>Part {i}/{n}</b>  ⏱ {a}–{b} (~{sec} sec)\n\n{text}\n\nRead this part aloud and send a <b>voice message</b>.",
    ),
    "part_redo_btn": (
        "↩️ Oldingi qismni qayta yozish",
        "↩️ Перезаписать предыдущую часть",
        "↩️ Re-record the previous part",
    ),
    "parts_intro": (
        "🧩 Bu parcha <b>{n} qismdan</b> iborat. Har bir qism uchun alohida ovozli xabar yozasiz, "
        "oxirida men hammasini videoga joylab beraman.\nBekor qilish uchun /start bosing.",
        "🧩 Этот фрагмент состоит из <b>{n} частей</b>. Для каждой части запишите отдельное голосовое, "
        "а в конце я соберу всё в видео.\nЧтобы отменить, нажмите /start.",
        "🧩 This clip has <b>{n} parts</b>. Record a separate voice message for each part, "
        "and I'll put everything together in the video at the end.\nPress /start to cancel.",
    ),
    "voice_proc_err": (
        "⚠️ Ovozni qayta ishlashda xatolik yuz berdi. Qaytadan urinib ko'ring: «{btn}» tugmasi.",
        "⚠️ Не удалось обработать голос. Попробуйте ещё раз: кнопка «{btn}».",
        "⚠️ Couldn't process your voice message. Please try again: “{btn}” button.",
    ),
    "clip_nf_retry": (
        "❌ Parcha topilmadi. «{btn}» tugmasidan qaytadan tanlang.",
        "❌ Фрагмент не найден. Выберите заново через кнопку «{btn}».",
        "❌ Clip not found. Pick again with the “{btn}” button.",
    ),
    "ffmpeg_off": (
        "⚠️ Hozircha video yig'ish ishlamayapti (server sozlanmoqda). Keyinroq urinib ko'ring.",
        "⚠️ Сборка видео сейчас не работает (сервер настраивается). Попробуйте позже.",
        "⚠️ Video assembly isn't available right now (the server is being set up). Please try later.",
    ),
    "voice_too_big": (
        "❌ Ovoz fayli juda katta. Qisqaroq ovoz yuboring.",
        "❌ Голосовой файл слишком большой. Отправьте покороче.",
        "❌ The voice file is too large. Please send a shorter one.",
    ),
    "voice_short": (
        "❌ Ovoz juda qisqa. Matnni o'qib, qayta yuboring.",
        "❌ Голос слишком короткий. Прочитайте текст и отправьте снова.",
        "❌ The voice message is too short. Read the script and send it again.",
    ),
    "voice_short_full": (
        "❌ Ovoz juda qisqa. Matnni to'liq o'qib, qayta yuboring.",
        "❌ Голос слишком короткий. Прочитайте текст полностью и отправьте снова.",
        "❌ The voice message is too short. Read the whole script and send it again.",
    ),
    "part_too_long": (
        "❌ Ovozingiz {d} soniya, bu qism uchun esa ~{w} soniyadan oshmasligi kerak.\nBiroz tezroq o'qib, qayta yuboring.",
        "❌ Ваш голос {d} сек, а для этой части должно быть не больше ~{w} сек.\nПрочитайте чуть быстрее и отправьте снова.",
        "❌ Your voice message is {d} sec, but this part must not exceed ~{w} sec.\nRead a bit faster and send it again.",
    ),
    "all_parts_ok": (
        "✅ Barcha qismlar qabul qilindi.\n⏳ Videongiz tayyorlanmoqda, 1-2 daqiqa ketishi mumkin...",
        "✅ Все части получены.\n⏳ Готовлю ваше видео, это может занять 1–2 минуты...",
        "✅ All parts received.\n⏳ Preparing your video, it may take 1–2 minutes...",
    ),
    "stale_btn": ("Bu tugma eskirgan.", "Эта кнопка устарела.", "This button is outdated."),
    "no_prev_part": (
        "Qayta yoziladigan oldingi qism yo'q.",
        "Нет предыдущей части для перезаписи.",
        "There is no previous part to re-record.",
    ),
    "clip_nf": ("❌ Parcha topilmadi.", "❌ Фрагмент не найден.", "❌ Clip not found."),
    "rewrite": ("↩️ Qayta yozing", "↩️ Запишите заново", "↩️ Record it again"),
    "st_1": (
        "⬇️ 1/3 — Material yuklanmoqda...",
        "⬇️ 1/3 — Загружаю материал...",
        "⬇️ 1/3 — Downloading material...",
    ),
    "st_2_parts": (
        "🎬 2/3 — Ovozlar videoga joylanmoqda...",
        "🎬 2/3 — Накладываю голоса на видео...",
        "🎬 2/3 — Adding your voices to the video...",
    ),
    "st_2_one": (
        "🎬 2/3 — Ovoz videoga qo'yilmoqda...",
        "🎬 2/3 — Накладываю голос на видео...",
        "🎬 2/3 — Adding your voice to the video...",
    ),
    "st_3": (
        "📤 3/3 — Tayyor video yuborilmoqda...",
        "📤 3/3 — Отправляю готовое видео...",
        "📤 3/3 — Sending the finished video...",
    ),
    "cap_voice": ("🎙 Sizning ovozingiz bilan!", "🎙 С вашим голосом!", "🎙 With your voice!"),
    "wrong_type": (
        "🎙 Iltimos, <b>ovozli xabar</b> (voice) yuboring — mikrofon tugmasini bosib turib matnni o'qing.\n"
        "Bekor qilish uchun /start bosing.",
        "🎙 Пожалуйста, отправьте <b>голосовое сообщение</b> — удерживая кнопку микрофона, прочитайте текст.\n"
        "Чтобы отменить, нажмите /start.",
        "🎙 Please send a <b>voice message</b> — hold the microphone button and read the script.\n"
        "Press /start to cancel.",
    ),
    "voice_no_state": (
        "🎙 Avval «{btn}» tugmasidan parcha tanlang, keyin matnni o'qib ovozli xabar yuboring.",
        "🎙 Сначала выберите фрагмент кнопкой «{btn}», затем прочитайте текст и отправьте голосовое сообщение.",
        "🎙 First pick a clip with the “{btn}” button, then read the script and send a voice message.",
    ),
    "bad_clip": ("❌ Noto'g'ri parcha.", "❌ Неверный фрагмент.", "❌ Invalid clip."),
    "video_send_err": (
        "⚠️ Videoni yuborishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.",
        "⚠️ Не удалось отправить видео. Попробуйте ещё раз чуть позже.",
        "⚠️ Couldn't send the video. Please try again in a moment.",
    ),
    "script_prompt": (
        "📜 <b>Matn:</b>\n\n{script}\n\n🎙 Endi shu matnni o'qib, <b>ovozli xabar</b> (voice) yuboring.{hint}\n"
        "Bekor qilish uchun /start bosing.",
        "📜 <b>Текст:</b>\n\n{script}\n\n🎙 Теперь прочитайте этот текст и отправьте <b>голосовое сообщение</b>.{hint}\n"
        "Чтобы отменить, нажмите /start.",
        "📜 <b>Script:</b>\n\n{script}\n\n🎙 Now read this script aloud and send a <b>voice message</b>.{hint}\n"
        "Press /start to cancel.",
    ),
    "length_hint": (
        " Videoning davomiyligi: <b>{d}</b>.",
        " Длительность видео: <b>{d}</b>.",
        " Video length: <b>{d}</b>.",
    ),
    "voice_longer": (
        "❌ Ovozingiz ({a}) videodan ({b}) uzun.\nBiroz tezroq o'qib, qayta yuboring.",
        "❌ Ваш голос ({a}) длиннее видео ({b}).\nПрочитайте чуть быстрее и отправьте снова.",
        "❌ Your voice message ({a}) is longer than the video ({b}).\nRead a bit faster and send it again.",
    ),
    "voice_ok": (
        "✅ Ovozingiz qabul qilindi.\n⏳ Videongiz tayyorlanmoqda, 1 daqiqagacha vaqt ketishi mumkin...",
        "✅ Голос получен.\n⏳ Готовлю видео, это может занять до минуты...",
        "✅ Voice message received.\n⏳ Preparing your video, it may take up to a minute...",
    ),
    "video_fail": (
        "⚠️ Video yaratishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.",
        "⚠️ Не удалось создать видео. Попробуйте ещё раз чуть позже.",
        "⚠️ Couldn't create the video. Please try again in a moment.",
    ),
}


def t(lang: str, key: str, **kw) -> str:
    row = TEXTS[key]
    text = row[LANGS.index(lang)] if lang in LANGS else row[0]
    return text.format(**kw) if kw else text


def all_variants(key: str) -> set[str]:
    """Bir matnning uchala tildagi ko'rinishi (menyu tugmalarini tanish uchun)."""
    return set(TEXTS[key])


# ---------------- foydalanuvchi tili (users.lang) ----------------
_cache: dict[int, str] = {}


async def get_lang(user_id: int) -> str | None:
    """Tanlangan til yoki None (hali tanlamagan)."""
    if user_id in _cache:
        return _cache[user_id]
    try:
        async with aiosqlite.connect(db.path) as conn:
            cur = await conn.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,))
            row = await cur.fetchone()
    except Exception:
        return None
    lang = row[0] if row and row[0] in LANGS else None
    if lang:
        _cache[user_id] = lang
    return lang


async def ulang(user_id: int) -> str:
    """Til (tanlanmagan bo'lsa — standart)."""
    return await get_lang(user_id) or DEFAULT_LANG


async def set_lang(user_id: int, lang: str):
    if lang not in LANGS:
        return
    async with aiosqlite.connect(db.path) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO users (user_id, full_name, username) VALUES (?, '', NULL)",
            (user_id,),
        )
        await conn.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))
        await conn.commit()
    _cache[user_id] = lang
