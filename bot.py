import os
import json
import csv
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from threading import Timer

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# === КОНСТАНТЫ / ШАБЛОНЫ ===
TZ = ZoneInfo("Asia/Tbilisi")
DATA_DIR = "data"
SCHEDULE_FILE = os.path.join(DATA_DIR, "schedule.json")
RECORDS_FILE = os.path.join(DATA_DIR, "records.csv")
LOG_FILE     = os.path.join(DATA_DIR, "bot.log")

MESSAGES = {
    "start": (
        "👋 Привет! Я бот для записи на вокал.\n\n"
        "❓ Чтобы записаться: нажми «Записаться» и следуй меню.\n"
        "ℹ️ Чтобы узнать, что я умею, нажми /help."
    ),
    "help": (
        "/start – вернуться в главное меню\n"
        "Записаться – выбрать преподавателя, дату и время\n"
        "Моя запись – посмотреть текущую бронь\n"
        "Отменить – отменить текущую бронь\n"
    ),
    "booking_confirmed": "✅ Ваша запись подтверждена: {teacher} {date}, {hour}",
    "reminder_before": "🔔 Через 2 часа урок у {teacher} в {date}, {hour}",
    "reminder_after": (
        "✅ Урок у {teacher} в {date}, {hour} завершён!\n"
        "Если вдруг решишь ещё – можешь выбрать свободное время 😉"
    ),
    "admin_new": "🆕 Новая запись: {teacher} {date}, {hour}\n👤 {name} (ID {uid})",
}

# === НАСТРОЙКИ ЛОГИРОВАНИЯ ===
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

# === СЕРВЕР ДЛЯ HEALTH‐CHECK (Render) ===
PORT = int(os.environ.get("PORT", 8000))
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
def run_health():
    HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()
threading.Thread(target=run_health, daemon=True).start()

# === BOT SETUP ===
TOKEN = os.getenv("BOT_TOKEN")
bot   = telebot.TeleBot(TOKEN)

# === ПРЕПОДАВАТЕЛИ И РАСПИСАНИЕ ===
TEACHERS = {
    "Юля":      {"wd": [1,2,3,4], "hours": ["15:00","16:00","17:00","18:00","19:00","20:00"]},
    "Торнике":  {"wd": [5,6,0], "hours": ["08:00","09:00","10:00","11:00","12:00",
                                        "13:00","14:00","15:00","16:00","17:00",
                                        "18:00","19:00","20:00","21:00","22:00"]},
}

# === АДМИНЫ ПО ID ===
ADMINS = {388183067:"joolay_joolay", 7758773154:"joolay_vocal"}

# === ЗАГРУЗКА / СОХРАНЕНИЕ ===
def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        return json.load(open(SCHEDULE_FILE, 'r', encoding='utf-8'))
    return {}
def save_schedule(data):
    with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

