from datetime import datetime, timedelta
import re
import sqlite3
import logging

logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('reservations.db')
    cursor = conn.cursor()

    # Создаем таблицу с полями для продолжительности и дополнительной информации
    cursor.execute('''CREATE TABLE IF NOT EXISTS reservations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        username TEXT,
                        author_name TEXT,
                        event_name TEXT, 
                        date TEXT,
                        time TEXT,
                        duration INTEGER)''')  # Добавлено поле для продолжительности
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect('reservations.db')  # или другие параметры подключения
    conn.row_factory = sqlite3.Row  # опционально
    return conn

def is_valid_time(time_str):
    """Проверяет корректность формата времени HH:MM"""
    try:
        # Проверяем, что строка времени соответствует формату HH:MM
        if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', time_str):
            return False

        hour, minute = time_str.split(":")
        hour_int = int(hour)
        minute_int = int(minute)

        # Проверяем диапазоны
        if 0 <= hour_int <= 23 and 0 <= minute_int <= 59:
            return True
        return False
    except ValueError:
        return False

# Функция для добавления бронирования
def add_reservation(user_id, username, author_name, event_name, date, time, duration):
    """Добавляет новое бронирование с проверкой данных"""
    try:
        # Проверяем формат времени
        if not is_valid_time(time):
            raise ValueError("Некорректный формат времени. Используйте HH:MM")

        # Проверяем длительность
        try:
            duration = int(duration)
            if duration <= 0:
                raise ValueError("Длительность должна быть положительным числом")
        except (ValueError, TypeError):
            raise ValueError("Некорректная длительность. Используйте число минут")

        with sqlite3.connect('reservations.db') as conn:
            cursor = conn.cursor()

            # Проверка на наличие бронирования
            cursor.execute("""
                SELECT 1 FROM reservations 
                WHERE date = ? AND time = ?
            """, (date, time))

            if cursor.fetchone():
                return False

            # Добавляем бронирование
            cursor.execute("""
                INSERT INTO reservations 
                (user_id, username, author_name, event_name, date, time, duration) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, username, author_name, event_name, date, time, duration))

            conn.commit()
            return True

    except sqlite3.Error as e:
        logger.error(f"Ошибка базы данных: {e}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при добавлении бронирования: {e}")
        raise

def is_valid_time(time_str):
    """Проверка формата времени HH:MM"""
    try:
        # Проверяем, что строка времени соответствует формату HH:MM
        hour, minute = time_str.split(":")
        if len(hour) == 2 and len(minute) == 2:
            int(hour)  # Проверим, что часы — целое число
            int(minute)  # Проверим, что минуты — целое число
            return True
    except ValueError:
        pass
    return False

def is_time_available(date, time, duration, reservations=None):
    """Проверяет доступность временного интервала"""
    if reservations is None:
        with sqlite3.connect('reservations.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT time, duration FROM reservations WHERE date = ?", (date,))
            reservations = cursor.fetchall()

    try:
        requested_start = datetime.strptime(time, "%H:%M")
        requested_end = requested_start + timedelta(minutes=int(duration))

        for booked_time, booked_duration in reservations:
            booked_start = datetime.strptime(booked_time, "%H:%M")
            booked_end = booked_start + timedelta(minutes=int(booked_duration))

            if not (requested_end <= booked_start or requested_start >= booked_end):
                return False

        return True
    except Exception as e:
        logger.error(f"Error in is_time_available: {e}")
        return False

def find_nearest_available_time(time, duration, existing_reservations):
    """Находит ближайшее доступное время"""
    time_slots = [
        "05:00", "05:30", "06:00", "06:30", "07:00", "07:30",
        "08:00", "08:30", "09:00", "09:30", "10:00", "10:30",
        "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
        "14:00", "14:30", "15:00", "15:30", "16:00", "16:30",
        "17:00", "17:30", "18:00", "18:30", "19:00", "19:30"
    ]

    requested_start = datetime.strptime(time, "%H:%M")
    duration = int(duration)

    for slot in time_slots:
        slot_time = datetime.strptime(slot, "%H:%M")
        if slot_time >= requested_start:
            is_available = True
            slot_end = slot_time + timedelta(minutes=duration)

            for res_time, res_duration in existing_reservations:
                res_start = datetime.strptime(res_time, "%H:%M")
                res_end = res_start + timedelta(minutes=int(res_duration))

                if not (slot_end <= res_start or slot_time >= res_end):
                    is_available = False
                    break

            if is_available:
                return slot

    return None

# Функция для получения всех бронирований
def get_reservations():
    conn = sqlite3.connect('reservations.db')
    cursor = conn.cursor()
    cursor.execute("SELECT username, author_name, event_name, date, time, duration FROM reservations")
    reservations = cursor.fetchall()
    conn.close()
    return reservations

# Функция для получения бронирований всех пользователей
def get_all_reservations():
    """Получает все бронирования в базе данных."""
    conn = sqlite3.connect('reservations.db')
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username, author_name, event_name, date, time, duration
        FROM reservations
    """)
    reservations = cursor.fetchall()
    conn.close()
    return reservations

