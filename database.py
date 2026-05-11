import sqlite3
import os
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(__file__), "salon.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            description TEXT,
            price       INTEGER NOT NULL,   -- in RUB
            duration    INTEGER NOT NULL,   -- in minutes
            active      INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            username    TEXT,
            phone       TEXT,
            service_id  INTEGER NOT NULL,
            book_date   TEXT    NOT NULL,   -- YYYY-MM-DD
            book_time   TEXT    NOT NULL,   -- HH:MM
            status      TEXT    DEFAULT 'active',  -- active | cancelled
            reminder_sent INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (service_id) REFERENCES services(id)
        )
    """)

    # Blocked / custom slots per day
    c.execute("""
        CREATE TABLE IF NOT EXISTS slot_overrides (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_date   TEXT    NOT NULL,   -- YYYY-MM-DD
            slot_time   TEXT    NOT NULL,   -- HH:MM
            available   INTEGER DEFAULT 0   -- 0 = blocked, 1 = extra open
        )
    """)

    conn.commit()

    # Seed default services if table is empty
    if not c.execute("SELECT 1 FROM services LIMIT 1").fetchone():
        _seed_services(c)
        conn.commit()

    conn.close()


def _seed_services(c):
    services = [
        ("Стрижка женская",      "Модельная стрижка + укладка",               2500, 60),
        ("Стрижка мужская",      "Классическая или модельная стрижка",         1200, 45),
        ("Окрашивание волос",    "Однотонное окрашивание, цвет по выбору",     4500, 120),
        ("Мелирование",          "Классическое или балаяж",                    5500, 150),
        ("Кератиновое выпрямление", "Разглаживание + восстановление структуры", 8000, 180),
        ("Укладка / блоу-драй",  "Профессиональная укладка феном",             1500, 40),
        ("Лечение волос",        "Ботокс / нанопластика",                      6000, 120),
        ("Детская стрижка",      "До 12 лет",                                   800, 30),
    ]
    c.executemany(
        "INSERT INTO services (name, description, price, duration) VALUES (?,?,?,?)",
        services,
    )


# ── Services ─────────────────────────────────────────────────────────────────

def get_services(active_only=True):
    conn = get_conn()
    q = "SELECT * FROM services"
    if active_only:
        q += " WHERE active = 1"
    rows = conn.execute(q + " ORDER BY id").fetchall()
    conn.close()
    return rows


def get_service(service_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
    conn.close()
    return row


def add_service(name, description, price, duration):
    conn = get_conn()
    conn.execute(
        "INSERT INTO services (name, description, price, duration) VALUES (?,?,?,?)",
        (name, description, price, duration),
    )
    conn.commit()
    conn.close()


def update_service(service_id, name, description, price, duration):
    conn = get_conn()
    conn.execute(
        "UPDATE services SET name=?, description=?, price=?, duration=? WHERE id=?",
        (name, description, price, duration, service_id),
    )
    conn.commit()
    conn.close()


def delete_service(service_id):
    conn = get_conn()
    conn.execute("UPDATE services SET active=0 WHERE id=?", (service_id,))
    conn.commit()
    conn.close()


# ── Bookings ─────────────────────────────────────────────────────────────────

def get_booked_slots(book_date: str):
    """Return list of 'HH:MM' that are already booked on a given date."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT book_time FROM bookings WHERE book_date=? AND status='active'",
        (book_date,),
    ).fetchall()
    conn.close()
    return [r["book_time"] for r in rows]


def create_booking(user_id, username, phone, service_id, book_date, book_time):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """INSERT INTO bookings
           (user_id, username, phone, service_id, book_date, book_time)
           VALUES (?,?,?,?,?,?)""",
        (user_id, username, phone, service_id, book_date, book_time),
    )
    booking_id = c.lastrowid
    conn.commit()
    conn.close()
    return booking_id


def get_user_bookings(user_id, active_only=True):
    conn = get_conn()
    q = """SELECT b.*, s.name as svc_name, s.price as svc_price
           FROM bookings b JOIN services s ON b.service_id=s.id
           WHERE b.user_id=?"""
    if active_only:
        q += " AND b.status='active'"
    q += " ORDER BY b.book_date, b.book_time"
    rows = conn.execute(q, (user_id,)).fetchall()
    conn.close()
    return rows


def get_all_bookings(active_only=True):
    conn = get_conn()
    q = """SELECT b.*, s.name as svc_name, s.price as svc_price
           FROM bookings b JOIN services s ON b.service_id=s.id"""
    if active_only:
        q += " WHERE b.status='active'"
    q += " ORDER BY b.book_date, b.book_time"
    rows = conn.execute(q).fetchall()
    conn.close()
    return rows


def cancel_booking(booking_id):
    conn = get_conn()
    conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()


def get_booking(booking_id):
    conn = get_conn()
    row = conn.execute(
        """SELECT b.*, s.name as svc_name, s.price as svc_price
           FROM bookings b JOIN services s ON b.service_id=s.id
           WHERE b.id=?""",
        (booking_id,),
    ).fetchone()
    conn.close()
    return row


def get_upcoming_bookings_for_reminder(now_str: str, remind_str: str):
    """
    Returns bookings where appointment is between now and remind_str,
    reminder not yet sent, status active.
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT b.*, s.name as svc_name
           FROM bookings b JOIN services s ON b.service_id=s.id
           WHERE b.status='active'
             AND b.reminder_sent=0
             AND (b.book_date || ' ' || b.book_time) > ?
             AND (b.book_date || ' ' || b.book_time) <= ?
        """,
        (now_str, remind_str),
    ).fetchall()
    conn.close()
    return rows


def mark_reminder_sent(booking_id):
    conn = get_conn()
    conn.execute("UPDATE bookings SET reminder_sent=1 WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()
