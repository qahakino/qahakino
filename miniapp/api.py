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
import time
from pathlib import Path
from urllib.parse import parse_qsl

import aiosqlite
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import BufferedInputFile
from aiohttp import web

from config import ADMIN_IDS, BOT_TOKEN, REQUIRED_CHANNELS, STORAGE_CHANNEL_ID
from database import db
from utils.search import matches
from utils.subscription import get_unsubscribed_channels

GENRES = ["Jangari", "Komediya", "Drama", "Fantastika", "Triller",
          "Sarguzasht", "Qo'rqinchli", "Romantika", "Multfilm", "Boshqa"]
WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://qahakino-production.up.railway.app/app/")

# Kino va seriallar bitta ro'yxat sifatida (kod ikkalasi uchun ham yagona)
ITEMS = """
SELECT code, name, 'movie' AS kind, release_year AS year, genres, views,
       added_at AS created, description, duration_min AS duration, poster_file_id
FROM movies WHERE is_active = 1
UNION ALL
SELECT code, name, 'series', release_year, genres, views,
       created_at, description, NULL, poster_file_id
FROM series WHERE is_active = 1
"""
CARD = "SELECT code, name, kind, year, genres, views, poster_file_id FROM (" + ITEMS + ")"


# ---------------- migratsiya (faqat qo'shadi, hech narsani o'chirmaydi) ----------------
async def migrate():
    add = {
        "movies": [("description", "TEXT"), ("release_year", "INTEGER"), ("genres", "TEXT"),
                   ("duration_min", "INTEGER"), ("views", "INTEGER DEFAULT 0"),
                   ("is_active", "INTEGER DEFAULT 1"), ("poster_file_id", "TEXT")],
        "series": [("description", "TEXT"), ("release_year", "INTEGER"), ("genres", "TEXT"),
                   ("views", "INTEGER DEFAULT 0"), ("is_active", "INTEGER DEFAULT 1"), ("poster_file_id", "TEXT")],
    }
    async with aiosqlite.connect(db.path) as c:
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
    async with aiosqlite.connect(db.path) as c:
        c.row_factory = aiosqlite.Row
        await c.execute("PRAGMA busy_timeout=5000")
        cur = await c.execute(sql, args)
        return [dict(r) for r in await cur.fetchall()]


async def execute(sql, args=()):
    async with aiosqlite.connect(db.path) as c:
        await c.execute("PRAGMA busy_timeout=5000")
        await c.execute(sql, args)
        await c.commit()


def card(r):
    return {"code": r["code"], "name": r["name"] or "", "kind": r["kind"], "year": r["year"],
            "genres": [g for g in (r["genres"] or "").split(",") if g], "views": r["views"] or 0,
            "poster": hashlib.md5(r["poster_file_id"].encode()).hexdigest()[:8] if r.get("poster_file_id") else None}


async def set_poster(code: str, file_id: str):
    """Poster Telegram file_id sifatida saqlanadi (kino yoki serial kodi bo'yicha)."""
    await execute("UPDATE movies SET poster_file_id=? WHERE code=?", (file_id, code))
    await execute("UPDATE series SET poster_file_id=? WHERE code=?", (file_id, code))


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
    return await handler(request)


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
    return ok({"bot": (await request.app["bot"].me()).username, "genres": GENRES,
               "is_admin": uid in ADMIN_IDS, "stats": {"favs": favs, "movies": movies, "series": series},
               "recent": [card(r) for r in recent]})


async def home(request):
    latest = await fetch(CARD + " WHERE kind='movie' ORDER BY created DESC LIMIT 10")
    popular = await fetch(CARD + " ORDER BY views DESC, created DESC LIMIT 10")
    series = await fetch(CARD + " WHERE kind='series' ORDER BY created DESC LIMIT 10")
    return ok({"latest": [card(r) for r in latest], "popular": [card(r) for r in popular],
               "series": [card(r) for r in series]})


async def catalog(request):
    q = request.query
    where, args = [], []
    if q.get("type") in ("movie", "series"):
        where.append("kind=?"); args.append(q["type"])
    if q.get("genre"):
        where.append("(',' || IFNULL(genres,'') || ',') LIKE ?"); args.append(f"%,{q['genre']},%")
    if q.get("year", "").isdigit():
        where.append("year=?"); args.append(int(q["year"]))
    order = {"popular": "views DESC, created DESC", "name": "name COLLATE NOCASE"}.get(
        q.get("sort"), "created DESC")
    sql = CARD + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + order
    rows = await fetch(sql, args)

    text = (q.get("q") or "").strip()
    if text:  # botdagi bilan bir xil qidiruv (o', g' apostroflari, so'z tartibi) + kod bo'yicha
        rows = [r for r in rows if r["code"] == text or matches(text, r["name"] or "")]

    limit = min(int(q.get("limit", 20) or 20), 50)
    offset = max(int(q.get("offset", 0) or 0), 0)
    page = rows[offset: offset + limit]
    return ok({"items": [card(r) for r in page], "has_more": offset + limit < len(rows)})


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
    dur = int(b["duration"]) if str(b.get("duration") or "").isdigit() else None
    desc = (b.get("description") or "").strip()[:1000] or None
    await execute("UPDATE movies SET description=?, release_year=?, genres=?, duration_min=? WHERE code=?",
                  (desc, year, genres, dur, code))
    await execute("UPDATE series SET description=?, release_year=?, genres=? WHERE code=?",
                  (desc, year, genres, code))
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
        web.get("/me", me), web.get("/home", home), web.get("/catalog", catalog),
        web.get("/random", random_item), web.get("/item/{code}", item),
        web.get("/favorites", favorites), web.post("/fav", toggle_fav),
        web.post("/watch", watch), web.put("/admin/item/{code}", admin_edit), web.put("/admin/poster/{code}", admin_poster),
    ])
    app.add_subapp("/api", api)
    app.router.add_get("/poster/{code}", poster)

    nocache = {"Cache-Control": "no-cache"}
    app.router.add_get("/app", lambda r: web.HTTPFound("/app/"))
    app.router.add_get("/app/", lambda r: web.FileResponse(WEBAPP_DIR / "index.html", headers=nocache))
    app.router.add_static("/app/", WEBAPP_DIR)
