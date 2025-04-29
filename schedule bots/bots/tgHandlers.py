import re
import sqlite3

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
import logging
from calendar import monthrange
from telegram.ext import ConversationHandler, CallbackContext
from db.db import add_reservation, get_reservations_for_user, \
    update_reservation, get_db_connection, get_reservations_for_date, save_reservation, delete_reservation, \
    is_time_available, is_valid_time
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
DATE, TIME_SELECTION, HOUR_SELECTION, DURATION_SELECTION, MINUTE_SELECTION, AUTHOR_NAME, EVENT_NAME, EDIT_SELECTION = range(8)

SELECT_MONTH, SELECT_DAY = range(8, 10)

# Часы и минуты для выбора
HOURS = [f"{i:02d}" for i in range(5, 23)]  # от 09 до 22
MINUTES = ["00", "15", "30", "45"]
DAYS = [f"{i:02d}" for i in range(1, 32)]  # Дни месяца от 01 до 31

async def start(update: Update, context: CallbackContext):
    # Обновленная главная клавиатура с двумя разными кнопками для расписаний
    keyboard = [
        ['📆 Общее расписание', '📅 Мои бронирования'],
        ['📌 Бронь', 'ℹ️ О боте']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text("Привет! Я бот для управления расписанием. Выберите действие:",
                                    reply_markup=reply_markup)

async def edit_date(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    # Указываем, что редактируем дату
    context.user_data["edit_field"] = "date"

    months_keyboard = [
        [InlineKeyboardButton(f"{i:02d}", callback_data=f"edit_month_{i:02d}") for i in range(j, j + 4)]
        for j in range(1, 13, 4)
    ]
    reply_markup = InlineKeyboardMarkup(months_keyboard)
    await query.edit_message_text("📅 Выберите новый месяц:", reply_markup=reply_markup)

    return DATE

async def start_reservation(update: Update, context: CallbackContext):
    """Запускает процесс бронирования, предлагает выбрать месяц."""
    context.user_data["year"] = str(datetime.now().year)  # Устанавливаем текущий год

    months_keyboard = [
        [InlineKeyboardButton(f"{i:02d}", callback_data=f"month_{i:02d}") for i in range(j, j + 4)]
        for j in range(1, 13, 4)
    ]

    reply_markup = InlineKeyboardMarkup(months_keyboard)
    await update.message.reply_text("📅 Выберите месяц:", reply_markup=reply_markup)
    return DATE  # Остаемся в состоянии DATE для выбора месяца


async def month_callback(update: Update, context: CallbackContext):
    """Обрабатывает выбор месяца и предлагает выбрать день."""
    query = update.callback_query
    await query.answer("Выберите день")  # Подтверждаем нажатие кнопки

    try:
        # Получаем выбранный месяц
        month = int(query.data.split('_')[1])
        context.user_data["month"] = f"{month:02d}"  # Сохраняем месяц
        year = int(context.user_data.get("year", 2025))  # Используем год (по умолчанию 2025)

        # Получаем количество дней в месяце
        days_in_month = monthrange(year, month)[1]

        # Генерируем кнопки для дней месяца
        days_keyboard = [
            [InlineKeyboardButton(f"{i:02d}", callback_data=f"day_{i:02d}") for i in
             range(j, min(j + 4, days_in_month + 1))]
            for j in range(1, days_in_month + 1, 4)
        ]
        reply_markup = InlineKeyboardMarkup(days_keyboard)

        # Отправляем сообщение с выбором дня
        await query.edit_message_text("📅 Выберите день:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при обработке месяца: {e}")
        await query.message.reply_text("Ошибка! Попробуйте выбрать месяц еще раз")

    return DATE  # Остаемся в состоянии DATE для выбора дня

async def day_callback(update: Update, context: CallbackContext):
    """Обрабатывает выбор дня и отображает расписание для этого дня."""
    query = update.callback_query
    await query.answer()

    # Получаем выбранный день
    day = query.data.split('_')[1]
    context.user_data["day"] = day

    # Составляем дату в формате YYYY-MM-DD
    date = f"{context.user_data['year']}-{context.user_data['month']}-{day}"
    context.user_data["date"] = date

    # Получаем все бронирования на этот день
    reservations = get_reservations_for_date(date)
    booked_hours = {res[0].split(":")[0] for res in reservations}  # Собираем занятые часы

    # Генерация визуальной таблицы с занятыми и свободными слотами
    time_slots = ["05:00", "06:00", "07:00", "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"]
    table = f"📅 Ваше расписание на {date}:\n\n"
    for slot in time_slots:
        if slot in booked_hours:
            table += f"{slot} 🟥 (занято)\n"
        else:
            table += f"{slot} 🟩 (свободно)\n"

    # Добавляем кнопки для выбора времени, если слот свободен
    timeKeyboard = []
    for slot in time_slots:
        if slot not in booked_hours:
            timeKeyboard.append([InlineKeyboardButton(f"Выбрать {slot}", callback_data=f"hour_{slot}")])

    # Если есть свободные слоты, выводим их
    if timeKeyboard:
        reply_markup = InlineKeyboardMarkup(timeKeyboard)
        await query.edit_message_text(table + "\nВыберите время:", reply_markup=reply_markup)
    else:
        await query.edit_message_text(table + "\nК сожалению, все слоты заняты на этот день.")

    return HOUR_SELECTION

async def hour_callback(update: Update, context: CallbackContext):
    """Обрабатывает выбор часа и показывает выбор минут"""
    query = update.callback_query
    await query.answer()

    # Извлекаем выбранный час из callback_data
    hour = query.data.split('_')[1]
    context.user_data["hour"] = hour

    # Создаем клавиатуру для выбора минут в одном ряду
    keyboard = [[
        InlineKeyboardButton(minute, callback_data=f"minute_{minute}")
        for minute in MINUTES
    ]]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"Выбран час: {hour}. Теперь выберите минуты:", reply_markup=reply_markup)
    return MINUTE_SELECTION

async def select_day_callback(update, context):
    """Отображаем расписание для выбранного дня."""
    query = update.callback_query
    await query.answer()

    # Получаем выбранный день и месяц
    selected_day = int(query.data.split("_")[2])
    selected_month = context.user_data.get("month")
    selected_year = context.user_data.get("year", datetime.now().year)  # Если нет года в user_data, используем текущий
    selected_date = f"{selected_day:02d}-{selected_month:02d}-{selected_year}"

    # Получаем все бронирования для выбранного дня
    reservations = get_reservations_for_date(selected_date)

    # Генерация таблицы с состоянием времени
    time_slots = ["05:00", "06:00", "07:00", "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"]
    table = f"⏰ Расписание на {selected_date}:\n\n"
    for slot in time_slots:
        if any(res[0] == slot for res in reservations):  # Если слот занят
            table += f"{slot} 🟥 (занято)\n"
        else:
            table += f"{slot} 🟩 (свободно)\n"

    await query.edit_message_text(table)


async def minute_callback(update: Update, context: CallbackContext):
    """Обрабатывает выбор минут и проверяет доступность времени"""
    query = update.callback_query
    await query.answer()

    try:
        # Получаем выбранные минуты
        minute = query.data.split('_')[1]

        # Проверяем допустимые значения минут (только 00, 15, 30, 45)
        if minute not in ["00", "15", "30", "45"]:
            keyboard = [
                [InlineKeyboardButton("00", callback_data="minute_00"),
                 InlineKeyboardButton("15", callback_data="minute_15")],
                [InlineKeyboardButton("30", callback_data="minute_30"),
                 InlineKeyboardButton("45", callback_data="minute_45")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "❌ Пожалуйста, выберите минуты из предложенных вариантов:",
                reply_markup=reply_markup
            )
            return MINUTE_SELECTION

        # Получаем сохраненные данные
        hour = context.user_data["hour"]
        date = context.user_data["date"]

        # Если hour содержит полное время, извлекаем только час
        hour = hour.split(':')[0]  # Берем только часы из значения времени

        # Проверяем, что hour это число
        if not hour.isdigit():
            logger.error(f"Invalid hour format: {hour}")
            await query.edit_message_text("❌ Неверный формат времени. Попробуйте еще раз.")
            return MINUTE_SELECTION

        # Форматируем время (убедимся, что час тоже в двузначном формате)
        time = f"{int(hour):02d}:{minute}"
        context.user_data["time"] = time

        # Проверяем доступность времени
        reservations = get_reservations_for_date(date)

        # Преобразуем время с правильным форматом
        try:
            start_time = datetime.strptime(time, "%H:%M")
            duration = context.user_data.get("duration", 60)
            end_time = start_time + timedelta(minutes=duration)
        except ValueError as e:
            logger.error(f"Time format error: {time} - {str(e)}")
            await query.edit_message_text("❌ Ошибка формата времени. Попробуйте еще раз.")
            return MINUTE_SELECTION

        is_available = True
        for res in reservations:
            res_time = res[2]  # предполагаем формат "HH:MM"

            # Проверяем формат времени бронирования
            if not re.match(r'^\d{2}:\d{2}$', res_time):
                continue

            try:
                res_start = datetime.strptime(res_time, "%H:%M")
                res_duration = int(res[3]) if len(res) > 3 else 60
                res_end = res_start + timedelta(minutes=res_duration)

                if not (end_time <= res_start or start_time >= res_end):
                    is_available = False
                    break
            except ValueError as e:
                logger.error(f"Invalid reservation time format: {res_time} - {str(e)}")
                continue

        if not is_available:
            nearest_time = find_nearest_available_time(time, duration, reservations)
            if nearest_time:
                context.user_data["time"] = nearest_time
                await query.edit_message_text(
                    f"⚠️ Время {time} уже занято.\n"
                    f"🔄 Автоматически выбрано ближайшее доступное время: {nearest_time}\n"
                    "Теперь укажите длительность мероприятия (в минутах):"
                )
            else:
                await query.edit_message_text(
                    f"⚠️ Время {time} уже занято и нет доступных слотов.\n"
                    "Пожалуйста, выберите другое время:"
                )
                return await hour_callback(update, context)
        else:
            await query.edit_message_text(
                f"✅ Вы выбрали время: {time}\n"
                "Теперь укажите длительность мероприятия (в минутах):"
            )

        return DURATION_SELECTION

    except Exception as e:
        logger.error(f"Error in minute_callback: {str(e)}", exc_info=True)
        await query.edit_message_text("❌ Произошла ошибка. Пожалуйста, попробуйте еще раз.")
        return MINUTE_SELECTION

async def get_author_name(update: Update, context: CallbackContext):
    """Запрашивает имя пользователя."""
    author_name = update.message.text.strip()
    context.user_data["author_name"] = author_name

    # Запрашиваем наименование мероприятия
    await update.message.reply_text("Теперь введите наименование мероприятия:")
    return EVENT_NAME


async def get_event_name(update: Update, context: CallbackContext):
    """Получает название мероприятия и завершает бронирование."""
    event_name = update.message.text.strip()
    context.user_data['event_name'] = event_name

    user_id = update.message.from_user.id
    username = update.message.from_user.username or "Unknown"
    author_name = context.user_data.get('author_name', "Неизвестный")
    date = context.user_data['date']
    time = context.user_data['time']
    duration = context.user_data.get('duration', 60)  # Длительность теперь берется из предыдущего шага

    # Приводим время к формату HH:MM
    if time.count(":") == 2:
        time = ":".join(time.split(":")[:2])

    if add_reservation(user_id, username, author_name, event_name, date, time, duration):
        await update.message.reply_text("✅ Бронирование успешно добавлено!")
    else:
        await update.message.reply_text("⚠️ Это время уже занято, попробуйте другое.")

    return ConversationHandler.END


def format_time_range(start_time, duration):
    """Формирует строку с промежутком времени бронирования."""
    try:
        start = datetime.strptime(start_time, "%H:%M")
        end = start + timedelta(minutes=int(duration))
        return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
    except ValueError:
        return start_time  # Если ошибка, просто вернуть начальное время


def format_reservations_list(reservations):
    """Форматирует бронирования в виде списка с промежутками времени."""
    if not reservations:
        return "Нет активных бронирований."

    lines = []
    for reservation in reservations:
        if len(reservation) == 6:
            username, author, event, date, time, duration = reservation
        else:
            username, author, event, date, time = reservation
            duration = None

        time_range = format_time_range(time, duration) if duration else f"{time} (длительность не указана)"
        author_text = author if author else "Неизвестный"
        event_text = event if event else "Без названия"
        lines.append(f"📅 {date} ⏰ {time_range}\n👤 {author_text}\n📌 {event_text}\n")

    return "\n".join(lines)

async def my_reservations(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    bookings = get_reservations_for_user(user_id)

    if bookings:
        text = "Ваши бронирования:\n"
        keyboard = []
        for i, booking in enumerate(bookings, 1):
            booking_id, username, author_name, event_name, date, time, duration = booking
            time_range = f"{time} (🕒 {duration} мин)" if duration else f"{time} (длительность не указана)"
            text += f"{i}. {event_name} на {date} в {time_range}\n"
            keyboard.append([
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{booking_id}"),
                InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_confirm_{booking_id}")
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text("У вас нет бронирований.")


async def cancel_confirmation(update: Update, context: CallbackContext):
    """Запрашивает подтверждение перед удалением бронирования."""
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    if len(data) < 3:
        await query.edit_message_text("Ошибка! Попробуйте еще раз.")
        return

    reservation_id = data[2]
    context.user_data["cancel_reservation_id"] = reservation_id

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_cancel_{reservation_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("Вы уверены, что хотите отменить бронь?", reply_markup=reply_markup)

async def confirm_cancel(update: Update, context: CallbackContext):
    """Удаляет бронирование после подтверждения."""
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    if len(data) < 3:
        await query.edit_message_text("Ошибка данных. Попробуйте еще раз.")
        return

    reservation_id = data[2]  # Получаем ID брони
    logger.info(f"Попытка отмены бронирования ID: {reservation_id}")

    # ✅ Проверяем, что ID бронирования корректный
    print(f"Удаление бронирования ID: {reservation_id}")

    success = delete_reservation(reservation_id)

    if success:
        await query.edit_message_text("✅ Бронирование успешно отменено.")
    else:
        await query.edit_message_text("⚠️ Ошибка! Возможно, бронь уже была удалена.")


async def all_reservations(update: Update, context: CallbackContext):
    """Запрашивает месяц для просмотра общего расписания."""
    context.user_data["view_year"] = str(datetime.now().year)  # Устанавливаем текущий год

    months_keyboard = [
        [InlineKeyboardButton(f"{i:02d}", callback_data=f"select_month_{i:02d}") for i in range(j, j + 4)]
        for j in range(1, 13, 4)
    ]

    reply_markup = InlineKeyboardMarkup(months_keyboard)
    await update.message.reply_text("📅 Выберите месяц для просмотра расписания:", reply_markup=reply_markup)
    return SELECT_MONTH


async def month_for_view_callback(update: Update, context: CallbackContext):
    """Обрабатывает выбор месяца и предлагает выбрать день для просмотра расписания."""
    query = update.callback_query
    await query.answer("Выберите день для просмотра")

    try:
        # Получаем выбранный месяц
        month = int(query.data.split('_')[2])
        context.user_data["view_month"] = f"{month:02d}"  # Сохраняем месяц
        year = int(context.user_data.get("view_year", datetime.now().year))

        # Получаем количество дней в месяце
        days_in_month = monthrange(year, month)[1]

        # Генерируем кнопки для дней месяца
        days_keyboard = [
            [InlineKeyboardButton(f"{i:02d}", callback_data=f"select_day_{i:02d}") for i in
             range(j, min(j + 4, days_in_month + 1))]
            for j in range(1, days_in_month + 1, 4)
        ]
        reply_markup = InlineKeyboardMarkup(days_keyboard)

        # Отправляем сообщение с выбором дня
        await query.edit_message_text("📅 Выберите день для просмотра расписания:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при обработке месяца для просмотра: {e}")
        await query.message.reply_text("Ошибка! Попробуйте выбрать месяц еще раз")

    return SELECT_DAY


def get_reservations_for_date(date: str):
    # Заглушка для получения данных бронирования
    return [("Игорь", "ЧСВ", "11:00", "60")]


async def day_for_view_callback(update: Update, context: CallbackContext):
    """Отображает расписание для выбранного дня с правильным экранированием Markdown"""
    query = update.callback_query
    await query.answer()

    # Получаем выбранную дату
    day = query.data.split('_')[2]
    year = context.user_data.get("view_year", datetime.now().year)
    month = context.user_data.get("view_month")
    selected_date = f"{year}-{month}-{day}"

    try:
        # Подключаемся к БД
        with sqlite3.connect('reservations.db') as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT author_name, event_name, time, duration 
                FROM reservations 
                WHERE date = ?
                ORDER BY time
            """, (selected_date,))
            reservations = cursor.fetchall()

        # Функция для правильного экранирования MarkdownV2
        def escape_md(text):
            if not text:
                return ""
            escape_chars = r'_*[]()~`>#+-=|{}.!'
            return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

        # Если бронирований нет
        if not reservations:
            await query.edit_message_text(
                escape_md(f"📅 На {day}.{month}.{year} нет бронирований"),
                parse_mode="MarkdownV2"
            )
            return ConversationHandler.END

        # Формируем список временных слотов
        time_slots = [
            "05:00", "05:30", "06:00", "06:30", "07:00", "07:30",
            "08:00", "08:30", "09:00", "09:30", "10:00", "10:30",
            "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
            "14:00", "14:30", "15:00", "15:30", "16:00", "16:30",
            "17:00", "17:30", "18:00", "18:30", "19:00", "19:30"
        ]

        # Собираем информацию о занятости слотов
        schedule = []
        for slot in time_slots:
            slot_time = datetime.strptime(slot, "%H:%M").time()
            slot_info = {
                "time": slot,
                "status": "🟩 СВОБОДНО",
                "events": []
            }

            for author, event, time_str, duration in reservations:
                try:
                    start = datetime.strptime(time_str, "%H:%M").time()
                    end = (datetime.combine(datetime.today(), start) +
                           timedelta(minutes=int(duration or 60))).time()

                    if start <= slot_time < end:
                        slot_info["status"] = "🟥 ЗАНЯТО"
                        slot_info["events"].append(
                            escape_md(f"{event} ({author})")
                        )

                except Exception as e:
                    logger.error(f"Ошибка обработки времени: {e}")
                    continue

            schedule.append(slot_info)

        # Формируем сообщение
        message_parts = []
        message_parts.append(escape_md(f"📅 Расписание на {day}.{month}.{year}:"))
        message_parts.append("")

        # Группируем по 2 слота в строку
        for i in range(0, len(schedule), 2):
            slot1 = schedule[i]
            line = f"{escape_md(slot1['time'])} {escape_md(slot1['status'])}"

            if i + 1 < len(schedule):
                slot2 = schedule[i + 1]
                line += f" \\| {escape_md(slot2['time'])} {escape_md(slot2['status'])}"

            message_parts.append(line)

            if slot1['events']:
                message_parts.append("• " + "\n• ".join(slot1['events']))

            if i + 1 < len(schedule) and slot2['events']:
                message_parts.append("• " + "\n• ".join(slot2['events']))

        # Отправляем сообщение (не более 4096 символов)
        full_message = "\n".join(message_parts)
        if len(full_message) > 4000:  # Оставляем запас
            full_message = full_message[:4000] + "\n..."  # Обрезаем если слишком длинное

        await query.edit_message_text(
            full_message,
            parse_mode="MarkdownV2"
        )

    except Exception as e:
        logger.error(f"Ошибка при отображении расписания: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Произошла ошибка при загрузке расписания. Попробуйте позже."
        )

    return ConversationHandler.END

async def edit_reservation(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer(cache_time=0)

    # Получаем ID бронирования из callback_data
    reservation_id = int(query.data.split("_")[1])

    # Сохраняем его в user_data
    context.user_data["reservation_id"] = reservation_id

    keyboard = [
        [InlineKeyboardButton("📅 Изменить дату", callback_data="edit_date")],
        [InlineKeyboardButton("⏰ Изменить время", callback_data="edit_time")],
        [InlineKeyboardButton("👤 Изменить имя", callback_data="edit_author")],
        [InlineKeyboardButton("📌 Изменить событие", callback_data="edit_event")],
        [InlineKeyboardButton("❌ Отмена", callback_data="edit_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text("Что вы хотите изменить?", reply_markup=reply_markup)
    return EDIT_SELECTION  # Возвращаем состояние выбора редактирования

async def edit_time(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    # Указываем, что редактируем время
    context.user_data["edit_field"] = "time"

    time_keyboard = [
        [InlineKeyboardButton(hour, callback_data=f"edit_hour_{hour}") for hour in HOURS[i:i + 4]]
        for i in range(0, len(HOURS), 4)
    ]
    reply_markup = InlineKeyboardMarkup(time_keyboard)

    await query.edit_message_text("⏰ Выберите новый час:", reply_markup=reply_markup)
    return HOUR_SELECTION

async def edit_month_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    try:
        month = int(query.data.split('_')[2])
        context.user_data["edit_month"] = f"{month:02d}"
        year = int(datetime.now().year)
        days_in_month = monthrange(year, month)[1]

        days_keyboard = [
            [InlineKeyboardButton(f"{i:02d}", callback_data=f"edit_day_{i:02d}") for i in
             range(j, min(j + 4, days_in_month + 1))]
            for j in range(1, days_in_month + 1, 4)
        ]
        reply_markup = InlineKeyboardMarkup(days_keyboard)

        await query.edit_message_text("📅 Выберите новый день:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка при выборе месяца: {e}")
        await query.message.reply_text("Ошибка! Попробуйте выбрать месяц еще раз")

    return DATE


async def edit_day_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    day = query.data.split('_')[2]
    context.user_data["edit_day"] = day

    # Формируем новую дату
    new_date = f"{datetime.now().year}-{context.user_data['edit_month']}-{day}"
    context.user_data["new_date"] = new_date

    # Логируем выбранную дату
    logger.info(f"Выбрана новая дата: {new_date}")

    # Генерация клавиатуры для выбора часов
    time_keyboard = []
    for i in range(0, len(HOURS), 4):
        row = []
        for j in range(4):
            if i + j < len(HOURS):
                hour = HOURS[i + j]
                row.append(InlineKeyboardButton(hour, callback_data=f"edit_hour_{hour}"))
        time_keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(time_keyboard)

    # Отправляем сообщение с новой датой и клавиатурой для выбора времени
    await query.edit_message_text(f"Вы выбрали новую дату: {new_date}. Теперь выберите новый час:", reply_markup=reply_markup)

    return HOUR_SELECTION

async def edit_hour_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    hour = query.data.split('_')[2]
    context.user_data["edit_hour"] = hour

    keyboard = [[InlineKeyboardButton(minute, callback_data=f"edit_minute_{minute}") for minute in MINUTES]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"Вы выбрали новый час: {hour}. Теперь выберите новые минуты:",
                                  reply_markup=reply_markup)
    return MINUTE_SELECTION

async def edit_minute_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    minute = query.data.split('_')[2]
    time = f"{context.user_data['edit_hour']}:{minute}"
    context.user_data["new_time"] = time

    reservation_id = context.user_data["reservation_id"]
    new_time = context.user_data["new_time"]

    success = True

    # Если выбрана новая дата — обновляем и дату, и время
    if "new_date" in context.user_data:
        new_date = context.user_data["new_date"]

        # Обновляем дату
        if not update_database(reservation_id, "date", new_date):
            success = False

        # Удалим после использования, чтобы не мешалось при следующем редактировании
        del context.user_data["new_date"]

    # Обновляем время
    if not update_database(reservation_id, "time", new_time):
        success = False

    if success:
        await query.edit_message_text(f"✅ Бронирование успешно обновлено!\nНовое время: {new_time}")
    else:
        await query.edit_message_text("❌ Ошибка при обновлении. Попробуйте снова.")

    return ConversationHandler.END


async def edit_author(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    # Указываем, что редактируем автора
    context.user_data["edit_field"] = "author"

    await query.edit_message_text("Введите новое имя автора:")
    return AUTHOR_NAME


async def edit_event(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    # Указываем, что редактируем событие
    context.user_data["edit_field"] = "event"

    await query.edit_message_text("Введите новое название мероприятия:")
    return EVENT_NAME

async def cancel_edit(update: Update, context: CallbackContext):
    """Закрывает меню редактирования без изменений."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Редактирование отменено.")
    return ConversationHandler.END


async def save_edit(update: Update, context: CallbackContext) -> int:
    if "reservation_id" not in context.user_data:
        await update.message.reply_text("Ошибка: ID бронирования не найден.")
        return ConversationHandler.END

    reservation_id = context.user_data["reservation_id"]
    new_value = update.message.text  # Новое значение, введённое пользователем
    field = context.user_data.get("edit_field")

    field_mapping = {
        "author": "author_name",  # Исправлено: маппинг для правильных имен полей
        "event": "event_name"
    }

    if field in field_mapping:
        field = field_mapping[field]  # Преобразуем в правильное имя поля

    if field:
        # Пытаемся обновить бронирование
        if update_database(reservation_id, field, new_value):  # Убедитесь, что update_reservation() принимает три аргумента
            await update.message.reply_text(f"✅ Изменения сохранены: новое значение - {new_value}")
        else:
            await update.message.reply_text("❌ Ошибка при обновлении. Попробуйте снова.")
    else:
        await update.message.reply_text("❌ Ошибка: поле для редактирования не определено")

    return ConversationHandler.END


def update_database(reservation_id, field, new_value):
    allowed_fields = ["date", "time", "author_name", "event_name"]
    if field not in allowed_fields:
        print(f"[DEBUG] Недопустимое поле: {field}")
        return False

    conn = sqlite3.connect("reservations.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,))
    if not cursor.fetchone():
        print(f"[DEBUG] Бронь с ID {reservation_id} не найдена")
        conn.close()
        return False

    try:
        query = f"UPDATE reservations SET {field} = ? WHERE id = ?"
        print(f"[DEBUG] SQL: {query} | values: {new_value}, {reservation_id}")
        cursor.execute(query, (new_value, reservation_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DEBUG] Ошибка при обновлении: {e}")
        return False
    finally:
        conn.close()


async def about(update: Update, context: CallbackContext) -> None:
    about_text = (
        "Здравствуйте, Я — бот для управления вашим расписанием и бронирования столиков. "
        "С помощью меня вы можете:\n"
        "1. Просматривать общее расписание бронирований 📆\n"
        "2. Просматривать свои бронирования 📅\n"
        "3. Забронировать столик 📌\n"
        "Просто выберите нужную опцию и следуйте инструкциям!\n\n"
        "Я помогу вам с организацией времени и удобным бронированием"
    )

    await update.message.reply_text(about_text)

# Запрос кол-во часов

async def save_duration(update: Update, context: CallbackContext):
    """Сохраняет длительность бронирования."""
    duration = update.message.text.strip()

    if not duration.isdigit() or int(duration) <= 0:
        await update.message.reply_text("Пожалуйста, укажите длительность в минутах (например, 60).")
        return DURATION_SELECTION

    context.user_data['duration'] = int(duration)

    # Теперь запрашиваем имя пользователя (автора)
    await update.message.reply_text("Теперь, пожалуйста, введите ваше имя:")
    return AUTHOR_NAME  # Переход к следующему шагу

async def edit_duration(update: Update, context: CallbackContext):
    """Запрашивает новую длительность мероприятия."""
    await update.callback_query.message.reply_text("Введите новую длительность в минутах:")
    return DURATION_SELECTION

async def save_duration_edit(update: Update, context: CallbackContext):
    """Сохраняет новую длительность мероприятия."""
    duration = update.message.text.strip()

    if not duration.isdigit() or int(duration) <= 0:
        await update.message.reply_text("⚠️ Введите корректное число минут.")
        return DURATION_SELECTION

    reservation_id = context.user_data['edit_reservation_id']
    update_database(reservation_id, "duration", int(duration))

    await update.message.reply_text("✅ Длительность обновлена!")
    return ConversationHandler.END

# Вывод ближайшего свободного времени

def get_reservations_on_date(date):
    """Получает все бронирования на заданную дату."""
    return get_reservations_for_date(date)  # [(time, duration), ...]


def find_nearest_available_time(time, duration, reservations):
    """Находит ближайшее доступное время"""
    try:
        # Преобразуем входное время
        current_time = datetime.strptime(time, "%H:%M")
        duration = int(duration)

        # Проверяем все возможные временные слоты
        for minutes_to_add in range(15, 24 * 60, 15):  # проверяем каждые 15 минут в течение 24 часов
            new_time = current_time + timedelta(minutes=minutes_to_add)
            new_time_str = new_time.strftime("%H:%M")

            # Проверяем, не выходит ли за границы рабочего дня
            if new_time.hour >= 20:  # после 20:00 не работаем
                continue

            new_end = new_time + timedelta(minutes=duration)
            if new_end.hour >= 20:  # если мероприятие заканчивается после 20:00
                continue

            # Проверяем доступность
            is_available = True
            for res in reservations:
                res_time = res[2]
                if not re.match(r'^\d{2}:\d{2}$', res_time):
                    continue

                try:
                    res_start = datetime.strptime(res_time, "%H:%M")
                    res_duration = int(res[3]) if len(res) > 3 else 60
                    res_end = res_start + timedelta(minutes=res_duration)

                    if not (new_end <= res_start or new_time >= res_end):
                        is_available = False
                        break
                except ValueError:
                    continue

            if is_available:
                return new_time_str

        return None

    except Exception as e:
        logger.error(f"Error in find_nearest_available_time: {str(e)}", exc_info=True)
        return None

async def book_table(update: Update, context: CallbackContext):
    """Попытка забронировать столик, если время занято – уведомляем и предлагаем ближайшее свободное"""
    user_id = update.message.from_user.id
    event_name = "Ваше мероприятие"  # Нужно взять из контекста или сообщения пользователя
    date = "2025-04-12"  # Нужно взять из контекста или сообщения пользователя
    time = "14:00"  # Нужно взять из контекста или сообщения пользователя
    duration = 120  # Например, 2 часа

    reservations = get_reservations_on_date(date)
    nearest_time = find_nearest_available_time(time, duration, reservations)

    requested_start = datetime.strptime(time, "%H:%M")
    requested_end = requested_start + timedelta(minutes=duration)

    # Проверяем, не пересекается ли запрашиваемое время с текущими бронированиями
    for start_time, booked_duration in reservations:
        booked_start = datetime.strptime(start_time, "%H:%M")
        booked_end = booked_start + timedelta(minutes=int(booked_duration))

        if not (requested_end <= booked_start or requested_start >= booked_end):
            # Время занято, предлагаем ближайшее
            await update.message.reply_text(
                f"⚠️ Запрошенное время ({time}) уже занято.\n"
                f"Ближайшее доступное время: {nearest_time}. Хотите забронировать его?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Да, забронировать", callback_data=f"confirm_{date}_{nearest_time}_{duration}")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
                ])
            )
            return  # Прерываем выполнение функции

    # Если время свободно, бронируем
    save_reservation(user_id, event_name, date, time, duration)
    await update.message.reply_text(f"✅ Ваше бронирование подтверждено: {event_name} на {date} с {time} до {nearest_time}")