"""SQLite helpers for CampusTrace.

Everything here uses Python's built-in sqlite3 module and parameterized
queries only (no string concatenation of user input into SQL).
"""

import os
import sqlite3
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

CATEGORIES = [
    "ID Card",
    "Electronics",
    "Keys",
    "Books",
    "Stationery",
    "Wallet",
    "Accessories",
    "Other",
]

LOCATIONS = [
    "Main Gate",
    "Library",
    "Library 2nd Floor",
    "Block A",
    "Block B",
    "Canteen",
    "Physics Lab",
    "Chemistry Lab",
    "Computer Lab",
    "Auditorium",
    "Playground",
    "Badminton Court",
    "Parking Area",
    "Other",
]

STATUSES = ["LOST", "FOUND", "RESOLVED"]

# Public columns only. The secret answer is never part of this list, so it can
# never leak into a template, a card or an API response by accident.
PUBLIC_COLUMNS = (
    "id, item_name, category, status, location, item_date, description, created_at"
)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create database.db and the items table if they do not exist yet."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
        schema = handle.read()
    conn = get_connection()
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def tracking_id(item_id, status):
    """Human-friendly tracking ID, e.g. CT-L-000007."""
    letter = {"LOST": "L", "FOUND": "F", "RESOLVED": "R"}.get(status, "X")
    return "CT-%s-%06d" % (letter, item_id)


def insert_item(data):
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO items (
                item_name, category, status, location, item_date,
                description, contact, secret_hint, secret_answer, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["item_name"],
                data["category"],
                data["status"],
                data["location"],
                data["item_date"],
                data.get("description", ""),
                data.get("contact", ""),
                data["secret_hint"],
                data["secret_answer"],
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_item(item_id):
    """Return public fields plus the secret question (never the answer)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT %s, secret_hint FROM items WHERE id = ?" % PUBLIC_COLUMNS,
            (item_id,),
        ).fetchone()
    finally:
        conn.close()


def get_items_by_status(status):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT %s FROM items WHERE status = ? ORDER BY id DESC" % PUBLIC_COLUMNS,
            (status,),
        ).fetchall()
    finally:
        conn.close()


def get_items_by_ids(ids):
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT %s FROM items WHERE id IN (%s) ORDER BY id DESC"
            % (PUBLIC_COLUMNS, placeholders),
            tuple(ids),
        ).fetchall()
    finally:
        conn.close()


def search_items(query="", category="All", location="All", status="All"):
    sql = "SELECT %s FROM items WHERE 1 = 1" % PUBLIC_COLUMNS
    params = []

    if query:
        sql += " AND (LOWER(item_name) LIKE ? OR LOWER(description) LIKE ?)"
        like = "%" + query.lower() + "%"
        params.extend([like, like])
    if category and category != "All":
        sql += " AND category = ?"
        params.append(category)
    if location and location != "All":
        sql += " AND location = ?"
        params.append(location)
    if status and status != "All":
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY id DESC"

    conn = get_connection()
    try:
        return conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()


def get_stats():
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'LOST' THEN 1 ELSE 0 END) AS lost,
                SUM(CASE WHEN status = 'FOUND' THEN 1 ELSE 0 END) AS found,
                SUM(CASE WHEN status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved
            FROM items
            """
        ).fetchone()
        return {
            "lost": row["lost"] or 0,
            "found": row["found"] or 0,
            "resolved": row["resolved"] or 0,
        }
    finally:
        conn.close()


def check_secret_answer(item_id, submitted_answer):
    """Compare answers server-side only, ignoring case and outer whitespace."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT secret_answer FROM items WHERE id = ?", (item_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return False
    return row["secret_answer"].strip().lower() == (submitted_answer or "").strip().lower()


def mark_resolved(item_id):
    conn = get_connection()
    try:
        conn.execute("UPDATE items SET status = 'RESOLVED' WHERE id = ?", (item_id,))
        conn.commit()
    finally:
        conn.close()


SAMPLE_ITEMS = [
    ("Casio fx-991CW Calculator", "Electronics", "LOST", "Physics Lab", "2026-09-24",
     "Black calculator with a red sticker on the back.", "ananya@college.edu",
     "What colour sticker is on the back?", "Red"),
    ("Student ID Card", "ID Card", "LOST", "Library", "2026-09-22",
     "Second year ID card in a transparent holder.", "9876543210",
     "What is the last digit of the roll number?", "7"),
    ("Blue Water Bottle", "Accessories", "LOST", "Canteen", "2026-09-21",
     "Steel blue bottle with a dented cap.", "rahul@college.edu",
     "What is dented on the bottle?", "Cap"),
    ("Black USB-C Charger", "Electronics", "LOST", "Computer Lab", "2026-09-23",
     "65W black charger with a white cable tie.", "meera@college.edu",
     "What colour is the cable tie?", "White"),
    ("Red Spiral Notebook", "Stationery", "LOST", "Block B", "2026-09-20",
     "Red spiral notebook with physics notes.", "dev@college.edu",
     "Which subject are the notes for?", "Physics"),
    ("Casio Scientific Calculator", "Electronics", "FOUND", "Physics Lab", "2026-09-24",
     "Black scientific calculator found on the last bench.", "Submit at Physics Lab desk",
     "What is stuck on the back of it?", "Red sticker"),
    ("Student ID Card", "ID Card", "FOUND", "Library", "2026-09-23",
     "ID card found between library shelves.", "Collect at library counter",
     "What year is printed on the card?", "Second"),
    ("Black USB-C Charger", "Electronics", "FOUND", "Computer Lab", "2026-09-23",
     "Black charger left near a lab socket.", "Collect at lab assistant desk",
     "What is tied around the cable?", "White tie"),
]


def seed_sample_data():
    """Insert demo rows once. Safe to call on every start-up."""
    conn = get_connection()
    try:
        existing = conn.execute("SELECT COUNT(*) AS total FROM items").fetchone()["total"]
    finally:
        conn.close()
    if existing:
        return 0
    for row in SAMPLE_ITEMS:
        insert_item(
            {
                "item_name": row[0],
                "category": row[1],
                "status": row[2],
                "location": row[3],
                "item_date": row[4],
                "description": row[5],
                "contact": row[6],
                "secret_hint": row[7],
                "secret_answer": row[8],
            }
        )
    return len(SAMPLE_ITEMS)


# ---------------------------------------------------------------------------
#  User authentication helpers
# ---------------------------------------------------------------------------

def create_user(name, email, password):
    """Create a new user with a hashed password.

    Returns the new user's id on success, or None if the email is already
    registered.  The password is never stored in plain text.
    """
    password_hash = generate_password_hash(password)
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (name, email, password_hash, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, email.lower().strip(), password_hash,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # UNIQUE constraint on email
        return None
    finally:
        conn.close()


def get_user_by_email(email):
    """Return a safe user dict (id, name, email) or None.  Never exposes
    the password hash."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, email FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"]}


def verify_user(email, password):
    """Check credentials.  Returns a safe user dict on success, None on
    failure.  The hash never leaves this function."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    if not check_password_hash(row["password_hash"], password):
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"]}