schedule = load_schedule()
# Инициализация CSV‐журнала
if not os.path.exists(RECORDS_FILE):
    with open(RECORDS_FILE, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(["Timestamp","Teacher","Date","Hour","UserID","Name","Status"])

# === ХЕЛПЕРЫ ===
def dates_for_teacher(teacher, week_offset):
    """Возвращает список дат YYYY-MM-DD для teacher на эту/следующую неделю."""
    now = datetime.now(TZ).date()
    # находим понедельник этой недели
    mon = now - timedelta(days=now.weekday())
    target_mon = mon + timedelta(weeks=week_offset)
    dates = []
    for d in range(7):
        dt = target_mon + timedelta(days=d)
        if dt.weekday() in TEACHERS[teacher]["wd"]:
            dates.append(dt.isoformat())
    return dates

def is_taken(teacher, date_str, hour):
    return (teacher in schedule
            and date_str in schedule[teacher]
            and hour in schedule[teacher][date_str])

def schedule_reminders(teacher, date_str, hour, uid):
    """Запланировать 2-часовое и послебронирование напоминания."""
    dt = datetime.fromisoformat(date_str).replace(
        tzinfo=TZ,
        hour=int(hour.split(":")[0]),
        minute=int(hour.split(":")[1]),
        second=0, microsecond=0
    )
    now = datetime.now(TZ)
    # до 2 часов
    delta1 = (dt - timedelta(hours=2) - now).total_seconds()
    if delta1 > 0:
        Timer(delta1, lambda: bot.send_message(
            uid,
            MESSAGES["reminder_before"].format(teacher=teacher, date=date_str, hour=hour),
            parse_mode="Markdown"
        )).start()
    # через 2 часа после
    delta2 = (dt + timedelta(hours=1) + timedelta(hours=2) - now).total_seconds()
    if delta2 > 0:
        Timer(delta2, lambda: bot.send_message(
            uid,
            MESSAGES["reminder_after"].format(teacher=teacher, date=date_str, hour=hour),
            parse_mode="Markdown"
        )).start()

def cleanup_old():
    """Удалить записи старше 14 дней без уведомлений."""
    cutoff = datetime.now(TZ).date() - timedelta(days=14)
    changed = False
    for tch in list(schedule):
        for ds in list(schedule[tch]):
            if datetime.fromisoformat(ds).date() < cutoff:
                del schedule[tch][ds]
                changed = True
        if tch in schedule and not schedule[tch]:
            del schedule[tch]
            changed = True
    if changed:
        save_schedule(schedule)
        logging.info("Cleaned old entries")
    # запланировать следующий запуск на завтра в 00:05
    now = datetime.now(TZ)
    next_mid = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    Timer((next_mid-now).total_seconds(), cleanup_old).start()

# старт очистки
cleanup_old()

# === MAIN MENU & HELP ===
@bot.message_handler(commands=['start'])
def cmd_start(m):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📅 Записаться", callback_data="book"))
    markup.add(InlineKeyboardButton("👀 Моя запись", callback_data="view"))
    markup.add(InlineKeyboardButton("❌ Отменить",   callback_data="cancel"))
    if m.from_user.id in ADMINS:
        markup.add(InlineKeyboardButton("⚙️ Админка", callback_data="admin"))
    bot.send_message(
        m.chat.id,
        MESSAGES["start"],
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['help'])
def cmd_help(m):
    bot.send_message(m.chat.id, MESSAGES["help"], parse_mode="Markdown")

# === CALLBACK HANDLER ===
@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    data = c.data
    uid  = c.from_user.id

    # — БРОНИРОВАНИЕ —
    if data == "book":
        # шаг 1: выбор преподавателя
        kb = InlineKeyboardMarkup()
        for tch in TEACHERS:
            kb.add(InlineKeyboardButton(tch, callback_data=f"teacher_{tch}"))
        bot.edit_message_text("Выберите преподавателя:", c.message.chat.id, c.message.message_id, reply_markup=kb)

    elif data.startswith("teacher_"):
        tch = data.split("_",1)[1]
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("Эта неделя",     callback_data=f"week_{tch}_0"))
        kb.add(InlineKeyboardButton("Следующая неделя",callback_data=f"week_{tch}_1"))
        bot.edit_message_text(f"Преподаватель *{tch}*. На какую неделю?", c.message.chat.id, c.message.message_id, parse_mode="Markdown", reply_markup=kb)

    elif data.startswith("week_"):
        _, tch, w = data.split("_",2)
        dates = dates_for_teacher(tch, int(w))
        kb = InlineKeyboardMarkup(row_width=3)
        for ds in dates:
            kb.add(InlineKeyboardButton(ds, callback_data=f"date_{tch}_{ds}"))
        bot.edit_message_text("Выберите дату:", c.message.chat.id, c.message.message_id, parse_mode="Markdown", reply_markup=kb)

    elif data.startswith("date_"):
        _, tch, ds = data.split("_",2)
        kb = InlineKeyboardMarkup()
        for hr in TEACHERS[tch]["hours"]:
            if not is_taken(tch, ds, hr):
                kb.add(InlineKeyboardButton(hr, callback_data=f"time_{tch}_{ds}_{hr}"))
        text = f"Преподаватель *{tch}*, дата *{ds}*.\nВыберите время:" if kb.keyboard else "Нет свободных слотов."
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, parse_mode="Markdown", reply_markup=kb)

    elif data.startswith("time_"):
        _, tch, ds, hr = data.split("_",3)
        # сохраняем временный контекст
        bot.delete_message(c.message.chat.id, c.message.message_id)
        msg = bot.send_message(c.message.chat.id, f"Введите своё имя для записи на {tch}, {ds} в {hr}:")
        bot.register_next_step_handler(msg, finish_booking, tch, ds, hr, uid)

    elif data == "view":
        # показать текущую бронь
        for tch in schedule:
            for ds in schedule[tch]:
                for hr, info in schedule[tch][ds].items():
                    if info["user_id"] == uid:
                        bot.answer_callback_query(c.id, show_alert=True, text=f"{tch} {ds} {hr} — {info['name']} ({info['status']})")
                        return
        bot.answer_callback_query(c.id, text="У вас нет брони.")

    elif data == "cancel":
        # отмена пользователем
        for tch in list(schedule):
            for ds in list(schedule[tch]):
                for hr, info in list(schedule[tch][ds].items()):
                    if info["user_id"] == uid:
                        del schedule[tch][ds][hr]
                        if not schedule[tch][ds]: del schedule[tch][ds]
                        save_schedule(schedule)
                        logging.info(f"User {uid} canceled {tch} {ds} {hr}")
                        bot.answer_callback_query(c.id, text="Ваша бронь отменена.")
                        return
        bot.answer_callback_query(c.id, text="Нечего отменять.")

    # — ПОДТВЕРЖДЕНИЕ АДМИНОМ —
    elif data.startswith("confirm_") and uid in ADMINS:
        _, tch, ds, hr = data.split("_",3)
        entry = schedule[tch][ds][hr]
        entry["status"] = "confirmed"
        save_schedule(schedule)
        bot.answer_callback_query(c.id, text="Запись подтверждена.")
        bot.send_message(
            entry["user_id"],
            MESSAGES["booking_confirmed"].format(teacher=tch, date=ds, hour=hr),
            parse_mode="Markdown"
        )
        schedule_reminders(tch, ds, hr, entry["user_id"])
        logging.info(f"Booking confirmed: {tch} {ds} {hr} for {entry['user_id']}")
    # — АДМИН‐ПАНЕЛЬ —
    elif data == "admin" and uid in ADMINS:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("📋 Все записи", callback_data="all"))
        kb.add(InlineKeyboardButton("📅 По преподавателю", callback_data="byteacher"))
        bot.edit_message_text("Админка: выберите действие", c.message.chat.id, c.message.message_id, reply_markup=kb)

    elif data == "all" and uid in ADMINS:
        text = ""
        for tch in schedule:
            for ds in schedule[tch]:
                for hr, info in schedule[tch][ds].items():
                    text += f"{tch} {ds} {hr} — {info['name']} ({info['status']})\n"
        bot.send_message(c.message.chat.id, text or "Нет записей.")
        bot.answer_callback_query(c.id)

    elif data == "byteacher" and uid in ADMINS:
        kb = InlineKeyboardMarkup()
        for tch in TEACHERS:
            kb.add(InlineKeyboardButton(tch, callback_data=f"adm_tch_{tch}"))
        bot.edit_message_text("Выберите преподавателя:", c.message.chat.id, c.message.message_id, reply_markup=kb)

    elif data.startswith("adm_tch_") and uid in ADMINS:
        tch = data.split("_",2)[2]
        kb = InlineKeyboardMarkup()
        for ds in sorted(schedule.get(tch,{})):
            kb.add(InlineKeyboardButton(ds, callback_data=f"adm_day_{tch}_{ds}"))
        bot.edit_message_text(f"Записи у {tch}:", c.message.chat.id, c.message.message_id, reply_markup=kb)

    elif data.startswith("adm_day_") and uid in ADMINS:
        _, tch, ds = data.split("_",2)
        text = ""
        kb = InlineKeyboardMarkup()
        for hr, info in schedule.get(tch,{}).get(ds,{}).items():
            text += f"{hr} — {info['name']} ({info['status']})\n"
            kb.add(InlineKeyboardButton(f"❌ {hr}", callback_data=f"del_{tch}_{ds}_{hr}"))
        bot.send_message(c.message.chat.id, text or "Нет записей.", reply_markup=kb)
        bot.answer_callback_query(c.id)

    elif data.startswith("del_") and uid in ADMINS:
        _, tch, ds, hr = data.split("_",3)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Да, удалить", callback_data=f"do_del_{tch}_{ds}_{hr}"))
        kb.add(InlineKeyboardButton("❌ Отмена", callback_data="admin"))
        bot.send_message(c.message.chat.id, f"Удалить запись {tch} {ds} {hr}?", reply_markup=kb)
        bot.answer_callback_query(c.id)

    elif data.startswith("do_del_") and uid in ADMINS:
        _, tch, ds, hr = data.split("_",3)
        del schedule[tch][ds][hr]
        if not schedule[tch][ds]: del schedule[tch][ds]
        save_schedule(schedule)
        bot.answer_callback_query(c.id, text="Удалено.")
        logging.info(f"Admin {uid} deleted {tch} {ds} {hr}")

    else:
        bot.answer_callback_query(c.id, "Доступ запрещён или неизвестная команда.")

# === ЗАВЕРШЕНИЕ БРОНИ ===
def finish_booking(msg, tch, ds, hr, uid):
    name = msg.text.strip()
    # создаём запись в статусе pending
    schedule.setdefault(tch,{}).setdefault(ds,{})
    schedule[tch][ds][hr] = {
        "user_id": uid,
        "name": name,
        "status": "pending"
    }
    save_schedule(schedule)
    logging.info(f"Booking pending: {tch} {ds} {hr} by {name} ({uid})")

    bot.send_message(msg.chat.id,
                     f"⏳ Ваша запись на {tch} «{ds}» в {hr} ожидает подтверждения администратора.",
                     parse_mode="Markdown")

    # уведомить админов
    note = MESSAGES["admin_new"].format(teacher=tch, date=ds, hour=hr, name=name, uid=uid)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_{tch}_{ds}_{hr}"))
    for aid in ADMINS:
        bot.send_message(aid, note, parse_mode="Markdown", reply_markup=kb)

# === RUN ===
if __name__ == "__main__":
    bot.infinity_polling()
