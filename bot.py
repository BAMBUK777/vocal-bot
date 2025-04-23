```python
# ЧАСТЬ 1 — Импорты и конфигурация

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import csv
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import telebot
from telebot import types

# ——— КОНФИГУРАЦИЯ ———

PORT           = int(os.getenv("PORT", "9999"))  # для Render health-check
DATA_DIR       = "data"
LANG_FILE      = os.path.join(DATA_DIR, "lang.json")
SCHEDULE_FILE  = os.path.join(DATA_DIR, "schedule.json")
TRANSFERS_FILE = os.path.join(DATA_DIR, "transfers.json")
RECORDS_FILE   = os.path.join(DATA_DIR, "records.csv")
FEEDBACK_FILE  = os.path.join(DATA_DIR, "feedback.csv")
LOG_FILE       = os.path.join(DATA_DIR, "bot.log")
TZ             = ZoneInfo("Asia/Tbilisi")

ADMINS = {
    7758773154: "joolay_vocal",
    388183067:  "joolay_joolay"
}

TEACHERS = {
    "Юля":     {"wd": [1,2,3,4], "hours": [f"{h}:00" for h in range(15,21)]},
    "Торнике": {"wd": [5,6,0],   "hours": [f"{h}:00" for h in range(8,23)]},
}

WD_SHORT = {
    0: "пн", 1: "вт", 2: "ср", 3: "чт",
    4: "пт", 5: "сб", 6: "вс"
}

LANGUAGES = ["ru", "en", "ka"]
LANG_NAMES = {
    "ru": "Русский 🇷🇺",
    "en": "English 🇬🇧",
    "ka": "ქართული 🇬🇪"
}
DEFAULT_LANG = "ru"
```

# ЧАСТЬ 2 — ИНИЦИАЛИЗАЦИЯ ФАЙЛОВ, ЛОГИРОВАНИЕ, HEALTHCHECK, BOT INIT И УТИЛИТЫ

# Создаём папку data
os.makedirs(DATA_DIR, exist_ok=True)

# Утилиты для JSON
def ensure_json(path):
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

for path in (LANG_FILE, SCHEDULE_FILE, TRANSFERS_FILE):
    ensure_json(path)

# Утилиты для CSV
def ensure_csv(path, headers):
    if not os.path.exists(path):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

ensure_csv(RECORDS_FILE, ['ts','teacher','date','time','uid','name','status'])
ensure_csv(FEEDBACK_FILE, ['ts','teacher','date','time','uid','stars','text','approved'])

# Настройка логирования
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Health-check сервер на порту PORT
class HC(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", PORT), HC).serve_forever(),
    daemon=True
).start()

# Инициализация бота
bot = telebot.TeleBot(os.getenv("BOT_TOKEN"))
bot.remove_webhook()

# Утилиты работы с файлами
def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Утилиты для работы с языком
def get_lang(uid):
    langs = load_json(LANG_FILE)
    return langs.get(str(uid), DEFAULT_LANG)

def set_lang(uid, code):
    langs = load_json(LANG_FILE)
    langs[str(uid)] = code
    save_json(LANG_FILE, langs)

# Функция локализации
def txt(uid, key, **kwargs):
    lang = get_lang(uid)
    return MESSAGES[lang][key].format(**kwargs)

# Клавиатуры
def kb_main(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btns = [
        txt(uid, "btn_book"),
        txt(uid, "btn_my"),
        txt(uid, "btn_transfer"),
        txt(uid, "btn_cancel"),
        txt(uid, "btn_help")
    ]
    kb.add(btns[0], btns[1])
    kb.add(btns[2], btns[3])
    kb.add(btns[4])
    if uid in ADMINS:
        kb.add(txt(uid, "btn_admin"))
    return kb

def kb_back(uid):
    text = {"ru": "🔙 Назад", "en": "🔙 Back", "ka": "🔙 უკან"}[get_lang(uid)]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(text, callback_data="main"))
    return kb
# ЧАСТЬ 3 — HANDLERS: /start, выбор языка, главное меню, flow бронирования и отмены

SESS = {}

@bot.message_handler(commands=["start", "help"])
def h_start(m):
    uid = m.from_user.id
    langs = load_json(LANG_FILE)
    langs.pop(str(uid), None)
    save_json(LANG_FILE, langs)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for code in LANGUAGES:
        kb.add(LANG_NAMES[code])
    bot.send_message(uid, MESSAGES["ru"]["choose_lang"], reply_markup=kb)

@bot.message_handler(func=lambda m: m.text in LANG_NAMES.values())
def h_choose_language(m):
    uid = m.from_user.id
    code = next(k for k,v in LANG_NAMES.items() if v==m.text)
    set_lang(uid, code)
    bot.send_message(uid, txt(uid,"lang_set",lang=m.text), reply_markup=kb_main(uid))