# Функция для получения всех бронирований пользователя
def get_reservations_for_user(user_id):
    conn = sqlite3.connect('reservations.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, username, author_name, event_name, date, time, duration
        FROM reservations
        WHERE user_id = ?
    """, (user_id,))
    reservations = cursor.fetchall()
    conn.close()
    return reservations

# Функция для получения всех бронирований по дате
def get_reservations_for_date(date):
    """Возвращает список бронирований для указанной даты"""
    try:
        conn = sqlite3.connect('reservations.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, date, time, duration FROM reservations WHERE date = ?", (date,))
        results = cursor.fetchall()
        conn.close()

        # Фильтруем только валидные записи
        valid_results = []
        for res in results:
            try:
                # Проверяем формат времени
                if not re.match(r'^\d{2}:\d{2}$', res[2]):
                    logger.warning(f"Пропущено бронирование с некорректным временем: {res}")
                    continue
                valid_results.append(res)
            except (IndexError, TypeError):
                continue

        return valid_results
    except Exception as e:
        logger.error(f"Ошибка при получении бронирований: {str(e)}")
        return []

# Функция для удаления бронирования
def delete_reservation(reservation_id):
    """Удаляет бронирование из базы данных."""
    try:
        conn = sqlite3.connect('reservations.db')
        cursor = conn.cursor()

        # Проверяем существование записи перед удалением
        cursor.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,))
        reservation = cursor.fetchone()
        if not reservation:
            logger.warning(f"Бронирование ID {reservation_id} не найдено в базе.")
            return False

        cursor.execute("DELETE FROM reservations WHERE id = ?", (reservation_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted
    except Exception as e:
        logger.error(f"Ошибка удаления бронирования ID {reservation_id}: {e}")
        return False

def clean_invalid_time_entries():
    """Удаляет записи с некорректным форматом времени"""
    try:
        conn = sqlite3.connect('reservations.db')
        cursor = conn.cursor()

        # Находим записи с некорректным временем
        cursor.execute("SELECT id, time FROM reservations")
        to_delete = []
        for row in cursor.fetchall():
            if not re.match(r'^\d{2}:\d{2}$', row[1]):
                to_delete.append(row[0])

        # Удаляем некорректные записи
        if to_delete:
            cursor.execute("DELETE FROM reservations WHERE id IN ({})".format(','.join(['?'] * len(to_delete))),
                           to_delete)
            conn.commit()
            logger.warning(f"Удалено {len(to_delete)} записей с некорректным временем")

        conn.close()
    except Exception as e:
        logger.error(f"Ошибка очистки БД: {e}")

# Функция для обновления бронирования
def update_reservation(reservation_id, field, new_value):
    # Логика обновления записи в базе данных или другом хранилище
    # Пример:
    try:
        # Пример обновления резервации (можно заменить на реальную логику)
        # update database query here
        print(f"Updating reservation {reservation_id}: {field} = {new_value}")
        return True  # Возвращаем True при успешном обновлении
    except Exception as e:
        print(f"Error updating reservation: {str(e)}")
        return False

# Функция для сохранения бронирования
def save_reservation(user_id, username, author_name, event_name, date, time, duration):
    """Сохраняет бронирование в базе данных."""
    with sqlite3.connect('reservations.db') as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reservations 
            (user_id, username, author_name, event_name, date, time, duration) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, author_name, event_name, date, time, duration))
        conn.commit()

# Функция для обновления структуры базы данных (если нужно добавить новое поле)
def update_db():
    conn = sqlite3.connect('reservations.db')
    cursor = conn.cursor()

    try:
        cursor.execute("ALTER TABLE reservations ADD COLUMN duration INTEGER")
    except sqlite3.OperationalError:
        print("Поле 'duration' уже существует.")

    conn.commit()
    conn.close()

# Вызываем обновление базы данных для добавления поля
update_db()