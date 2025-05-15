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
            last_success TIMESTAMP,
            is_special BOOL DEFAULT FALSE
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
    kb.add('📝 Записаться на урок', '📋 Мои записи')
    kb.add('🌈 Доп. материалы', '📞 Контакты')
    bot.send_message(chat_id, "✨ Главное меню. Что делаем дальше?", reply_markup=kb)

# ------------------- ПРИВЕТСТВИЕ -------------------
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    text = (
        "Привет! 👋\n\n"
        "Это <b>Joolay Vocal Studio</b>. Я помогу тебе записаться на урок, посмотреть свои записи, а ещё — "
        "открою доступ к секретным материалам для своих! 😉\n\n"
        "Если что-то непонятно — просто напиши, я рядом."
    )
    bot.send_message(msg.chat.id, text, parse_mode='HTML')
    show_main_menu(msg.chat.id)

@bot.message_handler(func=lambda m: m.text == '🏠 Главное меню')
def main_menu(msg):
    show_main_menu(msg.chat.id)

# ------------------- КОНТАКТЫ -------------------
@bot.message_handler(func=lambda m: m.text == '📞 Контакты')
def show_contacts(msg):
    text = (
        "👩‍🏫 <b>Преподаватели:</b>\n"
        "• <a href=\"https://t.me/joolay_joolay\">Юля</a>\n"
        "• <a href=\"https://t.me/tornik_e\">Торнике</a>\n"
        "• <b>Марина</b> <i>(расписание в разработке)</i>\n\n"
        "🤝 <b>Вопросы/Реклама:</b> <a href=\"https://t.me/joolay_vocal\">@joolay_vocal</a> <i>[biz]</i>\n\n"
        "🏢 <b>Адрес:</b>\n"
        "Joolay Vocal Studio\n"
        "2/7, Zaarbriuken Square, Tbilisi\n"
        "📍 <a href=\"https://maps.app.goo.gl/XtXSVWX2exaRmHpp9\">На карте</a>"
    )
    bot.send_message(msg.chat.id, text, parse_mode='HTML', disable_web_page_preview=True)

# ------------------- ДОП. МАТЕРИАЛЫ (ТОЛЬКО ДЛЯ “ИЗБРАННЫХ”) -------------------
@bot.message_handler(func=lambda m: m.text == '🌈 Доп. материалы')
def show_materials(msg):
    uid = msg.from_user.id
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT is_special FROM users WHERE user_id=%s", (uid,))
    row = cur.fetchone()
    conn.close()
    if row and row['is_special']:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT title, url, category FROM materials ORDER BY id")
        materials = cur.fetchall()
        conn.close()
        if not materials:
            bot.send_message(msg.chat.id, "⏳ Раздел в разработке, скоро появятся полезные материалы.")
        else:
            text = "🎓 <b>Дополнительные материалы:</b>\n\n"
            for t, url, cat in materials:
                text += f"• <a href=\"{url}\">{t}</a>\n"
            bot.send_message(msg.chat.id, text, parse_mode='HTML', disable_web_page_preview=True)
    else:
        bot.send_message(msg.chat.id, "🌈 Этот раздел доступен только постоянным ученикам, прошедшим хотя бы 1 урок.")
    show_main_menu(msg.chat.id)

# ------------------- ЗАПИСЬ НА УРОК -------------------
@bot.message_handler(func=lambda m: m.text == '📝 Записаться на урок')
def choose_teacher(msg):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton('Юля', callback_data='teacher:Юля'))
    kb.add(types.InlineKeyboardButton('Торнике', callback_data='teacher:Торнике'))
    kb.add(types.InlineKeyboardButton('Марина (в разработке)', callback_data='teacher:Марина'))
    bot.send_message(msg.chat.id, "К какому преподавателю хочешь записаться?", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('teacher:'))
def cb_teacher(c):
    teacher = c.data.split(':', 1)[1]
    uid = c.from_user.id
    if teacher == "Марина":
        bot.answer_callback_query(c.id, "Расписание Марины скоро появится 🛠")
        return
    user_data[uid] = {'teacher': teacher}
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    m = bot.send_message(c.message.chat.id, "Как тебя зовут? (ФИО)", reply_markup=kb)
    bot.register_next_step_handler(m, process_name)

