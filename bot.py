
import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import telebot
from telebot import types

TZ = ZoneInfo("Asia/Tbilisi")
PORT = int(os.getenv("PORT", 9999))
DATA_DIR = "data"
LANG_FILE = os.path.join(DATA_DIR, "lang.json")
SCHEDULE_FILE = os.path.join(DATA_DIR, "schedule.json")
DEFAULT_LANG = "ru"

ADMINS = {
    7758773154: "joolay_vocal",
    388183067:  "joolay_joolay"
}

TEACHERS = {
    "Юля":     {"wd": [1, 2, 3, 4], "hours": [f"{h}:00" for h in range(15, 21)]},
    "Торнике": {"wd": [5, 6, 0],    "hours": [f"{h}:00" for h in range(8, 23)]}
}

WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
LANGUAGES = {"ru": "Русский 🇷🇺", "en": "English 🇬🇧"}

MESSAGES = {
    "ru": {
        "choose_lang": "👋 Привет! Выберите язык:",
        "lang_set": "Язык установлен: {lang}",
        "main_menu": "Главное меню:",
        "btn_book": "📅 Записаться",
        "btn_my": "👁 Моя запись",
        "btn_cancel": "❌ Отменить запись",
        "btn_admin": "🛠 Админка",
        "choose_teacher": "Выберите преподавателя:",
        "choose_week": "Выберите неделю:",
        "choose_day": "Выберите день:",
        "choose_time": "Выберите время:",
        "enter_name": "Введите ваше имя:",
        "pending": "⏳ Запись создана. Ожидайте подтверждения.",
        "confirmed": "✅ Ваша запись подтверждена: {t} {d} {h}",
        "cancel_q": "Вы уверены, что хотите отменить запись?",
        "cancel_ok": "✅ Запись отменена.",
        "no_booking": "У вас нет активных записей.",
        "admin_notify": "🆕 Новая заявка: {t} {d} {h}\n👤 {n} (ID {u})"
    },
    "en": {
        "choose_lang": "👋 Welcome! Choose your language:",
        "lang_set": "Language set to: {lang}",
        "main_menu": "Main menu:",
        "btn_book": "📅 Book",
        "btn_my": "👁 My booking",
        "btn_cancel": "❌ Cancel booking",
        "btn_admin": "🛠 Admin panel",
        "choose_teacher": "Choose a teacher:",
        "choose_week": "Choose week:",
        "choose_day": "Choose a day:",
        "choose_time": "Choose a time:",
        "enter_name": "Enter your name:",
        "pending": "⏳ Booking created. Await confirmation.",
        "confirmed": "✅ Booking confirmed: {t} {d} {h}",
        "cancel_q": "Are you sure you want to cancel your booking?",
        "cancel_ok": "✅ Booking cancelled.",
        "no_booking": "You have no active bookings.",
        "admin_notify": "🆕 New booking: {t} {d} {h}\n👤 {n} (ID {u})"
    }
}

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(LANG_FILE): json.dump({}, open(LANG_FILE, "w", encoding="utf-8"))
if not os.path.exists(SCHEDULE_FILE): json.dump({}, open(SCHEDULE_FILE, "w", encoding="utf-8"))

def load_json(path): return json.load(open(path, "r", encoding="utf-8"))
def save_json(path, data): json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
def get_lang(uid): return load_json(LANG_FILE).get(str(uid), DEFAULT_LANG)
def txt(uid, key, **kwargs): return MESSAGES[get_lang(uid)][key].format(**kwargs)

bot = telebot.TeleBot(os.getenv("BOT_TOKEN"))

class HC(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), HC).serve_forever(), daemon=True).start()

# Напоминалка
def start_reminder_loop():
    def check_loop():
        while True:
            now = datetime.now(TZ)
            sch = load_json(SCHEDULE_FILE)
            changed = False

            for teacher, days in sch.items():
                for d, times in days.items():
                    for h, info in times.items():
                        if info["status"] == "confirmed":
                            lesson_time = datetime.fromisoformat(f"{d}T{h}").replace(tzinfo=TZ)
                            delta = (lesson_time - now).total_seconds()
                            if 0 < delta <= 7200:
                                try:
                                    bot.send_message(
                                        info["uid"],
                                        f"🔔 Напоминание: через 2 часа у вас занятие с {teacher} в {h}",
                                        reply_markup=None
                                    )
                                    info["status"] = "reminded"
                                    changed = True
                                except:
                                    pass

            if changed:
                save_json(SCHEDULE_FILE, sch)

            threading.Event().wait(3600)

    threading.Thread(target=check_loop, daemon=True).start()

# Заглушка вместо полной логики
start_reminder_loop()
bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
