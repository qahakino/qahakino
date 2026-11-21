# 🎬 Kino Telegram Bot

Kanalga majburiy obuna + kod orqali kino beruvchi Telegram bot. Barcha kinolar
sizning yopiq (private) kanalingizda saqlanadi, foydalanuvchiga esa o'sha
yerdan nusxa (copy) qilib yuboriladi.

## 📁 Loyiha tuzilishi

```
kino_bot/
├── main.py                # Botni ishga tushiruvchi fayl
├── config.py              # .env dan sozlamalarni o'qiydi
├── database.py            # SQLite bilan ishlash (foydalanuvchilar, kinolar)
├── states.py               # Admin uchun FSM holatlari
├── keyboards.py           # Inline tugmalar
├── handlers/
│   ├── user.py            # /start, obuna tekshirish, kod qabul qilish
│   └── admin.py           # /admin, kino qo'shish, /stats, /delete
├── utils/
│   └── subscription.py    # Obunani tekshirish funksiyasi
├── requirements.txt
└── .env.example
```

## ⚙️ Qanday ishlaydi

1. **/start** — foydalanuvchi qo'shiladi, kerakli kanallarga obunasi tekshiriladi.
2. Obuna bo'lmagan bo'lsa — obuna bo'lmagan kanallar ro'yxati va
   "✅ Obuna bo'ldim" tugmasi chiqadi. Bosilganda qayta tekshiriladi.
