
import os
import telebot
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- Токен ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# --- Пример простейшего хэндлера ---
@bot.message_handler(commands=["start"])
def start_message(message):
    bot.send_message(message.chat.id, "Привет! Бот работает.")

# --- Health-check HTTP сервер ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# --- Запуск всего ---
if __name__ == "__main__":
    threading.Thread(target=run_fake_server, daemon=True).start()
    bot.polling(none_stop=True)
