from __future__ import annotations

from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from config import ADMIN_USERNAME, DEFAULT_TIME_SLOTS, BOOKING_DAYS_AHEAD

# ── Conversation states ───────────────────────────────────────────────────────
SVC_NAME, SVC_DESC, SVC_PRICE, SVC_DURATION = range(10, 14)


def _is_admin(update: Update) -> bool:
    return update.effective_user.username == ADMIN_USERNAME


def _admin_guard(func):
    """Decorator: returns None silently if not admin."""
    import functools

    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_admin(update):
            if update.callback_query:
                await update.callback_query.answer("⛔ Нет доступа", show_alert=True)
            else:
                await update.message.reply_text("⛔ Нет доступа.")
            return
        return await func(update, ctx)

    return wrapper


# ── Panel entry ───────────────────────────────────────────────────────────────

@_admin_guard
async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = _admin_keyboard()
    await update.message.reply_text(
        "🔧 *Панель администратора*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@_admin_guard
async def admin_panel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔧 *Панель администратора*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(_admin_keyboard()),
    )


def _admin_keyboard():
    return [
        [InlineKeyboardButton("✂️ Услуги",        callback_data="admin_services")],
        [InlineKeyboardButton("📋 Записи",         callback_data="admin_bookings")],
        [InlineKeyboardButton("🕐 Слоты",          callback_data="admin_slots")],
    ]


# ── Services management ───────────────────────────────────────────────────────

def _build_services_message():
    """Returns (text, keyboard) for the services list."""
    services = db.get_services(active_only=False)
    text = "✂️ *Услуги салона:*\n\n"
    keyboard = []

    for svc in services:
        status = "✅" if svc["active"] else "❌"
        text += f"{status} *{svc['name']}* — {svc['price']} ₽ ({svc['duration']} мин)\n"
        if svc["description"]:
            text += f"   _{svc['description']}_\n"
        text += "\n"
        if svc["active"]:
            keyboard.append([
                InlineKeyboardButton(f"✏️ {svc['name'][:25]}", callback_data=f"admin_edit_svc_{svc['id']}"),
                InlineKeyboardButton("🗑️", callback_data=f"admin_del_svc_{svc['id']}"),
            ])

    keyboard.append([InlineKeyboardButton("➕ Добавить услугу", callback_data="admin_add_svc")])
    keyboard.append([InlineKeyboardButton("« Назад", callback_data="admin_panel")])
    return text, keyboard


