import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

import database as db
from config import REMINDER_HOURS_BEFORE

logger = logging.getLogger(__name__)


async def send_reminders(app: Application):
    now = datetime.now()
    remind_at = now + timedelta(hours=REMINDER_HOURS_BEFORE)

    now_str = now.strftime("%Y-%m-%d %H:%M")
    remind_str = remind_at.strftime("%Y-%m-%d %H:%M")

    bookings = db.get_upcoming_bookings_for_reminder(now_str, remind_str)

    for bk in bookings:
        try:
            await app.bot.send_message(
                chat_id=bk["user_id"],
                text=(
                    f"⏰ *Напоминание о записи!*\n\n"
                    f"Через {REMINDER_HOURS_BEFORE} часа у вас запись:\n"
                    f"✂️ *{bk['svc_name']}*\n"
                    f"📅 {bk['book_date']} в {bk['book_time']}\n\n"
                    f"Ждём вас! 💇"
                ),
                parse_mode="Markdown",
            )
            db.mark_reminder_sent(bk["id"])
            logger.info(f"Reminder sent for booking #{bk['id']}")
        except Exception as e:
            logger.error(f"Failed to send reminder for booking #{bk['id']}: {e}")


def setup_scheduler(app: Application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_reminders,
        trigger="interval",
        minutes=15,
        args=[app],
        id="reminder_job",
    )
    scheduler.start()
    logger.info("Reminder scheduler started (checks every 15 minutes)")
