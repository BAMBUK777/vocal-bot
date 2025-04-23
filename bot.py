import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ————— health check server —————
PORT = int(os.environ.get("PORT", 8000))
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
def run_health_server():
    HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()
threading.Thread(target=run_health_server, daemon=True).start()
# ————— конец health check —————

TOKEN = os.getenv("BOT_TOKEN")
# … остальной код без изменений …




# === НАСТРОЙКИ ===
TOKEN = os.getenv("BOT_TOKEN")
DATA_FOLDER = 'data'
SCHEDULE_FILE = os.path.join(DATA_FOLDER, 'schedule.json')
DAYS = ['Вторник', 'Среда', 'Четверг', 'Пятница']
HOURS = ['15:00', '16:00', '17:00', '18:00', '19:00', '20:00']

# Администраторы (чужие запросы игнорим)
ADMINS = {
    388183067: 'joolay_joolay',
    7758773154: 'joolay_vocal'
}

bot = telebot.TeleBot(TOKEN)

# === ЗАГРУЗКА И СОХРАНЕНИЕ ===
if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_schedule(schedule):
    with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
        json.dump(schedule, f, ensure_ascii=False, indent=4)

schedule_data = load_schedule()

# === ХЭЛПЕРЫ ===
def get_user_record(user_id):
    for day in schedule_data:
        for hour in schedule_data[day]:
            if schedule_data[day][hour]['user_id'] == user_id:
                return day, hour
    return None, None

def is_slot_taken(day, hour):
    return day in schedule_data and hour in schedule_data[day]

def book_slot(day, hour, user_id, name):
    if day not in schedule_data:
        schedule_data[day] = {}
    schedule_data[day][hour] = {'user_id': user_id, 'name': name}
    save_schedule(schedule_data)

def cancel_booking(user_id):
    for day in list(schedule_data.keys()):
        for hour in list(schedule_data[day].keys()):
            if schedule_data[day][hour]['user_id'] == user_id:
                del schedule_data[day][hour]
                if not schedule_data[day]:
                    del schedule_data[day]
                save_schedule(schedule_data)
                return True
    return False

def format_schedule(day=None):
    # возвращает текстовую строку с расписанием
    data = schedule_data if day is None else {day: schedule_data.get(day, {})}
    lines = []
    for d in DAYS:
        if d not in data:
            lines.append(f"🔹 *{d}* — пусто")
            continue
        lines.append(f"🔹 *{d}*")
        for h in HOURS:
            if h in data[d]:
                name = data[d][h]['name']
                lines.append(f"   • {h} — {name}")
            else:
                lines.append(f"   • {h} — _свободно_")
    return "\n".join(lines)