@bot.callback_query_handler(func=lambda c: c.data=="main")
def h_back_main(c):
    bot.answer_callback_query(c.id)
    bot.send_message(c.from_user.id, txt(c.from_user.id,"main_menu"), reply_markup=kb_main(c.from_user.id))

@bot.message_handler(func=lambda m: m.text==txt(m.from_user.id,"btn_book"))
def h_book(m):
    uid=m.from_user.id
    kb=types.InlineKeyboardMarkup()
    for tch in TEACHERS:
        kb.add(types.InlineKeyboardButton(tch,callback_data=f"t|{tch}"))
    bot.send_message(uid, txt(uid,"btn_book"), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("t|"))
def h_choose_teacher(c):
    uid=c.from_user.id
    tch=c.data.split("|",1)[1]
    SESS[uid]={"t":tch}
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Эта неделя",callback_data="w|0"))
    kb.add(types.InlineKeyboardButton("Следующая неделя",callback_data="w|1"))
    kb.add(types.InlineKeyboardButton("🔙 Назад",callback_data="main"))
    bot.edit_message_text(f"{tch}: Выберите неделю:",uid,c.message.message_id,reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("w|"))
def h_choose_week(c):
    uid=c.from_user.id; wk=int(c.data.split("|",1)[1]); tch=SESS[uid]["t"]
    today=date.today()
    mon=today - timedelta(days=today.weekday()) + timedelta(weeks=wk)
    kb=types.InlineKeyboardMarkup(row_width=3)
    for i in range(7):
        d=mon+timedelta(days=i)
        if d>=today and d.weekday() in TEACHERS[tch]["wd"]:
            label=f"{d.strftime('%d.%m.%y')} ({WD_SHORT[d.weekday()]})"
            kb.add(types.InlineKeyboardButton(label,callback_data=f"d|{d.isoformat()}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад",callback_data="main"))
    bot.edit_message_text("Выберите день:",uid,c.message.message_id,reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("d|"))
def h_choose_day(c):
    uid=c.from_user.id; d=c.data.split("|",1)[1]; tch=SESS[uid]["t"]
    SESS[uid]["d"]=d
    sch=load_json(SCHEDULE_FILE).get(tch,{}).get(d,{})
    kb=types.InlineKeyboardMarkup(row_width=2)
    for h in TEACHERS[tch]["hours"]:
        if h not in sch:
            kb.add(types.InlineKeyboardButton(h,callback_data=f"h|{h}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад",callback_data="main"))
    bot.edit_message_text("Выберите время:",uid,c.message.message_id,reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("h|"))
def h_choose_hour(c):
    uid=c.from_user.id; h=c.data.split("|",1)[1]; SESS[uid]["h"]=h
    bot.send_message(uid, "Введите ваше имя:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler_by_chat_id(uid, finish_booking)

def finish_booking(m):
    uid=m.chat.id; name=m.text.strip()
    tch,d,h=SESS[uid]["t"],SESS[uid]["d"],SESS[uid]["h"]
    sch=load_json(SCHEDULE_FILE)
    sch.setdefault(tch,{}).setdefault(d,{})[h]={"uid":uid,"name":name,"status":"pending"}
    save_json(SCHEDULE_FILE,sch)
    with open(RECORDS_FILE,"a",newline="",encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now(TZ).isoformat(),tch,d,h,uid,name,"pending"])
    bot.send_message(uid, txt(uid,"pending"), reply_markup=kb_main(uid))
    for aid in ADMINS:
        kb=types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅",callback_data=f"conf|{tch}|{d}|{h}"))
        kb.add(types.InlineKeyboardButton("❌",callback_data=f"rej|{tch}|{d}|{h}"))
        bot.send_message(aid, txt(uid,"admin_notify",teacher=tch,date=d,time=h,name=name,uid=uid), reply_markup=kb)
    del SESS[uid]

