import logging
import asyncio
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
from config import BOT_TOKEN
from database import init_db
from handlers import user_handlers, admin_handlers
from scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # ── User conversation: booking flow ──────────────────────────────────────
    booking_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(user_handlers.start_booking, pattern="^book$")
        ],
        states={
            user_handlers.SELECT_SERVICE: [
                CallbackQueryHandler(user_handlers.select_service, pattern="^svc_")
            ],
            user_handlers.SELECT_DATE: [
                CallbackQueryHandler(user_handlers.select_date,        pattern="^date_"),
                CallbackQueryHandler(user_handlers.nav_calendar,       pattern="^cal_"),
                CallbackQueryHandler(user_handlers.back_to_services_cb, pattern="^back_to_services$"),
            ],
            user_handlers.SELECT_TIME: [
                CallbackQueryHandler(user_handlers.select_time,        pattern="^time_"),
                CallbackQueryHandler(user_handlers.back_to_date_cb,    pattern="^back_to_date$"),
            ],
            user_handlers.ENTER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, user_handlers.enter_phone)
            ],
            user_handlers.CONFIRM: [
                CallbackQueryHandler(user_handlers.confirm_booking,      pattern="^confirm$"),
                CallbackQueryHandler(user_handlers.cancel_booking_flow,  pattern="^cancel_flow$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", user_handlers.cancel_booking_flow),
            CallbackQueryHandler(user_handlers.cancel_booking_flow, pattern="^cancel_flow$"),
        ],
        per_message=False,
    )

    # ── Admin conversation: add/edit service ─────────────────────────────────
    admin_svc_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_handlers.admin_add_service, pattern="^admin_add_svc$"),
            CallbackQueryHandler(admin_handlers.admin_edit_service_start, pattern="^admin_edit_svc_"),
        ],
        states={
            admin_handlers.SVC_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.svc_get_name)
            ],
            admin_handlers.SVC_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.svc_get_desc)
            ],
            admin_handlers.SVC_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.svc_get_price)
            ],
            admin_handlers.SVC_DURATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handlers.svc_get_duration)
            ],
        },
        fallbacks=[CommandHandler("cancel", admin_handlers.admin_cancel)],
        per_message=False,
    )

    # ── Handlers registration ─────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", user_handlers.start))
    app.add_handler(CommandHandler("admin", admin_handlers.admin_panel))
    app.add_handler(CommandHandler("my_bookings", user_handlers.my_bookings))

    app.add_handler(booking_conv)
    app.add_handler(admin_svc_conv)

    # Admin callbacks
    app.add_handler(CallbackQueryHandler(admin_handlers.admin_panel_cb,       pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_handlers.admin_services,        pattern="^admin_services$"))
    app.add_handler(CallbackQueryHandler(admin_handlers.admin_delete_service,  pattern="^admin_del_svc_"))
    app.add_handler(CallbackQueryHandler(admin_handlers.admin_bookings,        pattern="^admin_bookings$"))
    app.add_handler(CallbackQueryHandler(admin_handlers.admin_cancel_booking,  pattern="^admin_cancel_bk_"))
    app.add_handler(CallbackQueryHandler(admin_handlers.admin_slots,           pattern="^admin_slots$"))
    app.add_handler(CallbackQueryHandler(admin_handlers.admin_toggle_slot,     pattern="^admin_slot_"))
    app.add_handler(CallbackQueryHandler(admin_handlers.admin_add_slot_day,    pattern="^admin_addslot_"))

    # User callbacks
    app.add_handler(CallbackQueryHandler(user_handlers.cancel_booking_cb,      pattern="^cancel_bk_"))
    app.add_handler(CallbackQueryHandler(user_handlers.my_bookings_cb,         pattern="^my_bookings$"))

    setup_scheduler(app)

    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
