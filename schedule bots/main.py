import asyncio
import threading
import os
import sys
from bots import VkBot
from config import VK_TOKEN
from datetime import datetime, timedelta
import pytz

def is_working_hours():
    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz)
    return 5 <= now.hour < 21

def schedule_exit():
    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz)
    stop_time = now.replace(hour=21, minute=0, second=0, microsecond=0)

    if now >= stop_time:
        return  # Уже поздно, бот не работает

    delay = (stop_time - now).total_seconds()
    print(f"⏳ Боты завершат работу через {int(delay // 60)} минут.")
    threading.Timer(delay, lambda: os._exit(0)).start()

def schedule_start():
    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz)
    start_time = now.replace(hour=5, minute=0, second=0, microsecond=0)

    # Если сейчас уже после 5 утра, запускать сразу
    if now >= start_time:
        return

    delay = (start_time - now).total_seconds()
    print(f"⏳ Боты запустятся через {int(delay // 60)} минут.")
    threading.Timer(delay, lambda: os._exit(0)).start()

if not is_working_hours():
    print("⛔ Вне рабочего времени. Бот не запускается.")
    sys.exit()

class TelegramBotRunner:
    def __init__(self):
        self.loop = asyncio.new_event_loop()

    def _run_bot(self):
        from bots.tgBot import main
        main()

    def run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_in_executor(None, self._run_bot)
            self.loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.loop.close()

def run_vk_bot():
    bot = VkBot(VK_TOKEN)
    bot.run()

if __name__ == "__main__":
    print("🚀 Запускаем обоих ботов...")
    schedule_start()
    schedule_exit()

    # Запускаем ВК-бота в отдельном потоке
    vk_thread = threading.Thread(target=run_vk_bot, daemon=True)
    vk_thread.start()

    # Запускаем телеграм-бота
    tg_runner = TelegramBotRunner()
    tg_runner.run()