def process_name(msg):
    if msg.text == '↩️ Назад':
        return show_main_menu(msg.chat.id)
    uid = msg.from_user.id
    user_data[uid]['fullname'] = msg.text.strip()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    m = bot.send_message(msg.chat.id, "Оставь свой контакт (телега или номер):", reply_markup=kb)
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
    else:
        days = [1, 2, 3, 4]  # вт, ср, чт, пт
    for d in range(14):
        day = today + timedelta(days=d)
        if day.weekday() in days:
            kb.add(types.InlineKeyboardButton(
                day.strftime('%d/%m'), callback_data=f"date:{day.isoformat()}"
            ))
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back_menu'))
    bot.send_message(msg.chat.id, "Выбери дату:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'back_menu')
def back_menu(c):
    bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, None)
    show_main_menu(c.message.chat.id)
    bot.answer_callback_query(c.id)

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
    bot.send_message(c.message.chat.id, "Выбери время:", reply_markup=kb)
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
    # Добавляем пользователя (или обновляем ФИО)
    cur.execute("""
        INSERT INTO users (user_id, fullname) VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET fullname=EXCLUDED.fullname
    """, (uid, d['fullname']))
    conn.commit()
    conn.close()

    bot.send_message(uid, "✅ Ты записан(а) на урок! Как только админ подтвердит — пришлю напоминание за 1 час 😊")
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

# ------------------- АДМИНСКОЕ ОДОБРЕНИЕ/ОТКЛОНЕНИЕ -------------------
@bot.callback_query_handler(func=lambda c: c.data.startswith('admin_approve:') or c.data.startswith('admin_reject:'))
def process_admin_decision(c):
    data = c.data
    appt_id = data.split(':', 1)[1]

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, teacher, date, time, fullname FROM appointments WHERE id=%s", (appt_id,))
    row = cur.fetchone()
    if not row:
        bot.answer_callback_query(c.id, "Запись не найдена!")
        conn.close()
        return

    user_id, teacher, date, time_slot, fullname = row['user_id'], row['teacher'], row['date'], row['time'], row['fullname']
    if data.startswith('admin_approve:'):
        cur.execute("UPDATE appointments SET status='approved', updated_at=NOW() WHERE id=%s", (appt_id,))
        # Ставим is_special=True если первый раз проходит урок
        cur.execute("""
            UPDATE users SET is_special=TRUE WHERE user_id=%s
        """, (user_id,))
        conn.commit()
        bot.send_message(user_id, "✅ Урок подтверждён! До встречи 👋")
        bot.answer_callback_query(c.id, "Заявка одобрена.")
        # Напоминание преподавателю
        teacher_notify = {
            "Юля": 388183067,       # id чата, можно руками заменить на нужный
            "Торнике": 123456789,   # заменить на id Торнике
            "Марина": None          # пока не нужен
        }
        # Отправляем только если id указан (иначе просто не отправляем)
        tid = teacher_notify.get(teacher)
        if tid:
            t_text = (
                f"⏰ Напоминание: Через час урок!\n"
                f"Ученик: {fullname}\n"
                f"Дата: {date} {time_slot}"
            )
            bot.send_message(tid, t_text)
        # Запускаем отложенное напоминание пользователю и преподавателю за 1 час (псевдо-реализация)
        def schedule_reminder():
            appt_time = datetime.combine(date, datetime.strptime(time_slot, "%H:%M").time()).replace(tzinfo=TIMEZONE)
            now = datetime.now(TIMEZONE)
            delay = (appt_time - now - timedelta(hours=1)).total_seconds()
            if delay > 0:
                time.sleep(delay)
            try:
                bot.send_message(user_id, f"⏰ Через час твой урок у преподавателя {teacher}! Не забудь 🤗")
                if tid:
                    bot.send_message(tid, f"⏰ Через час у тебя урок с {fullname} ({date} {time_slot})")
            except Exception as ex:
                print(f"Ошибка отправки напоминания: {ex}")
        Thread(target=schedule_reminder, daemon=True).start()
    else:
        cur.execute("UPDATE appointments SET status='cancelled', updated_at=NOW() WHERE id=%s", (appt_id,))
        conn.commit()
        bot.send_message(user_id, "❌ Запись отклонена админом. Можно попробовать выбрать другое время.")
        bot.answer_callback_query(c.id, "Заявка отклонена.")
    conn.close()

# ------------------- МОИ ЗАПИСИ -------------------
@bot.message_handler(func=lambda m: m.text == '📋 Мои записи')
def my_appointments(msg):
    uid = msg.from_user.id
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, teacher, date, time, status FROM appointments
        WHERE user_id=%s ORDER BY created_at DESC LIMIT 3
    """, (uid,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        bot.send_message(msg.chat.id, "У тебя нет активных записей.")
        show_main_menu(msg.chat.id)
        return
    text = "🗓 <b>Твои ближайшие записи:</b>\n\n"
    for row in rows:
        appt_id, teacher, date, time_slot, status = row
        status_str = "⏳ Ожидает подтверждения" if status == "pending" else "✅ Подтверждена" if status == "approved" else "❌ Отменена"
        text += f"• {teacher} — {date} {time_slot} ({status_str})\n"
    bot.send_message(msg.chat.id, text, parse_mode='HTML')
    show_main_menu(msg.chat.id)

# ------------------- ОШИБКИ и СТАРТ -------------------
@bot.message_handler(func=lambda m: True)
def fallback(msg):
    show_main_menu(msg.chat.id)

if __name__ == '__main__':
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.error(f"Polling упал: {e}")
            time.sleep(3)
