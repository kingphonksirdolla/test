from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from config import ADMIN_USERNAME, BOOKING_DAYS_AHEAD, DEFAULT_TIME_SLOTS

# ── Conversation states ───────────────────────────────────────────────────────
SELECT_SERVICE, SELECT_DATE, SELECT_TIME, ENTER_PHONE, CONFIRM = range(5)

MONTHS_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


# ── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("✂️ Записаться", callback_data="book")],
        [InlineKeyboardButton("📋 Мои записи", callback_data="my_bookings")],
    ]
    if update.effective_user.username == ADMIN_USERNAME:
        keyboard.append([InlineKeyboardButton("🔧 Панель администратора", callback_data="admin_panel")])

    await update.message.reply_text(
        "👋 Добро пожаловать в салон красоты!\n\n"
        "Здесь вы можете записаться на услугу, выбрать удобное время и получить напоминание.\n\n"
        "Что вас интересует?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── My bookings ───────────────────────────────────────────────────────────────

async def my_bookings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bookings = db.get_user_bookings(user_id)
    if not bookings:
        text = "У вас нет активных записей."
        keyboard = [[InlineKeyboardButton("✂️ Записаться", callback_data="book")]]
    else:
        text = "📋 *Ваши записи:*\n\n"
        keyboard = []
        for bk in bookings:
            dt = datetime.strptime(f"{bk['book_date']} {bk['book_time']}", "%Y-%m-%d %H:%M")
            text += (
                f"📌 *{bk['svc_name']}*\n"
                f"   📅 {dt.strftime('%d.%m.%Y')} в {bk['book_time']}\n"
                f"   💰 {bk['svc_price']} ₽\n\n"
            )
            keyboard.append([
                InlineKeyboardButton(
                    f"❌ Отменить {bk['svc_name'][:20]} {bk['book_time']}",
                    callback_data=f"cancel_bk_{bk['id']}"
                )
            ])
        keyboard.append([InlineKeyboardButton("✂️ Записаться ещё", callback_data="book")])

    msg = update.message or update.callback_query.message
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def my_bookings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await my_bookings(update, ctx)


async def cancel_booking_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[-1])
    bk = db.get_booking(booking_id)

    if not bk or bk["user_id"] != update.effective_user.id:
        await query.edit_message_text("❌ Запись не найдена.")
        return

    db.cancel_booking(booking_id)
    await query.edit_message_text(
        f"✅ Запись на *{bk['svc_name']}* {bk['book_date']} в {bk['book_time']} отменена.",
        parse_mode="Markdown",
    )


# ── Booking flow ──────────────────────────────────────────────────────────────

