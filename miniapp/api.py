"""Qaxakino Mini App API.

Bot bilan bir jarayonda va bir xil SQLite bazada ishlaydi. Mavjud jadvallar
o'zgarmaydi: faqat yangi ustunlar va yangi jadvallar qo'shiladi.
"""
import hashlib
import hmac
import json
import logging
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import BufferedInputFile
from aiohttp import web

from config import ADMIN_IDS, BOT_TOKEN, REQUIRED_CHANNELS, STORAGE_CHANNEL_ID
from database import db
from i18n import LANGS, get_lang, set_lang
from utils.search import item_matches, split_aliases
from utils.subscription import get_unsubscribed_channels

GENRES = ["Jangari", "Komediya", "Drama", "Fantastika", "Triller",
          "Sarguzasht", "Qo'rqinchli", "Romantika", "Multfilm", "Boshqa"]
WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://qahakino-production.up.railway.app/app/")

# Kino va seriallar bitta ro'yxat sifatida (kod ikkalasi uchun ham yagona)
ITEMS = """
SELECT code, name, 'movie' AS kind, release_year AS year, genres, views,
       added_at AS created, description, duration_min AS duration, poster_file_id, aliases
FROM movies WHERE is_active = 1
UNION ALL
SELECT code, name, 'series', release_year, genres, views,
       created_at, description, NULL, poster_file_id, aliases
FROM series WHERE is_active = 1
"""
# Ma'lumoti yetishmaydigan: izoh, janr yoki poster yo'q
MISSING = ("(IFNULL(description, '') = '' OR IFNULL(genres, '') = '' "
           "OR IFNULL(poster_file_id, '') = '')")
CARD = "SELECT code, name, kind, year, genres, views, poster_file_id, description, aliases FROM (" + ITEMS + ")"