3. Obuna to'liq bo'lsa — botga istalgan matn (kod) yuborilsa, baza ichidan
   qidiriladi va topilsa `copy_message` orqali storage kanaldan nusxa
   qilib yuboriladi (bu "forward" dan farqli o'laroq "Forwarded from"
   yozuvini ko'rsatmaydi va manba kanalni yashiradi).
4. **/admin** — faqat `.env` dagi `ADMIN_IDS` ro'yxatidagi userlar uchun
   ishlaydi: kino nomi → kod → kino fayli/forward so'raladi, so'ng bot uni
   avtomatik storage kanalga joylab, kodni bazaga yozadi.

### Nima uchun "kod → forward/copy qilish" usuli tanlandi

Buni siz ham to'g'ri taxmin qilgansiz — bu eng tez va eng arzon yo'l:
kino fayli faqat BIR MARTA (siz uni kanalga yuklaganda) Telegram serverlariga
yuklanadi, keyin har bir foydalanuvchiga faqat **havola ko'chiriladi**, fayl
qayta yuklanmaydi. Bu tezroq ishlaydi va serveringizga hech qanday
disk/trafik yukini bermaydi (fayl sizning kompyuteringiz yoki serveringiz
orqali emas, to'g'ridan-to'g'ri Telegram serverlari ichida ko'chadi).

### Kino qo'shishda: fayl yuklashmi yoki kanaldan forwardmi?

Ikkisi ham kodda qo'llab-quvvatlanadi, lekin katta hajmli kinolar
(odatda 50 MB dan katta) uchun **forward usuli tavsiya etiladi**:

- Bot orqali botga **to'g'ridan-to'g'ri fayl yuklashda** standart Telegram
  Bot API cheklovi bor — odatda ~50 MB gacha fayl yuborish mumkin.
- Agar kinoni avval oddiy Telegram ilovasi orqali o'zingizning storage
  kanalingizga yuklasangiz (bunda cheklov yo'q — 2 GB gacha, Telegram
  Premium'da 4 GB gacha), so'ng O'SHA POSTNI botga forward qilsangiz,
  bot buni aniqlab, hech qanday qayta nusxalashsiz to'g'ridan-to'g'ri
  o'sha post ID sini bazaga yozadi. Bu usul hajm chegarasiga umuman
  uchramaydi.

Shuning uchun admin oqimida bot ikkalasini ham qabul qiladi, lekin katta
fayllar uchun birinchi (forward) usulni tavsiya qiladigan xabar chiqaradi.

## 🚀 O'rnatish (lokal test)

### 1. Bot tokenini oling

[@BotFather](https://t.me/BotFather) ga yozing → `/newbot` → nomini bering →
tokenni saqlab qo'ying.

### 2. Kanallarni tayyorlang

- **Majburiy obuna kanal(lar)i** — foydalanuvchi obuna bo'lishi kerak
  bo'lgan kanal(lar). Botni ularga **admin** qilib qo'shing (kamida
  "obunachilarni ko'rish" huquqi bilan).
- **Storage (saqlash) kanali** — alohida, butunlay YOPIQ kanal yarating,
  faqat siz va bot a'zo bo'ladi. Kinolar shu yerda saqlanadi. Botni bu
  yerga ham **admin** qilib qo'shing.

> ⚠️ Bot kanalda admin bo'lmasa, obunani tekshira olmaydi va storage
> kanalga xabar yubora olmaydi.

### 3. Kanal ID sini toping

- Ochiq kanal bo'lsa — shunchaki `@kanal_username` yetarli.
- Yopiq kanal bo'lsa (masalan storage kanal) — ID raqamini bilish kerak
  (`-100` bilan boshlanadi). Buning uchun eng oson yo'l: kanalga istalgan
  xabar yuboring, uni [@userinfobot](https://t.me/userinfobot) yoki
  [@getidsbot](https://t.me/getidsbot) ga forward qiling — sizga chat ID
  ni ko'rsatadi.

### 4. Loyihani sozlang

```bash
cd kino_bot
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env faylini oching va o'zingizning qiymatlaringizni kiriting:
#   BOT_TOKEN, ADMIN_IDS, STORAGE_CHANNEL_ID, REQUIRED_CHANNELS
```

### 5. Ishga tushiring

```bash
python3 main.py
```

Telegramda botingizga `/start` yozib sinab ko'ring, so'ng o'zingiz
(`ADMIN_IDS` da bo'lgan holda) `/admin` orqali birinchi kinongizni qo'shing.

## 🔑 Admin buyruqlari

| Buyruq | Vazifasi |
|---|---|
| `/admin` | Yangi kino qo'shish oqimini boshlaydi |
| `/cancel` | Joriy admin amalini bekor qiladi |
| `/stats` | Foydalanuvchilar va kinolar sonini ko'rsatadi |
| `/delete <kod>` | Berilgan koddagi kinoni bazadan HAM, storage kanaldagi postdan HAM o'chiradi |

## 🌍 Botni doimiy (24/7) ishlatish uchun qayerga joylash kerak

Bot hozircha **polling** rejimida ishlaydi (`start_polling`) — ya'ni doimiy
internetga ulanib turadigan, uzluksiz ishlaydigan bitta jarayon kerak.
Shuning uchun oddiy shared-hosting yoki vaqtinchalik ishlaydigan muhitlar
(masalan PythonAnywhere'ning bepul rejasi) mos kelmaydi. Quyidagi variantlar
tavsiya etiladi:

### Variant A — Arzon VPS (eng ishonchli va tavsiya etiladigan)

Bu eng keng tarqalgan va boshqarish oson yo'l. Har qanday Ubuntu VPS provayderi
mos keladi (Hetzner, Contabo, DigitalOcean va h.k. — narxlar va shartlar
tez-tez o'zgarib turadi, shuning uchun joriy narxni provayderning saytidan
tekshiring).

1. VPS sotib oling (Ubuntu 22.04/24.04), SSH orqali kiring.
2. Python, git o'rnating:
   ```bash
   sudo apt update && sudo apt install -y python3-venv python3-pip git
   ```
3. Loyihani serverga yuklang (git orqali yoki `scp` bilan ko'chiring),
   so'ng yuqoridagi 4-5-bosqichlarni serverda takrorlang.
4. Botni **systemd** xizmati sifatida sozlang, shunda server qayta
   yoqilganda ham avtomatik ishga tushadi:

   `/etc/systemd/system/kinobot.service` faylini yarating:
   ```ini
   [Unit]
   Description=Kino Telegram Bot
   After=network.target

   [Service]
   User=root
   WorkingDirectory=/root/kino_bot
   ExecStart=/root/kino_bot/venv/bin/python3 main.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
5. Ishga tushiring:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable kinobot
   sudo systemctl start kinobot
   sudo systemctl status kinobot   # holatini tekshirish
   journalctl -u kinobot -f        # loglarni jonli kuzatish
   ```

### Variant B — PaaS platformalar (Railway, Render va h.k.)

Bu platformalar kodni GitHub'dan tortib, "worker"/"background service"
sifatida doimiy ishlatib turadi (server bilan o'zingiz shug'ullanishingiz
shart emas). Ammo:

- Bularning narx siyosati va bepul limitlari tez-tez o'zgaradi, shuning
  uchun ishga tushirishdan oldin albatta platformaning o'zining joriy
  narxlar sahifasini tekshiring.
- Odatda bunday "har doim yonib turadigan" fon jarayoni uchun eng arzon
  bepul reja YETARLI BO'LMAYDI (bepul rejalar ko'pincha vaqtinchalik
  "sleep" qiladi yoki cheklangan soatlarga ega) — sizga ozgina pullik
  reja (oyiga bir necha dollar) kerak bo'ladi.
- Umumiy qadamlar: loyihani GitHub'ga joylang → platformada yangi loyiha
  yarating → GitHub repo'ni bog'lang → "Start Command" sifatida
  `python main.py` ni ko'rsating → Environment Variables bo'limiga
  `.env` dagi barcha qiymatlarni (BOT_TOKEN, ADMIN_IDS va h.k.) qo'lda
  kiriting (`.env` faylining o'zini yuklamang, u git'ga qo'shilmasligi
  kerak — `.gitignore` da bor).

**Tavsiya:** birinchi marta qilayotgan bo'lsangiz, arzon VPS + systemd
(Variant A) eng barqaror va tushunarli yo'l. Keyinchalik trafik oshsa,
kerak bo'lsa PaaS'ga yoki kattaroq VPS'ga o'tishingiz mumkin.

## 🗄️ Zaxira nusxa (backup)

`bot.db` — SQLite fayli, unda barcha foydalanuvchilar va kino kodlari
saqlanadi. Buni vaqti-vaqti bilan boshqa joyga nusxalab turing:

```bash
cp bot.db bot_backup_$(date +%F).db
```

## ➕ Kelajakda qo'shsa bo'ladigan narsalar

- Bir nechta admin uchun kino qo'shgan admin ismini logga yozib borish
- Kinolarni kategoriya/janr bo'yicha inline qidiruv
- `/broadcast` — barcha foydalanuvchilarga xabar yuborish (bazadagi
  `all_user_ids()` funksiyasi allaqachon tayyor, shu ustiga handler
  qo'shish kifoya)

## Serial tizimi

Admin uchun `/serial` buyrug'i serial boshqaruvini ochadi:

- mavjud seriallar knopka bilan chiqadi;
- `➕ Yangi serial` orqali yangi serial yaratiladi;
- yangi serialda nomi, kodi, poster rasmi va birinchi qismi saqlanadi;
- mavjud serial tanlanib, keyingi qism raqami va videosi qo'shiladi;
- serial va qismlar ham storage kanalida saqlanadi;
- foydalanuvchi `/start` dan keyin serial kodini yuborsa poster va `📺 Qismlarni ko'rish` tugmasi chiqadi;
- tugma bosilganda barcha mavjud qismlar knopka bo'lib chiqadi;
- qism tanlanganda video storage kanaldan foydalanuvchiga nusxalanadi.

Seriallar uchun `series` va `episodes` jadvallari bot ishga tushganda avtomatik yaratiladi. Mavjud `bot.db` saqlanadi va eski kinolar o'chmaydi.

## `/delete`

`/delete` endi kodni keyingi xabarda ham qabul qiladi:

1. Admin `/delete` yuboradi.
2. Bot `🗑 Kino kodini kiriting:` deb so'raydi.
3. Admin kodni yuboradi.
4. Kino bazadan va imkon bo'lsa storage kanaldan o'chiriladi.

Eski `/delete 123` ko'rinishidagi usul ham ishlaydi.

## Menyu tugmalari (klaviatura o'rnida)

`/start` dan keyin foydalanuvchida doimiy tugmalar chiqadi:

- **🔢 Kod orqali qidirish** — kod so'raydi (oddiy matn sifatida kod yuborish ham avvalgidek ishlaydi).
- **🔎 Nomi orqali qidirish** — nomning bir qismi bilan qidiradi (`o'`, `g'` harflari turlicha yozilsa ham topadi). Bitta natija bo'lsa darrov yuboradi, ko'p bo'lsa tugmalar ro'yxatini ko'rsatadi (kino va seriallar).
- **🎙 Ovozli kino** — kinodan parcha tanlanadi, bot video va matnni yuboradi, foydalanuvchi matnni o'qib ovozli xabar yuboradi, bot videoga uning ovozini qo'yib qaytaradi.

## Ovozli kino (admin uchun)

| Buyruq | Vazifasi |
|---|---|
| `/clip` | Yangi parcha qo'shish |
| `/clips` | Parchalar ro'yxati, bosib o'chirish |

`/clip` tartibi:
1. **Nomi**
2. **Asl video** — foydalanuvchiga ko'rsatiladi (hajmi cheklanmagan).
3. **Faqat orqa fonli video** — gaplar olib tashlangan, asl bilan bir xil uzunlikda, **20 MB dan kichik**.
4. **Qismlar** — bitta xabarda, har qator `MM:SS-MM:SS | matn`:

```
00:05-00:12 | Salom, men keldim
00:13-00:20 | Qayerdan keldingiz?
```

Foydalanuvchi qismlarni ketma-ket ovoz bilan yozadi (xohlasa oldingi qismni
qayta yozadi). Bot har ovozni o'z vaqtiga qo'yib, orqa fon musiqa ustiga
aralashtiradi (video qayta kodlanmaydi — tez). Har ovoz o'z oralig'idan
`PART_EXTRA_SECONDS` (standart 1) soniyadan ko'p uzun bo'lsa qabul qilinmaydi.

Eski usulda (qismsiz) qo'shilgan parchalar ham avvalgidek ishlaydi.

Orqa fonli videoni tayyorlash: gap ovozini musiqadan ajratuvchi vosita
(Demucs, Ultimate Vocal Remover yoki onlayn xizmatlar) bilan ovozni olib
tashlab, "gapsiz" qismini videoga qaytarib qo'yasiz.

**Ovoz balandligi.** Foydalanuvchi ovozi avtomatik bir xil balandlikka keltiriladi
(past yozilgan bo'lsa ham). Sozlash uchun Railway Variables:
- `VOICE_LUFS` (standart `-14`): kattaroq son (masalan `-12`) — ovoz balandroq, kichikroq (`-18`) — pastroq.
- `BG_VOLUME` (standart `0.5`): orqa fon musiqa balandligi, `1.0` — o'zgarmas, `0.3` — ancha past.

**Server talabi:** ffmpeg o'rnatilgan bo'lishi kerak.
Railway (Railpack) da: *Service → Variables* ga
`RAILPACK_DEPLOY_APT_PACKAGES=ffmpeg` qo'shing va qayta deploy qiling.
Lokal Ubuntu'da: `sudo apt install ffmpeg`.

**Cheklov:** Telegram bot 20 MB dan katta faylni yuklab ola olmaydi, shuning
uchun orqa fonli video 20 MB dan kichik bo'lishi kerak.

## Webhook xavfsizligi (tavsiya etiladi)

`.env` / Railway Variables ga `WEBHOOK_SECRET=istalgan_uzun_harf_raqam_matni`
qo'shing (faqat harf, raqam, `_`, `-`). Shunda `/webhook` manziliga faqat
Telegram yuborgan so'rovlar qabul qilinadi; begona kishi soxta so'rov bilan
o'zini admin qilib ko'rsata olmaydi.
