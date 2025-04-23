import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import telebot
from telebot import types

# ——— КОНСТАНТЫ ———
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

# ——— ХЕЛПЕРЫ ———
def load_json(path): return json.load(open(path, "r", encoding="utf-8"))
def save_json(path, data): json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
def get_lang(uid): return load_json(LANG_FILE).get(str(uid), DEFAULT_LANG)
def txt(uid, key, **kwargs): return MESSAGES[get_lang(uid)][key].format(**kwargs)

# ——— БОТ ———
bot = telebot.TeleBot(os.getenv("BOT_TOKEN"))

SESS = {}

# ——— HEALTHCHECK ———
class HC(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

threading.Thread(target=lambda: HTTPServer(("0.0.0.0", PORT), HC).serve_forever(), daemon=True).start()

# ——— КНОПКИ ———
def kb_main(uid):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.add(txt(uid, "btn_book"), txt(uid, "btn_my"))
    k.add(txt(uid, "btn_cancel"))
    if uid in ADMINS:
        k.add(txt(uid, "btn_admin"))
    return k

def kb_back(uid):
    text = {"ru": "🔙 Назад", "en": "🔙 Back"}[get_lang(uid)]
    k = types.InlineKeyboardMarkup()
    k.add(types.InlineKeyboardButton(text, callback_data="main"))
    return k

# ——— ОБРАБОТЧИКИ ———
@bot.message_handler(commands=["start"])
def h_start(m):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for code, label in LANGUAGES.items():
        kb.add(label)
    bot.send_message(m.chat.id, MESSAGES["ru"]["choose_lang"], reply_markup=kb)

@bot.message_handler(func=lambda m: m.text in LANGUAGES.values())
def h_set_lang(m):
    code = next(k for k, v in LANGUAGES.items() if v == m.text)
    langs = load_json(LANG_FILE)
    langs[str(m.from_user.id)] = code
    save_json(LANG_FILE, langs)
    bot.send_message(m.chat.id, txt(m.from_user.id, "lang_set", lang=m.text), reply_markup=kb_main(m.from_user.id))

@bot.callback_query_handler(func=lambda c: c.data == "main")
def h_back(c):
    bot.answer_callback_query(c.id)
    bot.send_message(c.from_user.id, txt(c.from_user.id, "main_menu"), reply_markup=kb_main(c.from_user.id))

@bot.message_handler(func=lambda m: m.text == txt(m.from_user.id, "btn_book"))
def h_book(m):
    uid = m.from_user.id
    kb = types.InlineKeyboardMarkup()
    for t in TEACHERS:
        kb.add(types.InlineKeyboardButton(t, callback_data=f"t|{t}"))
    bot.send_message(uid, txt(uid, "choose_teacher"), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("t|"))
def h_teacher(c):
    uid = c.from_user.id
    SESS[uid] = {"t": c.data.split("|")[1]}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Эта неделя", callback_data="w|0"))
    kb.add(types.InlineKeyboardButton("Следующая неделя", callback_data="w|1"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="main"))
    bot.edit_message_text(txt(uid, "choose_week"), uid, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("w|"))
def h_week(c):
    uid = c.from_user.id
    week = int(c.data.split("|")[1])
    tch = SESS[uid]["t"]
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week)
    kb = types.InlineKeyboardMarkup(row_width=2)
    for i in range(7):
        d = monday + timedelta(days=i)
        if d >= today and d.weekday() in TEACHERS[tch]["wd"]:
            label = f"{d.strftime('%d.%m.%y')} ({WD_SHORT[d.weekday()]})"
            kb.add(types.InlineKeyboardButton(label, callback_data=f"d|{d.isoformat()}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="main"))
    bot.edit_message_text(txt(uid, "choose_day"), uid, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("d|"))
def h_day(c):
    uid = c.from_user.id
    date_str = c.data.split("|")[1]
    tch = SESS[uid]["t"]
    SESS[uid]["d"] = date_str
    sch = load_json(SCHEDULE_FILE).get(tch, {}).get(date_str, {})
    kb = types.InlineKeyboardMarkup(row_width=3)
    for h in TEACHERS[tch]["hours"]:
        if h not in sch:
            kb.add(types.InlineKeyboardButton(h, callback_data=f"h|{h}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="main"))
    bot.edit_message_text(txt(uid, "choose_time"), uid, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("h|"))
def h_hour(c):
    uid = c.from_user.id
    h = c.data.split("|")[1]
    SESS[uid]["h"] = h
    bot.send_message(uid, txt(uid, "enter_name"), reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler_by_chat_id(uid, finalize_booking)

def finalize_booking(m):
    uid = m.chat.id
    name = m.text.strip()
    t, d, h = SESS[uid]["t"], SESS[uid]["d"], SESS[uid]["h"]
    sch = load_json(SCHEDULE_FILE)
    sch.setdefault(t, {}).setdefault(d, {})[h] = {"uid": uid, "name": name, "status": "pending"}
    save_json(SCHEDULE_FILE, sch)
    bot.send_message(uid, txt(uid, "pending"), reply_markup=kb_main(uid))
    for aid in ADMINS:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅", callback_data=f"conf|{t}|{d}|{h}"))
        kb.add(types.InlineKeyboardButton("❌", callback_data=f"rej|{t}|{d}|{h}"))
        bot.send_message(aid, txt(uid, "admin_notify", t=t, d=d, h=h, n=name, u=uid), reply_markup=kb)
    del SESS[uid]

@bot.message_handler(func=lambda m: m.text == txt(m.from_user.id, "btn_my"))
def h_my(m):
    uid = m.from_user.id
    sch = load_json(SCHEDULE_FILE)
    for t in sch:
        for d in sch[t]:
            for h, info in sch[t][d].items():
                if info["uid"] == uid:
                    bot.send_message(uid, f"{t} {d} {h} ({info['status']})", reply_markup=kb_main(uid))
                    return
    bot.send_message(uid, txt(uid, "no_booking"), reply_markup=kb_main(uid))

@bot.message_handler(func=lambda m: m.text == txt(m.from_user.id, "btn_cancel"))
def h_cancel(m):
    uid = m.from_user.id
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅", callback_data="canc|yes"))
    kb.add(types.InlineKeyboardButton("❌", callback_data="canc|no"))
    bot.send_message(uid, txt(uid, "cancel_q"), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("canc|"))
def h_cancel_confirm(c):
    uid = c.from_user.id
    if c.data == "canc|yes":
        sch = load_json(SCHEDULE_FILE)
        for t in sch:
            for d in sch[t]:
                for h in list(sch[t][d]):
                    if sch[t][d][h]["uid"] == uid:
                        del sch[t][d][h]
                        save_json(SCHEDULE_FILE, sch)
                        bot.send_message(uid, txt(uid, "cancel_ok"), reply_markup=kb_main(uid))
                        return
        bot.send_message(uid, txt(uid, "no_booking"), reply_markup=kb_main(uid))
    else:
        bot.send_message(uid, txt(uid, "main_menu"), reply_markup=kb_main(uid))

@bot.message_handler(func=lambda m: m.text == txt(m.from_user.id, "btn_admin") and m.from_user.id in ADMINS)
def h_admin_panel(m):
    uid = m.from_user.id
    sch = load_json(SCHEDULE_FILE)
    msg = "📋 Все записи:\n"
    for t in sch:
        for d in sch[t]:
            for h, info in sch[t][d].items():
                msg += f"{t} {d} {h} — {info['name']} ({info['status']})\n"
    bot.send_message(uid, msg or "Нет записей", reply_markup=kb_main(uid))

@bot.callback_query_handler(func=lambda c: c.data.startswith(("conf|", "rej|")))
def h_admin_action(c):
    uid = c.from_user.id
    action, t, d, h = c.data.split("|")
    sch = load_json(SCHEDULE_FILE)
    if action == "conf":
        sch[t][d][h]["status"] = "confirmed"
        bot.send_message(sch[t][d][h]["uid"], txt(sch[t][d][h]["uid"], "confirmed", t=t, d=d, h=h))
    else:
        bot.send_message(sch[t][d][h]["uid"], txt(sch[t][d][h]["uid"], "cancel_ok"))
        del sch[t][d][h]
    save_json(SCHEDULE_FILE, sch)
    bot.answer_callback_query(c.id)

# ——— RUN ———
bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