# ---------------- migratsiya (faqat qo'shadi, hech narsani o'chirmaydi) ----------------
async def migrate():
    add = {
        "users": [("lang", "TEXT")],
        "movies": [("description", "TEXT"), ("release_year", "INTEGER"), ("genres", "TEXT"),
                   ("duration_min", "INTEGER"), ("views", "INTEGER DEFAULT 0"),
                   ("is_active", "INTEGER DEFAULT 1"), ("poster_file_id", "TEXT"), ("aliases", "TEXT")],
        "series": [("description", "TEXT"), ("release_year", "INTEGER"), ("genres", "TEXT"),
                   ("views", "INTEGER DEFAULT 0"), ("is_active", "INTEGER DEFAULT 1"), ("poster_file_id", "TEXT"), ("aliases", "TEXT")],
    }
    async with db.conn() as c:
        for table, cols in add.items():
            cur = await c.execute(f"PRAGMA table_info({table})")
            have = {r[1] for r in await cur.fetchall()}
            for name, typ in cols:
                if name not in have:
                    await c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        await c.execute("""CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL, code TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, code))""")
        await c.execute("""CREATE TABLE IF NOT EXISTS watch_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            code TEXT NOT NULL, episode_number INTEGER,
            watched_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_hist_user ON watch_history(user_id, watched_at)")
        await c.execute("CREATE INDEX IF NOT EXISTS idx_movies_added ON movies(added_at)")
        await c.commit()


async def fetch(sql, args=()):
    # Botning umumiy ulanishidan foydalanamiz (row_factory'ga tegmaymiz)
    async with db.conn() as c:
        cur = await c.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in await cur.fetchall()]


async def execute(sql, args=()):
    async with db.conn() as c:
        await c.execute(sql, args)
        await c.commit()


def card(r, admin: bool = False):
    d = {"code": r["code"], "name": r["name"] or "", "kind": r["kind"], "year": r["year"],
            "genres": [g for g in (r["genres"] or "").split(",") if g], "views": r["views"] or 0,
            "poster": hashlib.md5(r["poster_file_id"].encode()).hexdigest()[:8] if r.get("poster_file_id") else None}
    if admin:   # adminga: izoh, janr yoki poster yetishmasa belgi chiqadi
        d["miss"] = not (r.get("description") and r.get("genres") and r.get("poster_file_id"))
    return d


async def set_poster(code: str, file_id: str):
    """Poster Telegram file_id sifatida saqlanadi (kino yoki serial kodi bo'yicha)."""
    await execute("UPDATE movies SET poster_file_id=? WHERE code=?", (file_id, code))
    await execute("UPDATE series SET poster_file_id=? WHERE code=?", (file_id, code))


_ALIASES = {
    "боевик": "Jangari", "action": "Jangari", "комедия": "Komediya", "comedy": "Komediya",
    "драма": "Drama", "фантастика": "Fantastika", "sci-fi": "Fantastika", "scifi": "Fantastika",
    "триллер": "Triller", "thriller": "Triller", "приключения": "Sarguzasht", "adventure": "Sarguzasht",
    "ужасы": "Qo'rqinchli", "horror": "Qo'rqinchli", "мелодрама": "Romantika", "romance": "Romantika",
    "мультфильм": "Multfilm", "animation": "Multfilm", "другое": "Boshqa", "other": "Boshqa",
}


def _gkey(text: str) -> str:
    return re.sub(r"['‘’`ʻʼ´]", "", text.strip().lower())


_GENRE_MAP = {_gkey(g): g for g in GENRES} | {_gkey(k): v for k, v in _ALIASES.items()}


def parse_duration(text) -> int | None:
    """Davomiylikni daqiqaga aylantiradi. Qabul qilinadigan yozuvlar:

      105  ·  1:45  ·  1.45  ·  1,45  ·  1-45  ·  1 45   → 105 daqiqa (soat:daqiqa)
      1.5  ·  2,5                                          → 1,5 soat = 90 daqiqa
      2                                                    → 2 soat (10 dan kichik yagona son — soat)
      1 soat 45 daqiqa  ·  1s 45d  ·  1h45m  ·  2 час 5 мин → birliklar bilan
    Tushunarsiz bo'lsa — None.
    """
    s = str(text or "").strip().lower().replace(",", ".")
    if not s:
        return None

    def ok(v):
        return v if 1 <= v <= 999 else None

    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:soat|hours?|hrs?|час[а-я]*|ч|h|s)(?![a-zа-я])", s)
    mins = re.search(r"(\d+)\s*(?:daqiqa|daq|min[a-z]*|мин[а-я]*|m|d)(?![a-zа-я])", s)
    if hours or mins:
        total = round(float(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
        return ok(total)

    m = re.fullmatch(r"(\d{1,2})\s*([:.\-/ ])\s*(\d{1,2})", s)
    if m:
        h, sep, ms = int(m.group(1)), m.group(2), m.group(3)
        if sep == "." and len(ms) == 1:          # 1.5 — o'nli kasr: 1,5 soat
            return ok(round((h + int(ms) / 10) * 60))
        return ok(h * 60 + int(ms)) if int(ms) < 60 else None

    if re.fullmatch(r"\d{1,3}", s):
        n = int(s)
        return ok(n * 60 if n <= 9 else n)
    return None


def parse_info(text: str) -> dict:
    """Admin yozgan matnni tahlil qiladi.

    Birinchi qatorda «|» bo'lib, unda yil / daqiqa / tanish janr uchrasa — bu meta-qator
    (yil | janrlar | daqiqa, tartibsiz ham bo'ladi):
        2024 | Komediya, Drama | 120
    Qolgan qatorlar — izoh. Aks holda butun matn izoh hisoblanadi.
    """
    text = (text or "").strip()
    lines = text.splitlines()
    info = {"description": None, "year": None, "genres": None, "duration": None, "unknown": []}

    meta = {"year": None, "duration": None, "genres": None, "unknown": []}
    recognized = 0
    if lines and "|" in lines[0]:
        for part in (p.strip() for p in lines[0].split("|")):
            if not part:
                continue
            if re.fullmatch(r"(19|20)\d\d", part):
                meta["year"] = int(part); recognized += 1
            elif re.search(r"\d", part):      # raqam bor — davomiylik (105, 1:45, 1.5 soat ...)
                minutes = parse_duration(part)
                if minutes:
                    meta["duration"] = minutes; recognized += 1
                else:
                    meta["unknown"].append(part)
            else:
                names = []
                for g in re.split(r"[,;]", part):
                    if not g.strip():
                        continue
                    name = _GENRE_MAP.get(_gkey(g))
                    if name:
                        recognized += 1
                        if name not in names:
                            names.append(name)
                    else:
                        meta["unknown"].append(g.strip())
                if names:
                    meta["genres"] = names

    if recognized:
        info.update(meta)
        body = "\n".join(lines[1:]).strip()
    else:
        body = text
    if body:
        info["description"] = body[:1000]
    return info


def clean_aliases(text) -> list[str]:
    """Qo'shimcha nomlar: takrorlarsiz, ko'pi bilan 10 ta, har biri 80 belgigacha."""
    seen, out = set(), []
    for a in split_aliases(text if isinstance(text, str) else "\n".join(text or [])):
        key = a.casefold()
        if key not in seen:
            seen.add(key)
            out.append(a[:80])
    return out[:10]


async def set_info(code: str, *, description=None, year=None, genres=None, duration=None, aliases=None):
    """Faqat berilgan maydonlarni yangilaydi, qolganlariga tegmaydi."""
    fields = {}
    if description is not None:
        fields["description"] = description[:1000] or None
    if year is not None:
        fields["release_year"] = year
    if genres is not None:
        fields["genres"] = ",".join(genres)
    if aliases is not None:
        fields["aliases"] = "\n".join(clean_aliases(aliases)) or None
    for table in ("movies", "series"):
        f = dict(fields)
        if table == "movies" and duration is not None:
            f["duration_min"] = duration
        if f:
            sets = ", ".join(f"{k}=?" for k in f)  # ustun nomlari yuqorida qat'iy belgilangan
            await execute(f"UPDATE {table} SET {sets} WHERE code=?", (*f.values(), code))
    db.invalidate()   # qidiruv keshi yangilansin


async def get_info(code: str):
    rows = await fetch(
        f"SELECT code, name, kind, year, genres, description, duration, aliases FROM ({ITEMS}) WHERE code=?", (code,))
    return rows[0] if rows else None


async def next_missing_info(exclude=()):
    """Izohi yoki janri yo'q keyingi kino/serial kodi (bot /info navbati uchun)."""
    marks = ",".join("?" * len(exclude))
    sql = (f"SELECT code FROM ({ITEMS}) WHERE (IFNULL(description,'')='' OR IFNULL(genres,'')='')"
           + (f" AND code NOT IN ({marks})" if exclude else "") + " ORDER BY created DESC LIMIT 1")
    rows = await fetch(sql, tuple(exclude))
    return rows[0]["code"] if rows else None


def ok(data, status=200):
    return web.json_response(data, status=status)


def err(code, status):
    return web.json_response({"error": code}, status=status)


# ---------------- Telegram initData tekshiruvi (rasmiy usul) ----------------
def verify_init_data(init_data: str, max_age: int = 86400):
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received or not BOT_TOKEN:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return json.loads(pairs["user"])
    except (ValueError, KeyError):
        return None


@web.middleware
async def auth_mw(request, handler):
    user = verify_init_data(request.headers.get("Authorization", "").removeprefix("tma "))
    if not user:
        return err("unauthorized", 401)
    request["user"] = user
    response = await handler(request)
    if isinstance(response, web.Response):
        response.enable_compression()      # JSON javoblar gzip bilan yuboriladi
    return response


# ---------------- endpointlar ----------------
async def me(request):
    u = request["user"]
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x)
    await db.add_user(u["id"], name, u.get("username"))
    uid = u["id"]
    favs = (await fetch("SELECT COUNT(*) n FROM favorites WHERE user_id=?", (uid,)))[0]["n"]
    movies = (await fetch("""SELECT COUNT(DISTINCT code) n FROM watch_history
        WHERE user_id=? AND code IN (SELECT code FROM movies)""", (uid,)))[0]["n"]
    series = (await fetch("""SELECT COUNT(DISTINCT code) n FROM watch_history
        WHERE user_id=? AND code IN (SELECT code FROM series)""", (uid,)))[0]["n"]
    recent = await fetch(
        f"""SELECT i.code, i.name, i.kind, i.year, i.genres, i.views, i.poster_file_id FROM
        (SELECT code, MAX(watched_at) w FROM watch_history WHERE user_id=? GROUP BY code
         ORDER BY w DESC LIMIT 10) h JOIN ({ITEMS}) i ON i.code = h.code""", (uid,))
    is_admin = uid in ADMIN_IDS
    missing = (await fetch(f"SELECT COUNT(*) n FROM ({ITEMS}) WHERE {MISSING}"))[0]["n"] if is_admin else 0
    return ok({"bot": (await request.app["bot"].me()).username, "genres": GENRES, "lang": await get_lang(uid),
               "is_admin": is_admin, "missing": missing, "stats": {"favs": favs, "movies": movies, "series": series},
               "recent": [card(r) for r in recent]})


async def set_language(request):
    lang = (await request.json()).get("lang")
    if lang not in LANGS:
        return err("bad_lang", 400)
    await set_lang(request["user"]["id"], lang)
    return ok({"lang": lang})


async def home(request):
    latest = await fetch(CARD + " WHERE kind='movie' ORDER BY created DESC LIMIT 10")
    popular = await fetch(CARD + " ORDER BY views DESC, created DESC LIMIT 10")
    series = await fetch(CARD + " WHERE kind='series' ORDER BY created DESC LIMIT 10")
    return ok({"latest": [card(r) for r in latest], "popular": [card(r) for r in popular],
               "series": [card(r) for r in series]})


async def catalog(request):
    q = request.query
    uid = request["user"]["id"]
    where, args = [], []
    if q.get("type") in ("movie", "series"):
        where.append("kind=?"); args.append(q["type"])
    if q.get("genre"):
        where.append("(',' || IFNULL(genres,'') || ',') LIKE ?"); args.append(f"%,{q['genre']},%")
    if q.get("year", "").isdigit():
        where.append("year=?"); args.append(int(q["year"]))
    if q.get("missing") == "1" and uid in ADMIN_IDS:   # faqat adminlar uchun
        where.append(MISSING)
    order = {"popular": "views DESC, created DESC", "name": "name COLLATE NOCASE"}.get(
        q.get("sort"), "created DESC")
    sql = CARD + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + order

    limit = max(1, min(int(q.get("limit", 20) or 20), 50))
    offset = max(int(q.get("offset", 0) or 0), 0)
    text = (q.get("q") or "").strip()

    if text:  # botdagi bilan bir xil qidiruv (o', g' apostroflari, so'z tartibi) + kod bo'yicha
        rows = [r for r in await fetch(sql, args) if r["code"] == text or item_matches(text, r["name"] or "", r.get("aliases"))]
        page, has_more = rows[offset: offset + limit], offset + limit < len(rows)
    else:     # oddiy ro'yxat: faqat kerakli qismi bazadan olinadi
        rows = await fetch(sql + " LIMIT ? OFFSET ?", args + [limit + 1, offset])
        page, has_more = rows[:limit], len(rows) > limit

    out = {"items": [card(r, uid in ADMIN_IDS) for r in page], "has_more": has_more}
    if offset == 0:  # filtr uchun mavjud yillar
        out["years"] = [r["y"] for r in await fetch(
            f"SELECT DISTINCT year y FROM ({ITEMS}) WHERE year IS NOT NULL ORDER BY year DESC")]
    return ok(out)


async def random_item(request):
    rows = await fetch(CARD)
    return ok({"code": random.choice(rows)["code"]} if rows else {"code": None})


async def item(request):
    code, uid = request.match_info["code"], request["user"]["id"]
    rows = await fetch(f"SELECT * FROM ({ITEMS}) WHERE code=?", (code,))
    if not rows:
        return err("not_found", 404)
    r = rows[0]
    out = card(r) | {"description": r["description"] or "", "duration": r["duration"]}
    out["fav"] = bool(await fetch("SELECT 1 FROM favorites WHERE user_id=? AND code=?", (uid, code)))
    out["episodes"], out["last_episode"] = [], None
    if r["kind"] == "series":
        eps = await fetch("""SELECT episode_number n FROM episodes
            WHERE series_id=(SELECT id FROM series WHERE code=?) ORDER BY episode_number""", (code,))
        out["episodes"] = [e["n"] for e in eps]
        last = await fetch("""SELECT episode_number n FROM watch_history WHERE user_id=? AND code=?
            AND episode_number IS NOT NULL ORDER BY id DESC LIMIT 1""", (uid, code))
        out["last_episode"] = last[0]["n"] if last else None
    if uid in ADMIN_IDS:
        out["description"] = r["description"] or ""
        out["aliases"] = ", ".join(split_aliases(r.get("aliases")))
        nxt = await fetch(f"SELECT code FROM ({ITEMS}) WHERE {MISSING} AND code != ? ORDER BY created DESC LIMIT 1", (code,))
        out["next_missing"] = nxt[0]["code"] if nxt else None
    return ok(out)


async def favorites(request):
    rows = await fetch(
        f"""SELECT i.code, i.name, i.kind, i.year, i.genres, i.views, i.poster_file_id FROM favorites f
        JOIN ({ITEMS}) i ON i.code = f.code WHERE f.user_id=? ORDER BY f.created_at DESC""",
        (request["user"]["id"],))
    return ok({"items": [card(r) for r in rows]})


async def toggle_fav(request):
    uid = request["user"]["id"]
    code = str((await request.json()).get("code", ""))
    if not await fetch(f"SELECT 1 FROM ({ITEMS}) WHERE code=?", (code,)):
        return err("not_found", 404)
    if await fetch("SELECT 1 FROM favorites WHERE user_id=? AND code=?", (uid, code)):
        await execute("DELETE FROM favorites WHERE user_id=? AND code=?", (uid, code))
        return ok({"fav": False})
    await execute("INSERT INTO favorites (user_id, code) VALUES (?, ?)", (uid, code))
    return ok({"fav": True})


_last_watch: dict[int, float] = {}


async def watch(request):
    """Videoni bot orqali foydalanuvchi chatiga copy_message bilan yuboradi.
    channel_id / message_id hech qachon frontendga berilmaydi."""
    bot, uid = request.app["bot"], request["user"]["id"]
    body = await request.json()
    code, ep = str(body.get("code", "")), body.get("episode")

    now = time.monotonic()
    if now - _last_watch.get(uid, 0) < 3:
        return err("too_fast", 429)
    _last_watch[uid] = now

    if REQUIRED_CHANNELS:  # botdagi majburiy obuna qoidasi Mini App'da ham ishlaydi
        unsub = await get_unsubscribed_channels(bot, uid, REQUIRED_CHANNELS)
        if unsub:
            return web.json_response({"error": "subscribe", "channels": [c["link"] for c in unsub]}, status=403)

    movie = await db.get_movie(code)
    if movie:
        src, table = (movie[2], movie[3]), "movies"
    else:
        series = await db.get_series_by_code(code)
        if not series:
            return err("not_found", 404)
        try:
            episode = await db.get_episode_by_number(series[0], int(ep))
        except (TypeError, ValueError):
            episode = None
        if not episode:
            return err("not_found", 404)
        src, table = (episode[3], episode[4]), "series"

    try:
        await bot.copy_message(chat_id=uid, from_chat_id=src[0], message_id=src[1])
    except TelegramForbiddenError:
        return err("start_bot", 403)
    except Exception:
        logging.exception("Mini App: video yuborishda xatolik")
        return err("send_failed", 502)

    await execute("INSERT INTO watch_history (user_id, code, episode_number) VALUES (?, ?, ?)",
                  (uid, code, int(ep) if table == "series" else None))
    await execute(f"UPDATE {table} SET views = IFNULL(views, 0) + 1 WHERE code=?", (code,))
    return ok({"sent": True})


async def admin_edit(request):
    if request["user"]["id"] not in ADMIN_IDS:
        return err("forbidden", 403)
    code, b = request.match_info["code"], await request.json()
    genres = ",".join(g for g in b.get("genres", []) if g in GENRES)
    year = int(b["year"]) if str(b.get("year") or "").isdigit() else None
    raw_dur = str(b.get("duration") or "").strip()
    dur = parse_duration(raw_dur) if raw_dur else None
    if raw_dur and dur is None:
        return err("bad_duration", 400)
    desc = (b.get("description") or "").strip()[:1000] or None
    await execute("UPDATE movies SET description=?, release_year=?, genres=?, duration_min=? WHERE code=?",
                  (desc, year, genres, dur, code))
    await execute("UPDATE series SET description=?, release_year=?, genres=? WHERE code=?",
                  (desc, year, genres, code))
    if "aliases" in b:   # eski brauzer nusxasi yubormasa, mavjud nomlar o'chib ketmasin
        names = "\n".join(clean_aliases(b.get("aliases"))) or None
        await execute("UPDATE movies SET aliases=? WHERE code=?", (names, code))
        await execute("UPDATE series SET aliases=? WHERE code=?", (names, code))
    db.invalidate()
    return ok({"saved": True})


_poster_cache: dict[str, tuple[str, bytes]] = {}


async def poster(request):
    """Poster rasmini Telegramdan olib beradi (bot tokeni foydalanuvchiga ko'rinmaydi)."""
    code = request.match_info["code"]
    rows = await fetch(f"SELECT poster_file_id f FROM ({ITEMS}) WHERE code=?", (code,))
    fid = rows[0]["f"] if rows else None
    if not fid:
        raise web.HTTPNotFound()
    hit = _poster_cache.get(code)
    if not hit or hit[0] != fid:
        try:
            bot = request.app["bot"]
            buf = await bot.download_file((await bot.get_file(fid)).file_path)
        except Exception:
            logging.exception("Poster yuklab bo'lmadi: %s", code)
            raise web.HTTPNotFound()
        if len(_poster_cache) > 300:
            _poster_cache.pop(next(iter(_poster_cache)))
        hit = _poster_cache[code] = (fid, buf.read())
    return web.Response(body=hit[1], content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=604800"})


async def admin_poster(request):
    """Mini App'dan yuklangan posterni storage kanalga joylab, file_id ni saqlaydi."""
    if request["user"]["id"] not in ADMIN_IDS:
        return err("forbidden", 403)
    code, data = request.match_info["code"], await request.read()
    if not data or len(data) > 5 * 1024 * 1024 or not STORAGE_CHANNEL_ID:
        return err("bad_image", 400)
    if not await fetch(f"SELECT 1 FROM ({ITEMS}) WHERE code=?", (code,)):
        return err("not_found", 404)
    try:
        msg = await request.app["bot"].send_photo(
            chat_id=STORAGE_CHANNEL_ID, photo=BufferedInputFile(data, "poster.jpg"),
            caption=f"🖼 Poster: {code}")
    except Exception:
        logging.exception("Poster yuborilmadi")
        return err("send_failed", 502)
    await set_poster(code, msg.photo[-1].file_id)
    return ok({"saved": True})


def setup_miniapp(app: web.Application, bot):
    api = web.Application(middlewares=[auth_mw], client_max_size=6 * 1024 * 1024)
    api["bot"] = bot
    api.add_routes([
        web.get("/me", me), web.post("/lang", set_language), web.get("/home", home), web.get("/catalog", catalog),
        web.get("/random", random_item), web.get("/item/{code}", item),
        web.get("/favorites", favorites), web.post("/fav", toggle_fav),
        web.post("/watch", watch), web.put("/admin/item/{code}", admin_edit), web.put("/admin/poster/{code}", admin_poster),
    ])
    app.add_subapp("/api", api)
    app.router.add_get("/poster/{code}", poster)

    def index_html() -> web.Response:
        """index.html dagi ?v=... ni fayl mazmunining qisqa xeshiga almashtiradi:
        fayl o'zgarsa versiya ham o'zgaradi, o'zgarmasa brauzer keshdan oladi."""
        html_text = (WEBAPP_DIR / "index.html").read_text(encoding="utf-8")

        def stamp(match):
            name = match.group(1)
            digest = hashlib.md5((WEBAPP_DIR / name).read_bytes()).hexdigest()[:8]
            return f"{name}?v={digest}"

        html_text = re.sub(r"(style\.css|app\.js)\?v=\w+", stamp, html_text)
        resp = web.Response(text=html_text, content_type="text/html", headers={"Cache-Control": "no-cache"})
        resp.enable_compression()
        return resp

    root = WEBAPP_DIR.resolve()
    types = {".js": "application/javascript", ".css": "text/css", ".html": "text/html"}

    async def static_file(request):
        path = (WEBAPP_DIR / request.match_info["name"]).resolve()
        if root not in path.parents or not path.is_file():
            raise web.HTTPNotFound()
        ctype = types.get(path.suffix)
        if ctype:  # matn fayllari: siqiladi; ?v=<xesh> bilan kelsa — bir yil keshlanadi
            resp = web.Response(body=path.read_bytes(), content_type=ctype, charset="utf-8")
            resp.enable_compression()
        else:
            resp = web.FileResponse(path)
        versioned = "v" in request.query and ctype in ("application/javascript", "text/css")
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if versioned else "no-cache"
        return resp

    app.router.add_get("/app", lambda r: web.HTTPFound("/app/"))
    app.router.add_get("/app/", lambda r: index_html())
    app.router.add_get("/app/{name:.+}", static_file)
