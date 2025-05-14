from dotenv import load_dotenv
load_dotenv()  # загружаем переменные из .env

import os
import time
import sqlite3
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask
from threading import Thread

import telebot
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler

# ---------------- ЛОГИРОВАНИЕ ----------------
logging.basicConfig(level=logging.INFO)
telebot.logger.setLevel(logging.DEBUG)

# ---------------- Мини-веб-сервер для health checks ----------------
app = Flask(__name__)
@app.route("/")
def ping():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web, daemon=True).start()

# ---------------- Переменные окружения ----------------
TOKEN     = os.getenv("TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DB_PATH   = os.getenv("DB_PATH", "vocal_lessons.db")
TIMEZONE  = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tbilisi"))

if not TOKEN or not ADMIN_IDS:
    raise RuntimeError("Пожалуйста, заполните .env: TOKEN и ADMIN_IDS")

# ---------------- Настройка TeleBot ----------------
bot = telebot.TeleBot(TOKEN)
bot.remove_webhook()  # сброс старых webhooks

# ---------------- Инициализация БД ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        fullname TEXT,
        phone TEXT,
        teacher TEXT,
        date TEXT,
        time TEXT,
        status TEXT DEFAULT 'pending',
        reminder_sent INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------- Хранилище промежуточных данных ----------------
user_data = {}

# ---------------- Главное меню ----------------
def show_main_menu(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add('📝 Записаться на урок', 'Моя запись', '📞 Контакты')
    bot.send_message(chat_id, "Привет! Выберите действие:", reply_markup=kb)

@bot.message_handler(commands=['start'])
def cmd_start(msg):
    show_main_menu(msg.chat.id)

# ---------------- Контакты ----------------
@bot.message_handler(func=lambda m: m.text == '📞 Контакты')
def show_contacts(msg):
    text = (
        "<b>Контакты:</b>\n"
        "📞 Телефон: +995 123 456 789\n"
        "✉️ Email: example@joolay.vocal\n"
        "\n🔴🔴🔴🔴🔴🔴🔴🔴🔴\n\n"
        "<b>Преподаватели:</b>\n"
        " • <b>Юля</b>\n"
        " • <b>Торнике</b>\n\n"
        "<b>Адрес:</b>\n"
        "Joolay Vocal Studio\n"
        "2/7, Zaarbriuken Square, Tbilisi\n"
        "📍 <a href=\"https://maps.app.goo.gl/XtXSVWX2exaRmHpp9\">Посмотреть на карте</a>"
    )
    bot.send_message(
        msg.chat.id, text,
        parse_mode='HTML',
        disable_web_page_preview=True,
        reply_markup=types.ReplyKeyboardRemove()
    )
    # вернём меню после показа
    show_main_menu(msg.chat.id)

# ---------------- Бронирование урока ----------------
@bot.message_handler(func=lambda m: m.text == '📝 Записаться на урок')
def choose_teacher(msg):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton('Юля', callback_data='select_teacher:Юля'),
        types.InlineKeyboardButton('Торнике', callback_data='select_teacher:Торнике')
    )
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back'))
    bot.send_message(msg.chat.id, "Выберите преподавателя:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'back')
def cb_back(c):
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, None)
    show_main_menu(c.message.chat.id)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('select_teacher:'))
def cb_select_teacher(c):
    teacher = c.data.split(':',1)[1]
    uid = c.from_user.id
    user_data[uid] = {'teacher': teacher}
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, None)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    m = bot.send_message(c.message.chat.id, "Введите ваше ФИО:", reply_markup=kb)
    bot.answer_callback_query(c.id)
    bot.register_next_step_handler(m, process_name)

def process_name(msg):
    if msg.text == '↩️ Назад':
        return show_main_menu(msg.chat.id)
    uid = msg.from_user.id
    user_data[uid]['fullname'] = msg.text.strip()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    m = bot.send_message(
        msg.chat.id,
        "Оставьте ваш контакт TG или любой удобный контакт:",
        reply_markup=kb
    )
    bot.register_next_step_handler(m, process_phone)

def process_phone(msg):
    if msg.text == '↩️ Назад':
        return show_main_menu(msg.chat.id)
    uid = msg.from_user.id
    user_data[uid]['phone'] = msg.text.strip()
    send_date_selection(msg)