async def start_booking(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    return await _show_services(query)


async def _show_services(query):
    services = db.get_services()
    if not services:
        await query.edit_message_text("😔 Список услуг временно недоступен. Попробуйте позже.")
        return ConversationHandler.END

    keyboard = []
    for svc in services:
        keyboard.append([
            InlineKeyboardButton(
                f"{svc['name']} — {svc['price']} ₽ ({svc['duration']} мин)",
                callback_data=f"svc_{svc['id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="cancel_flow")])

    await query.edit_message_text(
        "✂️ *Выберите услугу:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_SERVICE


async def select_service(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_id = int(query.data.split("_")[1])
    svc = db.get_service(service_id)
    ctx.user_data["service_id"] = service_id
    ctx.user_data["service_name"] = svc["name"]
    ctx.user_data["service_price"] = svc["price"]

    today = date.today()
    ctx.user_data["cal_year"] = today.year
    ctx.user_data["cal_month"] = today.month

    await _send_calendar(query, today.year, today.month, ctx)
    return SELECT_DATE


async def nav_calendar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, direction, year, month = query.data.split("_")
    year, month = int(year), int(month)

    if direction == "prev":
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    else:
        month += 1
        if month == 13:
            month, year = 1, year + 1

    ctx.user_data["cal_year"] = year
    ctx.user_data["cal_month"] = month
    await _send_calendar(query, year, month, ctx)
    return SELECT_DATE


async def _send_calendar(query, year, month, ctx):
    today = date.today()
    max_date = today + timedelta(days=BOOKING_DAYS_AHEAD)

    keyboard = []
    # Header
    keyboard.append([
        InlineKeyboardButton("◀️", callback_data=f"cal_prev_{year}_{month}"),
        InlineKeyboardButton(f"{MONTHS_RU[month]} {year}", callback_data="noop"),
        InlineKeyboardButton("▶️", callback_data=f"cal_next_{year}_{month}"),
    ])
    # Weekday labels
    keyboard.append([InlineKeyboardButton(d, callback_data="noop") for d in WEEKDAYS_RU])

    first_day = date(year, month, 1)
    start_weekday = first_day.weekday()  # 0 = Monday

    # Days in month
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    day = 1
    week = [InlineKeyboardButton(" ", callback_data="noop")] * start_weekday

    for _ in range(start_weekday, 7):
        if day > last_day.day:
            week.append(InlineKeyboardButton(" ", callback_data="noop"))
        else:
            d = date(year, month, day)
            if d < today or d > max_date or d.weekday() == 6:  # no Sundays
                week.append(InlineKeyboardButton(f"·{day}·", callback_data="noop"))
            else:
                week.append(InlineKeyboardButton(
                    str(day), callback_data=f"date_{d.isoformat()}"
                ))
            day += 1

    keyboard.append(week)

    while day <= last_day.day:
        week = []
        for _ in range(7):
            if day > last_day.day:
                week.append(InlineKeyboardButton(" ", callback_data="noop"))
            else:
                d = date(year, month, day)
                if d < today or d > max_date or d.weekday() == 6:
                    week.append(InlineKeyboardButton(f"·{day}·", callback_data="noop"))
                else:
                    week.append(InlineKeyboardButton(
                        str(day), callback_data=f"date_{d.isoformat()}"
                    ))
                day += 1
        keyboard.append(week)

    keyboard.append([InlineKeyboardButton("« Назад к услугам", callback_data="back_to_services")])

    await query.edit_message_text(
        f"📅 *Выберите дату для услуги:*\n_{ctx.user_data.get('service_name', '')}_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def select_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chosen_date = query.data.split("_", 1)[1]  # date_YYYY-MM-DD -> YYYY-MM-DD
    ctx.user_data["book_date"] = chosen_date

    booked = db.get_booked_slots(chosen_date)
    available = [t for t in DEFAULT_TIME_SLOTS if t not in booked]

    # Filter out past time slots if the chosen date is today
    if chosen_date == date.today().isoformat():
        now = datetime.now()
        # Add 30-minute buffer so people can't book something that starts in 5 min
        cutoff = (now + timedelta(minutes=30)).strftime("%H:%M")
        available = [t for t in available if t >= cutoff]

    if not available:
        await query.edit_message_text(
            "😔 На выбранную дату свободных слотов нет. Пожалуйста, выберите другой день.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« К календарю", callback_data="back_to_services")
            ]])
        )
        return SELECT_DATE

    keyboard = []
    row = []
    for t in available:
        row.append(InlineKeyboardButton(t, callback_data=f"time_{t}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("« Назад к дате", callback_data="back_to_date")])

    d = datetime.strptime(chosen_date, "%Y-%m-%d")
    await query.edit_message_text(
        f"🕐 *Выберите время на {d.strftime('%d.%m.%Y')}:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SELECT_TIME


async def back_to_services_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Back button handler — return to service list."""
    query = update.callback_query
    await query.answer()
    return await _show_services(query)


async def back_to_date_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Back button handler — return to calendar."""
    query = update.callback_query
    await query.answer()
    year = ctx.user_data.get("cal_year", date.today().year)
    month = ctx.user_data.get("cal_month", date.today().month)
    await _send_calendar(query, year, month, ctx)
    return SELECT_DATE


async def select_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["book_time"] = query.data.split("_", 1)[1]

    await query.edit_message_text(
        "📱 Пожалуйста, введите ваш *номер телефона* для подтверждения записи:",
        parse_mode="Markdown",
    )
    return ENTER_PHONE


async def enter_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()

    # Strip everything except digits and leading +
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)

    # Normalize Russian 8XXXXXXXXXX → +7XXXXXXXXXX
    if re.match(r"^8\d{10}$", cleaned):
        cleaned = "+7" + cleaned[1:]
    # Add + if starts with 7 and has 11 digits
    elif re.match(r"^7\d{10}$", cleaned):
        cleaned = "+" + cleaned
    # Add +7 if 10 digits (local format)
    elif re.match(r"^\d{10}$", cleaned):
        cleaned = "+7" + cleaned
    # Already has +
    elif re.match(r"^\+\d{11,12}$", cleaned):
        pass
    else:
        await update.message.reply_text(
            "❌ Не могу распознать номер.\n\n"
            "Пожалуйста, введите в одном из форматов:\n"
            "• +79001234567\n"
            "• 89001234567\n"
            "• 79001234567\n"
            "• 9001234567"
        )
        return ENTER_PHONE

    ctx.user_data["phone"] = cleaned

    svc_name = ctx.user_data["service_name"]
    svc_price = ctx.user_data["service_price"]
    book_date = ctx.user_data["book_date"]
    book_time = ctx.user_data["book_time"]
    d = datetime.strptime(book_date, "%Y-%m-%d")

    text = (
        "✅ *Подтвердите запись:*\n\n"
        f"✂️ Услуга: *{svc_name}*\n"
        f"💰 Стоимость: *{svc_price} ₽*\n"
        f"📅 Дата: *{d.strftime('%d.%m.%Y')}*\n"
        f"🕐 Время: *{book_time}*\n"
        f"📱 Телефон: *{cleaned}*"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_flow")],
    ]
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM


async def confirm_booking(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    booking_id = db.create_booking(
        user_id=user.id,
        username=user.username or user.full_name,
        phone=ctx.user_data["phone"],
        service_id=ctx.user_data["service_id"],
        book_date=ctx.user_data["book_date"],
        book_time=ctx.user_data["book_time"],
    )

    d = datetime.strptime(ctx.user_data["book_date"], "%Y-%m-%d")
    await query.edit_message_text(
        f"🎉 *Запись успешно создана!*\n\n"
        f"✂️ {ctx.user_data['service_name']}\n"
        f"📅 {d.strftime('%d.%m.%Y')} в {ctx.user_data['book_time']}\n\n"
        f"Мы напомним вам за 4 часа до визита. До встречи! 💇",
        parse_mode="Markdown",
    )

    # Notify admin
    uname = f"@{user.username}" if user.username else user.full_name
    admin_text = (
        f"🔔 *Новая запись #{booking_id}*\n\n"
        f"👤 Клиент: {uname}\n"
        f"📱 Телефон: {ctx.user_data['phone']}\n"
        f"✂️ Услуга: {ctx.user_data['service_name']}\n"
        f"📅 {d.strftime('%d.%m.%Y')} в {ctx.user_data['book_time']}"
    )
    try:
        await ctx.bot.send_message(
            chat_id=f"@{ADMIN_USERNAME}",
            text=admin_text,
            parse_mode="Markdown",
        )
    except Exception as e:
        pass  # admin might not have started the bot yet

    ctx.user_data.clear()
    return ConversationHandler.END


async def cancel_booking_flow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = "🏠 *Главное меню*\n\nЧем могу помочь?"
    keyboard = [
        [InlineKeyboardButton("✂️ Записаться", callback_data="book")],
        [InlineKeyboardButton("📋 Мои записи", callback_data="my_bookings")],
    ]
    if update.effective_user.username and update.effective_user.username.lower() == ADMIN_USERNAME.lower():
        keyboard.append([InlineKeyboardButton("🔧 Панель администратора", callback_data="admin_panel")])

    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
    return ConversationHandler.END