@bot.message_handler(func=lambda m: m.text==txt(m.from_user.id,"btn_cancel"))
def h_cancel(m):
    uid=m.from_user.id
    kb=types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅",callback_data="cnf|yes"))
    kb.add(types.InlineKeyboardButton("❌",callback_data="cnf|no"))
    bot.send_message(uid, txt(uid,"cancel_q"), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cnf|"))
def h_cancel_confirm(c):
    uid=c.from_user.id; ans=c.data.split("|",1)[1]
    if ans=="yes":
        sch=load_json(SCHEDULE_FILE)
        for tch in list(sch):
            for d in list(sch[tch]):
                for h,info in list(sch[tch][d].items()):
                    if info["uid"]==uid:
                        del sch[tch][d][h]
                        save_json(SCHEDULE_FILE,sch)
                        bot.send_message(uid, txt(uid,"cancel_ok"), reply_markup=kb_main(uid))
                        return
        bot.send_message(uid, txt(uid,"no_booking"), reply_markup=kb_main(uid))
    else:
        bot.send_message(uid, txt(uid,"main_menu"), reply_markup=kb_main(uid))
# ЧАСТЬ 4 — ПОДТВЕРЖДЕНИЕ, ПЕРЕНОС, МОИ ЗАПИСИ, АДМИН-ПАНЕЛЬ

# 7) Подтверждение/отклонение админом
@bot.callback_query_handler(lambda c: c.data.startswith(("conf|", "rej|")))
def h_admin_confirm(c):
    uid = c.from_user.id
    action, tch, d, h = c.data.split("|")
    sch = load_json(SCHEDULE_FILE)
    info = sch[tch][d][h]
    if action == "conf":
        info["status"] = "confirmed"
        save_json(SCHEDULE_FILE, sch)
        bot.answer_callback_query(c.id, "Подтверждено")
        bot.send_message(
            info["uid"],
            txt(info["uid"], "confirmed", teacher=tch, date=d, time=h),
            reply_markup=kb_main(info["uid"])
        )
    else:
        del sch[tch][d][h]
        save_json(SCHEDULE_FILE, sch)
        bot.answer_callback_query(c.id, "Отклонено")
        bot.send_message(
            info["uid"],
            txt(info["uid"], "cancel_ok"),
            reply_markup=kb_main(info["uid"])
        )

# 8) Перенос записи
@bot.message_handler(func=lambda m: m.text == txt(m.from_user.id, "btn_transfer"))
def h_transfer(m):
    uid = m.from_user.id
    sch = load_json(SCHEDULE_FILE)
    for tch in sch:
        for d in sch[tch]:
            for h, info in sch[tch][d].items():
                if info["uid"] == uid:
                    SESS[uid] = {"old": (tch, d, h)}
                    kb = types.InlineKeyboardMarkup()
                    kb.add(
                        types.InlineKeyboardButton("✅", callback_data="tr|yes"),
                        types.InlineKeyboardButton("❌", callback_data="tr|no")
                    )
                    bot.send_message(uid, txt(uid, "transfer_q"), reply_markup=kb)
                    return
    bot.send_message(uid, txt(uid, "no_booking"), reply_markup=kb_main(uid))

@bot.callback_query_handler(lambda c: c.data.startswith("tr|"))
def h_transfer_confirm(c):
    uid = c.from_user.id
    ans = c.data.split("|",1)[1]
    if ans == "yes":
        # снова запускаем flow бронирования
        h_book(c.message)
    else:
        bot.answer_callback_query(c.id, "Отмена")

# 9) Мои записи
@bot.message_handler(func=lambda m: m.text == txt(m.from_user.id, "btn_my"))
def h_my(m):
    uid = m.from_user.id
    sch = load_json(SCHEDULE_FILE)
    lines = []
    for tch in sch:
        for d in sch[tch]:
            for h, info in sch[tch][d].items():
                if info["uid"] == uid:
                    lines.append(f"{tch} {d} {h} ({info['status']})")
    bot.send_message(uid, "\n".join(lines) or txt(uid, "no_booking"), reply_markup=kb_main(uid))

# 10) Админ-панель
@bot.message_handler(func=lambda m: m.text == txt(m.from_user.id, "btn_admin") and m.from_user.id in ADMINS)
def h_admin_panel(m):
    uid = m.from_user.id
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📋 Записи", callback_data="ad|book"),
        types.InlineKeyboardButton("✍️ Отзывы", callback_data="ad|fb"),
        types.InlineKeyboardButton("🔁 Переносы", callback_data="ad|tr")
    )
    bot.send_message(uid, txt(uid, "main_menu"), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ad|"))
def h_admin_router(c):
    uid = c.from_user.id
    cmd = c.data.split("|",1)[1]
    if cmd == "book":
        sch = load_json(SCHEDULE_FILE)
        text = "Все записи:\n"
        for tch in sch:
            for d in sch[tch]:
                for h, info in sch[tch][d].items():
                    text += f"{tch} {d} {h} — {info['name']} ({info['status']})\n"
        c.message.edit_text(text or "Пусто")
    elif cmd == "fb":
        fb_lines = []
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                fb_lines.append(f"{r['date']} {r['time']} {r['teacher']} — {r['stars']}★ {r['text']}")
        c.message.edit_text("\n".join(fb_lines) or "Нет отзывов")
    elif cmd == "tr":
        tr = load_json(TRANSFERS_FILE)
        text = "Переносы:\n"
        for uid_k, data in tr.items():
            text += f"{data['old']} → {data['new']} (ID {uid_k})\n"
        c.message.edit_text(text or "Нет переносов")
```python
# ЧАСТЬ 5 — НАПОМИНАНИЯ, ОТЗЫВЫ И АВТО-ОЧИСТКА

# Фоновый цикл для напоминаний, запросов отзывов и очистки старых данных
def schedule_tasks():
    def worker():
        while True:
            now = datetime.now(TZ)
            sch = load_json(SCHEDULE_FILE)
            changed = False

            # Напоминания и запросы отзывов
            for tch, days in sch.items():
                for d, hours in days.items():
                    for h, info in list(hours.items()):
                        if info["status"] in ("confirmed", "reminded"):
                            lesson_dt = datetime.fromisoformat(f"{d}T{h}").replace(tzinfo=TZ)
                            delta = (lesson_dt - now).total_seconds()

                            # Напоминание за 2 часа
                            if 0 < delta <= 7200 and info["status"] == "confirmed":
                                bot.send_message(
                                    info["uid"],
                                    txt(info["uid"], "rem_before", teacher=tch, date=d, time=h)
                                )
                                info["status"] = "reminded"
                                changed = True

                            # Запрос отзыва через 30 минут после урока
                            if -1800 <= delta < 0 and info["status"] == "reminded":
                                kb = types.InlineKeyboardMarkup(row_width=5)
                                for stars in range(1, 6):
                                    kb.add(types.InlineKeyboardButton(
                                        f"{stars}★",
                                        callback_data=f"fb|{tch}|{d}|{h}|{stars}"
                                    ))
                                bot.send_message(
                                    info["uid"],
                                    txt(info["uid"], "feedback_req", teacher=tch, date=d, time=h),
                                    reply_markup=kb
                                )
                                info["status"] = "feedback_pending"
                                changed = True

            # Авто-очистка записей старше 14 дней
            cutoff = date.today() - timedelta(days=14)
            for tch in list(sch):
                for d in list(sch[tch]):
                    lesson_date = datetime.fromisoformat(f"{d}T00:00:00").date()
                    if lesson_date < cutoff:
                        del sch[tch][d]
                        changed = True
                if not sch[tch]:
                    del sch[tch]
                    changed = True

            if changed:
                save_json(SCHEDULE_FILE, sch)

            threading.Event().wait(3600)  # проверять каждый час

    threading.Thread(target=worker, daemon=True).start()

# Обработчик выбора оценки отзыва
@bot.callback_query_handler(func=lambda c: c.data.startswith("fb|"))
def h_feedback_rating(c):
    c.answer()
    _, tch, d, h, stars = c.data.split("|")
    uid = c.from_user.id
    SESS[uid] = {"tch": tch, "date": d, "time": h, "stars": stars}
    bot.send_message(uid, txt(uid, "ask_comment"), reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(
        bot.send_message(uid, "Комментарий:"),
        h_feedback_comment
    )

# Обработчик текста отзыва
def h_feedback_comment(m):
    uid = m.chat.id
    data = SESS.pop(uid)
    comment = m.text.strip()
    approved_flag = "approved" if int(data["stars"]) == 5 else "pending"
    # Сохраняем в feedback.csv
    with open(FEEDBACK_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.now(TZ).isoformat(),
            data["tch"], data["date"], data["time"],
            uid, data["stars"], comment, approved_flag
        ])
    bot.send_message(uid, txt(uid, "thanks_fb"), reply_markup=kb_main(uid))
    # Если отзыв не 5★, уведомляем админов для модерации
    if approved_flag == "pending":
        for aid in ADMINS:
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton(
                "✅ Одобрить",
                callback_data=f"appr|{uid}|{data['tch']}|{data['date']}|{data['time']}|{data['stars']}|{comment}"
            ))
            bot.send_message(
                aid,
                f"Новый отзыв от {uid}: {data['stars']}★ {comment}",
                reply_markup=kb
            )

# Обработчик одобрения отзыва админом
@bot.callback_query_handler(func=lambda c: c.data.startswith("appr|"))
def h_approve_feedback(c):
    c.answer("Отзыв одобрен")
    parts = c.data.split("|")[1:]
    target_uid, tch, d, h, stars, comment = parts
    rows = []
    # Читаем и обновляем статус
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if (r["uid"] == target_uid and r["teacher"] == tch and
                r["date"] == d and r["time"] == h and
                r["stars"] == stars and r["text"] == comment and
                r["approved"] == "pending"):
                r["approved"] = "approved"
            rows.append(r)
    # Записываем обратно
    with open(FEEDBACK_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)

# Запускаем фоновый цикл и polling
schedule_tasks()

if __name__ == "__main__":
    bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
```
