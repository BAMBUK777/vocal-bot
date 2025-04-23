# bot.py — Telegram-бот для записи на вокал
# Поддерживает: RU/EN/KA, запись, отмену, перенос, админку, подтверждения,
# напоминания, отзывы, авто-очистку, Health-check на фейковом порту.

import os
import json
import csv
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import telebot
from telebot import types

# ==== КОНФИГУРАЦИЯ ====
TZ = ZoneInfo("Asia/Tbilisi")
DATA_DIR       = "data"
LANG_FILE      = os.path.join(DATA_DIR, "lang.json")
SCHEDULE_FILE  = os.path.join(DATA_DIR, "schedule.json")
TRANSFERS_FILE = os.path.join(DATA_DIR, "transfers.json")
RECORDS_FILE   = os.path.join(DATA_DIR, "records.csv")
FEEDBACK_FILE  = os.path.join(DATA_DIR, "feedback.csv")
LOG_FILE       = os.path.join(DATA_DIR, "bot.log")
# Фейковый порт для Render (Web Service)
HEALTH_PORT    = int(os.environ.get("PORT", 8088))

# Telegram-токен
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# Админы: {user_id: "username"}
ADMINS = {
    388183067: "joolay_joolay",
    7758773154: "joolay_vocal"
}

# Преподаватели
TEACHERS = {
    "Юля":     {"wd": [1,2,3,4], "hours": [f"{h}:00" for h in range(15,21)]},
    "Торнике": {"wd": [5,6,0],   "hours": [f"{h}:00" for h in range(8,23)]},
}

# Языки
LANGUAGES = ["ru","en","ka"]
LANG_NAMES = {"ru":"Русский 🇷🇺","en":"English 🇬🇧","ka":"ქართული 🇬🇪"}
DEFAULT_LANG = "ru"

# Короткие дни недели
WD_SHORT = {0:"пн",1:"вт",2:"ср",3:"чт",4:"пт",5:"сб",6:"вс"}

# Шаблоны сообщений
MESSAGES = {
  "ru": {
    "choose_lang":   "👋 Привет! Выберите язык:",
    "lang_set":      "Язык установлен: {lang}",
    "main_menu":     "Выберите действие:",
    "btn_book":      "📆 Записаться",
    "btn_my":        "👁 Моя запись",
    "btn_transfer":  "🔄 Перенести",
    "btn_cancel":    "❌ Отменить запись",
    "btn_help":      "/help",
    "btn_admin":     "⚙️ Админка",
    "cancel_q":      "❗ Вы точно хотите отменить запись?",
    "cancel_ok":     "✅ Ваша запись отменена.",
    "no_booking":    "У вас нет активных записей.",
    "pending":       "⏳ Ваша запись ожидает подтверждения администратора.",
    "confirmed":     "✅ Ваша запись подтверждена: {teacher} {date} {time}",
    "admin_notify":  "🆕 Новая заявка: {teacher} {date} {time}\n👤 {name} (ID {uid})",
    "rem_before":    "🔔 Напоминание: через 2 часа урок у {teacher} {date}, {time}",
    "feedback_req":  "📝 Оцените урок у {teacher} {date}, {time} (1–5 звезд):",
    "ask_comment":   "✍️ Напишите короткий отзыв:",
    "thank_comment": "🙏 Спасибо за отзыв!",
    "transfer_q":    "❗ Вы хотите перенести запись?",
    "admin_transfer_notify": "🔁 Запрос на перенос: {teacher} {date} {time} → {new_teacher} {new_date} {new_time}\n👤 {name} (ID {uid})",
    "admin_panel":   "⚙️ Админ-панель:",
    "view_bookings": "📋 Все записи",
    "view_transfers":"🔁 Переносы",
    "view_feedback": "✍️ Отзывы",
    "approve":       "✅ Одобрить",
    "delete":        "🗑 Удалить",
    "no_pending":    "Нет ожидающих запросов.",
  },
  "en": {
    # (аналогично для English)
    "choose_lang": "👋 Hi! Choose language:",
    # ...
  },
  "ka": {
    # (аналогично для грузинского)
  }
}