@_admin_guard
async def admin_services(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text, keyboard = _build_services_message()
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@_admin_guard
async def admin_delete_service(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    service_id = int(query.data.split("_")[-1])
    svc = db.get_service(service_id)
    db.delete_service(service_id)
    # Answer with alert (only once)
    await query.answer(f"🗑️ Услуга «{svc['name']}» удалена", show_alert=True)
    # Refresh the list in the same message
    text, keyboard = _build_services_message()
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


# ── Add service flow ──────────────────────────────────────────────────────────

@_admin_guard
async def admin_add_service(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["editing_service_id"] = None
    await query.edit_message_text("📝 Введите *название* новой услуги:", parse_mode="Markdown")
    return SVC_NAME


@_admin_guard
async def admin_edit_service_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_id = int(query.data.split("_")[-1])
    ctx.user_data["editing_service_id"] = service_id
    svc = db.get_service(service_id)
    ctx.user_data["old_svc"] = dict(svc)
    await query.edit_message_text(
        f"✏️ Редактирование услуги *{svc['name']}*\n\nВведите новое *название* (или отправьте «.» чтобы оставить прежнее):",
        parse_mode="Markdown",
    )
    return SVC_NAME


async def svc_get_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    old = ctx.user_data.get("old_svc", {})
    ctx.user_data["svc_name"] = old.get("name", "") if text == "." else text
    await update.message.reply_text("📝 Введите *описание* услуги (или «.» пропустить):", parse_mode="Markdown")
    return SVC_DESC


async def svc_get_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    old = ctx.user_data.get("old_svc", {})
    ctx.user_data["svc_desc"] = old.get("description", "") if text == "." else text
    await update.message.reply_text("💰 Введите *цену* в рублях (только число):", parse_mode="Markdown")
    return SVC_PRICE


async def svc_get_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Введите число, например: 1500")
        return SVC_PRICE
    ctx.user_data["svc_price"] = int(text)
    await update.message.reply_text("⏱️ Введите *длительность* в минутах (число):", parse_mode="Markdown")
    return SVC_DURATION


async def svc_get_duration(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Введите число минут, например: 60")
        return SVC_DURATION

    service_id = ctx.user_data.get("editing_service_id")
    name = ctx.user_data["svc_name"]
    desc = ctx.user_data["svc_desc"]
    price = ctx.user_data["svc_price"]
    duration = int(text)

    if service_id:
        db.update_service(service_id, name, desc, price, duration)
        msg = f"✅ Услуга *{name}* обновлена."
    else:
        db.add_service(name, desc, price, duration)
        msg = f"✅ Услуга *{name}* добавлена."

    keyboard = [[InlineKeyboardButton("« К услугам", callback_data="admin_services")]]
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    ctx.user_data.clear()
    return ConversationHandler.END


async def admin_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Отменено.")
    return ConversationHandler.END


# ── Bookings view ─────────────────────────────────────────────────────────────

@_admin_guard
async def admin_bookings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bookings = db.get_all_bookings(active_only=True)

    if not bookings:
        text = "📋 Нет активных записей."
        keyboard = [[InlineKeyboardButton("« Назад", callback_data="admin_panel")]]
    else:
        text = "📋 *Активные записи:*\n\n"
        keyboard = []
        for bk in bookings:
            uname = f"@{bk['username']}" if bk['username'] and not bk['username'].startswith('@') else bk['username'] or "—"
            text += (
                f"#{bk['id']} *{bk['svc_name']}*\n"
                f"   📅 {bk['book_date']} {bk['book_time']}\n"
                f"   👤 {uname} | 📱 {bk['phone'] or '—'}\n\n"
            )
            keyboard.append([
                InlineKeyboardButton(
                    f"❌ Отменить #{bk['id']}",
                    callback_data=f"admin_cancel_bk_{bk['id']}"
                )
            ])
        keyboard.append([InlineKeyboardButton("« Назад", callback_data="admin_panel")])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


@_admin_guard
async def admin_cancel_booking(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[-1])
    bk = db.get_booking(booking_id)
    if bk:
        db.cancel_booking(booking_id)
        await query.answer(f"Запись #{booking_id} отменена", show_alert=True)
        # Notify client
        try:
            await ctx.bot.send_message(
                chat_id=bk["user_id"],
                text=f"ℹ️ Ваша запись на *{bk['svc_name']}* {bk['book_date']} в {bk['book_time']} была отменена администратором.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
    # Refresh
    await admin_bookings(update, ctx)


# ── Slots management ──────────────────────────────────────────────────────────

@_admin_guard
async def admin_slots(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show next 7 days with slot info."""
    query = update.callback_query
    await query.answer()
    today = date.today()
    keyboard = []
    for i in range(7):
        d = today + timedelta(days=i)
        booked = db.get_booked_slots(d.isoformat())
        free = len(DEFAULT_TIME_SLOTS) - len(booked)
        label = f"{d.strftime('%d.%m %a')} — свободно {free} слотов"
        keyboard.append([
            InlineKeyboardButton(label, callback_data=f"admin_addslot_{d.isoformat()}")
        ])
    keyboard.append([InlineKeyboardButton("« Назад", callback_data="admin_panel")])
    await query.edit_message_text(
        "🕐 *Управление слотами (ближайшие 7 дней)*\n\nВыберите день чтобы посмотреть слоты:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@_admin_guard
async def admin_add_slot_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    day = query.data.split("_")[-1]
    booked = db.get_booked_slots(day)
    keyboard = []
    row = []
    for t in DEFAULT_TIME_SLOTS:
        status = "🔴" if t in booked else "🟢"
        row.append(InlineKeyboardButton(f"{status} {t}", callback_data=f"admin_slot_{day}_{t}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("« Назад", callback_data="admin_slots")])

    d_fmt = date.fromisoformat(day).strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"🕐 *Слоты на {d_fmt}:*\n🟢 свободно  🔴 занято",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@_admin_guard
async def admin_toggle_slot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admins can see slot status; booking cancellation happens via bookings menu."""
    query = update.callback_query
    await query.answer("Для отмены конкретной записи используйте меню «Записи»", show_alert=True)