# === ОБЩЕЕ МЕНЮ ===
@bot.message_handler(commands=['start'])
def handle_start(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📅 Записаться", callback_data="book"))
    markup.add(InlineKeyboardButton("👀 Моя запись", callback_data="view"))
    markup.add(InlineKeyboardButton("❌ Отменить запись", callback_data="cancel"))
    if message.from_user.id in ADMINS:
        markup.add(InlineKeyboardButton("⚙️ Админка", callback_data="admin"))
    bot.send_message(message.chat.id, "Привет! Я бот для записи на вокал к Юле. Выберите действие:", reply_markup=markup, parse_mode='Markdown')

# === КНОПКИ И ЗАПИСЬ ===
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    data = call.data
    uid  = call.from_user.id

    # Сразу логируем, что пришло
    logging.info(f"Callback received: '{data}' from user {uid}")

    # === основной свитч по data ===

    # 1) Начало бронирования
    if data == "book":
        kb = InlineKeyboardMarkup()
        for tch in TEACHERS:
            kb.add(InlineKeyboardButton(tch, callback_data=f"teacher_{tch}"))
        bot.edit_message_text("Выберите преподавателя:", call.message.chat.id, call.message.message_id, reply_markup=kb)
        return

    # 2) Выбор недели
    if data.startswith("teacher_"):
        tch = data.split("_",1)[1]
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("Эта неделя",      callback_data=f"week_{tch}_0"))
        kb.add(InlineKeyboardButton("Следующая неделя", callback_data=f"week_{tch}_1"))
        bot.edit_message_text(f"Преподаватель *{tch}*. На какую неделю?", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        return

    # 3) Выбор даты
    if data.startswith("week_"):
        _, tch, w = data.split("_",2)
        dates = dates_for_teacher(tch, int(w))
        kb = InlineKeyboardMarkup(row_width=3)
        for ds in dates:
            kb.add(InlineKeyboardButton(ds, callback_data=f"date_{tch}_{ds}"))
        bot.edit_message_text("Выберите дату:", call.message.chat.id, call.message.message_id, reply_markup=kb)
        return

    # 4) Выбор времени
    if data.startswith("date_"):
        _, tch, ds = data.split("_",2)
        kb = InlineKeyboardMarkup()
        for hr in TEACHERS[tch]["hours"]:
            if not is_taken(tch, ds, hr):
                kb.add(InlineKeyboardButton(hr, callback_data=f"time_{tch}_{ds}_{hr}"))
        text = f"Преподаватель *{tch}*, дата *{ds}*.\nВыберите время:" if kb.keyboard else "Нет свободных слотов."
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=kb)
        return

    # 5) Ввод имени и финализация брони
    if data.startswith("time_"):
        _, tch, ds, hr = data.split("_",3)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        msg = bot.send_message(call.message.chat.id, f"Введите своё имя для записи на {tch}, {ds} в {hr}:")
        bot.register_next_step_handler(msg, finish_booking, tch, ds, hr, uid)
        return

    # 6) Просмотр своей брони
    if data == "view":
        tch, ds, hr = get_user_record(uid)
        if tch:
            info = schedule[tch][ds][hr]
            bot.answer_callback_query(call.id, show_alert=True, text=f"{tch} {ds} {hr} — {info['name']} ({info['status']})")
        else:
            bot.answer_callback_query(call.id, text="У вас нет брони.")
        return

    # 7) Отмена своей брони
    if data == "cancel":
        if cancel_user(uid):
            bot.answer_callback_query(call.id, text="Ваша бронь отменена.")
            logging.info(f"User {uid} cancelled their booking")
        else:
            bot.answer_callback_query(call.id, text="Нечего отменять.")
        return

    # 8) Админка — вход
    if data == "admin" and uid in ADMINS:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("📋 Все записи",           callback_data="all"))
        kb.add(InlineKeyboardButton("📅 По преподавателю",    callback_data="by_teacher"))
        bot.edit_message_text("Админка: выберите действие", call.message.chat.id, call.message.message_id, reply_markup=kb)
        return

    # 9) Подтверждение новой записи
    if data.startswith("confirm_") and uid in ADMINS:
        tch, ds, hr = data.split("_")[1:]
        schedule[tch][ds][hr]["status"] = "confirmed"
        save_schedule(schedule)
        entry = schedule[tch][ds][hr]
        bot.answer_callback_query(call.id, text="Запись подтверждена.")
        bot.send_message(entry["user_id"], MESSAGES["booking_confirmed"].format(teacher=tch, date=ds, hour=hr), parse_mode="Markdown")
        logging.info(f"Admin {uid} confirmed booking {tch} {ds} {hr}")
        return

    # 10) Ручное удаление админом
    if data.startswith("del_") and uid in ADMINS:
        tch, ds, hr = data.split("_")[1:]
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Да, удалить", callback_data=f"do_del_{tch}_{ds}_{hr}"))
        kb.add(InlineKeyboardButton("❌ Отмена",       callback_data="admin"))
        bot.send_message(call.message.chat.id, f"Удалить {tch} {ds} {hr}?", reply_markup=kb)
        return

    if data.startswith("do_del_") and uid in ADMINS:
        tch, ds, hr = data.split("_")[1:]
        del schedule[tch][ds][hr]
        if not schedule[tch][ds]: del schedule[tch][ds]
        save_schedule(schedule)
        bot.answer_callback_query(call.id, text="Удалено.")
        logging.info(f"Admin {uid} deleted booking {tch} {ds} {hr}")
        return

    # — ВАЖНО — если ни одно условие не подошло
    logging.warning(f"Unhandled callback_data: '{data}' from {uid}")
    bot.answer_callback_query(call.id, "Доступ запрещён или неизвестная команда.")

    # — админка —
    elif data == 'admin' and user_id in ADMINS:
        m = InlineKeyboardMarkup()
        m.add(InlineKeyboardButton("📋 Все записи", callback_data="all"))
        m.add(InlineKeyboardButton("📅 По дню", callback_data="byday"))
        m.add(InlineKeyboardButton("🆓 Свободные слоты", callback_data="free"))
        bot.edit_message_text("Админка: выберите действие", call.message.chat.id, call.message.message_id, reply_markup=m)

    elif data == 'all' and user_id in ADMINS:
        text = format_schedule()
        bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
        bot.answer_callback_query(call.id)

    elif data == 'byday' and user_id in ADMINS:
        m = InlineKeyboardMarkup()
        for day in DAYS:
            m.add(InlineKeyboardButton(day, callback_data=f"dayview_{day}"))
        bot.edit_message_text("Выберите день для просмотра:", call.message.chat.id, call.message.message_id, reply_markup=m)

    elif data.startswith("dayview_") and user_id in ADMINS:
        day = data.split("_",1)[1]
        text = format_schedule(day)
        bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
        bot.answer_callback_query(call.id)

    elif data == 'free' and user_id in ADMINS:
        text = format_schedule()
        # отфильтруем только свободные
        lines = []
        for line in text.split('\n'):
            if '— _свободно_' in line or line.startswith('🔹'):
                lines.append(line)
        bot.send_message(call.message.chat.id, "\n".join(lines), parse_mode='Markdown')
        bot.answer_callback_query(call.id)

    elif data.startswith("delete_") and user_id in ADMINS:
        _, day, hour = data.split("_",2)
        name = schedule_data[day][hour]['name']
        m = InlineKeyboardMarkup()
        m.add(InlineKeyboardButton("✅ Да, удалить", callback_data=f"do_delete_{day}_{hour}"))
        m.add(InlineKeyboardButton("❌ Отмена", callback_data="admin"))
        bot.send_message(call.message.chat.id,
                         f"Удалить запись?\n*{day}, {hour} — {name}*",
                         parse_mode='Markdown', reply_markup=m)

    elif data.startswith("do_delete_") and user_id in ADMINS:
        _, day, hour = data.split("_",2)
        del schedule_data[day][hour]
        if not schedule_data[day]:
            del schedule_data[day]
        save_schedule(schedule_data)
        bot.send_message(call.message.chat.id,
                         f"✅ Запись {day}, {hour} удалена.")
        bot.answer_callback_query(call.id)

    else:
        bot.answer_callback_query(call.id, "Доступ запрещён или неверная команда.")

# === ЗАВЕРШЕНИЕ БРОНИ ===
def finalize_booking(message, day, hour, user_id):
    name = message.text.strip()
    book_slot(day, hour, user_id, name)
    # уведомление пользователю
    bot.send_message(message.chat.id,
                     f"✅ Вы записаны на *{day}* в *{hour}* как *{name}*.",
                     parse_mode='Markdown')
    # уведомление администраторам
    note = (f"📝 *Новая запись!*\n"
            f"👤 {name} (ID {user_id})\n"
            f"📅 {day} {hour}")
    for adm_id in ADMINS:
        bot.send_message(adm_id, note, parse_mode='Markdown')

bot.infinity_polling()
