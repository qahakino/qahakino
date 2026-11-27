import os

from dotenv import load_dotenv

load_dotenv()

# @BotFather dan olingan bot tokeni
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Admin(lar)ning Telegram user_id lari, vergul bilan ajratiladi
# Masalan: ADMIN_IDS=111111111,222222222
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Barcha kinolar saqlanadigan sizning YOPIQ (private) kanalingiz ID si.
# Bot shu kanalda ADMIN bo'lishi shart.
# Masalan: STORAGE_CHANNEL_ID=-1001234567890
STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID", "0"))

# Kino buyurtmalari keladigan GURUH ID si (bot shu guruhda bo'lishi kerak).
# Guruhda adminlardan biri /chatid yozsa, bot ID ni ko'rsatadi. Masalan: ORDERS_CHAT_ID=-1001234567890
# Bo'sh qoldirilsa, buyurtmalar har bir adminning shaxsiy chatiga yuboriladi.
ORDERS_CHAT_ID = int(os.getenv("ORDERS_CHAT_ID", "0") or 0)

# Har kuni avtomatik zaxira nusxa: soat (Toshkent vaqti bilan) va qayerga yuborilishi.
# BACKUP_CHAT_ID bo'sh bo'lsa — hamma adminga shaxsiy xabar bilan. BACKUP_HOUR=-1 — o'chirish.
BACKUP_HOUR = int(os.getenv("BACKUP_HOUR", "3"))
BACKUP_CHAT_ID = int(os.getenv("BACKUP_CHAT_ID", "0") or 0)

DB_PATH = os.getenv("DB_PATH", "bot.db")

# Webhook xavfsizligi uchun (ixtiyoriy, lekin tavsiya etiladi).
# Faqat harf, raqam, _ va - ishlatiladi. Masalan: WEBHOOK_SECRET=qaxa_secret_2026
# Bo'sh qoldirilsa, tekshiruv o'chiq turadi (avvalgidek ishlaydi).
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Ovozli parcha: foydalanuvchi ovozi videodan necha soniyaga uzun bo'lishi mumkin
VOICE_EXTRA_SECONDS = int(os.getenv("VOICE_EXTRA_SECONDS", "3"))

# Ovoz balandligi: foydalanuvchi ovozi shu loudness (LUFS) ga keltiriladi.
# Raqam kattaroq (masalan -12) bo'lsa ovoz balandroq, kichikroq (-18) bo'lsa pastroq.
VOICE_LUFS = float(os.getenv("VOICE_LUFS", "-14"))

# Orqa fon musiqa balandligi (1.0 = o'zgarmas, 0.5 = ikki barobar past)
BG_VOLUME = float(os.getenv("BG_VOLUME", "0.5"))

# Qismli parcha: ovoz o'z vaqt oralig'idan necha soniya uzun bo'lishi mumkin
PART_EXTRA_SECONDS = int(os.getenv("PART_EXTRA_SECONDS", "1"))

# Bitta parchada qismlar soni chegarasi
MAX_CLIP_PARTS = 20

# Telegram Bot API orqali bot yuklab ola oladigan fayl chegarasi (20 MB)
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def _parse_channels(raw: str) -> list[dict]:
    """
    Majburiy obuna kanallarini o'qiydi. Ikki xil formatni qabul qiladi:

    1) Ochiq (public) kanal uchun:      @kanal_username
    2) Yopiq (private) kanal uchun:     -1001234567890|https://t.me/+xxxxxxxx
       (chat_id va taklif havolasi "|" bilan ajratiladi, chunki private
       kanalning @username i bo'lmaydi va bot uni get_chat_member orqali
       tekshirish uchun aynan ID kerak, foydalanuvchiga esa bosish uchun link)

    .env da bir nechtasi vergul bilan yoziladi:
    REQUIRED_CHANNELS=@kanal1,@kanal2,-1009876543210|https://t.me/+abc123
    """
    channels = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "|" in item:
            chat_id, link = item.split("|", 1)
            channels.append({"id": int(chat_id), "link": link.strip()})
        else:
            username = item.lstrip("@")
            channels.append({"id": f"@{username}", "link": f"https://t.me/{username}"})
    return channels


REQUIRED_CHANNELS = _parse_channels(os.getenv("REQUIRED_CHANNELS", ""))
