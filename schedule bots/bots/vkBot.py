import logging
import random
import datetime
import re
import sqlite3

from vk_api import VkApi
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from datetime import datetime, timedelta
from calendar import monthrange
import json

from db.db import init_db, add_reservation, get_reservations_for_user, update_reservation, \
    get_reservations_for_date, delete_reservation

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FIELD_NAMES = {
    "date": "Дата",
    "time": "Время",
    "author_name": "Имя автора",
    "event_name": "Название мероприятия",
    "duration": "Длительность"
}


# Состояния пользователя для FSM (Finite State Machine)
STATES = {
    'START': "start",
    'DATE': "date",
    'MONTH_PERIOD_SELECTION': 'month_period_selection',
    'MONTH_SELECTION': 'month_selection',
    'DAY_PERIOD_SELECTION': 'day_period_selection',
    'DAY_SELECTION': 'day_selection',
    'HOUR_PERIOD_SELECTION': 'hour_period_selection',
    'HOUR_SELECTION': 'hour_selection',
    'MINUTE_SELECTION': "minute_selection",
    'DURATION_SELECTION': "duration_selection",
    'AUTHOR_NAME': "author_name",
    'EVENT_NAME': "event_name",
    'EDIT_SELECTION': "edit_selection",
    'SELECT_MONTH': "select_month",
    'SELECT_DAY': "select_day",
    'SCHEDULE_MONTH_PERIOD': 'schedule_month_period',
    'SCHEDULE_MONTH_SELECTION': 'schedule_month_selection',
    'SCHEDULE_DAY_PERIOD': 'schedule_day_period',
    'SCHEDULE_DAY_SELECTION': 'schedule_day_selection',
    'VIEW_RESERVATIONS': 'view_reservations',
    'EDIT_DATE_SELECTION': 'edit_date_selection',
    'EDIT_MONTH_SELECTION': 'edit_month_selection',
    'EDIT_DAY_SELECTION': 'edit_day_selection',
    'EDIT_HOUR_SELECTION': 'edit_hour_selection',
    'EDIT_TIME_DATE_CHOICE': 'edit_time_date_choice',
    'EDIT_HOUR_PERIOD_SELECTION': 'edit_hour_period_selection',
    'EDIT_MINUTE_SELECTION': 'edit_minute_selection',
    'EDIT_TIME_PERIOD_SELECTION': 'edit_time_period_selection',
    'EDIT_TIME_HOUR_SELECTION': 'edit_time_hour_selection',
    'EDIT_TIME_MINUTE_SELECTION': 'edit_time_minute_selection',
}

# Глобальный словарь для хранения состояния пользователей
user_states = {}
user_data = {}

