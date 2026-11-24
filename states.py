from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    # Kino
    waiting_movie_name = State()
    waiting_movie_code = State()
    waiting_movie_content = State()
    waiting_movie_poster = State()
    waiting_movie_info = State()

    # Eski kino/serialga poster ulash (/poster)
    waiting_poster_code = State()
    waiting_poster_photo = State()

    # Kino/serialga izoh, yil, janr qo'shish (/info)
    waiting_info_text = State()

    # Kino o'chirish
    waiting_delete_movie_code = State()

    # Serial
    waiting_series_name = State()
    waiting_series_code = State()
    waiting_series_poster = State()
    waiting_series_episode_number = State()
    waiting_series_episode_content = State()

    # Eski serialga yangi qism qo'shish
    waiting_existing_series_episode_number = State()
    waiting_existing_series_episode_content = State()

    # Ovozli parcha (kinodan 2-3 daqiqalik lavha)
    waiting_clip_title = State()
    waiting_clip_video = State()   # 1) asl video (foydalanuvchiga ko'rsatiladi)
    waiting_clip_bg = State()      # 2) faqat orqa fonli video (yig'ish uchun)
    waiting_clip_parts = State()   # 3) vaqt belgili matn qismlari


class UserStates(StatesGroup):
    # "🔎 Nomi orqali qidirish" bosilgandan keyin
    waiting_name = State()

    # Eski usul: bitta ovoz bilan butun videoni almashtirish
    waiting_voice = State()

    # Yangi usul: qism-qism ovoz yig'ish
    waiting_part = State()
