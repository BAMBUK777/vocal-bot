import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import telebot
from telebot import types
from apscheduler.schedulers.background import BackgroundScheduler

# ---------------- Настройки ----------------
TOKEN = '7985388321:AAHHqwd-zQqzTJZ8sJwb2NN3mYFZ5uDAr7g'
bot = telebot.TeleBot(TOKEN)
DB_PATH = 'vocal_lessons.db'
ADMIN_IDS = [7758773154, 388183067]
TIMEZONE = ZoneInfo('Asia/Tbilisi')

# -------------- Инициализация БД --------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Базовая схема
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        date TEXT,
        time TEXT
    )
    """)
    # Миграции: добавляем нужные колонки, если их нет
    cursor.execute("PRAGMA table_info(appointments)")
    existing = [row[1] for row in cursor.fetchall()]
    migrations = {
        'fullname': "TEXT",
        'phone': "TEXT",
        'teacher': "TEXT",
        'status': "TEXT",
        'reminder_sent': "INTEGER DEFAULT 0"
    }
    for col, definition in migrations.items():
        if col not in existing:
            cursor.execute(f"ALTER TABLE appointments ADD COLUMN {col} {definition}")
    conn.commit()
    conn.close()

init_db()

# --------- Хранилище для диалога ---------
user_data = {}  # { user_id: {'teacher':..., 'fullname':..., 'phone':..., 'date':..., 'time':...} }

# --------- Утилита: главное меню ---------
def show_main_menu(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add('📝 Записаться на урок', 'Моя запись', '📞 Контакты', '↩️ Назад')
    bot.send_message(chat_id, "Привет! Выберите действие:", reply_markup=kb)

# --------- /start ---------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    show_main_menu(message.chat.id)

# --------- «Назад» (текстовая кнопка) ---------
@bot.message_handler(func=lambda m: m.text == '↩️ Назад')
def handle_back_text(message):
    show_main_menu(message.chat.id)

# --------- Поток записи на урок ---------
@bot.message_handler(func=lambda m: m.text == '📝 Записаться на урок')
def choose_teacher(message):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton('Юля', callback_data='select_teacher:Юля'),
        types.InlineKeyboardButton('↩️ Назад', callback_data='back')
    )
    bot.send_message(message.chat.id, "Выберите преподавателя:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == 'back')
def callback_back(call):
    # Убираем inline-кнопки и возвращаемся в главное меню
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    show_main_menu(call.message.chat.id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('select_teacher:'))
def process_teacher(call):
    teacher = call.data.split(':',1)[1]
    user_data[call.from_user.id] = {'teacher': teacher}
    # Очистим inline-кнопки
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    # Запросим ФИО через reply-клавиатуру с кнопкой Назад
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    msg = bot.send_message(call.message.chat.id, "Введите, пожалуйста, ваше ФИО:", reply_markup=kb)
    bot.answer_callback_query(call.id)
    bot.register_next_step_handler(msg, process_name_step)

def process_name_step(message):
    if message.text == '↩️ Назад':
        return handle_back_text(message)
    uid = message.from_user.id
    user_data[uid]['fullname'] = message.text.strip()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add('↩️ Назад')
    msg = bot.send_message(
        message.chat.id,
        "Оставьте ваш контакт TG или любой удобный контакт, по которому с вами можно связаться.",
        reply_markup=kb
    )
    bot.register_next_step_handler(msg, process_phone_step)

def process_phone_step(message):
    if message.text == '↩️ Назад':
        return handle_back_text(message)
    uid = message.from_user.id
    user_data[uid]['phone'] = message.text.strip()
    send_date_selection(message)

def send_date_selection(message):
    today = datetime.now(TIMEZONE).date()
    kb = types.InlineKeyboardMarkup(row_width=4)
    for d in range(14):
        day = today + timedelta(days=d)
        # Вторник=1 ... Пятница=4
        if 1 <= day.weekday() <= 4:
            kb.add(types.InlineKeyboardButton(
                day.strftime('%d/%m'),
                callback_data=f"select_date:{day.isoformat()}"
            ))
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back'))
    bot.send_message(
        message.chat.id,
        "Выберите дату (следующие 2 недели, вторник–пятница):",
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith('select_date:'))
def process_date_selection(call):
    if call.data == 'back':
        return callback_back(call)
    date_iso = call.data.split(':',1)[1]
    user_data[call.from_user.id]['date'] = date_iso
    # Очистим старые inline
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    # Слоты времени
    kb = types.InlineKeyboardMarkup(row_width=4)
    for hour in range(14, 23):
        slot = f"{hour:02d}:00"
        kb.add(types.InlineKeyboardButton(slot, callback_data=f"select_time:{slot}"))
    kb.add(types.InlineKeyboardButton('↩️ Назад', callback_data='back'))
    bot.send_message(call.message.chat.id, "Выберите время начала урока:", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('select_time:'))
def process_time_selection(call):
    if call.data == 'back':
        return callback_back(call)
    time_slot = call.data.split(':',1)[1]
    user_data[call.from_user.id]['time'] = time_slot
    finalize_appointment(call.message)

def finalize_appointment(message):
    uid = message.chat.id
    data = user_data.get(uid, {})
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO appointments
      (user_id, fullname, phone, teacher, date, time, status, reminder_sent)
    VALUES (?, ?, ?, ?, ?, ?, 'pending', 0)
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

    # Удаляем клавиатуру ожидания
    bot.send_message(uid,
                     "Ваша заявка отправлена на рассмотрение администратору.\n"
                     "Вы получите уведомление после подтверждения.",
                     reply_markup=types.ReplyKeyboardRemove())

    # Уведомляем админов
    text = (
        f"Новая заявка #{appt_id}\n"
        f"Ученик: {data.get('fullname')}\n"
        f"Телефон: {data.get('phone')}\n"
        f"Преподаватель: {data.get('teacher')}\n"
        f"Дата: {data.get('date')} в {data.get('time')}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton('✅ Одобрить', callback_data=f"admin_approve:{appt_id}"),
        types.InlineKeyboardButton('❌ Отклонить', callback_data=f"admin_reject:{appt_id}")
    )
    for admin_id in ADMIN_IDS:
        bot.send_message(admin_id, text, reply_markup=kb)

# --------- Обработка решения админа ---------
@bot.callback_query_handler(func=lambda c: c.data.startswith('admin_'))
def process_admin_decision(call):
    action, appt_id = call.data.split(':',1)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, date, time FROM appointments WHERE id = ?", (appt_id,))
    row = cursor.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Запись не найдена.")
        conn.close()
        return
    user_id, date_iso, time_slot = row
    if action == 'admin_approve':
        cursor.execute("UPDATE appointments SET status='approved' WHERE id = ?", (appt_id,))
        conn.commit()
        bot.send_message(user_id, f"Ваша запись на {date_iso} в {time_slot} подтверждена.")
        bot.answer_callback_query(call.id, "Запись одобрена.")
    else:
        cursor.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        conn.commit()
        bot.send_message(user_id, "К сожалению, вашу запись отклонили.")
        bot.answer_callback_query(call.id, "Запись отклонена.")
    # Убираем кнопки в чате админа
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    conn.close()

# --------- «Моя запись» и отмена ---------
@bot.message_handler(func=lambda m: m.text == 'Моя запись')
def my_appointments(message):
    uid = message.chat.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    today_iso = datetime.now(TIMEZONE).date().isoformat()
    cursor.execute("""
        SELECT id, teacher, date, time
          FROM appointments
         WHERE user_id = ? AND status = 'approved' AND date >= ?
         ORDER BY date, time
    """, (uid, today_iso))
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        bot.send_message(uid, "У вас нет активных записей.")
        return
    for appt_id, teacher, date_iso, time_slot in rows:
        text = f"#{appt_id} Преподаватель: {teacher}\nДата: {date_iso} в {time_slot}"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton('❌ Отменить запись', callback_data=f"cancel_request:{appt_id}"),
               types.InlineKeyboardButton('↩️ Назад', callback_data='back'))
        bot.send_message(uid, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('cancel_request:'))
def process_cancel_request(call):
    if call.data == 'back':
        return callback_back(call)
    appt_id = call.data.split(':',1)[1]
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton('Да, отменить', callback_data=f"cancel_confirm:{appt_id}"),
        types.InlineKeyboardButton('Нет',          callback_data='cancel_deny')
    )
    bot.send_message(call.message.chat.id, "Вы точно хотите отменить эту запись?", reply_markup=kb)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('cancel_'))
def process_cancel_confirm(call):
    data = call.data
    if data == 'cancel_deny':
        bot.send_message(call.message.chat.id, "Отмена отменена.")
        bot.answer_callback_query(call.id)
        return
    appt_id = data.split(':',1)[1]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT fullname, date, time FROM appointments WHERE id = ?", (appt_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        bot.send_message(call.message.chat.id, "Запись не найдена.")
        return
    fullname, date_iso, time_slot = row
    text = (
        f"Пользователь {fullname} просит отменить запись #{appt_id}\n"
        f"Дата: {date_iso} в {time_slot}"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton('✅ Подтвердить отмену', callback_data=f"admin_cancel_confirm:{appt_id}"),
        types.InlineKeyboardButton('❌ Отклонить запрос',   callback_data=f"admin_cancel_reject:{appt_id}")
    )
    for admin_id in ADMIN_IDS:
        bot.send_message(admin_id, text, reply_markup=kb)
    bot.send_message(call.message.chat.id, "Ваш запрос на отмену отправлен администратору.")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith('admin_cancel_'))
def process_admin_cancel(call):
    action, appt_id = call.data.split(':',1)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM appointments WHERE id = ?", (appt_id,))
    row = cursor.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "Запись не найдена.")
        conn.close()
        return
    user_id = row[0]
    if action == 'admin_cancel_confirm':
        cursor.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
        conn.commit()
        bot.send_message(user_id, "Ваша запись успешно отменена.")
        bot.answer_callback_query(call.id, "Отмена подтверждена.")
    else:
        bot.send_message(user_id, "Запрос на отмену отклонён администратором.")
        bot.answer_callback_query(call.id, "Отмена отклонена.")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    conn.close()

# --------- Контакты ---------
@bot.message_handler(func=lambda m: m.text == '📞 Контакты')
def send_contacts(message):
    show_main_menu(message.chat.id)  # очистка меню
    bot.send_message(
        message.chat.id,
        "📞 Контакты:\n"
        "@joolay_joolay (Юля)\n"
        "@joolay_vocal (Менеджер по сотрудничеству)"
    )

# --------- Напоминания и очистка старых записей ---------
def send_reminders():
    now = datetime.now(TIMEZONE)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, fullname, teacher, date, time
          FROM appointments
         WHERE status='approved' AND reminder_sent=0
    """)
    for appt_id, fullname, teacher, date_iso, time_slot in cursor.fetchall():
        dt = datetime.strptime(f"{date_iso} {time_slot}", "%Y-%m-%d %H:%M")\
                    .replace(tzinfo=TIMEZONE)
        if 0 <= (dt - now).total_seconds() <= 3600:
            text = (
                f"Напоминание: урок #{appt_id}\n"
                f"Ученик: {fullname}\n"
                f"Преподаватель: {teacher}\n"
                f"Время: {date_iso} {time_slot}"
            )
            for admin_id in ADMIN_IDS:
                bot.send_message(admin_id, text)
            cursor.execute("UPDATE appointments SET reminder_sent=1 WHERE id = ?", (appt_id,))
    conn.commit()
    conn.close()

def clean_past_appointments():
    now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM appointments
         WHERE status='approved'
           AND datetime(date || ' ' || time) < ?
    """, (now_str,))
    conn.commit()
    conn.close()

scheduler = BackgroundScheduler(timezone=TIMEZONE)
scheduler.add_job(send_reminders, 'interval', minutes=1)
scheduler.add_job(clean_past_appointments, 'cron', hour=0, minute=0)
scheduler.start()

# --------- Запуск ---------
if __name__ == '__main__':
    bot.infinity_polling()
