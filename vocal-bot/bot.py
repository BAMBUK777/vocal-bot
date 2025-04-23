import os
import json
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("BOT_TOKEN")
DATA_FOLDER = 'data'
SCHEDULE_FILE = os.path.join(DATA_FOLDER, 'schedule.json')
DAYS = ['Вторник', 'Среда', 'Четверг', 'Пятница']
HOURS = ['15:00', '16:00', '17:00', '18:00', '19:00', '20:00']

bot = telebot.TeleBot(TOKEN)

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

@bot.message_handler(commands=['start'])
def handle_start(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📅 Записаться", callback_data="book"))
    markup.add(InlineKeyboardButton("👀 Моя запись", callback_data="view"))
    markup.add(InlineKeyboardButton("❌ Отменить запись", callback_data="cancel"))
    bot.send_message(message.chat.id, "Привет! Я бот для записи на вокал к Юле. Выберите действие:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = str(call.from_user.id)

    if call.data == 'book':
        existing_day, _ = get_user_record(user_id)
        if existing_day:
            bot.answer_callback_query(call.id, "У вас уже есть запись.")
            return
        markup = InlineKeyboardMarkup()
        for day in DAYS:
            markup.add(InlineKeyboardButton(day, callback_data=f"day_{day}"))
        bot.edit_message_text("Выберите день:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data.startswith("day_"):
        selected_day = call.data.split("_")[1]
        markup = InlineKeyboardMarkup()
        for hour in HOURS:
            if not is_slot_taken(selected_day, hour):
                markup.add(InlineKeyboardButton(hour, callback_data=f"time_{selected_day}_{hour}"))
        if markup.keyboard:
            bot.edit_message_text(f"Выберите время на {selected_day}:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        else:
            bot.edit_message_text(f"На {selected_day} нет свободных слотов.", call.message.chat.id, call.message.message_id)

    elif call.data.startswith("time_"):
        _, day, hour = call.data.split("_")
        msg = bot.send_message(call.message.chat.id, f"Вы выбрали {day}, {hour}. Введите своё имя:")
        bot.register_next_step_handler(msg, finalize_booking, day, hour, user_id)

    elif call.data == 'view':
        day, hour = get_user_record(user_id)
        if day:
            name = schedule_data[day][hour]['name']
            bot.answer_callback_query(call.id, show_alert=True, text=f"Ваша запись:\n{day}, {hour}\nИмя: {name}")
        else:
            bot.answer_callback_query(call.id, text="У вас нет активной записи.")

    elif call.data == 'cancel':
        if cancel_booking(user_id):
            bot.answer_callback_query(call.id, text="Запись отменена.")
        else:
            bot.answer_callback_query(call.id, text="У вас не было записи.")

def finalize_booking(message, day, hour, user_id):
    name = message.text.strip()
    book_slot(day, hour, user_id, name)
    bot.send_message(message.chat.id, f"✅ Вы записаны на {day} в {hour} как {name}.")

bot.infinity_polling()