def send_date_selection(msg):
    today = datetime.now(TIMEZONE).date()
    kb = types.InlineKeyboardMarkup(row_width=4)
    for d in range(14):
        day = today + timedelta(days=d)
        if 1 <= day.weekday() <= 4:  # вт–пт
            kb.add(types.InlineKeyboardButton(
                day.strftime('%d/%m'),
                callback_data=f"select_date:{day.isoformat()}"
            ))
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back'))
    bot.send_message(msg.chat.id, "Выберите дату:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('select_date:'))
def cb_select_date(c):
    if c.data == 'back':
        return cb_back(c)
    date_iso = c.data.split(':',1)[1]
    uid = c.from_user.id
    user_data[uid]['date'] = date_iso
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, None)
    kb = types.InlineKeyboardMarkup(row_width=4)
    for hour in range(14, 23):
        slot = f"{hour:02d}:00"
        kb.add(types.InlineKeyboardButton(slot, callback_data=f"select_time:{slot}"))
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back'))
    bot.send_message(c.message.chat.id, "Выберите время:", reply_markup=kb)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('select_time:'))
def cb_select_time(c):
    if c.data == 'back':
        return cb_back(c)
    slot = c.data.split(':',1)[1]
    uid = c.from_user.id
    user_data[uid]['time'] = slot
    finalize_appointment(c.message)

def finalize_appointment(msg):
    uid = msg.chat.id
    d = user_data.get(uid, {})
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("""
        INSERT INTO appointments
        (user_id, fullname, phone, teacher, date, time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (uid, d['fullname'], d['phone'], d['teacher'], d['date'], d['time']))
    appt_id = cur.lastrowid
    conn.commit(); conn.close()

    bot.send_message(uid, "Ваша заявка отправлена. Ожидайте подтверждения.",
                     reply_markup=types.ReplyKeyboardRemove())

    text = (f"Новая заявка #{appt_id}\n"
            f"Ученик: {d['fullname']}\n"
            f"Контакт: {d['phone']}\n"
            f"Преподаватель: {d['teacher']}\n"
            f"Дата: {d['date']} в {d['time']}")
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton('✅ Одобрить', callback_data=f"admin_approve:{appt_id}"),
        types.InlineKeyboardButton('❌ Отклонить',  callback_data=f"admin_reject:{appt_id}")
    )
    for aid in ADMIN_IDS:
        bot.send_message(aid, text, reply_markup=kb)

# ---------------- Обработка админских кнопок ----------------
@bot.callback_query_handler(func=lambda c: c.data.startswith('admin_'))
def process_admin_decision(call: types.CallbackQuery):
    action, appt_id = call.data.split(':',1)
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT user_id, date, time FROM appointments WHERE id = ?", (appt_id,))
    row = cur.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "❌ Запись не найдена.")
        conn.close()
        return
    user_id, date_iso, time_slot = row
    if action == 'admin_approve':
        cur.execute("UPDATE appointments SET status='approved' WHERE id = ?", (appt_id,))
        conn.commit()
        bot.send_message(user_id, f"✅ Ваша запись на {date_iso} в {time_slot} подтверждена.")
        bot.answer_callback_query(call.id, "Запись одобрена.")
    else:
        cur.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        conn.commit()
        bot.send_message(user_id, "❌ Ваша запись отклонена.")
        bot.answer_callback_query(call.id, "Запись отклонена.")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    conn.close()

# ---------------- Напоминания и очистка ----------------
def send_reminders():
    now = datetime.now(TIMEZONE)
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("""
        SELECT id, fullname, teacher, date, time
          FROM appointments
         WHERE status='approved' AND reminder_sent=0
    """)
    for appt_id, fullname, teacher, date_iso, time_slot in cur.fetchall():
        dt = datetime.fromisoformat(f"{date_iso}T{time_slot}").replace(tzinfo=TIMEZONE)
        if 0 <= (dt - now).total_seconds() <= 3600:
            text = (f"⏰ Напоминание: урок #{appt_id}\n"
                    f"Ученик: {fullname}\nПреподаватель: {teacher}\n"
                    f"Время: {date_iso} {time_slot}")
            for aid in ADMIN_IDS:
                bot.send_message(aid, text)
            cur.execute("UPDATE appointments SET reminder_sent=1 WHERE id = ?", (appt_id,))
    conn.commit(); conn.close()

def clean_past_appointments():
    cutoff = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("""
        DELETE FROM appointments
         WHERE status='approved'
           AND datetime(date || ' ' || time) < ?
    """, (cutoff,))
    conn.commit(); conn.close()

# ---------------- Запуск планировщика и polling ----------------
if __name__ == '__main__':
    sched = BackgroundScheduler(timezone=TIMEZONE)
    sched.add_job(send_reminders, 'interval', minutes=1)
    sched.add_job(clean_past_appointments, 'cron', hour=0, minute=0)
    sched.start()

    # сбросим вебхук, чтобы точно работать через getUpdates
    bot.delete_webhook()

    # непрерывный polling с защитой от ошибок 409 и любых других
    while True:
        try:
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60,
                skip_pending=True,
                non_stop=True
            )
        except Exception:
            logging.exception("Polling упало, перезапускаем через 1 сек…")
            time.sleep(1)
