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
    user_id = call.from_user.id
    data = call.data

    # — запись обычного пользователя —
    if data == 'book':
        existing_day, _ = get_user_record(user_id)
        if existing_day:
            bot.answer_callback_query(call.id, "У вас уже есть запись.")
            return
        m = InlineKeyboardMarkup()
        for day in DAYS:
            m.add(InlineKeyboardButton(day, callback_data=f"day_{day}"))
        bot.edit_message_text("Выберите день:", call.message.chat.id, call.message.message_id, reply_markup=m)

    elif data.startswith("day_"):
        day = data.split("_",1)[1]
        m = InlineKeyboardMarkup()
        for hour in HOURS:
            if not is_slot_taken(day, hour):
                m.add(InlineKeyboardButton(hour, callback_data=f"time_{day}_{hour}"))
        text = f"Выберите время на *{day}*:" if m.keyboard else f"На *{day}* нет свободных слотов."
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=m, parse_mode='Markdown')

    elif data.startswith("time_"):
        _, day, hour = data.split("_",2)
        msg = bot.send_message(call.message.chat.id, f"Вы выбрали *{day}*, {hour}.\nВведите своё имя для записи:", parse_mode='Markdown')
        bot.register_next_step_handler(msg, finalize_booking, day, hour, user_id)

    elif data == 'view':
        day, hour = get_user_record(user_id)
        if day:
            name = schedule_data[day][hour]['name']
            bot.answer_callback_query(call.id, show_alert=True, text=f"Ваша запись:\n{day}, {hour}\nИмя: {name}")
        else:
            bot.answer_callback_query(call.id, text="У вас нет активной записи.")

    elif data == 'cancel':
        if cancel_booking(user_id):
            bot.answer_callback_query(call.id, text="Ваша запись отменена.")
        else:
            bot.answer_callback_query(call.id, text="У вас не было записи.")

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
