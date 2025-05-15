from dotenv import load_dotenv
load_dotenv()

import os
import logging
import time
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask
from threading import Thread

import telebot
from telebot import types

# ------------------- ЛОГИРОВАНИЕ -------------------
logging.basicConfig(level=logging.INFO)
telebot.logger.setLevel(logging.DEBUG)

# ------------------- HTTP SERVER для UptimeRobot -------------------
app = Flask(__name__)

@app.route("/")
def ping():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web, daemon=True).start()

# ------------------- ПЕРЕМЕННЫЕ -------------------
TOKEN = os.getenv("TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DB_URL = os.getenv("DB_URL")
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tbilisi"))

if not TOKEN or not ADMIN_IDS or not DB_URL:
    raise RuntimeError("Пожалуйста, заполните .env: TOKEN, ADMIN_IDS и DB_URL")

bot = telebot.TeleBot(TOKEN)
bot.remove_webhook()

# ------------------- ПОДКЛЮЧЕНИЕ К БАЗЕ -------------------
def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=DictCursor)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # appointments
    cur.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            fullname TEXT,
            phone TEXT,
            teacher TEXT,
            date DATE,
            time TEXT,
            status TEXT DEFAULT 'pending', -- pending, approved, cancel_requested, cancelled
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            fullname TEXT,
            last_success DATETIME
        )
    """)
    # materials
    cur.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id SERIAL PRIMARY KEY,
            title TEXT,
            url TEXT,
            category TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ------------------- МАТЕРИАЛЫ (ПРИМЕР) -------------------
def preload_materials():
    conn = get_conn()
    cur = conn.cursor()
    # Если таблица пуста — добавляем
    cur.execute("SELECT count(*) FROM materials")
    if cur.fetchone()[0] == 0:
        materials = [
            ("Видео урок: как не бояться петь", "https://youtu.be/PjETXaGWPOY?si=MyFStY9e_27UMJZ1", "video"),
            ("Видео: подготовка голоса", "https://youtu.be/yOOBTaE_pbI?si=vfcPekxvTQlO7tuv", "video"),
            ("Плейлист с упражнениями", "https://youtube.com/playlist?list=PLyYODOfmFKhfv9p2S33RpELWIMCh45Pz4&si=JZyyuFTaFaYqHT89", "video"),
            ("Статья: почему мы боимся сцены", "https://dzen.ru/a/ZOTlwIPR0RvVlv5u", "article"),
            ("Книга: Пойте как звёзды", "https://royallib.com/book/riggs_set/poyte_kak_zvyozdi.html", "book")
        ]
        for t, u, c in materials:
            cur.execute("INSERT INTO materials (title, url, category) VALUES (%s, %s, %s)", (t, u, c))
    conn.commit()
    conn.close()

preload_materials()

# ------------------- ХРАНИЛИЩЕ ВРЕМЕННЫХ ДАННЫХ -------------------
user_data = {}

# ------------------- ГЛАВНОЕ МЕНЮ -------------------
def show_main_menu(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add('📝 Записаться на урок', 'Моя запись')
    kb.add('🌈 Доп. материалы', '📞 Контакты')
    kb.add('🏠 Главное меню')
    bot.send_message(chat_id, "✨ Выберите действие:", reply_markup=kb)

@bot.message_handler(commands=['start'])
def cmd_start(msg):
    show_main_menu(msg.chat.id)

@bot.message_handler(func=lambda m: m.text == '🏠 Главное меню')
def main_menu(msg):
    show_main_menu(msg.chat.id)

# ------------------- КОНТАКТЫ -------------------
@bot.message_handler(func=lambda m: m.text == '📞 Контакты')
def show_contacts(msg):
    text = (
        "👩‍🏫 <b>Преподаватели:</b>\n"
        "• Юля\n"
        "• Торнике\n\n"
        "🏢 <b>Адрес:</b>\n"
        "Joolay Vocal Studio\n"
        "2/7, Zaarbriuken Square, Tbilisi\n"
        "📍 <a href=\"https://maps.app.goo.gl/XtXSVWX2exaRmHpp9\">На карте</a>"
    )
    bot.send_message(msg.chat.id, text, parse_mode='HTML', disable_web_page_preview=True)
    show_main_menu(msg.chat.id)

# ------------------- ЗАПИСЬ НА УРОК -------------------
@bot.message_handler(func=lambda m: m.text == '📝 Записаться на урок')
def choose_teacher(msg):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton('Юля', callback_data='teacher:Юля'))
    kb.add(types.InlineKeyboardButton('Торнике', callback_data='teacher:Торнике'))
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back_menu'))
    bot.send_message(msg.chat.id, "👩‍🏫 К кому хотите записаться?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'back_menu')
def back_menu(c):
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, None)
    show_main_menu(c.message.chat.id)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('teacher:'))
def cb_teacher(c):
    teacher = c.data.split(':', 1)[1]
    uid = c.from_user.id
    user_data[uid] = {'teacher': teacher}
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, None)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    m = bot.send_message(c.message.chat.id, "✏️ Введите ваше ФИО:", reply_markup=kb)
    bot.register_next_step_handler(m, process_name)

def process_name(msg):
    if msg.text == '↩️ Назад':
        return show_main_menu(msg.chat.id)
    uid = msg.from_user.id
    user_data[uid]['fullname'] = msg.text.strip()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    m = bot.send_message(msg.chat.id, "📱 Укажите контакт для связи (телеграм, телефон и т.д.):", reply_markup=kb)
    bot.register_next_step_handler(m, process_phone)

def process_phone(msg):
    if msg.text == '↩️ Назад':
        return show_main_menu(msg.chat.id)
    uid = msg.from_user.id
    user_data[uid]['phone'] = msg.text.strip()
    send_date_selection(msg)

def send_date_selection(msg):
    uid = msg.from_user.id
    teacher = user_data[uid]['teacher']
    today = datetime.now(TIMEZONE).date()
    kb = types.InlineKeyboardMarkup(row_width=4)
    if teacher == "Торнике":
        days = [0, 4, 5, 6]  # пн, пт, сб, вс
        work_hours = range(8, 24)
    else:
        days = [1, 2, 3, 4]  # вт, ср, чт, пт
        work_hours = range(15, 21)
    for d in range(14):
        day = today + timedelta(days=d)
        if day.weekday() in days:
            kb.add(types.InlineKeyboardButton(
                day.strftime('%d/%m'), callback_data=f"date:{day.isoformat()}"
            ))
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back_menu'))
    bot.send_message(msg.chat.id, "📅 Выберите дату:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('date:'))
def cb_date(c):
    uid = c.from_user.id
    teacher = user_data[uid]['teacher']
    date_iso = c.data.split(':', 1)[1]
    user_data[uid]['date'] = date_iso
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, None)
    kb = types.InlineKeyboardMarkup(row_width=4)
    if teacher == "Торнике":
        for hour in range(8, 24):
            slot = f"{hour:02d}:00"
            kb.add(types.InlineKeyboardButton(slot, callback_data=f"time:{slot}"))
    else:
        for hour in range(15, 21):
            slot = f"{hour:02d}:00"
            kb.add(types.InlineKeyboardButton(slot, callback_data=f"time:{slot}"))
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back_menu'))
    bot.send_message(c.message.chat.id, "⏰ Выберите время:", reply_markup=kb)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('time:'))
def cb_time(c):
    uid = c.from_user.id
    slot = c.data.split(':', 1)[1]
    user_data[uid]['time'] = slot
    finalize_appointment(c.message)

def finalize_appointment(msg):
    uid = msg.chat.id
    d = user_data.get(uid, {})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO appointments (user_id, fullname, phone, teacher, date, time)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (uid, d['fullname'], d['phone'], d['teacher'], d['date'], d['time']))
    appt_id = cur.fetchone()[0]
    conn.commit()
    # Добавляем пользователя, если нет
    cur.execute("""
        INSERT INTO users (user_id, fullname) VALUES (%s, %s)
        ON CONFLICT (user_id) DO NOTHING
    """, (uid, d['fullname']))
    conn.commit()
    conn.close()

    bot.send_message(uid, "✅ Ваша заявка отправлена! Ожидайте подтверждения.")
    text = (
        f"🎉 Новая заявка #{appt_id}\n"
        f"👤 {d['fullname']}\n"
        f"📱 {d['phone']}\n"
        f"🧑‍🏫 {d['teacher']}\n"
        f"📅 {d['date']} {d['time']}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton('✅ Одобрить', callback_data=f"admin_approve:{appt_id}"),
        types.InlineKeyboardButton('❌ Отклонить', callback_data=f"admin_reject:{appt_id}")
    )
    for aid in ADMIN_IDS:
        bot.send_message(aid, text, reply_markup=kb)
    show_main_menu(uid)

# ------------------- МОЯ ЗАПИСЬ / ОТМЕНА -------------------
@bot.message_handler(func=lambda m: m.text == 'Моя запись')
def my_appointment(msg):
    uid = msg.from_user.id
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, teacher, date, time, status FROM appointments
        WHERE user_id=%s AND status IN ('pending','approved') ORDER BY created_at DESC LIMIT 1
    """, (uid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        bot.send_message(msg.chat.id, "ℹ️ У вас нет активных записей.")
        show_main_menu(msg.chat.id)
        return
    appt_id, teacher, date, time_slot, status = row
    status_str = "⏳ Ожидает подтверждения" if status == "pending" else "✅ Подтверждена"
    kb = types.InlineKeyboardMarkup()
    if status == "approved":
        kb.add(types.InlineKeyboardButton('🚫 Запросить отмену', callback_data=f"cancel_request:{appt_id}"))
    bot.send_message(msg.chat.id, f"🗓 Ваша запись:\n\n🧑‍🏫 {teacher}\n📅 {date} {time_slot}\nСтатус: {status_str}", reply_markup=kb)
    show_main_menu(msg.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('cancel_request:'))
def cancel_request(c):
    appt_id = c.data.split(':',1)[1]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton('Да, отменить', callback_data=f"confirm_cancel:{appt_id}"))
    kb.add(types.InlineKeyboardButton('Нет, оставить', callback_data="back_menu"))
    bot.send_message(c.from_user.id, "❓ Вы уверены, что хотите отменить запись?", reply_markup=kb)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('confirm_cancel:'))