class VkBot:
    def __init__(self, token):
        self.pages = None
        self.vk_api = None
        def captcha_handler(captcha):
            print(f"\n🧩 Капча от ВКонтакте: {captcha.get_url()}")
            key = input("Введите капчу: ").strip()
            return captcha.try_again(key)
        self.vk_session = VkApi(token=token, captcha_handler=captcha_handler)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkLongPoll(self.vk_session)
        init_db()  # Инициализация базы данных
        logger.info("VK бот инициализирован")

    def send_message(self, user_id, message, keyboard=None):
        """Отправляет сообщение пользователю"""
        try:
            params = {
                'user_id': user_id,
                'message': message,
                'random_id': random.randint(1, 2147483647)
            }

            if keyboard:
                params['keyboard'] = keyboard.get_keyboard()

            self.vk.messages.send(**params)
            logger.info(f"Сообщение отправлено пользователю {user_id}: {message}")

        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
            # Можно дополнительно отправить сообщение об ошибке пользователю
            self.send_message(user_id, "❌ Ошибка при отправке сообщения. Попробуйте позже.")

    def get_main_keyboard(self):
        """Создает основную клавиатуру бота"""
        keyboard = VkKeyboard(one_time=False)

        keyboard.add_button('📆 Общее расписание', color=VkKeyboardColor.PRIMARY)
        keyboard.add_button('📅 Мои бронирования', color=VkKeyboardColor.PRIMARY)
        keyboard.add_line()
        keyboard.add_button('📌 Бронь', color=VkKeyboardColor.POSITIVE)
        keyboard.add_button('ℹ️ О боте', color=VkKeyboardColor.SECONDARY)

        return keyboard

    def get_months_keyboard(self, user_id, prefix="month"):
        """Создает клавиатуру для выбора текущего и следующих трех месяцев"""
        keyboard = VkKeyboard(inline=True)

        # Получаем текущий месяц
        current_month = datetime.now().month

        # Список месяцев для отображения
        months = [(current_month + i - 1) % 12 + 1 for i in range(4)]  # Текущий и 3 следующие месяца
        months_str = [f"{month:02d}" for month in months]

        # Добавляем кнопки для месяцев
        button_count = 0  # Счётчик кнопок на текущей клавиатуре
        for month in months_str:
            keyboard.add_button(month, color=VkKeyboardColor.PRIMARY, payload={"button": f"{prefix}_{month}"})
            button_count += 1

            # Если на текущей клавиатуре 5 кнопок, добавляем новую строку
            if button_count % 5 == 0:
                keyboard.add_line()

        # Отправляем клавиатуру
        return keyboard

    def get_days_keyboard(self, user_id, year, month, prefix="day"):
        """Создает клавиатуру для выбора дня (только будущие дни), одной строкой (до 3 кнопок)"""
        days_in_month = monthrange(year, month)[1]
        keyboard = VkKeyboard(inline=True)

        today = datetime.now()
        current_day = today.day
        current_month = today.month
        current_year = today.year

        # Фильтруем только будущие дни
        days_to_show = [
            day for day in range(1, days_in_month + 1)
            if (year > current_year) or
               (year == current_year and month > current_month) or
               (year == current_year and month == current_month and day >= current_day)
        ]

        # Оставляем только первые 3 дня
        days_to_show = days_to_show[:4]

        # Добавляем все кнопки в одну строку
        for day in days_to_show:
            keyboard.add_button(f"{day:02d}", color=VkKeyboardColor.PRIMARY,
                                payload={"button": f"{prefix}_{day:02d}"})

        return keyboard

    def start(self, user_id):
        """Обработчик команды start"""
        keyboard = self.get_main_keyboard()
        self.send_message(user_id, "Привет! Я бот для управления расписанием. Выберите действие:", keyboard)
        user_states[user_id] = STATES['START']

    def about(self, user_id):
        """Обработчик команды about"""
        about_text = (
            "Здравствуйте, Я — бот для управления вашим расписанием и бронирования столиков. "
            "С помощью меня вы можете:\n"
            "1. Просматривать общее расписание бронирований 📆\n"
            "2. Просматривать свои бронирования 📅\n"
            "3. Забронировать столик 📌\n"
            "Просто выберите нужную опцию и следуйте инструкциям!\n\n"
            "Я помогу вам с организацией времени и удобным бронированием"
        )
        self.send_message(user_id, about_text, self.get_main_keyboard())

    def start_reservation(self, user_id):
        """Начинает процесс бронирования с выбора периода месяцев"""
        if user_id not in user_data:
            user_data[user_id] = {}

        keyboard = VkKeyboard(inline=True)
        keyboard.add_button("Январь-Апрель (1-4)", color=VkKeyboardColor.PRIMARY,
                            payload={"button": "month_period_1_4"})
        keyboard.add_button("Май-Август (5-8)", color=VkKeyboardColor.PRIMARY, payload={"button": "month_period_5_8"})
        keyboard.add_line()
        keyboard.add_button("Сентябрь-Декабрь (9-12)", color=VkKeyboardColor.PRIMARY,
                            payload={"button": "month_period_9_12"})

        self.send_message(user_id, "📅 Выберите период месяцев:", keyboard)
        user_states[user_id] = STATES['MONTH_PERIOD_SELECTION']

    def handle_message(self, user_id, message_text, payload=None):
        """Главный обработчик входящих сообщений от пользователя"""
        state = user_states.get(user_id, STATES['START'])
        message_text = message_text.strip()

        logger.info(f"[{user_id}] Состояние перед обработкой: {state}, сообщение: {message_text}")

        try:
            if state == STATES['EDIT_INPUT']:
                self.process_edit_input(user_id, message_text)
                return

            elif state == STATES['START']:
                self.send_message(user_id, "Выберите период (0–10, 10–20, 20–31):", self.get_periods_keyboard())
                user_states[user_id] = STATES['PERIOD_SELECTION']

            elif state == STATES['MONTH_SELECTION']:
                self.process_month_selection(user_id, message_text)

            elif state == STATES['DAY_SELECTION']:  # Теперь сразу переходим к выбору дня после месяца
                self.process_day_selection(user_id, message_text)

            elif state == STATES['HOUR_PERIOD_SELECTION']:
                self.process_hour_period_selection(user_id, message_text)

            elif state == STATES['HOUR_PERIOD_SELECTION']:
                self.process_hour_period_selection(user_id, message_text)

            elif state == STATES['HOUR_SELECTION']:
                logger.info(f"[{user_id}] Переход в состояние: {STATES['HOUR_SELECTION']}")
                self.process_hour_selection(user_id, message_text)

            elif state == STATES['MINUTE_SELECTION']:
                logger.info(f"[{user_id}] Переход в состояние: {STATES['MINUTE_SELECTION']}")
                self.process_minute_selection(user_id, message_text)

            elif state == STATES['DURATION_INPUT']:
                self.process_duration_input(user_id, message_text)

            elif state == STATES['AUTHOR_NAME']:
                self.process_author_name(user_id, message_text)

            elif state == STATES['EVENT_NAME']:
                self.process_event_name(user_id, message_text)

            else:
                self.send_message(user_id, "Неизвестное состояние. Начнем сначала.")
                user_states[user_id] = STATES['START']


        except Exception as e:
            logger.error(f"Ошибка обработки для {user_id}: {str(e)}")
            self.send_message(user_id, "❌ Произошла ошибка. Попробуйте снова.")
            user_states[user_id] = STATES['START']
            if user_id in user_data:
                user_data[user_id].clear()

    def process_month_period_selection(self, user_id, period):
        """Обрабатывает выбор периода месяцев"""
        try:
            period_map = {
                "month_period_1_4": [1, 2, 3, 4],
                "month_period_5_8": [5, 6, 7, 8],
                "month_period_9_12": [9, 10, 11, 12]
            }

            current_year = datetime.now().year
            current_month = datetime.now().month

            # Определяем доступные месяцы в выбранном периоде
            available_months = []
            for month in period_map[period]:
                # Если месяц в текущем году уже прошел, предлагаем следующий год
                if month < current_month:
                    available_months.append((month, current_year + 1))
                else:
                    available_months.append((month, current_year))

            # Создаем клавиатуру с доступными месяцами
            keyboard = VkKeyboard(inline=True)
            row_length = 0
            max_buttons_per_row = 2  # Максимальное количество кнопок в строке

            for i, (month, year) in enumerate(available_months):
                month_name = self.get_month_name(month)
                if year > current_year:
                    btn_text = f"{month_name} ({year})"
                else:
                    btn_text = month_name

                keyboard.add_button(btn_text, color=VkKeyboardColor.PRIMARY,
                                    payload={"button": f"select_month_{month}_{year}"})
                row_length += 1

                # Добавляем новую строку, если достигли максимума кнопок в строке
                # И это не последняя кнопка
                if row_length >= max_buttons_per_row and i != len(available_months) - 1:
                    keyboard.add_line()
                    row_length = 0

            self.send_message(user_id, "Выберите конкретный месяц:", keyboard)
            user_states[user_id] = STATES['MONTH_SELECTION']

        except Exception as e:
            logger.error(f"Ошибка при выборе периода месяцев: {e}")
            self.send_message(user_id, "❌ Ошибка! Попробуйте выбрать период еще раз.")

    def get_month_name(self, month_num):
        """Возвращает название месяца по номеру"""
        months = [
            "Январь", "Февраль", "Март", "Апрель",
            "Май", "Июнь", "Июль", "Август",
            "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
        ]
        return months[month_num - 1]

    def process_month_selection(self, user_id, month_data):
        """Обрабатывает выбор конкретного месяца и запрашивает день"""
        try:
            month = int(month_data["month"])
            year = int(month_data["year"])

            user_data[user_id]["month"] = f"{month:02d}"
            user_data[user_id]["year"] = str(year)

            logger.info(f"[{user_id}] Выбран месяц: {month:02d}.{year}")

            # Запрашиваем ввод дня
            self.send_message(user_id,
                              f"📅 Введите число месяца ({self.get_month_name(month)} {year}):")
            user_states[user_id] = STATES['DAY_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при обработке месяца: {e}")
            self.send_message(user_id, "❌ Ошибка! Попробуйте выбрать месяц еще раз")

    def get_months_keyboard(self, user_id, prefix="month"):
        """Создает клавиатуру для выбора месяцев с учетом текущей даты"""
        current_date = datetime.now()
        current_month = current_date.month

        keyboard = VkKeyboard(inline=True)

        # Добавляем месяцы текущего года (начиная с текущего)
        for month in range(current_month, 13):
            month_str = f"{month:02d}"
            keyboard.add_button(month_str, color=VkKeyboardColor.PRIMARY,
                                payload={"button": f"{prefix}_{month_str}"})
            if month % 4 == 0:  # 4 кнопки в строке
                keyboard.add_line()

        # Добавляем месяцы следующего года (до текущего месяца)
        for month in range(1, current_month):
            month_str = f"{month:02d}"
            keyboard.add_button(f"{month_str} (след. год)", color=VkKeyboardColor.SECONDARY,
                                payload={"button": f"{prefix}_{month_str}"})
            if (month + 12) % 4 == 0:  # 4 кнопки в строке
                keyboard.add_line()

        return keyboard

    def show_reservations_for_date(self, user_id, date):
        """Показывает все бронирования на указанную дату"""
        try:
            reservations = get_reservations_for_date(date)
            if not reservations:
                self.send_message(user_id, f"📅 На {date} бронирований нет.")
                return

            message = f"📅 Бронирования на {date}:\n\n"
            for res in reservations:
                time_range = self.format_time_range(res[2], res[3])
                message += f"⏰ {time_range} - {res[5]} ({res[4]})\n"

            self.send_message(user_id, message)
        except Exception as e:
            logger.error(f"[{user_id}] Ошибка показа бронирований: {e}")
            self.send_message(user_id, "❌ Ошибка при загрузке бронирований.")

    def is_day_fully_booked(self, date):
        """Проверяет, полностью ли занят день"""
        try:
            # Проверяем формат даты
            datetime.strptime(date, "%Y-%m-%d")

            reservations = get_reservations_for_date(date)
            MAX_SLOTS = 12  # Максимальное количество броней в день

            return len(reservations) >= MAX_SLOTS
        except Exception as e:
            logger.error(f"Ошибка проверки занятости дня {date}: {e}")
            return True  # В случае ошибки считаем день занятым

    def process_day_selection(self, user_id, day_input):
        """Обрабатывает выбор конкретного дня"""
        try:
            day = day_input.strip()
            logger.info(f"[{user_id}] Обработка дня: {day}")

            if not day.isdigit():
                self.send_message(user_id, "❌ Пожалуйста, введите число месяца.")
                return

            day = int(day)
            month = int(user_data[user_id]["month"])
            year = int(user_data[user_id]["year"])

            # Проверка корректности даты
            _, last_day = monthrange(year, month)
            if day < 1 or day > last_day:
                self.send_message(user_id, f"❌ В этом месяце дней от 1 до {last_day}. Попробуйте снова.")
                return

            # Форматируем дату
            date = f"{year}-{month:02d}-{day:02d}"
            user_data[user_id].update({
                "day": f"{day:02d}",
                "date": date,
                # Очищаем предыдущие значения времени
                "time": None,
                "hour": None
            })

            if self.is_day_fully_booked(date):
                self.send_message(user_id, "❌ Этот день уже полностью занят. Выберите другой день.")
                return

            # Переходим к выбору времени
            self.show_hour_periods(user_id)

        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка при обработке дня: {e}", exc_info=True)
            self.send_message(user_id, "❌ Произошла ошибка. Пожалуйста, начните процесс заново.")
            self.reset_user_state(user_id)

    def show_hour_periods(self, user_id):
        """Показывает периоды времени для выбранного дня с правильным форматом клавиатуры"""
        try:
            if user_id not in user_data or "date" not in user_data[user_id]:
                raise ValueError("Не выбрана дата")

            date = user_data[user_id]["date"]
            logger.info(f"[{user_id}] Показ периодов для даты: {date}")

            # Получаем и проверяем бронирования
            reservations = get_reservations_for_date(date)
            booked_slots = []

            for res in reservations:
                try:
                    time_str = res[2]
                    if not re.match(r'^\d{2}:\d{2}$', time_str):
                        continue

                    start = datetime.strptime(time_str, "%H:%M")
                    duration = int(res[3]) if len(res) > 3 and str(res[3]).isdigit() else 60
                    booked_slots.append((
                        start.hour * 60 + start.minute,
                        start.hour * 60 + start.minute + duration
                    ))
                except Exception as e:
                    logger.warning(f"[{user_id}] Пропущено некорректное бронирование: {res} - {e}")
                    continue

            # Проверяем доступные часы (5:00-19:00)
            available_hours = []
            for hour in range(5, 20):
                start_min = hour * 60
                end_min = start_min + 60  # Минимальный слот 1 час

                if all(end_min <= bs[0] or start_min >= bs[1] for bs in booked_slots):
                    available_hours.append(f"{hour:02d}")

            if not available_hours:
                self.send_message(user_id,
                                  "❌ На выбранный день нет свободного времени.\n"
                                  "Попробуйте выбрать другую дату.")
                return

            # Создаем клавиатуру с правильным форматом (не более 2 кнопок в строке)
            keyboard = VkKeyboard(inline=True)

            # Первая строка: ранние периоды
            keyboard.add_button("05:00-08:00", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "hour_period_5_8"})
            keyboard.add_button("09:00-12:00", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "hour_period_9_12"})

            # Вторая строка: поздние периоды
            keyboard.add_line()
            keyboard.add_button("13:00-16:00", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "hour_period_13_16"})
            keyboard.add_button("17:00-19:00", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "hour_period_17_19"})

            self.send_message(user_id, f"🕒 Выберите период времени для {date}:", keyboard)
            user_states[user_id] = STATES['HOUR_PERIOD_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при показе периодов: {e}", exc_info=True)
            self.send_message(user_id,
                              "❌ Ошибка при загрузке расписания. Попробуйте позже.")
            self.reset_user_state(user_id)

    def process_hour_period_selection(self, user_id, period):
        """Обрабатывает выбор периода часов с точной проверкой доступности"""
        try:
            if not isinstance(period, dict) or 'button' not in period:
                self.send_message(user_id, "❌ Неверный формат запроса. Пожалуйста, используйте кнопки.")
                return

            button_payload = period['button']

            # Периоды и их часы
            period_ranges = {
                'hour_period_5_8': (5, 8),
                'hour_period_9_12': (9, 12),
                'hour_period_13_16': (13, 16),
                'hour_period_17_19': (17, 19)
            }

            if button_payload not in period_ranges:
                self.send_message(user_id, "❌ Неверный период. Пожалуйста, выберите из предложенных.")
                return

            start_hour, end_hour = period_ranges[button_payload]
            date = user_data[user_id]["date"]
            duration = user_data[user_id].get("duration", 60)

            # Получаем актуальные бронирования для даты
            reservations = get_reservations_for_date(date)
            booked_slots = []

            for res in reservations:
                try:
                    time_str = res[2]
                    res_duration = int(res[3]) if len(res) > 3 else 60
                    start = datetime.strptime(time_str, "%H:%M")
                    start_min = start.hour * 60 + start.minute
                    end_min = start_min + res_duration
                    booked_slots.append((start_min, end_min))
                except Exception as e:
                    logger.warning(f"Пропущено некорректное бронирование: {res} - {e}")
                    continue

            # Проверяем доступность каждого часа в периоде
            available_hours = []
            for hour in range(start_hour, end_hour + 1):
                start_min = hour * 60
                end_min = start_min + duration

                # Проверяем пересечение с существующими бронированиями
                is_available = True
                for (booked_start, booked_end) in booked_slots:
                    if not (end_min <= booked_start or start_min >= booked_end):
                        is_available = False
                        break

                if is_available:
                    available_hours.append(f"{hour:02d}")

            if not available_hours:
                # Предлагаем ближайшие доступные варианты
                nearest = self.find_nearest_available_time(date, duration)
                if nearest:
                    msg = (f"❌ В выбранном периоде нет свободных часов.\n"
                           f"🔄 Ближайшее доступное время: {nearest}\n"
                           f"Хотите забронировать на это время?")
                    keyboard = VkKeyboard(inline=True)
                    keyboard.add_button("Да", color=VkKeyboardColor.POSITIVE,
                                        payload={"button": f"book_nearest_{nearest}"})
                    keyboard.add_button("Нет", color=VkKeyboardColor.NEGATIVE,
                                        payload={"button": "cancel_booking"})
                    self.send_message(user_id, msg, keyboard)
                else:
                    self.send_message(user_id,
                                      "❌ К сожалению, на выбранную дату нет свободного времени.\n"
                                      "Пожалуйста, выберите другую дату.")
                return

            # Создаем клавиатуру с доступными часами
            keyboard = VkKeyboard(inline=True)
            for i, hour in enumerate(available_hours):
                keyboard.add_button(hour, color=VkKeyboardColor.PRIMARY,
                                    payload={"button": f"hour_{hour}"})
                if (i + 1) % 3 == 0 and i != len(available_hours) - 1:
                    keyboard.add_line()

            self.send_message(user_id, f"🕒 Доступные часы в периоде {start_hour}:00-{end_hour}:00:", keyboard)
            user_states[user_id] = STATES['HOUR_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка выбора периода: {e}", exc_info=True)
            self.send_message(user_id, "❌ Ошибка обработки. Пожалуйста, начните заново.")
            self.reset_user_state(user_id)

    def process_hour_selection(self, user_id, hour_input):
        """Обрабатывает выбор часа с полной проверкой доступности"""
        try:
            logger.info(f"[{user_id}] Обработка выбора часа: {hour_input}")

            # Проверяем базовые условия
            if user_id not in user_data:
                raise ValueError("Данные пользователя не найдены")

            date = user_data[user_id].get("date")
            if not date:
                raise ValueError("Не выбрана дата")

            # Проверяем и форматируем час
            if not isinstance(hour_input, str) or not hour_input.isdigit():
                raise ValueError("Час должен быть числом")

            hour = f"{int(hour_input):02d}"  # Гарантируем двузначный формат
            time_str = f"{hour}:00"

            # Проверяем доступность времени
            if self.is_time_booked(date, time_str):
                raise ValueError("Выбранное время уже занято")

            # Сохраняем данные
            user_data[user_id].update({
                "hour": hour,
                "time": time_str
            })

            # Создаем клавиатуру для минут (2 кнопки в строке)
            keyboard = self.create_minutes_keyboard("minute")

            self.send_message(user_id, f"⏰ Вы выбрали {time_str}. Укажите минуты:", keyboard)
            user_states[user_id] = STATES['MINUTE_SELECTION']

        except ValueError as e:
            logger.warning(f"[{user_id}] Ошибка выбора часа: {e}")
            nearest = self.find_nearest_available_time(
                user_data[user_id]["date"],
                user_data[user_id].get("duration", 60)
            )
            if nearest:
                msg = (f"❌ Время {hour_input}:00 недоступно.\n"
                       f"🔄 Ближайшее свободное время: {nearest}\n"
                       f"Хотите выбрать его?")

                keyboard = VkKeyboard(inline=True)
                keyboard.add_button("Да", color=VkKeyboardColor.POSITIVE,
                                    payload={"button": f"accept_nearest_{nearest.replace(':', '')}"})
                keyboard.add_button("Нет", color=VkKeyboardColor.NEGATIVE,
                                    payload={"button": "cancel_time_selection"})

                self.send_message(user_id, msg, keyboard)
            else:
                self.send_message(user_id,
                                  "❌ Нет доступного времени. Пожалуйста, выберите другую дату.")

        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка: {e}", exc_info=True)
            self.send_message(user_id, "❌ Системная ошибка. Пожалуйста, начните заново.")
            self.reset_user_state(user_id)

    def create_minutes_keyboard(self, prefix):
        """Создает клавиатуру для выбора минут"""
        keyboard = VkKeyboard(inline=True)
        minutes = ["00", "15", "30", "45"]

        # Добавляем кнопки по 2 в строку
        for i in range(0, len(minutes), 2):
            # Первая кнопка в паре
            keyboard.add_button(minutes[i], color=VkKeyboardColor.PRIMARY,
                                payload={"button": f"{prefix}_{minutes[i]}"})

            # Вторая кнопка, если есть
            if i + 1 < len(minutes):
                keyboard.add_button(minutes[i + 1], color=VkKeyboardColor.PRIMARY,
                                    payload={"button": f"{prefix}_{minutes[i + 1]}"})

            # Перенос строки, если не последняя пара
            if i + 2 < len(minutes):
                keyboard.add_line()

        return keyboard

    def is_time_booked(self, date, time, reservation_id=None):
        """Проверяет, занято ли конкретное время"""
        conn = sqlite3.connect('reservations.db')
        cursor = conn.cursor()

        query = "SELECT id FROM reservations WHERE date = ? AND time = ?"
        params = [date, time]

        if reservation_id:
            query += " AND id != ?"
            params.append(reservation_id)

        cursor.execute(query, params)
        result = cursor.fetchone() is not None
        conn.close()

        return result

    def process_minute_selection(self, user_id, minute):
        """Обрабатывает выбор минут"""
        try:
            # Если пришло сообщение с кнопки
            if isinstance(minute, dict) and "button" in minute:
                minute = minute["button"].split("_")[1]

            minute = minute.strip().zfill(2)

            # Проверяем допустимые значения минут
            if minute not in ["00", "15", "30", "45"]:
                # Показываем клавиатуру снова, если введено недопустимое значение
                keyboard = VkKeyboard(inline=True)
                keyboard.add_button("00", color=VkKeyboardColor.PRIMARY, payload={"button": f"minute_00"})
                keyboard.add_button("15", color=VkKeyboardColor.PRIMARY, payload={"button": f"minute_15"})
                keyboard.add_line()
                keyboard.add_button("30", color=VkKeyboardColor.PRIMARY, payload={"button": f"minute_30"})
                keyboard.add_button("45", color=VkKeyboardColor.PRIMARY, payload={"button": f"minute_45"})

                self.send_message(user_id,
                                  "❌ Пожалуйста, выберите минуты из предложенных вариантов:",
                                  keyboard)
                return False

            hour = user_data[user_id]["hour"]
            date = user_data[user_id]["date"]
            time = f"{hour}:{minute}"
            user_data[user_id]["time"] = time

            duration = user_data[user_id].get("duration", 60)
            start_time = datetime.strptime(time, "%H:%M")
            end_time = start_time + timedelta(minutes=duration)

            # Проверка доступности времени
            reservations = get_reservations_for_date(date)
            for res in reservations:
                res_start = datetime.strptime(res[2], "%H:%M")
                res_end = res_start + timedelta(minutes=int(res[3]))

                if not (end_time <= res_start or start_time >= res_end):
                    # Найдено пересечение - время занято
                    nearest_time = self.find_nearest_available_time(time, duration, reservations)
                    user_data[user_id]["time"] = nearest_time
                    self.send_message(user_id,
                                      f"⚠️ Время {time} уже занято.\n"
                                      f"🔄 Перенесено на {nearest_time}")
                    self.show_duration_keyboard(user_id)
                    return True
            occupied_times = [res[2] for res in reservations]

            if time in occupied_times:
                nearest_time = self.find_nearest_available_time(time, 60, reservations)
                user_data[user_id]["time"] = nearest_time
                self.send_message(user_id,
                                  f"⚠️ Время {time} уже занято.\n"
                                  f"🔄 Бронирование автоматически перенесено на ближайшее доступное: {nearest_time}.\n")
                self.show_duration_keyboard(user_id)
            else:
                self.send_message(user_id, f"✅ Вы выбрали время: {time}.")
                self.show_duration_keyboard(user_id)

            return True

        except Exception as e:
            logger.error(f"Error in minute selection for user {user_id}: {str(e)}")
            self.send_message(user_id, "❌ Ошибка! Попробуйте выбрать минуты еще раз.")
            return False

    def show_duration_keyboard(self, user_id):
        """Показывает клавиатуру для выбора длительности"""
        keyboard = VkKeyboard(inline=True)
        durations = ["30", "60", "120", "180"]

        for i, duration in enumerate(durations):
            keyboard.add_button(f"{duration} мин", color=VkKeyboardColor.PRIMARY,
                                payload={"button": f"duration_{duration}"})
            if i < len(durations) - 1:
                keyboard.add_line()  # Каждая кнопка на новой строке

        self.send_message(user_id, "Выберите длительность мероприятия:", keyboard)
        user_states[user_id] = STATES['DURATION_SELECTION']

    def process_duration_input(self, user_id, duration_input):
        """Обрабатывает ввод длительности (через кнопки или ввод вручную)"""
        try:
            # Если duration_input пришло из payload (нажатие кнопки)
            if isinstance(duration_input, dict) and "button" in duration_input:
                duration = duration_input["button"].split("_")[1]
            else:
                duration = duration_input.strip()

            # Проверяем допустимые значения
            if duration not in ["60", "120", "180"]:
                self.show_duration_keyboard(user_id)
                return

            user_data[user_id]['duration'] = int(duration)

            # Запрашиваем имя автора
            self.send_message(user_id, "Теперь, пожалуйста, введите ваше имя:")
            user_states[user_id] = STATES['AUTHOR_NAME']

        except Exception as e:
            logger.error(f"Ошибка при вводе длительности: {e}")
            self.send_message(user_id, "❌ Ошибка! Пожалуйста, выберите длительность из предложенных.")
            self.show_duration_keyboard(user_id)

    def process_author_name(self, user_id, text):
        """Обрабатывает ввод имени автора"""
        author_name = text.strip()
        user_data[user_id]["author_name"] = author_name

        # Запрашиваем название мероприятия
        self.send_message(user_id, "Теперь введите наименование мероприятия:")
        user_states[user_id] = STATES['EVENT_NAME']

    def process_event_name(self, user_id, text):
        """Обрабатывает ввод названия мероприятия и завершает бронирование"""
        event_name = text.strip()
        user_data[user_id]['event_name'] = event_name

        # Получаем все данные
        author_name = user_data[user_id].get('author_name', "Неизвестный")
        date = user_data[user_id]['date']
        time = user_data[user_id]['time']
        duration = user_data[user_id].get('duration', 60)

        # Добавляем бронирование
        if add_reservation(user_id, f"vk{user_id}", author_name, event_name, date, time, duration):
            self.send_message(user_id, "✅ Бронирование успешно добавлено!", self.get_main_keyboard())
        else:
            self.send_message(user_id, "⚠️ Это время уже занято, попробуйте другое.", self.get_main_keyboard())

        user_states[user_id] = STATES['START']

    def show_my_reservations(self, user_id):
        """Показывает список бронирований пользователя с правильной клавиатурой"""
        try:
            reservations = get_reservations_for_user(user_id)

            if not reservations:
                self.send_message(user_id, "У вас пока нет бронирований.", self.get_main_keyboard())
                return

            # Отправляем общее сообщение со списком бронирований
            message = "📅 Ваши бронирования:\n\n"
            for i, res in enumerate(reservations, 1):
                message += f"{i}. {res[4]} - {res[2]}: {res[3]}\nАвтор: {res[1]}\nВремя: {res[5]}\nДлительность: {res[6]} мин\n\n"

            # Максимальное количество бронирований в одной клавиатуре (ограничение VK API)
            MAX_RESERVATIONS_PER_KEYBOARD = 5

            # Отправляем сообщение с первой частью кнопок
            first_part = reservations[:MAX_RESERVATIONS_PER_KEYBOARD]
            keyboard = VkKeyboard(inline=True)

            # Добавляем кнопки для первых бронирований
            for i, res in enumerate(first_part, 1):
                keyboard.add_button(f"✏️ Редактировать {i}", color=VkKeyboardColor.PRIMARY,
                                    payload={"button": f"edit_booking_{res[0]}"})
                keyboard.add_button(f"❌ Отменить {i}", color=VkKeyboardColor.NEGATIVE,
                                    payload={"button": f"cancel_confirm_{res[0]}"})
                if i < len(first_part):
                    keyboard.add_line()

            # Если есть еще бронирования, добавляем кнопку "Далее"
            if len(reservations) > MAX_RESERVATIONS_PER_KEYBOARD:
                keyboard.add_line()
                keyboard.add_button("Далее →", color=VkKeyboardColor.SECONDARY,
                                    payload={"action": "show_more_reservations",
                                             "offset": MAX_RESERVATIONS_PER_KEYBOARD})

            keyboard.add_line()
            keyboard.add_button("Назад", color=VkKeyboardColor.SECONDARY,
                                payload={"action": "main_menu"})

            self.send_message(user_id, message, keyboard)
            user_states[user_id] = STATES['VIEW_RESERVATIONS']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при показе бронирований: {e}")
            self.send_message(user_id, "❌ Ошибка при загрузке бронирований. Попробуйте позже.",
                              self.get_main_keyboard())

    def show_all_reservations(self, user_id):
        """Начинает процесс просмотра расписания с выбора периода месяцев"""
        try:
            # Инициализация данных пользователя
            if user_id not in user_data:
                user_data[user_id] = {}

            # Создаем клавиатуру с периодами месяцев
            keyboard = VkKeyboard(inline=True)
            keyboard.add_button("Январь-Апрель", color=VkKeyboardColor.PRIMARY,
                                payload={"action": "schedule_month_period", "period": "1_4"})
            keyboard.add_button("Май-Август", color=VkKeyboardColor.PRIMARY,
                                payload={"action": "schedule_month_period", "period": "5_8"})
            keyboard.add_line()
            keyboard.add_button("Сентябрь-Декабрь", color=VkKeyboardColor.PRIMARY,
                                payload={"action": "schedule_month_period", "period": "9_12"})
            keyboard.add_line()
            keyboard.add_button("Текущий месяц", color=VkKeyboardColor.POSITIVE,
                                payload={"action": "schedule_current_month"})
            keyboard.add_button("Главное меню", color=VkKeyboardColor.SECONDARY,
                                payload={"action": "main_menu"})

            self.send_message(user_id, "📅 Выберите период месяцев для просмотра расписания:", keyboard)
            user_states[user_id] = STATES['SCHEDULE_MONTH_PERIOD']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при показе периодов месяцев: {e}")
            self.send_message(user_id, "❌ Произошла ошибка. Попробуйте позже.")

    def process_schedule_month_period(self, user_id, period):
        """Обрабатывает выбор периода месяцев для расписания"""
        try:
            if period == "current":
                now = datetime.now()
                self.process_schedule_month_selection(user_id, {"month": now.month, "year": now.year})
                return

            start_month, end_month = map(int, period.split('_'))
            current_year = datetime.now().year
            current_month = datetime.now().month

            keyboard = VkKeyboard(inline=True)
            for month in range(start_month, end_month + 1):
                # Для месяцев текущего года
                if month >= current_month:
                    month_name = self.get_month_name(str(month).zfill(2))  # Преобразуем в формат "01", "02" и т.д.
                    keyboard.add_button(month_name, color=VkKeyboardColor.PRIMARY,
                                        payload={"action": "schedule_select_month",
                                                 "month": month, "year": current_year})
                # Для месяцев следующего года
                else:
                    month_name = f"{self.get_month_name(str(month).zfill(2))} ({current_year + 1})"
                    keyboard.add_button(month_name, color=VkKeyboardColor.SECONDARY,
                                        payload={"action": "schedule_select_month",
                                                 "month": month, "year": current_year + 1})

                if (month - start_month) % 2 == 1 and month != end_month:
                    keyboard.add_line()

            keyboard.add_line()
            keyboard.add_button("Назад к периодам", color=VkKeyboardColor.SECONDARY,
                                payload={"action": "show_all_reservations"})

            self.send_message(user_id, "Выберите конкретный месяц:", keyboard)
            user_states[user_id] = STATES['SCHEDULE_MONTH_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при обработке периода месяцев: {e}")
            self.send_message(user_id, "❌ Ошибка! Попробуйте выбрать период еще раз.")

    def process_schedule_month_selection(self, user_id, month_data):
        """Обрабатывает выбор месяца для расписания и предлагает периоды дней"""
        try:
            month = int(month_data["month"])
            year = int(month_data["year"])

            # Сохраняем выбранный месяц
            user_data[user_id] = {
                "schedule_month": f"{month:02d}",
                "schedule_year": str(year)
            }

            # Создаем клавиатуру с периодами дней
            _, num_days = monthrange(year, month)
            period_size = max(1, num_days // 4)
            periods = []

            for i in range(4):
                start_day = i * period_size + 1
                end_day = (i + 1) * period_size if i < 3 else num_days
                periods.append((start_day, end_day))

            keyboard = VkKeyboard(inline=True)
            for i, (start, end) in enumerate(periods):
                btn_text = f"{start}-{end}" if start != end else f"{start}"
                keyboard.add_button(btn_text, color=VkKeyboardColor.PRIMARY,
                                    payload={"action": "schedule_day_period",
                                             "start": start, "end": end})

                if i % 2 == 1 and i != len(periods) - 1:
                    keyboard.add_line()

            keyboard.add_line()
            keyboard.add_button("Назад к месяцам", color=VkKeyboardColor.SECONDARY,
                                payload={"action": "show_all_reservations"})

            month_name = self.get_month_name(month)
            self.send_message(user_id,
                              f"📅 Выберите период дней ({month_name} {year}):",
                              keyboard)
            user_states[user_id] = STATES['SCHEDULE_DAY_PERIOD']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при обработке месяца: {e}")
            self.send_message(user_id, "❌ Ошибка! Попробуйте выбрать месяц еще раз")

    def process_schedule_day_period(self, user_id, period_data):
        """Обрабатывает выбор периода дней для расписания"""
        try:
            start_day = int(period_data["start"])
            end_day = int(period_data["end"])
            month = int(user_data[user_id]["schedule_month"])
            year = int(user_data[user_id]["schedule_year"])

            # Получаем список доступных дней в периоде
            available_days = []
            for day in range(start_day, end_day + 1):
                date = f"{year}-{month:02d}-{day:02d}"
                reservations = get_reservations_for_date(date)
                if reservations:  # Показываем только дни с бронированиями
                    available_days.append(day)

            if not available_days:
                self.send_message(user_id, "❌ В выбранном периоде нет дней с бронированиями. Выберите другой период.")
                return

            # Создаем клавиатуру с днями
            keyboard = VkKeyboard(inline=True)
            for i, day in enumerate(available_days):
                keyboard.add_button(str(day), color=VkKeyboardColor.PRIMARY,
                                    payload={"action": "schedule_select_day", "day": day})

                if (i + 1) % 4 == 0 and i != len(available_days) - 1:
                    keyboard.add_line()

            keyboard.add_line()
            keyboard.add_button("Назад к периодам дней", color=VkKeyboardColor.SECONDARY,
                                payload={"action": "schedule_back_to_day_periods"})

            month_name = self.get_month_name(month)
            self.send_message(user_id,
                              f"📅 Выберите день ({month_name} {year}):",
                              keyboard)
            user_states[user_id] = STATES['SCHEDULE_DAY_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при обработке периода дней: {e}")
            self.send_message(user_id, "❌ Ошибка! Попробуйте выбрать период еще раз")

    def process_schedule_day_selection(self, user_id, day):
        """Показывает расписание для выбранного дня с автором и названием мероприятия"""
        try:
            day = int(day)
            month = int(user_data[user_id]["schedule_month"])
            year = int(user_data[user_id]["schedule_year"])
            date = f"{year}-{month:02d}-{day:02d}"

            # Получаем бронирования из базы данных
            conn = sqlite3.connect('reservations.db')
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, username, author_name, event_name, date, time, duration
                FROM reservations
                WHERE date = ?
                ORDER BY time
            """, (date,))
            reservations = cursor.fetchall()
            conn.close()

            if not reservations:
                self.send_message(user_id, f"❌ На {day}.{month:02d}.{year} нет бронирований.")
                return

            # Формируем красивое сообщение
            message = f"📅 Расписание на {day}.{month:02d}.{year}:\n\n"
            for i, res in enumerate(reservations, 1):
                message += (
                    f"{i}. {res[4]} - {res[2]}: {res[3]}\n"
                    f"Автор: {res[1]}\n"
                    f"Время: {res[5]}\n"
                    f"Длительность: {res[6]} мин\n\n"
                )

            # Клавиатура для навигации
            keyboard = VkKeyboard(inline=True)
            keyboard.add_button("Выбрать другой день", color=VkKeyboardColor.PRIMARY,
                                payload={"action": "schedule_back_to_days"})
            keyboard.add_line()
            keyboard.add_button("Новое расписание", color=VkKeyboardColor.PRIMARY,
                                payload={"action": "show_all_reservations"})
            keyboard.add_button("Главное меню", color=VkKeyboardColor.SECONDARY,
                                payload={"action": "main_menu"})

            self.send_message(user_id, message, keyboard)
            user_states[user_id] = STATES['START']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при показе расписания: {e}")
            self.send_message(user_id, "❌ Произошла ошибка. Попробуйте позже.")

    def process_month_for_view(self, user_id, month):
        """Обрабатывает выбор месяца для просмотра расписания"""
        try:
            # Инициализируем данные пользователя
            if user_id not in user_data:
                user_data[user_id] = {}

            # Сохраняем выбранный месяц
            month = int(month)
            user_data[user_id]["view_month"] = f"{month:02d}"
            year = int(user_data[user_id].get("view_year", str(datetime.now().year)))

            # Получаем клавиатуру с днями месяца
            keyboard = self.get_days_keyboard(user_id, year, month, "day")

            # Добавляем кнопки навигации
            keyboard.add_line()
            keyboard.add_button("Выбрать другой месяц", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "show_all_reservations"})
            keyboard.add_button("Главное меню", color=VkKeyboardColor.SECONDARY,
                                payload={"button": "main_menu"})

            month_name = self.get_month_name(month)
            self.send_message(user_id, f"📅 Выберите день ({month_name} {year}):", keyboard)
            user_states[user_id] = STATES['SELECT_DAY']

        except ValueError:
            logger.error(f"Ошибка при обработке месяца для пользователя {user_id}: некорректный формат месяца {month}")
            self.send_message(user_id, "❌ Ошибка! Попробуйте выбрать месяц еще раз")
        except Exception as e:
            logger.error(f"Ошибка при обработке месяца для пользователя {user_id}: {e}")
            self.send_message(user_id, "❌ Произошла ошибка. Попробуйте позже.")

    def process_day_for_view(self, user_id, day):
        """Показывает расписание для выбранного дня"""
        try:
            # Проверяем и инициализируем данные пользователя
            if user_id not in user_data:
                user_data[user_id] = {}

            # Форматируем день
            day = day.zfill(2) if len(day) == 1 else day
            year = user_data[user_id].get("view_year", str(datetime.now().year))
            month = user_data[user_id].get("view_month", f"{datetime.now().month:02d}")

            # Проверяем корректность даты
            try:
                selected_date = f"{year}-{month}-{day}"
                datetime.strptime(selected_date, "%Y-%m-%d")
            except ValueError:
                raise ValueError("Некорректная дата")

            # Получаем бронирования для выбранной даты
            reservations = get_reservations_for_date(selected_date)

            # Формируем таблицу с расписанием
            time_slots = [
                "05:00", "05:30", "06:00", "06:30", "07:00", "07:30",
                "08:00", "08:30", "09:00", "09:30", "10:00", "10:30",
                "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
                "14:00", "14:30", "15:00", "15:30", "16:00", "16:30",
                "17:00", "17:30", "18:00", "18:30", "19:00", "19:30"
            ]

            # Создаем словарь занятых слотов
            occupied_slots = {}
            for res in reservations:
                _, _, author, event, _, time_str, duration = res
                try:
                    start_time = datetime.strptime(time_str, "%H:%M")
                    duration = int(duration) if duration else 60
                    end_time = start_time + timedelta(minutes=duration)

                    current_time = start_time
                    while current_time < end_time:
                        slot_key = current_time.strftime("%H:%M")
                        if slot_key not in occupied_slots:
                            occupied_slots[slot_key] = []
                        occupied_slots[slot_key].append(
                            f"{event} ({author}, {duration} мин)"
                        )
                        current_time += timedelta(minutes=30)
                except Exception as e:
                    logger.error(f"Ошибка обработки времени брони {time_str}: {e}")
                    continue

            # Формируем текст сообщения
            formatted_date = f"{day}.{month}.{year}"
            message = f"📅 Расписание на {formatted_date}:\n\n"

            for slot in time_slots:
                if slot in occupied_slots:
                    message += f"🕒 {slot} - 🟥 ЗАНЯТО\n"
                    for detail in occupied_slots[slot]:
                        message += f"   • {detail}\n"
                else:
                    message += f"🕒 {slot} - 🟩 СВОБОДНО\n"

            # Создаем клавиатуру для навигации
            keyboard = VkKeyboard(inline=True)
            keyboard.add_button("Выбрать другой день", color=VkKeyboardColor.PRIMARY,
                                payload={"button": f"mo_{month}"})
            keyboard.add_line()
            keyboard.add_button("Выбрать другой месяц", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "show_all_reservations"})
            keyboard.add_line()
            keyboard.add_button("Главное меню", color=VkKeyboardColor.SECONDARY,
                                payload={"button": "main_menu"})

            self.send_message(user_id, message, keyboard)
            user_states[user_id] = STATES['START']

        except ValueError as e:
            logger.error(f"Ошибка даты для пользователя {user_id}: {e}")
            self.send_message(user_id, f"❌ Ошибка: {str(e)}", self.get_main_keyboard())
        except Exception as e:
            logger.error(f"Ошибка при получении расписания для пользователя {user_id}: {e}", exc_info=True)
            self.send_message(user_id, "❌ Произошла ошибка при загрузке расписания. Попробуйте позже.",
                              self.get_main_keyboard())
            user_states[user_id] = STATES['START']

    def process_cancel_confirmation(self, user_id, reservation_id):
        """Запрашивает подтверждение отмены бронирования"""
        user_data[user_id]["cancel_reservation_id"] = reservation_id

        keyboard = VkKeyboard(inline=True)
        keyboard.add_button("✅ Подтвердить", color=VkKeyboardColor.POSITIVE,
                            payload={"button": f"confirm_cancel_{reservation_id}"})
        keyboard.add_button("❌ Отмена", color=VkKeyboardColor.NEGATIVE,
                            payload={"button": "cancel_cancel"})

        self.send_message(user_id, "Вы уверены, что хотите отменить бронь?", keyboard)

    def process_confirm_cancel(self, user_id, reservation_id):
        """Удаляет бронирование после подтверждения"""
        success = delete_reservation(reservation_id)

        if success:
            self.send_message(user_id, "✅ Бронирование успешно отменено.", self.get_main_keyboard())
        else:
            self.send_message(user_id, "⚠️ Ошибка! Возможно, бронь уже была удалена.", self.get_main_keyboard())

    def find_nearest_available_time(self, date, duration):
        """Находит ближайшее доступное время на выбранную дату"""
        try:
            reservations = get_reservations_for_date(date)
            booked_slots = []

            for res in reservations:
                try:
                    time_str = res[2]
                    res_duration = int(res[3]) if len(res) > 3 else 60
                    start = datetime.strptime(time_str, "%H:%M")
                    booked_slots.append((
                        start.hour * 60 + start.minute,
                        start.hour * 60 + start.minute + res_duration
                    ))
                except:
                    continue

            # Проверяем все возможные часы (с 5:00 до 20:00)
            for hour in range(5, 21):
                for minute in [0, 15, 30, 45]:
                    start_min = hour * 60 + minute
                    end_min = start_min + duration

                    if all(end_min <= bs[0] or start_min >= bs[1] for bs in booked_slots):
                        return f"{hour:02d}:{minute:02d}"

            return None
        except Exception as e:
            logger.error(f"Ошибка поиска ближайшего времени: {e}")
            return None

    def process_edit_selection(self, user_id, booking_id):
        """Показывает меню редактирования с полной очисткой состояния"""
        # Полная очистка предыдущих данных
        user_data[user_id] = {
            'edit_reservation_id': booking_id,
            'edit_state': 'selection'
        }

        keyboard = VkKeyboard(inline=True)
        buttons = [
            ("📅 Дата", "edit_date"),
            ("⏰ Время", "edit_time"),
            ("👤 Имя", "edit_author"),
            ("📌 Событие", "edit_event"),
            ("🕒 Длительность", "edit_duration"),
            ("❌ Отмена", "edit_cancel")
        ]

        # Добавляем кнопки с разбивкой по строкам
        for i, (text, action) in enumerate(buttons):
            if i % 2 == 0 and i != 0:
                keyboard.add_line()
            keyboard.add_button(text, color=VkKeyboardColor.PRIMARY,
                                payload={"button": action})

        self.send_message(user_id, "Выберите что изменить:", keyboard)
        user_states[user_id] = STATES['EDIT_SELECTION']

    def process_edit_date(self, user_id):
        """Начинает процесс редактирования даты"""
        user_data[user_id].update({
            'edit_field': 'date',
            'edit_state': 'date_selection'
        })

        # Клавиатура с периодами месяцев (не более 2 кнопок в строке)
        keyboard = VkKeyboard(inline=True)

        # Используем единый формат для всех периодов
        keyboard.add_button("Январь-Апрель",
                            color=VkKeyboardColor.PRIMARY,
                            payload={"button": "edit_month_period_1_4"})
        keyboard.add_button("Май-Август",
                            color=VkKeyboardColor.PRIMARY,
                            payload={"button": "edit_month_period_5_8"})
        keyboard.add_line()
        keyboard.add_button("Сентябрь-Декабрь",
                            color=VkKeyboardColor.PRIMARY,
                            payload={"button": "edit_month_period_9_12"})

        self.send_message(user_id, "Выберите период месяцев:", keyboard)
        user_states[user_id] = STATES['EDIT_DATE_SELECTION']

    def process_edit_month_period_selection(self, user_id, period):
        """Обрабатывает выбор периода месяцев"""
        try:
            period_map = {
                "edit_month_period_1_4": [1, 2, 3, 4],
                "edit_month_period_5_8": [5, 6, 7, 8],
                "edit_month_period_9_12": [9, 10, 11, 12]
            }

            # Проверяем, что период допустим
            if period not in period_map:
                raise ValueError(f"Неверный период месяцев: {period}")

            current_year = datetime.now().year
            current_month = datetime.now().month

            # Создаем клавиатуру с доступными месяцами
            keyboard = VkKeyboard(inline=True)
            for i, month in enumerate(period_map[period]):
                year = current_year + 1 if month < current_month else current_year
                month_name = self.get_month_name(month)

                keyboard.add_button(f"{month_name} {year}" if year > current_year else month_name,
                                    color=VkKeyboardColor.PRIMARY,
                                    payload={"button": f"edit_select_month_{month}_{year}"})

                if i % 2 == 1 and i != len(period_map[period]) - 1:
                    keyboard.add_line()

            self.send_message(user_id, "Выберите конкретный месяц:", keyboard)
            user_states[user_id] = STATES['EDIT_MONTH_SELECTION']

        except ValueError as e:
            logger.error(f"[{user_id}] Неверный период месяцев: {period}")
            self.send_message(user_id, "❌ Неверный период месяцев. Пожалуйста, выберите из предложенных вариантов.",
                              self.get_main_keyboard())
        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при выборе периода месяцев: {e}")
            self.send_message(user_id, "❌ Ошибка! Попробуйте выбрать период еще раз.",
                              self.get_main_keyboard())

    def process_edit_month_selection(self, user_id, month_data):
        try:
            month = month_data["month"]
            year = month_data["year"]

            logger.info(f"[{user_id}] Выбран месяц: {month}, год: {year}")  # Логируем

            user_data[user_id].update({
                'edit_month': int(month),  # Сохраняем как число
                'edit_year': int(year)  # Сохраняем как число
            })

            self.send_message(user_id, f"📅 Введите число месяца:")
            user_states[user_id] = STATES['EDIT_DAY_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка в process_edit_month_selection: {e}")
            self.send_message(user_id, "❌ Ошибка выбора месяца. Попробуйте снова.")
            self.reset_user_state(user_id)

    def process_edit_day_selection(self, user_id, day_input):
        """Обрабатывает ввод дня при редактировании"""
        try:
            day = int(day_input)
            month = int(user_data[user_id]["edit_month"])  # Преобразуем в int
            year = int(user_data[user_id]["edit_year"])  # Преобразуем в int

            # Проверяем корректность дня
            _, last_day = monthrange(year, month)  # Теперь month - число
            if day < 1 or day > last_day:
                self.send_message(user_id, f"❌ В этом месяце дней от 1 до {last_day}. Попробуйте снова.")
                return

            # Формируем новую дату (добавляем ведущие нули)
            new_date = f"{year}-{month:02d}-{day:02d}"

            # Если это часть потока редактирования времени
            if user_data[user_id].get("edit_state") == "time_edit_flow":
                user_data[user_id]["new_date"] = new_date
                # Переходим к выбору времени
                self.show_edit_time_options(user_id)
            else:
                # Обновляем бронирование
                reservation_id = user_data[user_id]["edit_reservation_id"]
                if update_reservation(reservation_id, {'date': new_date}):
                    self.send_message(user_id, f"✅ Дата успешно изменена на {new_date}!",
                                      self.get_main_keyboard())
                else:
                    raise Exception("Ошибка при обновлении даты")
                self.reset_user_state(user_id)

        except ValueError:
            self.send_message(user_id, "❌ Пожалуйста, введите число месяца (например, 15).")
        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при вводе дня: {e}")
            self.send_message(user_id, "❌ Ошибка при обновлении даты. Попробуйте снова.",
                              self.get_main_keyboard())
            self.reset_user_state(user_id)

    def process_edit_time(self, user_id):
        """Начинает процесс редактирования времени"""
        try:
            reservation_id = user_data[user_id]["edit_reservation_id"]

            # Получаем текущее бронирование
            conn = sqlite3.connect('reservations.db')
            cursor = conn.cursor()
            cursor.execute("SELECT date, time FROM reservations WHERE id = ?", (reservation_id,))
            result = cursor.fetchone()
            conn.close()

            if not result:
                raise Exception("Бронирование не найдено")

            current_date, current_time = result

            # Сохраняем данные для процесса редактирования
            user_data[user_id].update({
                'edit_field': 'time',
                'edit_state': 'time_edit_flow',  # Флаг для отслеживания потока редактирования
                'original_date': current_date,
                'original_time': current_time,
                'new_date': current_date,  # По умолчанию оставляем текущую дату
                'new_time': None
            })

            # Предлагаем изменить дату
            keyboard = VkKeyboard(inline=True)
            keyboard.add_button("Изменить дату", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "edit_time_change_date"})
            keyboard.add_line()
            keyboard.add_button("Оставить текущую дату", color=VkKeyboardColor.SECONDARY,
                                payload={"button": "edit_time_keep_date"})

            self.send_message(user_id,
                              f"Текущая дата: {current_date}\n"
                              f"Хотите изменить дату бронирования?",
                              keyboard)
            user_states[user_id] = STATES['EDIT_TIME_DATE_CHOICE']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при начале редактирования времени: {e}")
            self.send_message(user_id, "❌ Ошибка при получении данных бронирования.",
                              self.get_main_keyboard())
            self.reset_user_state(user_id)

    def show_edit_month_periods(self, user_id):
        """Показывает периоды месяцев для выбора даты (единый формат)"""
        try:
            keyboard = VkKeyboard(inline=True)

            # Используем тот же формат, что и в process_edit_date
            keyboard.add_button("Январь-Апрель", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "edit_month_period_1_4"})
            keyboard.add_line()
            keyboard.add_button("Май-Август", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "edit_month_period_5_8"})
            keyboard.add_line()
            keyboard.add_button("Сентябрь-Декабрь", color=VkKeyboardColor.PRIMARY,
                                payload={"button": "edit_month_period_9_12"})

            self.send_message(user_id, "Выберите период месяцев:", keyboard)
            user_states[user_id] = STATES['EDIT_DATE_SELECTION']
        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при показе периодов месяцев: {e}")
            self.send_message(user_id, "❌ Ошибка при загрузке периодов месяцев.")
            self.reset_user_state(user_id)

    def process_edit_time_date_choice(self, user_id, choice):
        """Обрабатывает выбор изменения даты в процессе редактирования времени"""
        try:
            if choice == "edit_time_change_date":
                # Устанавливаем флаг, что мы в процессе редактирования времени
                user_data[user_id]["edit_state"] = "time_edit_flow"
                # Очищаем предыдущие данные о дате
                if "edit_date" in user_data[user_id]:
                    del user_data[user_id]["edit_date"]

                # Показываем периоды месяцев для выбора новой даты
                self.show_edit_month_periods(user_id)

            elif choice == "edit_time_keep_date":
                # Переходим сразу к выбору времени
                self.show_edit_time_options(user_id)

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при выборе даты: {e}")
            self.send_message(user_id, "❌ Ошибка при обработке выбора. Пожалуйста, попробуйте снова.",
                              self.get_main_keyboard())
            self.reset_user_state(user_id)

    def process_edit_date_selection(self, user_id, button):
        """Обрабатывает выбор периода месяцев"""
        try:
            periods = {
                "edit_month_period_1_4": ["01", "02", "03", "04"],
                "edit_month_period_5_8": ["05", "06", "07", "08"],
                "edit_month_period_9_12": ["09", "10", "11", "12"]
            }

            if button not in periods:
                raise ValueError("Неверный период месяцев")

            current_year = datetime.now().year
            current_month = datetime.now().month

            keyboard = VkKeyboard(inline=True)
            months = periods[button]

            for i in range(0, len(months), 2):
                month1 = months[i]
                month_name1 = self.get_month_name(int(month1))
                year = current_year + 1 if int(month1) < current_month else current_year
                keyboard.add_button(month_name1, color=VkKeyboardColor.PRIMARY,
                                    payload={"button": f"edit_select_month_{month1}_{year}"})

                if i + 1 < len(months):
                    month2 = months[i + 1]
                    month_name2 = self.get_month_name(int(month2))
                    year = current_year + 1 if int(month2) < current_month else current_year
                    keyboard.add_button(month_name2, color=VkKeyboardColor.PRIMARY,
                                        payload={"button": f"edit_select_month_{month2}_{year}"})

                if i + 2 < len(months):
                    keyboard.add_line()

            self.send_message(user_id, "Выберите месяц:", keyboard)
            user_states[user_id] = STATES['EDIT_MONTH_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при выборе периода месяцев: {e}")
            self.send_message(user_id, "❌ Ошибка при выборе периода. Пожалуйста, попробуйте снова.",
                              self.get_main_keyboard())
            self.reset_user_state(user_id)

    def get_month_name(self, month_num):
        """Возвращает название месяца по номеру (формат '01'-'12')"""
        try:
            month_num = int(month_num)  # Преобразуем строку в число
            months = {
                1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
                5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
                9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
            }
            return months.get(month_num, "Неизвестный месяц")
        except (ValueError, TypeError):
            return "Неизвестный месяц"

    def process_edit_date_success(self, user_id):
        """Вызывается после успешного изменения даты"""
        try:
            # Store the edited date in user_data
            user_data[user_id]["new_date"] = user_data[user_id].get("edit_date")

            # Set the state to indicate we're in time editing flow
            user_data[user_id]["edit_state"] = "time_edit_flow"

            # Continue with time editing
            self.show_edit_time_options(user_id)
        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при продолжении редактирования времени: {e}")
            self.send_message(user_id, "❌ Ошибка при обработке новой даты.",
                              self.get_main_keyboard())
            self.reset_user_state(user_id)

    def show_edit_time_options(self, user_id):
        """Показывает варианты выбора времени для редактирования"""
        try:
            date = user_data[user_id]["new_date"]
            reservation_id = user_data[user_id]["edit_reservation_id"]

            # Get booked time slots (excluding current reservation)
            conn = sqlite3.connect('reservations.db')
            cursor = conn.cursor()
            cursor.execute("""
                SELECT time, duration FROM reservations 
                WHERE date = ? AND id != ?
            """, (date, reservation_id))
            booked_slots = cursor.fetchall()
            conn.close()

            # Create list of booked intervals
            booked_intervals = []
            for time, duration in booked_slots:
                start = datetime.strptime(time, "%H:%M")
                start_minutes = start.hour * 60 + start.minute
                end_minutes = start_minutes + int(duration)
                booked_intervals.append((start_minutes, end_minutes))

            # Check available hours (5:00 - 20:00)
            available_hours = []
            for hour in range(5, 20):
                start_minutes = hour * 60
                end_minutes = start_minutes + 60  # minimum duration 60 min

                # Check overlap with existing bookings
                is_available = True
                for booked_start, booked_end in booked_intervals:
                    if not (end_minutes <= booked_start or start_minutes >= booked_end):
                        is_available = False
                        break

                if is_available:
                    available_hours.append(f"{hour:02d}")

            if not available_hours:
                self.send_message(user_id, "❌ На выбранную дату нет свободного времени.")
                return

            user_data[user_id]["available_hours"] = available_hours

            # Create keyboard with time periods
            keyboard = VkKeyboard(inline=True)
            periods = [
                ("5:00-8:00", {"button": "edit_time_period_5_8"}),  # Формат edit_time_period_X_Y
                ("9:00-12:00", {"button": "edit_time_period_9_12"}),
                ("13:00-16:00", {"button": "edit_time_period_13_16"}),
                ("17:00-20:00", {"button": "edit_time_period_17_20"})
            ]

            # Place 2 buttons per row
            # Добавляем кнопки (по 2 в строку)
            for i in range(0, len(periods), 2):
                text1, payload1 = periods[i]
                keyboard.add_button(text1, color=VkKeyboardColor.PRIMARY, payload=payload1)

                if i + 1 < len(periods):
                    text2, payload2 = periods[i + 1]
                    keyboard.add_button(text2, color=VkKeyboardColor.PRIMARY, payload=payload2)

                if i + 2 < len(periods):
                    keyboard.add_line()

            self.send_message(user_id, f"🕒 Выберите период времени для {date}:", keyboard)
            user_states[user_id] = STATES['EDIT_TIME_PERIOD_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при показе времени: {e}")
            self.send_message(user_id, "❌ Ошибка при загрузке расписания. Попробуйте позже.")
            self.reset_user_state(user_id)

    def show_edit_time_periods(self, user_id):
        """Показывает доступные периоды времени для редактирования"""
        try:
            date = user_data[user_id]["edit_date"]
            reservation_id = user_data[user_id]["edit_reservation_id"]

            # Получаем занятые слоты времени
            conn = sqlite3.connect('reservations.db')
            cursor = conn.cursor()
            cursor.execute("""
                SELECT time, duration FROM reservations 
                WHERE date = ? AND id != ?
            """, (date, reservation_id))
            reservations = cursor.fetchall()
            conn.close()

            # Формируем список занятых слотов
            booked_slots = []
            for time, duration in reservations:
                start = datetime.strptime(time, "%H:%M")
                start_minutes = start.hour * 60 + start.minute
                end_minutes = start_minutes + int(duration)
                booked_slots.append((start_minutes, end_minutes))

            # Проверяем доступные часы
            available_hours = []
            for hour in range(5, 20):
                start_minutes = hour * 60
                end_minutes = start_minutes + 60  # минимальная длительность

                # Проверяем пересечение с существующими бронированиями
                is_available = True
                for booked_start, booked_end in booked_slots:
                    if not (end_minutes <= booked_start or start_minutes >= booked_end):
                        is_available = False
                        break

                if is_available:
                    available_hours.append(f"{hour:02d}")

            if not available_hours:
                self.send_message(user_id, "❌ На выбранную дату нет свободного времени.")
                return

            user_data[user_id]["edit_available_hours"] = available_hours

            # Создаем клавиатуру с периодами
            keyboard = VkKeyboard(inline=True)
            periods = [
                ("5-8", "edit_hour_period_5_8"),
                ("9-12", "edit_hour_period_9_12"),
                ("13-16", "edit_hour_period_13_16"),
                ("17-19", "edit_hour_period_17_19")
            ]

            for i, (text, action) in enumerate(periods):
                if i % 2 == 0 and i != 0:
                    keyboard.add_line()
                keyboard.add_button(text, color=VkKeyboardColor.PRIMARY,
                                    payload={"button": action})

            self.send_message(user_id, f"🕒 Выберите период времени для {date}:", keyboard)
            user_states[user_id] = STATES['EDIT_HOUR_PERIOD_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при показе периодов времени: {e}")
            self.send_message(user_id, "❌ Ошибка при загрузке доступного времени. Попробуйте позже.",
                              self.get_main_keyboard())

    def process_edit_hour_period_selection(self, user_id, period):
        """Обрабатывает выбор периода часов при редактировании"""
        try:
            if isinstance(period, dict) and 'button' in period:
                button = period['button']
                if button.startswith('edit_hour_period_'):
                    parts = button.split('_')
                    start = int(parts[3])
                    end = int(parts[4])

                    available_hours = user_data[user_id]["edit_available_hours"]
                    hours_in_period = [f"{h:02d}" for h in range(start, end + 1)
                                       if f"{h:02d}" in available_hours]

                    if not hours_in_period:
                        self.send_message(user_id, "❌ В выбранном периоде нет свободных часов.")
                        return

                    keyboard = VkKeyboard(inline=True)
                    for i, hour in enumerate(hours_in_period):
                        keyboard.add_button(hour, color=VkKeyboardColor.PRIMARY,
                                            payload={"button": f"edit_hour_{hour}"})
                        if (i + 1) % 3 == 0 and i != len(hours_in_period) - 1:
                            keyboard.add_line()

                    self.send_message(user_id, "Выберите час:", keyboard)
                    user_states[user_id] = STATES['EDIT_HOUR_SELECTION']
                else:
                    self.send_message(user_id, "❌ Неверный формат периода.")
            else:
                self.send_message(user_id, "❌ Пожалуйста, используйте кнопки.")

        except Exception as e:
            logger.error(f"Ошибка при выборе периода часов: {e}")
            self.send_message(user_id, "❌ Ошибка! Попробуйте снова.")

    def process_edit_hour_selection(self, user_id, payload):
        """Обрабатывает выбор часа при редактировании"""
        try:
            logger.debug(f"[{user_id}] Получен payload: {payload}")

            if not payload or not isinstance(payload, dict) or 'button' not in payload:
                raise ValueError("Неверный формат запроса")

            button = payload['button']

            if not button.startswith('edit_hour_'):
                raise ValueError("Неверный формат кнопки часа")

            # Извлекаем час из кнопки
            hour = button.split('_')[-1]

            # Проверяем формат часа
            if not hour.isdigit() or len(hour) != 2:
                raise ValueError("Некорректный формат часа")

            # Сохраняем выбранный час
            user_data[user_id]["edit_hour"] = hour
            logger.debug(f"[{user_id}] Сохранен час: {hour}")

            # Убедимся, что у нас есть все необходимые данные
            if "edit_date" not in user_data[user_id] and "new_date" in user_data[user_id]:
                user_data[user_id]["edit_date"] = user_data[user_id]["new_date"]

            if "edit_date" not in user_data[user_id]:
                raise ValueError("Отсутствует дата для изменения")

            # Показываем клавиатуру с минутами
            self._show_minute_keyboard(user_id)

        except ValueError as e:
            logger.warning(f"[{user_id}] Ошибка валидации: {str(e)}")
            self.send_message(user_id, f"❌ {str(e)}\nПожалуйста, выберите час снова.")
        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка: {str(e)}", exc_info=True)
            self.send_message(user_id, "❌ Системная ошибка. Пожалуйста, начните заново.")
            self.reset_user_state(user_id)

    def process_edit_time_period_selection(self, user_id, payload):
        """Обрабатывает выбор периода времени при редактировании"""
        logger.debug(f"[{user_id}] Текущее состояние: {user_states.get(user_id)}")

        try:
            if not payload or 'button' not in payload:
                raise ValueError("Неверный формат запроса")

            button = payload['button']
            logger.debug(f"[{user_id}] Полученная кнопка: {button}")  # Логирование полученной кнопки

            if not button.startswith('edit_time_period_'):
                raise ValueError("Неверный тип кнопки периода")

            # Извлекаем границы периода из кнопки (формат: edit_time_period_5_8)
            _, _, _, start_str, end_str = button.split('_')
            start_hour = int(start_str)
            end_hour = int(end_str)

            # Получаем доступные часы для этого периода
            available_hours = user_data[user_id]["available_hours"]
            hours_in_period = [h for h in available_hours
                               if start_hour <= int(h) <= end_hour]

            if not hours_in_period:
                self.send_message(user_id, "❌ В выбранном периоде нет свободных часов.")
                return

            # Создаем клавиатуру с доступными часами
            keyboard = VkKeyboard(inline=True)
            for i, hour in enumerate(hours_in_period):
                # Убедимся, что hour - строка с двузначным числом
                if not isinstance(hour, str) or not hour.isdigit():
                    logger.error(f"Некорректный час в available_hours: {hour}")
                    continue

                keyboard.add_button(
                    hour,
                    color=VkKeyboardColor.PRIMARY,
                    payload={"button": f"edit_hour_{hour}"}  # Формат: edit_hour_09
                )
                if (i + 1) % 3 == 0 and i != len(hours_in_period) - 1:
                    keyboard.add_line()

            self.send_message(user_id, "Выберите час:", keyboard)
            user_states[user_id] = STATES['EDIT_HOUR_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка выбора периода: {e}")
            self.send_message(user_id, "❌ Ошибка! Пожалуйста, начните заново.")
            user_states[user_id] = STATES['START']

    def process_edit_time_hour_selection(self, user_id, payload):
        """Обрабатывает выбор часа при редактировании времени"""
        try:
            logger.debug(f"[{user_id}] Начало обработки выбора часа, payload: {payload}")

            # Проверяем структуру payload
            if not payload or not isinstance(payload, dict) or 'button' not in payload:
                raise ValueError("Неверный формат запроса")

            button = payload['button']
            logger.debug(f"[{user_id}] Получена кнопка: {button}")

            # Проверяем формат кнопки часа
            if not button.startswith('edit_hour_'):
                raise ValueError("Неверный формат кнопки часа")

            # Извлекаем час из кнопки
            hour = button.split('_')[-1]

            # Проверяем формат часа
            if not hour.isdigit() or len(hour) != 2:
                raise ValueError("Некорректный формат часа")

            # Сохраняем выбранный час
            user_data[user_id]["edit_hour"] = hour
            logger.debug(f"[{user_id}] Сохранен час: {hour}")

            # Просим ввести минуты текстом
            self.send_message(
                user_id,
                f"Вы выбрали час {hour}. Теперь введите минуты (00, 15, 30 или 45):",
                self.get_cancel_keyboard()  # Клавиатура с кнопкой отмены
            )
            user_states[user_id] = STATES['EDIT_TIME_MINUTE_SELECTION']

        except ValueError as e:
            logger.warning(f"[{user_id}] Ошибка валидации: {str(e)}")
            self.send_message(
                user_id,
                f"❌ {str(e)}\nПожалуйста, выберите час снова.",
                self.get_hour_keyboard()
            )

        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка: {str(e)}", exc_info=True)
            self.send_message(
                user_id,
                "❌ Системная ошибка. Пожалуйста, начните заново.",
                self.get_main_keyboard()
            )
            self.reset_user_state(user_id)

    def process_edit_time_minute_selection(self, user_id, text):
        """Обработчик ввода минут"""
        try:
            logger.debug(f"[{user_id}] Обработка ввода минут: {text}")

            # Проверяем введенные минуты
            minute = text.strip()
            if minute not in ["00", "15", "30", "45"]:
                raise ValueError("Пожалуйста, введите одно из допустимых значений минут: 00, 15, 30 или 45")

            # Проверяем наличие всех необходимых данных
            required_keys = ["edit_hour", "new_date", "edit_reservation_id"]
            if not all(key in user_data.get(user_id, {}) for key in required_keys):
                raise ValueError("Отсутствуют необходимые данные")

            # Формируем новое время
            hour = user_data[user_id]["edit_hour"]
            date = user_data[user_id]["new_date"]
            reservation_id = user_data[user_id]["edit_reservation_id"]
            new_time = f"{hour}:{minute}"

            # Проверяем доступность времени
            conn = sqlite3.connect('reservations.db')
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM reservations 
                WHERE date = ? AND time = ? AND id != ?
            """, (date, new_time, reservation_id))

            if cursor.fetchone():
                conn.close()
                raise ValueError(f"Время {new_time} уже занято")

            # Обновляем бронирование
            cursor.execute("""
                UPDATE reservations 
                SET time = ?
                WHERE id = ?
            """, (new_time, reservation_id))
            conn.commit()
            conn.close()

            self.send_message(
                user_id,
                f"✅ Время успешно изменено на {new_time}",
                self.get_main_keyboard()
            )
            self.reset_user_state(user_id)

        except ValueError as e:
            logger.warning(f"[{user_id}] Ошибка валидации: {str(e)}")
            self.send_message(
                user_id,
                f"❌ {str(e)}\nПожалуйста, введите минуты снова (00, 15, 30 или 45):",
                self.get_cancel_keyboard()
            )

        except Exception as e:
            logger.error(f"[{user_id}] Критическая ошибка: {str(e)}", exc_info=True)
            self.send_message(
                user_id,
                "❌ Системная ошибка. Пожалуйста, начните заново.",
                self.get_main_keyboard()
            )
            self.reset_user_state(user_id)

    def _show_minute_keyboard(self, user_id, message="Выберите минуты:"):
        """Показывает клавиатуру выбора минут"""
        try:
            keyboard = VkKeyboard(inline=True)
            minutes = ["00", "15", "30", "45"]

            for i, minute in enumerate(minutes):
                if i % 2 == 0 and i != 0:
                    keyboard.add_line()
                keyboard.add_button(
                    minute,
                    color=VkKeyboardColor.PRIMARY,
                    payload={"button": f"edit_minute_{minute}"}
                )

            self.send_message(user_id, message, keyboard)
            user_states[user_id] = STATES['EDIT_MINUTE_SELECTION']

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при показе минут: {str(e)}")
            self.send_message(user_id, "❌ Ошибка при загрузке выбора минут.")
            self.reset_user_state(user_id)

    def process_edit_minute_selection(self, user_id, minute_input):
        """Обрабатывает выбор минут"""
        try:
            logger.debug(f"[{user_id}] Обработка выбора минут: {minute_input}")

            # Получаем минуты из ввода
            if isinstance(minute_input, dict) and "button" in minute_input:
                minute = minute_input["button"].split("_")[-1]
            else:
                minute = minute_input.strip().zfill(2)

            # Проверяем допустимые значения минут
            if minute not in ["00", "15", "30", "45"]:
                raise ValueError("Пожалуйста, выберите минуты из предложенных вариантов (00, 15, 30, 45)")

            # Проверяем наличие всех необходимых данных
            required_keys = ["edit_hour", "edit_reservation_id"]
            if not all(key in user_data.get(user_id, {}) for key in required_keys):
                raise ValueError("Отсутствуют необходимые данные для изменения времени")

            # Получаем дату (пробуем оба возможных ключа)
            date = user_data[user_id].get("edit_date") or user_data[user_id].get("new_date")
            if not date:
                raise ValueError("Отсутствует дата для изменения")

            hour = user_data[user_id]["edit_hour"]
            new_time = f"{hour}:{minute}"
            reservation_id = user_data[user_id]["edit_reservation_id"]

            # Проверяем доступность времени
            conn = sqlite3.connect('reservations.db')
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM reservations 
                WHERE date = ? AND time = ? AND id != ?
            """, (date, new_time, reservation_id))
            if cursor.fetchone():
                conn.close()
                raise Exception("Это время уже занято")

            # Обновляем бронирование
            cursor.execute("""
                UPDATE reservations 
                SET date = ?, time = ?
                WHERE id = ?
            """, (date, new_time, reservation_id))
            conn.commit()
            conn.close()

            self.send_message(user_id,
                              f"✅ Время успешно изменено!\n"
                              f"📅 Дата: {date}\n"
                              f"⏰ Время: {new_time}",
                              self.get_main_keyboard())

        except ValueError as e:
            logger.warning(f"[{user_id}] Ошибка валидации: {str(e)}")
            self._show_minute_keyboard(user_id, f"❌ {str(e)}")
        except Exception as e:
            logger.error(f"[{user_id}] Ошибка при обновлении времени: {e}")
            self.send_message(user_id, f"❌ Ошибка: {str(e)}", self.get_main_keyboard())
        finally:
            self.reset_user_state(user_id)

    def reset_user_state(self, user_id):
        """Сбрасывает состояние пользователя"""
        user_states[user_id] = STATES['START']
        if user_id in user_data:
            user_data[user_id].clear()

    def process_edit_author(self, user_id):
        """Начинает процесс изменения имени автора"""
        # Очищаем все предыдущие данные редактирования
        user_data[user_id].update({
            'edit_field': 'author_name',
            'edit_state': 'author_input'
        })

        self.send_message(user_id, "Введите новое имя автора:")
        user_states[user_id] = STATES['EDIT_INPUT']

    def process_edit_event(self, user_id):
        """Запрашивает ТОЛЬКО название мероприятия"""
        user_data[user_id].update({
            "edit_field": "event_name",
            'edit_state': 'event_input'
        })

        self.send_message(user_id, "Введите новое название мероприятия:")
        user_states[user_id] = STATES['EVENT_INPUT']

    def process_edit_duration(self, user_id):
        """Показывает клавиатуру для выбора новой длительности"""
        # Устанавливаем состояние редактирования длительности
        user_data[user_id].update({
            'edit_field': 'duration',
            'edit_state': 'duration_selection'
        })

        # Показываем клавиатуру с вариантами длительности
        keyboard = VkKeyboard(inline=True)
        durations = ["30", "60", "120", "180"]

        for i, duration in enumerate(durations):
            keyboard.add_button(f"{duration} мин", color=VkKeyboardColor.PRIMARY,
                                payload={"button": f"edit_duration_{duration}"})
            if i < len(durations) - 1:
                keyboard.add_line()  # Каждая кнопка на новой строке

        self.send_message(user_id, "Выберите новую длительность мероприятия:", keyboard)
        user_states[user_id] = STATES['EDIT_SELECTION']

    def process_edit_field_input(self, user_id, input_data):
        """Обрабатывает ввод данных для редактирования"""
        try:
            # Проверяем, что мы в режиме редактирования
            if user_id not in user_data or 'edit_reservation_id' not in user_data[user_id]:
                raise ValueError("Неверное состояние для редактирования")

            reservation_id = user_data[user_id]["edit_reservation_id"]
            field = user_data[user_id].get("edit_field")
            new_value = None

            # Обработка длительности (может приходить из кнопки или текстом)
            if field == 'duration':
                if isinstance(input_data, dict) and "button" in input_data:
                    if input_data["button"].startswith("edit_duration_"):
                        new_value = input_data["button"].split("_")[2]
                    else:
                        raise ValueError("Неверный формат данных длительности")
                else:
                    new_value = str(input_data).strip()

                if new_value not in ["30", "60", "120", "180"]:
                    self.process_edit_duration(user_id)
                    return

                new_value = int(new_value)
            else:
                new_value = str(input_data).strip()
                if not new_value:
                    raise ValueError("Значение не может быть пустым")

            # Обновление в базе данных
            if update_reservation(reservation_id, {field: new_value}):
                self.send_message(user_id, f"✅ {self.get_field_name(field)} успешно изменено на {new_value}!",
                                  self.get_main_keyboard())
            else:
                raise Exception("Ошибка при обновлении в базе данных")

        except Exception as e:
            self.send_message(user_id, f"❌ Ошибка: {str(e)}")
        finally:
            user_states[user_id] = STATES['START']
            if user_id in user_data:
                user_data[user_id].clear()

    def get_field_name(self, field):
        """Возвращает читаемое имя поля"""
        names = {
            'duration': 'Длительность мероприятия',
            'author_name': 'Имя автора',
            'event_name': 'Название мероприятия',
            'date': 'Дата',
            'time': 'Время'
        }
        return names.get(field, "Параметр")

    def process_cancel_edit(self, user_id):
        """Отменяет редактирование"""
        self.send_message(user_id, "❌ Редактирование отменено.", self.get_main_keyboard())
        user_states[user_id] = STATES['START']

    def get_time_keyboard(self):
        """Создает клавиатуру для выбора времени"""
        keyboard = VkKeyboard(inline=True)
        hours = ["09", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22"]

        row = 0
        for i in range(0, len(hours), 4):
            for j in range(4):
                if i + j < len(hours):
                    keyboard.add_button(hours[i + j], color=VkKeyboardColor.PRIMARY,
                                        payload={"button": f"hour_{hours[i + j]}:00"})
            row += 1
            if row < (len(hours) + 3) // 4:  # Если это не последняя строка
                keyboard.add_line()

        return keyboard

    def format_time_range(self, start_time, duration):
        """Формирует строку с промежутком времени бронирования."""
        try:
            if not isinstance(start_time, str) or not start_time.strip():
                raise ValueError("Пустое время")

            start = datetime.strptime(start_time.strip(), "%H:%M")
            end = start + timedelta(minutes=int(duration))
            return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"

        except ValueError as e:
            raise ValueError(
                f"Ошибка формата времени '{start_time}'. Требуется ЧЧ:ММ (например, 09:00). Оригинальная ошибка: {e}")

    def run(self):
        """Запускает основной цикл бота"""
        logger.info("Бот запущен...")
        for event in self.longpoll.listen():
            try:
                if event.type == VkEventType.MESSAGE_NEW and event.to_me:
                    user_id = event.user_id
                    text = event.text.strip()
                    payload = {}

                    # Проверяем наличие payload
                    try:
                        if hasattr(event, 'payload'):
                            payload = json.loads(event.payload)
                    except:
                        payload = {}

                    # Обработка состояний редактирования
                    if user_states.get(user_id) == STATES['EDIT_DAY_SELECTION'] and text:
                        self.process_edit_day_selection(user_id, text)

                    elif user_states.get(user_id) == STATES['EDIT_TIME_DATE_CHOICE']:
                        if payload and "button" in payload:
                            button = payload["button"]
                            if button in ["edit_time_change_date", "edit_time_keep_date"]:
                                self.process_edit_time_date_choice(user_id, button)

                    elif user_states.get(user_id) == STATES['EDIT_DATE_SELECTION']:
                        if payload and "button" in payload:
                            button = payload["button"]
                            if button in ["edit_month_period_1_4", "edit_month_period_5_8", "edit_month_period_9_12"]:
                                self.process_edit_date_selection(user_id, button)
                            else:
                                logger.error(f"[{user_id}] Получен недопустимый период: {button}")
                                self.send_message(user_id, "❌ Недопустимый период месяцев",
                                                  self.get_main_keyboard())


                    elif user_states.get(user_id) == STATES['EDIT_MONTH_SELECTION']:

                        if payload and "button" in payload:

                            button = payload["button"]

                            if button.startswith("edit_select_month_"):

                                parts = button.split("_")

                                if len(parts) >= 5:  # Проверяем, что есть все части

                                    month = parts[3]

                                    year = parts[4]

                                    self.process_edit_month_selection(user_id, {"month": month, "year": year})

                                else:

                                    logger.error(f"[{user_id}] Неверный формат кнопки месяца: {button}")

                                    self.send_message(user_id, "❌ Ошибка выбора месяца. Попробуйте снова.",

                                                      self.get_main_keyboard())

                    elif user_states.get(user_id) == STATES['EDIT_TIME_PERIOD_SELECTION']:
                        logger.debug(f"[{user_id}] Обработка EDIT_TIME_PERIOD_SELECTION, payload: {payload}")
                        if payload and "button" in payload:
                            button = payload["button"]
                            if button.startswith("edit_time_period_"):
                                self.process_edit_time_period_selection(user_id, payload)

                    elif user_states.get(user_id) == STATES['EDIT_TIME_HOUR_SELECTION']:
                        if payload and "button" in payload:
                            button = payload["button"]
                            if button.startswith("edit_hour_"):
                                hour = button.split('_')[-1]

                                # Проверяем наличие предыдущих данных

                                if user_id not in user_data:
                                    self.send_message(user_id, "❌ Сессия устарела", self.get_main_keyboard())
                                    self.reset_user_state(user_id)
                                    continue

                                # Сохраняем данные с проверкой

                                user_data[user_id].update({
                                    "edit_hour": hour,
                                    "new_date": user_data[user_id].get("edit_date", ""),
                                    "edit_reservation_id": user_data[user_id].get("edit_reservation_id", 0)
                                })

                                # Проверяем что все данные есть

                                if not all(user_data[user_id].get(k) for k in
                                           ["edit_hour", "new_date", "edit_reservation_id"]):
                                    self.send_message(user_id, "❌ Отсутствуют данные", self.get_main_keyboard())
                                    self.reset_user_state(user_id)
                                    continue
                                self._show_minute_keyboard(user_id, f"Вы выбрали {hour}:__. Теперь выберите минуты:")

                    elif user_states.get(user_id) == STATES['EDIT_TIME_MINUTE_SELECTION']:
                        # Обработка ввода минут текстом
                        self.process_edit_time_minute_selection(user_id, text)

                    elif user_states.get(user_id) == STATES['EDIT_HOUR_PERIOD_SELECTION']:
                        if payload and "button" in payload:
                            button = payload["button"]
                            if button.startswith("edit_hour_period_"):
                                self.process_edit_hour_period_selection(user_id, payload)

                    elif user_states.get(user_id) == STATES['EDIT_HOUR_SELECTION']:
                        if payload and "button" in payload:
                            button = payload["button"]
                            logger.debug(f"[{user_id}] Получена кнопка часа: {button}")  # Логирование
                            if button.startswith("edit_hour_"):
                                try:
                                    hour = button.split('_')[2]  # Получаем час из edit_hour_09
                                    self.process_edit_hour_selection(user_id, {"button": button})
                                except IndexError:
                                    logger.error(f"Неверный формат кнопки часа: {button}")
                                    self.send_message(user_id, "❌ Ошибка формата. Пожалуйста, выберите час снова.")

                    elif user_states.get(user_id) == STATES['EDIT_MINUTE_SELECTION']:
                        if payload and "button" in payload:
                            button = payload["button"]
                            if button.startswith("edit_minute_"):
                                self.process_edit_minute_selection(user_id, payload)

                    # Обработка текстовых команд
                    elif text == "начать" or text.lower() == "start" or text == "/start":
                        self.start(user_id)

                    elif text == "ℹ️ О боте":
                        self.about(user_id)

                    elif text == "📌 Бронь":
                        self.start_reservation(user_id)

                    elif text == "📅 Мои бронирования":
                        self.show_my_reservations(user_id)

                    elif text == "📆 Общее расписание":
                        self.show_all_reservations(user_id)

                    # Обработка payload с ключом "action"
                    elif payload and "action" in payload:
                        action = payload["action"]

                        if action == "main_menu":
                            self.start(user_id)

                        elif action == "show_all_reservations":
                            self.show_all_reservations(user_id)

                        elif action == "schedule_month_period":
                            if user_states.get(user_id) == STATES['SCHEDULE_MONTH_PERIOD']:
                                self.process_schedule_month_period(user_id, payload.get("period"))

                        elif action == "schedule_current_month":
                            self.process_schedule_month_period(user_id, "current")

                        elif action == "schedule_select_month":
                            if user_states.get(user_id) == STATES['SCHEDULE_MONTH_SELECTION']:
                                self.process_schedule_month_selection(user_id, payload)

                        elif action == "schedule_day_period":
                            if user_states.get(user_id) == STATES['SCHEDULE_DAY_PERIOD']:
                                self.process_schedule_day_period(user_id, payload)

                        elif action == "schedule_select_day":
                            if user_states.get(user_id) == STATES['SCHEDULE_DAY_SELECTION']:
                                self.process_schedule_day_selection(user_id, payload.get("day"))

                        elif action == "schedule_back_to_day_periods":
                            month_data = {
                                "month": user_data[user_id]["schedule_month"],
                                "year": user_data[user_id]["schedule_year"]
                            }
                            self.process_schedule_month_selection(user_id, month_data)

                        elif action == "schedule_back_to_days":
                            self.process_schedule_day_period(user_id, {
                                "start": user_data[user_id].get("period_start", 1),
                                "end": user_data[user_id].get("period_end", 7)
                            })

                    # Обработка payload с ключом "button"
                    elif payload and "button" in payload:
                        button = payload["button"]

                        if button.startswith("month_period_"):
                            if user_states.get(user_id) == STATES['MONTH_PERIOD_SELECTION']:
                                self.process_month_period_selection(user_id, button)

                        elif button.startswith("mo_"):
                            if user_states.get(user_id) == STATES['SELECT_MONTH']:
                                month = button.split("_")[1]
                                self.process_month_for_view(user_id, month)
                            elif user_states.get(user_id) == STATES['SELECT_DAY']:
                                month = button.split("_")[1]
                                self.process_month_for_view(user_id, month)

                        elif button.startswith("day_"):
                            if user_states.get(user_id) == STATES['SELECT_DAY']:
                                day = button.split("_")[1]
                                self.process_day_for_view(user_id, day)

                        elif button == "show_all_reservations":
                            self.show_all_reservations(user_id)

                        elif button == "edit_author":
                            self.process_edit_author(user_id)

                        elif button == "edit_event":
                            self.process_edit_event(user_id)

                        elif button == "edit_time":
                            self.process_edit_time(user_id)

                        elif button in ["edit_time_change_date", "edit_time_keep_date"]:
                            self.process_edit_time_date_choice(user_id, button)

                        elif button.startswith("edit_hour_period_"):
                            if user_states.get(user_id) == STATES['EDIT_HOUR_PERIOD_SELECTION']:
                                self.process_edit_hour_period_selection(user_id, payload)

                        elif button.startswith("edit_hour_"):
                            if user_states.get(user_id) == STATES['EDIT_HOUR_SELECTION']:
                                hour = button.split('_')[1]
                                self.process_edit_hour_selection(user_id, hour)

                        elif button.startswith("edit_minute_"):
                            if user_states.get(user_id) == STATES['EDIT_MINUTE_SELECTION']:
                                self.process_edit_minute_selection(user_id, payload)

                        elif button == "edit_date_back":
                            self.process_edit_date(user_id)

                        elif button.startswith("edit_duration_"):
                            if user_states.get(user_id) == STATES['EDIT_SELECTION']:
                                duration = button.split("_")[2]
                                self.process_edit_field_input(user_id, {"button": button})

                        elif button.startswith("edit_month_period_"):
                            self.process_edit_month_period_selection(user_id, button)

                        elif button.startswith("edit_select_month_"):
                            parts = button.split("_")
                            month = parts[3]
                            year = parts[4]
                            self.process_edit_month_selection(user_id, {"month": month, "year": year})

                        elif button.startswith("day_"):
                            day = button.split("_")[1]
                            self.process_day_selection(user_id, day)

                        elif button.startswith("hour_period_"):
                            if user_states.get(user_id) == STATES['HOUR_PERIOD_SELECTION']:
                                self.process_hour_period_selection(user_id, {"button": button})

                        elif button.startswith("hour_"):
                            hour = button.split("_")[1]
                            if user_states.get(user_id) == STATES['HOUR_SELECTION']:
                                self.process_hour_selection(user_id, hour)

                        elif button.startswith("minute_"):
                            minute = button.split("_")[1]
                            if user_states.get(user_id) == STATES['MINUTE_SELECTION']:
                                self.process_minute_selection(user_id, {"button": button})

                        elif button.startswith("duration_"):
                            duration = button.split("_")[1]
                            if user_states.get(user_id) == STATES['DURATION_SELECTION']:
                                self.process_duration_input(user_id, duration)

                        elif button.startswith("select_month_"):
                            if user_states.get(user_id) == STATES['MONTH_SELECTION']:
                                parts = button.split("_")
                                month = parts[2]
                                year = parts[3]
                                self.process_month_selection(user_id, {"month": month, "year": year})

                        elif button.startswith("day_period_"):
                            if user_states.get(user_id) == STATES['DAY_PERIOD_SELECTION']:
                                self.process_day_period_selection(user_id, button)
                            else:
                                logger.error(
                                    f"[{user_id}] Неверное состояние для day_period: {user_states.get(user_id)}")
                                self.send_message(user_id, "❌ Пожалуйста, начните процесс бронирования сначала.")
                                user_states[user_id] = STATES['START']

                        elif button.startswith("select_day_"):
                            if user_states.get(user_id) == STATES['DAY_SELECTION']:
                                day = button.split("_")[2]
                                self.process_day_selection(user_id, day)
                            else:
                                logger.error(
                                    f"[{user_id}] Неверное состояние для select_day: {user_states.get(user_id)}")
                                self.send_message(user_id, "❌ Пожалуйста, выберите период дней сначала.")

                        elif button.startswith("cancel_confirm_"):
                            reservation_id = button.split("_")[2]
                            self.process_cancel_confirmation(user_id, reservation_id)

                        elif button.startswith("confirm_cancel_"):
                            reservation_id = button.split("_")[2]
                            self.process_confirm_cancel(user_id, reservation_id)

                        elif button.startswith("edit_booking_"):
                            if user_states.get(user_id) == STATES['VIEW_RESERVATIONS']:
                                booking_id = button.split('_')[-1]
                                self.process_edit_selection(user_id, booking_id)
                            else:
                                logger.warning(
                                    f"[{user_id}] Попытка редактирования из неверного состояния: {user_states.get(user_id)}")

                        elif button == "edit_date":
                            self.process_edit_date(user_id)
                        elif button == "edit_time":
                            self.process_edit_time(user_id)
                        elif button == "edit_author":
                            self.process_edit_author(user_id)
                        elif button == "edit_event":
                            self.process_edit_event(user_id)
                        elif button == "edit_duration":
                            self.process_edit_duration(user_id)
                        elif button == "edit_cancel":
                            self.process_cancel_edit(user_id)

                    # Обработка других состояний
                    elif user_id in user_states:
                        state = user_states[user_id]

                        if state == STATES['DAY_SELECTION']:
                            try:
                                day = int(text)
                                month = int(user_data[user_id]["month"])
                                year = int(user_data[user_id]["year"])
                                date = f"{year}-{month:02d}-{day:02d}"
                                if not self.is_day_fully_booked(date):
                                    self.process_day_selection(user_id, text)
                                else:
                                    self.send_message(user_id, "❌ Этот день уже занят. Выберите другой день.")
                            except ValueError:
                                self.send_message(user_id, "❌ Пожалуйста, введите номер дня (например, 15).")

                        elif state == STATES['VIEW_RESERVATIONS']:
                            if payload and "button" in payload:
                                button = payload["button"]
                                if button.startswith("edit_booking_"):
                                    booking_id = button.split('_')[-1]
                                    self.process_edit_selection(user_id, booking_id)
                                elif button.startswith("cancel_confirm_"):
                                    booking_id = button.split('_')[-1]
                                    self.process_cancel_confirmation(user_id, booking_id)
                            else:
                                self.send_message(user_id,
                                                  "Пожалуйста, используйте кнопки для управления бронированиями.")

                        elif state == STATES['DURATION_SELECTION']:
                            self.process_duration_input(user_id, text)

                        elif state == STATES['AUTHOR_NAME']:
                            self.process_author_name(user_id, text)

                        elif state == STATES['EVENT_NAME']:
                            self.process_event_name(user_id, text)

                        elif state == STATES['EDIT_SELECTION']:
                            if "edit_field" in user_data[user_id]:
                                self.process_edit_field_input(user_id, text)

                    else:
                        self.send_message(user_id, "Я не понимаю вашу команду. Используйте кнопки меню.",
                                          self.get_main_keyboard())

            except Exception as e:
                logger.error(f"Ошибка при обработке события: {e}")

if __name__ == "__main__":
    # Сначала создайте файл config_vk.py с переменной VK_TOKEN
    from config import VK_TOKEN

    bot = VkBot(VK_TOKEN)
    bot.run()