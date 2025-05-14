from dotenv import load_dotenv
load_dotenv()  # Загрузка .env

import os
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

# --- Мини-веб-сервер для health checks (Render Web Service) ---
app = Flask(__name__)

@app.route("/")
def ping():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web, daemon=True).start()

# ---------------- ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ----------------
TOKEN     = os.getenv("TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DB_PATH   = os.getenv("DB_PATH", "vocal_lessons.db")
TIMEZONE  = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tbilisi"))

if not TOKEN or not ADMIN_IDS:
    raise RuntimeError("Пожалуйста, заполните .env: TOKEN и ADMIN_IDS")

# ---------------- TELEBOT SETUP ----------------
bot = telebot.TeleBot(TOKEN)
bot.remove_webhook()  # Сбрасываем старые webhooks, если были

# ---------------- ИНИЦИАЛИЗАЦИЯ БАЗЫ ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
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

# ---------------- ХРАНИЛИЩЕ ДЛЯ ДИАЛОГА ----------------
user_data = {}

# ---------------- ФУНКЦИИ МЕНЮ ----------------
def show_main_menu(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add('📝 Записаться на урок', 'Моя запись', '📞 Контакты', '↩️ Назад')
    bot.send_message(chat_id, "Привет! Выберите действие:", reply_markup=kb)

# ---------------- ОБРАБОТЧИКИ ----------------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    show_main_menu(message.chat.id)

@bot.message_handler(func=lambda m: m.text == '↩️ Назад')
def handle_back(message):
    show_main_menu(message.chat.id)

# Запись на урок
@bot.message_handler(func=lambda m: m.text == '📝 Записаться на урок')
def choose_teacher(message):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton('Юля', callback_data='select_teacher:Юля'),
        types.InlineKeyboardButton('↩️ Назад', callback_data='back')
    )
    bot.send_message(message.chat.id, "Выберите преподавателя:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'back')
def cb_back(call):
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, None)
    show_main_menu(call.message.chat.id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('select_teacher:'))
def cb_select_teacher(call):
    teacher = call.data.split(':',1)[1]
    uid = call.from_user.id
    user_data[uid] = {'teacher': teacher}
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, None)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    msg = bot.send_message(call.message.chat.id, "Введите ваше ФИО:", reply_markup=kb)
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler(msg, process_name)

def process_name(message):
    if message.text == '↩️ Назад':
        return handle_back(message)
    uid = message.from_user.id
    user_data[uid]['fullname'] = message.text.strip()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    msg = bot.send_message(
        message.chat.id,
        "Оставьте ваш контакт TG или любой удобный контакт:",
        reply_markup=kb
    )
    bot.register_next_step_handler(msg, process_phone)

def process_phone(message):
    if message.text == '↩️ Назад':
        return handle_back(message)
    uid = message.from_user.id
    user_data[uid]['phone'] = message.text.strip()
    send_date_selection(message)

def send_date_selection(message):
    today = datetime.now(TIMEZONE).date()
    kb = types.InlineKeyboardMarkup(row_width=4)
    for d in range(14):
        day = today + timedelta(days=d)
        if 1 <= day.weekday() <= 4:  # вт–пт
            kb.add(
                types.InlineKeyboardButton(
                    day.strftime('%d/%m'),
                    callback_data=f"select_date:{day.isoformat()}"
                )
            )
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back'))
    bot.send_message(message.chat.id, "Выберите дату:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('select_date:'))
def cb_select_date(call):
    if call.data == 'back':
        return cb_back(call)
    date_iso = call.data.split(':',1)[1]
    uid = call.from_user.id
    user_data[uid]['date'] = date_iso
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, None)
    kb = types.InlineKeyboardMarkup(row_width=4)
    for hour in range(14, 23):
        slot = f"{hour:02d}:00"
        kb.add(types.InlineKeyboardButton(slot, callback_data=f"select_time:{slot}"))
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back'))
    bot.send_message(call.message.chat.id, "Выберите время:", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('select_time:'))
def cb_select_time(call):
    if call.data == 'back':
        return cb_back(call)
    time_slot = call.data.split(':',1)[1]
    uid = call.from_user.id
    user_data[uid]['time'] = time_slot
    finalize_appointment(call.message)

# Сохранение и уведомление
def finalize_appointment(message):
    uid = message.chat.id
    data = user_data.get(uid, {})
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO appointments
      (user_id, fullname, phone, teacher, date, time)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        uid,
        data.get('fullname',''),
        data.get('phone',''),
        data.get('teacher',''),
        data.get('date',''),
        data.get('time','')
    ))
    appt_id = cursor.lastrowid
    conn.commit()
    conn.close()

    bot.send_message(
        uid,
        "Ваша заявка отправлена. Ожидайте подтверждения.",
        reply_markup=types.ReplyKeyboardRemove()
    )

    # Уведомление админам
    text = (
        f"Новая заявка #{appt_id}\n"
        f"Ученик: {data.get('fullname')}\n"
        f"Контакт: {data.get('phone')}\n"
        f"Преподаватель: {data.get('teacher')}\n"
        f"Дата: {data.get('date')} в {data.get('time')}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton('✅ Одобрить', callback_data=f"admin_approve:{appt_id}"),
        types.InlineKeyboardButton('❌ Отклонить', callback_data=f"admin_reject:{appt_id}")
    )
    for aid in ADMIN_IDS:
        bot.send_message(aid, text, reply_markup=kb)

# Админ-решения и остальные handlers…
# (Здесь нужно вставить остальной код из предыдущей версии —
#  approve/reject, my appointments, cancel flow, reminders, cleanup)

# ------- ПРАВИЛЬНЫЙ ЗАПУСК -------
if __name__ == '__main__':
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(send_reminders, 'interval', minutes=1)
    scheduler.add_job(clean_past_appointments, 'cron', hour=0, minute=0)
    scheduler.start()
    bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)

