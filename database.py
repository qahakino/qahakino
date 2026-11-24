import asyncio
import contextlib

import aiosqlite

from config import DB_PATH


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._conn_lock = asyncio.Lock()
        # Qidiruv uchun ro'yxatlar xotirada saqlanadi (qo'shish/o'chirishda tozalanadi)
        self._cache: dict[str, list] = {}

    # ---------- ulanish ----------
    # Har so'rovda yangi ulanish ochish o'rniga bitta doimiy ulanish ishlatiladi:
    # bu har bir bazaga murojaatni sezilarli tezlashtiradi.

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            async with self._conn_lock:
                if self._conn is None:
                    conn = await aiosqlite.connect(self.path)
                    await conn.execute("PRAGMA journal_mode=WAL")    # o'qish yozishga xalaqit bermaydi
                    await conn.execute("PRAGMA synchronous=NORMAL")  # WAL bilan xavfsiz va tez
                    await conn.execute("PRAGMA busy_timeout=5000")
                    await conn.execute("PRAGMA temp_store=MEMORY")
                    await conn.execute("PRAGMA cache_size=-20000")   # ~20 MB kesh
                    self._conn = conn
        return self._conn

    @contextlib.asynccontextmanager
    async def conn(self):
        yield await self._get_conn()

    async def close(self):
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def init(self):
        async with self.conn() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    joined_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS movies (
                    code TEXT PRIMARY KEY,
                    name TEXT,
                    chat_id INTEGER,
                    message_id INTEGER,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    poster_chat_id INTEGER NOT NULL,
                    poster_message_id INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id INTEGER NOT NULL,
                    episode_number INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(series_id, episode_number),
                    FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    script TEXT NOT NULL,
                    video_file_id TEXT NOT NULL,
                    duration INTEGER,
                    storage_chat_id INTEGER,
                    storage_message_id INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Eski bazalar uchun: yangi ustunlarni qo'shamiz (bor bo'lsa tegmaydi)
            cur = await conn.execute("PRAGMA table_info(clips)")
            clip_columns = {row[1] for row in await cur.fetchall()}
            if "bg_file_id" not in clip_columns:
                await conn.execute("ALTER TABLE clips ADD COLUMN bg_file_id TEXT")
            if "parts" not in clip_columns:
                await conn.execute("ALTER TABLE clips ADD COLUMN parts TEXT")

            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodes_series "
                "ON episodes(series_id, episode_number)"
            )

            await conn.commit()

    async def delete_series(self, code: str):
        self._cache.clear()
        async with self.conn() as conn:
            # Avval serialni topamiz
            cur = await conn.execute(
                """
                SELECT id, name, poster_chat_id, poster_message_id
                FROM series
                WHERE code = ?
                """,
                (code,),
            )
            series = await cur.fetchone()

            if not series:
                return None

            series_id, name, poster_chat_id, poster_message_id = series

            # Serialning barcha qismlarini olamiz
            cur = await conn.execute(
                """
                SELECT chat_id, message_id
                FROM episodes
                WHERE series_id = ?
                ORDER BY episode_number
                """,
                (series_id,),
            )
            episodes = await cur.fetchall()

            # Episodes o'chadi
            await conn.execute(
                "DELETE FROM episodes WHERE series_id = ?",
                (series_id,),
            )

            # Serial o'chadi
            await conn.execute(
                "DELETE FROM series WHERE id = ?",
                (series_id,),
            )

            await conn.commit()

            return {
                "id": series_id,
                "code": code,
                "name": name,
                "poster_chat_id": poster_chat_id,
                "poster_message_id": poster_message_id,
                "episodes": episodes,
            }
    # ---------- foydalanuvchilar ----------

    async def add_user(self, user_id: int, full_name: str, username: str | None):
        async with self.conn() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO users (user_id, full_name, username) VALUES (?, ?, ?)",
                (user_id, full_name, username),
            )
            await conn.commit()

    async def users_count(self) -> int:
        async with self.conn() as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM users")
            row = await cur.fetchone()
            return row[0] if row else 0

    async def all_user_ids(self) -> list[int]:
        async with self.conn() as conn:
            cur = await conn.execute("SELECT user_id FROM users")
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    # ---------- kinolar ----------

    async def add_movie(self, code: str, name: str, chat_id: int, message_id: int):
        self._cache.clear()
        async with self.conn() as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO movies (code, name, chat_id, message_id)
                VALUES (?, ?, ?, ?)
                """,
                (code, name, chat_id, message_id),
            )
            await conn.commit()

    async def get_movie(self, code: str):
        async with self.conn() as conn:
            cur = await conn.execute(
                "SELECT code, name, chat_id, message_id FROM movies WHERE code = ?",
                (code,),
            )
            return await cur.fetchone()

    async def movies_count(self) -> int:
        async with self.conn() as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM movies")
            row = await cur.fetchone()
            return row[0] if row else 0

    async def delete_movie(self, code: str) -> bool:
        self._cache.clear()
        async with self.conn() as conn:
            cur = await conn.execute("DELETE FROM movies WHERE code = ?", (code,))
            await conn.commit()
            return cur.rowcount > 0

    # ---------- umumiy kod ----------

    async def code_exists(self, code: str) -> bool:
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                SELECT 1 FROM movies WHERE code = ?
                UNION ALL
                SELECT 1 FROM series WHERE code = ?
                LIMIT 1
                """,
                (code, code),
            )
            return await cur.fetchone() is not None

    # ---------- seriallar ----------

    async def add_series(
        self,
        code: str,
        name: str,
        poster_chat_id: int,
        poster_message_id: int,
    ) -> int:
        self._cache.clear()
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                INSERT INTO series (code, name, poster_chat_id, poster_message_id)
                VALUES (?, ?, ?, ?)
                """,
                (code, name, poster_chat_id, poster_message_id),
            )
            await conn.commit()
            return cur.lastrowid

    async def get_series_by_code(self, code: str):
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                SELECT id, code, name, poster_chat_id, poster_message_id
                FROM series
                WHERE code = ?
                """,
                (code,),
            )
            return await cur.fetchone()

    async def get_series(self, series_id: int):
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                SELECT id, code, name, poster_chat_id, poster_message_id
                FROM series
                WHERE id = ?
                """,
                (series_id,),
            )
            return await cur.fetchone()

    async def all_series(self):
        if "series" not in self._cache:
            async with self.conn() as conn:
                cur = await conn.execute(
                    "SELECT id, code, name FROM series ORDER BY name COLLATE NOCASE"
                )
                self._cache["series"] = await cur.fetchall()
        return self._cache["series"]

    async def series_count(self) -> int:
        async with self.conn() as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM series")
            row = await cur.fetchone()
            return row[0] if row else 0

    async def add_episode(
        self,
        series_id: int,
        episode_number: int,
        chat_id: int,
        message_id: int,
    ) -> bool:
        async with self.conn() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO episodes
                        (series_id, episode_number, chat_id, message_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (series_id, episode_number, chat_id, message_id),
                )
                await conn.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def get_episode(self, episode_id: int):
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                SELECT id, series_id, episode_number, chat_id, message_id
                FROM episodes
                WHERE id = ?
                """,
                (episode_id,),
            )
            return await cur.fetchone()

    async def get_episode_by_number(self, series_id: int, episode_number: int):
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                SELECT id, series_id, episode_number, chat_id, message_id
                FROM episodes
                WHERE series_id = ? AND episode_number = ?
                """,
                (series_id, episode_number),
            )
            return await cur.fetchone()

    async def get_episodes(self, series_id: int):
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                SELECT id, episode_number, chat_id, message_id
                FROM episodes
                WHERE series_id = ?
                ORDER BY episode_number
                """,
                (series_id,),
            )
            return await cur.fetchall()

    # ---------- nom bo'yicha qidiruv uchun ----------

    async def all_movies_basic(self):
        """[(code, name), ...] — qidiruv Python tomonda (o', g' harflari uchun) bajariladi."""
        if "movies" not in self._cache:
            async with self.conn() as conn:
                cur = await conn.execute(
                    "SELECT code, name FROM movies ORDER BY name COLLATE NOCASE"
                )
                self._cache["movies"] = await cur.fetchall()
        return self._cache["movies"]

    # ---------- ovozli parchalar ----------

    async def add_clip(
        self,
        title: str,
        script: str,
        video_file_id: str,
        duration: int | None,
        storage_chat_id: int | None,
        storage_message_id: int | None,
        bg_file_id: str | None = None,
        parts_json: str | None = None,
    ) -> int:
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                INSERT INTO clips
                    (title, script, video_file_id, duration,
                     storage_chat_id, storage_message_id, bg_file_id, parts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title, script, video_file_id, duration,
                 storage_chat_id, storage_message_id, bg_file_id, parts_json),
            )
            await conn.commit()
            return cur.lastrowid

    async def get_clip(self, clip_id: int):
        """(id, title, script, video_file_id, duration)"""
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                SELECT id, title, script, video_file_id, duration
                FROM clips WHERE id = ?
                """,
                (clip_id,),
            )
            return await cur.fetchone()

    async def get_clip_full(self, clip_id: int):
        """Qismli (yangi) parchalar uchun to'liq ma'lumot, dict yoki None."""
        import json

        async with self.conn() as conn:
            cur = await conn.execute(
                """
                SELECT id, title, script, video_file_id, duration,
                       bg_file_id, parts
                FROM clips WHERE id = ?
                """,
                (clip_id,),
            )
            row = await cur.fetchone()
        if not row:
            return None

        parts = []
        if row[6]:
            try:
                parts = json.loads(row[6])
            except ValueError:
                parts = []

        return {
            "id": row[0],
            "title": row[1],
            "script": row[2],
            "video_file_id": row[3],
            "duration": row[4],
            "bg_file_id": row[5],
            "parts": parts,
        }

    async def all_clips(self):
        """[(id, title, duration), ...]"""
        async with self.conn() as conn:
            cur = await conn.execute(
                "SELECT id, title, duration FROM clips ORDER BY id DESC"
            )
            return await cur.fetchall()

    async def clips_count(self) -> int:
        async with self.conn() as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM clips")
            row = await cur.fetchone()
            return row[0] if row else 0

    async def delete_clip(self, clip_id: int):
        """O'chirilgan parcha ma'lumotini qaytaradi (yoki None)."""
        async with self.conn() as conn:
            cur = await conn.execute(
                """
                SELECT id, title, storage_chat_id, storage_message_id
                FROM clips WHERE id = ?
                """,
                (clip_id,),
            )
            row = await cur.fetchone()
            if not row:
                return None
            await conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
            await conn.commit()
            return {
                "id": row[0],
                "title": row[1],
                "storage_chat_id": row[2],
                "storage_message_id": row[3],
            }


db = Database(DB_PATH)
