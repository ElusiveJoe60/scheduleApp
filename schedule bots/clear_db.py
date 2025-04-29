#!/usr/bin/env python3
# clear_db.py - Надежный скрипт для очистки базы данных

import sqlite3
from datetime import datetime
import os


def clear_database():
    """Очищает базу данных с правильным управлением транзакциями"""
    conn = None
    try:
        print("\nНачало очистки базы данных...")

        # Подключаемся к базе данных с ручным управлением транзакциями
        conn = sqlite3.connect('reservations.db')
        conn.execute("PRAGMA journal_mode = WAL")  # Более надежный режим
        cursor = conn.cursor()

        # Получаем список всех пользовательских таблиц
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [table[0] for table in cursor.fetchall()]

        if not tables:
            print("В базе данных нет таблиц для очистки")
            return

        # Очищаем каждую таблицу в отдельной транзакции
        for table in tables:
            try:
                cursor.execute(f"DELETE FROM {table};")
                print(f"Очищена таблица: {table}")
                conn.commit()  # Фиксируем после каждой таблицы
            except Exception as e:
                print(f"Ошибка при очистке таблицы {table}: {e}")
                conn.rollback()

        # Оптимизация базы данных (требует отдельного соединения)
        conn.close()
        print("Выполняем оптимизацию базы данных...")

        # Новое соединение для VACUUM
        with sqlite3.connect('reservations.db') as vacuum_conn:
            vacuum_conn.execute("VACUUM;")

        print(f"\n✅ База данных успешно очищена и оптимизирована {datetime.now()}")

    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def create_backup():
    """Создает резервную копию базы данных"""
    backup_name = f"reservations_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    try:
        shutil.copy2('reservations.db', backup_name)
        print(f"\nСоздана резервная копия: {backup_name}")
        return True
    except Exception as e:
        print(f"\nНе удалось создать резервную копию: {e}")
        return False


if __name__ == "__main__":
    print("=== Очистка базы данных бронирований ===")
    print("ВНИМАНИЕ: Это действие необратимо удалит все данные!")

    confirm = input("\nВы уверены, что хотите очистить ВСЕ данные? (y/n): ")

    if confirm.lower() == 'y':
        # Сначала предлагаем создать резервную копию
        backup_confirm = input("Создать резервную копию перед очисткой? (y/n): ")
        if backup_confirm.lower() == 'y':
            try:
                import shutil

                if create_backup():
                    clear_database()
                else:
                    print("Очистка отменена из-за ошибки резервного копирования")
            except ImportError:
                print("Не удалось импортировать модуль shutil. Резервное копирование невозможно.")
                clear_database()
        else:
            clear_database()
    else:
        print("Очистка отменена")