def confirm_cancel(c):
    appt_id = c.data.split(':',1)[1]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE appointments SET status='cancel_requested', updated_at=NOW() WHERE id=%s", (appt_id,))
    conn.commit()
    conn.close()
    # Отправить запрос админу
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton('✅ Подтвердить отмену', callback_data=f"admin_cancel_ok:{appt_id}"),
        types.InlineKeyboardButton('❌ Отклонить', callback_data=f"admin_cancel_no:{appt_id}")
    )
    for aid in ADMIN_IDS:
        bot.send_message(aid, f"❗️ Запрос на отмену записи #{appt_id}", reply_markup=kb)
    bot.send_message(c.from_user.id, "⏳ Запрос на отмену отправлен админу. Ждите ответа.")
    show_main_menu(c.from_user.id)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('admin_cancel_ok:') or c.data.startswith('admin_cancel_no:'))
def process_cancel_admin(c):
    appt_id = c.data.split(':',1)[1]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM appointments WHERE id=%s", (appt_id,))
    row = cur.fetchone()
    if not row:
        bot.answer_callback_query(c.id, "Запись не найдена!")
        conn.close()
        return
    user_id = row['user_id']
    if c.data.startswith('admin_cancel_ok:'):
        cur.execute("UPDATE appointments SET status='cancelled', updated_at=NOW() WHERE id=%s", (appt_id,))
        conn.commit()
        bot.send_message(user_id, "❌ Ваша запись отменена по вашему запросу.")
        bot.answer_callback_query