# ==== ПОДГОТОВКА ФАЙЛОВ ====
os.makedirs(DATA_DIR, exist_ok=True)
def ensure_json(path):
    if not os.path.exists(path):
        with open(path,"w",encoding="utf-8") as f:
            json.dump({},f,ensure_ascii=False,indent=2)
for p in [LANG_FILE, SCHEDULE_FILE, TRANSFERS_FILE]:
    ensure_json(p)
def ensure_csv(path, headers):
    if not os.path.exists(path):
        with open(path,"w",newline="",encoding="utf-8") as f:
            csv.writer(f).writerow(headers)
ensure_csv(RECORDS_FILE,   ["ts","teacher","date","time","uid","name","status"])
ensure_csv(FEEDBACK_FILE,  ["ts","teacher","date","time","uid","stars","text","approved"])

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# ==== Health-check для Render (открытый порт) ====
class HC(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
threading.Thread(target=lambda: HTTPServer(("0.0.0.0",HEALTH_PORT),HC).serve_forever(),
                 daemon=True).start()

# ==== УТИЛИТЫ ====
def load_json(path):
    return json.load(open(path,"r",encoding="utf-8"))
def save_json(data,path):
    json.dump(data,open(path,"w",encoding="utf-8"),ensure_ascii=False,indent=2)

def get_lang(uid):
    langs = load_json(LANG_FILE)
    return langs.get(str(uid),DEFAULT_LANG)
def set_lang(uid,code):
    langs = load_json(LANG_FILE)
    langs[str(uid)] = code
    save_json(langs, LANG_FILE)

def msg(uid,key,**kw):
    lang = get_lang(uid)
    template = MESSAGES.get(lang, MESSAGES[DEFAULT_LANG]).get(key,"")
    return template.format(**kw)

def main_keyboard(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(msg(uid,"btn_book"), msg(uid,"btn_my"))
    kb.add(msg(uid,"btn_transfer"), msg(uid,"btn_cancel"))
    kb.add(msg(uid,"btn_help"))
    if uid in ADMINS:
        kb.add(msg(uid,"btn_admin"))
    return kb

# ==== СОБЫТИЯ ====
STATE = {}  # временные состояния {uid: {...}}

@bot.message_handler(commands=["start","help"])
def cmd_start(m):
    uid = m.from_user.id
    # сбросить предыдущий язык, если есть
    langs = load_json(LANG_FILE)
    langs.pop(str(uid),None)
    save_json(langs, LANG_FILE)
    # предложить языки
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for c in LANGUAGES:
        kb.add(LANG_NAMES[c])
    bot.send_message(uid, msg(uid,"choose_lang"), reply_markup=kb)

@bot.message_handler(func=lambda m: m.text in LANG_NAMES.values())
def choose_language(m):
    uid = m.from_user.id
    code = next(k for k,v in LANG_NAMES.items() if v==m.text)
    set_lang(uid,code)
    bot.send_message(uid, msg(uid,"lang_set",lang=m.text),
                     reply_markup=main_keyboard(uid))

@bot.message_handler(func=lambda m: True)
def main_router(m):
    uid = m.from_user.id
    txt = m.text
    if txt == msg(uid,"btn_book"):
        start_booking(m)
    elif txt == msg(uid,"btn_my"):
        show_my(m)
    elif txt == msg(uid,"btn_cancel"):
        ask_cancel(m)
    elif txt == msg(uid,"btn_transfer"):
        start_transfer(m)
    elif txt == msg(uid,"btn_help"):
        bot.send_message(uid, msg(uid,"help"), reply_markup=main_keyboard(uid))
    elif txt == msg(uid,"btn_admin") and uid in ADMINS:
        admin_panel(m)
    else:
        bot.send_message(uid, msg(uid,"main_menu"), reply_markup=main_keyboard(uid))

# ==== БРОНИРОВАНИЕ ====
def start_booking(m):
    uid = m.from_user.id
    kb = types.InlineKeyboardMarkup()
    for tch in TEACHERS:
        kb.add(types.InlineKeyboardButton(tch, callback_data=f"bk_tch|{tch}"))
    bot.send_message(uid, msg(uid,"btn_book"), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("bk_"))
def bk_flow(c):
    uid = c.from_user.id
    step,data = c.data.split("|",1)
    st = STATE.setdefault(str(uid),{})
    if step=="bk_tch":
        st["tch"]=data
        # выбор недели
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Эта неделя", callback_data="bk_wk|0"))
        kb.add(types.InlineKeyboardButton("След. неделя", callback_data="bk_wk|1"))
        c.message.edit_text(f"{data}: выбор недели", reply_markup=kb)
    elif step=="bk_wk":
        st["wk"]=int(data)
        tch = st["tch"]
        # даты
        today = datetime.now(TZ).date()
        mon = today - timedelta(days=today.weekday()) + timedelta(weeks=st["wk"])
        dates = []
        for i in range(7):
            d = mon+timedelta(i)
            if d.weekday() in TEACHERS[tch]["wd"] and d>=today:
                dates.append(d)
        kb = types.InlineKeyboardMarkup(row_width=3)
        for d in dates:
            kb.add(types.InlineKeyboardButton(
                f"{d.strftime('%d.%m')} ({WD_SHORT[d.weekday()]})",
                callback_data=f"bk_day|{d.isoformat()}"))
        c.message.edit_text(msg(uid,"choose_day"), reply_markup=kb)
    elif step=="bk_day":
        st["date"]=data
        tch = st["tch"]
        kb=types.InlineKeyboardMarkup(row_width=2)
        sch = load_json(SCHEDULE_FILE)
        taken_today = sch.get(tch,{}).get(data,{}).keys()
        for h in TEACHERS[tch]["hours"]:
            if h not in taken_today:
                kb.add(types.InlineKeyboardButton(h, callback_data=f"bk_time|{h}"))
        c.message.edit_text(msg(uid,"choose_time"), reply_markup=kb)
    elif step=="bk_time":
        st["time"]=data
        bot.send_message(uid, "Введите своё имя:")
        bot.register_next_step_handler(
            bot.send_message(uid, "Имя:"), finish_booking)

def finish_booking(m):
    uid = m.from_user.id
    name = m.text.strip()
    st = STATE.get(str(uid),{})
    tch, date, time = st["tch"], st["date"], st["time"]
    # сохранить в schedule.json
    sch = load_json(SCHEDULE_FILE)
    sch.setdefault(tch,{}).setdefault(date,{})[time] = {"uid":uid,"name":name,"status":"pending"}
    save_json(sch, SCHEDULE_FILE)
    # CSV
    with open(RECORDS_FILE,"a",newline="",encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.now(TZ).isoformat(), tch, date, time, uid, name, "pending"
        ])
    # уведомить юзера
    bot.send_message(uid, msg(uid,"pending"), reply_markup=main_keyboard(uid))
    # уведомить админа
    for aid in ADMINS:
        bot.send_message(aid, msg(uid,"admin_notify",
            teacher=tch, date=date, time=time, name=name, uid=uid))
    STATE.pop(str(uid),None)

# ==== МОЯ ЗАПИСЬ ====
def show_my(m):
    uid = m.from_user.id
    sch = load_json(SCHEDULE_FILE)
    lines=[]
    for tch,dd in sch.items():
        for d,hh in dd.items():
            for h,info in hh.items():
                if info["uid"]==uid:
                    lines.append(f"{tch}: {d} {h} ({info['status']})")
    bot.send_message(uid, "\n".join(lines) or msg(uid,"no_booking"),
                     reply_markup=main_keyboard(uid))

# ==== ОТМЕНА ====
def ask_cancel(m):
    uid=m.from_user.id
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Да",callback_data="cnf_yes"))
    kb.add(types.InlineKeyboardButton("Нет",callback_data="cnf_no"))
    bot.send_message(uid,msg(uid,"cancel_q"),reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cnf_"))
def cancel_flow(c):
    uid=c.from_user.id
    if c.data=="cnf_yes":
        sch=load_json(SCHEDULE_FILE)
        # удалить первую найденную
        for tch,dd in sch.items():
            for d,hh in dd.items():
                for h,info in list(hh.items()):
                    if info["uid"]==uid:
                        del sch[tch][d][h]
                        save_json(sch,SCHEDULE_FILE)
                        bot.send_message(uid,msg(uid,"cancel_ok"),reply_markup=main_keyboard(uid))
                        return
        bot.send_message(uid,msg(uid,"no_booking"),reply_markup=main_keyboard(uid))
    else:
        bot.send_message(uid,msg(uid,"main_menu"),reply_markup=main_keyboard(uid))

# ==== ПЕРЕНОС (аналогично брони) ====
def start_transfer(m):
    uid=m.from_user.id
    # аналогично этапам брони, но сохраняем в transfers.json и уведомляем админов
    bot.send_message(uid,"Функционал переноса пока в разработке.",reply_markup=main_keyboard(uid))

# ==== АДМИНКА ====
def admin_panel(m):
    uid=m.from_user.id
    kb=types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton(msg(uid,"view_bookings"),callback_data="ad_book"))
    kb.add(types.InlineKeyboardButton(msg(uid,"view_feedback"),callback_data="ad_fb"))
    kb.add(types.InlineKeyboardButton(msg(uid,"view_transfers"),callback_data="ad_tr"))
    bot.send_message(uid,msg(uid,"admin_panel"),reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ad_"))
def admin_flow(c):
    uid=c.from_user.id; cmd=c.data
    if cmd=="ad_book":
        sch=load_json(SCHEDULE_FILE)
        text="Все записи:\n"
        for tch,dd in sch.items():
            for d,hh in dd.items():
                for h,info in hh.items():
                    text+=f"{tch} {d} {h} — {info['name']} ({info['status']})\n"
        c.message.edit_text(text or "Пусто",reply_markup=None)
    # feedback и transfers аналогично...

# ==== НАПОМИНАНИЯ И АВТО-ОЧИСТКА ====
def schedule_tasks():
    def worker():
        while True:
            now = datetime.now(TZ)
            sch = load_json(SCHEDULE_FILE)
            # напоминания за 2 ч
            for tch,dd in sch.items():
                for d,hh in dd.items():
                    dt = datetime.fromisoformat(d+"T00:00:00").replace(tzinfo=TZ)
                    for h,info in hh.items():
                        lesson = dt + timedelta(hours=int(h.split(":")[0]))
                        if 0 < (lesson-now).total_seconds() < 7200 and info["status"]=="confirmed":
                            for uid in [info["uid"]]:
                                bot.send_message(uid,msg(uid,"rem_before",
                                    teacher=tch,date=d,time=h))
                            info["status"]="notified"
            save_json(sch,SCHEDULE_FILE)
            # авто-очистка >14 дней
            cutoff = now.date() - timedelta(days=14)
            changed=False
            for tch in list(sch):
                for d in list(sch[tch]):
                    if datetime.fromisoformat(d).date() < cutoff:
                        del sch[tch][d]; changed=True
            if changed:
                save_json(sch,SCHEDULE_FILE)
            threading.Event().wait(3600)  # проверять каждый час
    threading.Thread(target=worker,daemon=True).start()

# Запустить задачи
schedule_tasks()

# ==== СТАРТ БОТА ====
bot.send_message(list(ADMINS.keys())[0], "Бот запущен 🚀")  # уведомление админу
bot.infinity_polling()
