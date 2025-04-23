
import os
import json
import csv
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from threading import Timer

import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# --- HEALTH CHECK SERVER для Render ---
class HC(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_hc():
    HTTPServer(("0.0.0.0", 8000), HC).serve_forever()

threading.Thread(target=run_hc, daemon=True).start()

# --- Минимальный запуск бота ---
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(m.chat.id, "Бот работает! 🚀")

bot.polling()
