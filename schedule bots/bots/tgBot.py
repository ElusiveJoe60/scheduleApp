import logging
import asyncio
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, MessageHandler, CallbackQueryHandler, filters
)
from bots.tgHandlers import (
    start, start_reservation, about, month_callback, day_callback,
    hour_callback, minute_callback, my_reservations, all_reservations,
    get_author_name, get_event_name,
    edit_reservation, edit_month_callback, edit_day_callback, edit_hour_callback, edit_minute_callback,
    edit_author, edit_event, save_edit, DATE, HOUR_SELECTION, MINUTE_SELECTION,
    AUTHOR_NAME, EVENT_NAME, EDIT_SELECTION, cancel_edit, edit_date, edit_time, DURATION_SELECTION, save_duration_edit,
    edit_duration, save_duration, book_table, cancel_confirmation, confirm_cancel, select_day_callback, SELECT_MONTH,
    SELECT_DAY, month_for_view_callback, day_for_view_callback,
)
from db.db import init_db
from config import TGTOKEN


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def setup_handlers(app):
    """Настройка всех обработчиков для приложения"""
    # Обработчик бронирования через команду /book
    app.add_handler(CommandHandler("book", book_table))

    # Бронирование через ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("book", start_reservation),
                      MessageHandler(filters.Regex("^📌 Бронь$"), start_reservation)],
        states={
            DATE: [CallbackQueryHandler(month_callback, pattern=r'^month_'),
                   CallbackQueryHandler(day_callback, pattern=r'^day_')],
            HOUR_SELECTION: [CallbackQueryHandler(hour_callback, pattern=r'^hour_')],
            MINUTE_SELECTION: [CallbackQueryHandler(minute_callback, pattern=r'^minute_')],
            DURATION_SELECTION: [MessageHandler(filters.Regex(r'^\d+$'), save_duration)],
            AUTHOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_author_name)],
            EVENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_event_name)],
        },
        fallbacks=[CommandHandler("cancel", start),
                   MessageHandler(filters.Regex("^Отмена$"), start)],
        per_chat=True,
        per_user=True
    )

    view_schedule_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^📆 Общее расписание$'), all_reservations)],
        states={
            SELECT_MONTH: [CallbackQueryHandler(month_for_view_callback, pattern=r'^select_month_\d+$')],
            SELECT_DAY: [CallbackQueryHandler(day_for_view_callback, pattern=r'^select_day_\d+$')],
        },
        fallbacks=[CommandHandler("cancel", start),
                   MessageHandler(filters.Regex("^Отмена$"), start)],
        per_chat=True,
        per_user=True
    )

    # Обработчик редактирования бронирования
    edit_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_reservation, pattern=r'^edit_\d+$')],
        states={
            EDIT_SELECTION: [
                CallbackQueryHandler(edit_date, pattern=r'^edit_date$'),
                CallbackQueryHandler(edit_time, pattern=r'^edit_time$'),
                CallbackQueryHandler(edit_author, pattern=r'^edit_author$'),
                CallbackQueryHandler(edit_event, pattern=r'^edit_event$'),
                CallbackQueryHandler(edit_duration, pattern=r'^edit_duration$'),
                CallbackQueryHandler(cancel_edit, pattern=r'^edit_cancel$'),
            ],
            DATE: [
                CallbackQueryHandler(edit_month_callback, pattern=r'^edit_month_'),
                CallbackQueryHandler(edit_day_callback, pattern=r'^edit_day_')
            ],
            HOUR_SELECTION: [
                CallbackQueryHandler(edit_hour_callback, pattern=r'^edit_hour_')
            ],
            MINUTE_SELECTION: [
                CallbackQueryHandler(edit_minute_callback, pattern=r'^edit_minute_')
            ],
            AUTHOR_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit)
            ],
            EVENT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit)
            ],
            DURATION_SELECTION: [
                MessageHandler(filters.Regex(r'^\d+$'), save_duration_edit)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", start),
            MessageHandler(filters.Regex("^Отмена$"), cancel_edit)
        ],
        per_chat=True,
        per_user=True
    )

    # Добавляем обработчики
    app.add_handler(conv_handler)
    app.add_handler(edit_conv_handler)
    app.add_handler(view_schedule_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reservations", my_reservations))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ О боте$"), about))

    app.add_handler(CallbackQueryHandler(month_callback, pattern=r"^select_month_\d+$"))
    app.add_handler(CallbackQueryHandler(day_callback, pattern=r"^select_day_\d+$"))
    app.add_handler(CallbackQueryHandler(select_day_callback, pattern=r"^select_day_\d+$"))

    app.add_handler(CallbackQueryHandler(cancel_confirmation, pattern=r'^cancel_confirm_\d+$'))
    app.add_handler(CallbackQueryHandler(confirm_cancel, pattern=r'^confirm_cancel_\d+$'))

    app.add_handler(MessageHandler(filters.Regex(r'^📅 Мои бронирования$'), my_reservations))
    app.add_handler(MessageHandler(filters.Regex(r'^📆 Общее расписание$'), all_reservations))

async def run_bot():
    """Основная асинхронная функция для запуска бота"""
    init_db()  # Инициализируем базу данных

    app = Application.builder().token(TGTOKEN).build()
    setup_handlers(app)

    logger.info("Бот запускается...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        # Бесконечный цикл ожидания
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Остановка бота...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

def main():
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")

if __name__ == "__main__":
    main()