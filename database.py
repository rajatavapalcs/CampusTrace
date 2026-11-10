"""SQLite helpers for CampusTrace.

Everything here uses Python's built-in sqlite3 module and parameterized
queries only (no string concatenation of user input into SQL).
"""

import hmac
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
ROLES = ("STUDENT", "ADMIN")

# Public columns only. The secret answer is never part of this list, so it can
# never leak into a template, a card or an API response by accident.
PUBLIC_COLUMNS = (
    "id, item_name, category, status, location, location_details, item_date, "
    "description, created_at"
)
SECRET_ANSWER_HASH_PREFIX = "ct-answer-v1$"


def _normalize_secret_answer(answer):
    return (answer or "").strip().lower()


def _hash_secret_answer(answer):
    return SECRET_ANSWER_HASH_PREFIX + generate_password_hash(
        _normalize_secret_answer(answer)
    )


def _is_secret_answer_hash(value):
    return value.startswith(SECRET_ANSWER_HASH_PREFIX)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the database and safely add role/moderation fields to old DBs."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
        schema = handle.read()
    conn = get_connection()
    try:
        conn.executescript(schema)
        migrations = {
            "users": {
                "role": "TEXT NOT NULL DEFAULT 'STUDENT' CHECK (role IN ('STUDENT', 'ADMIN'))",
                "is_active": "INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))",
            },
            "items": {
                "is_hidden": "INTEGER NOT NULL DEFAULT 0 CHECK (is_hidden IN (0, 1))",
                "owner_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
                "location_details": "TEXT",
            },
            "claims": {
                "evidence": "TEXT",
                "linked_lost_item_id": "INTEGER REFERENCES items(id) ON DELETE SET NULL",
            },
        }
        for table, columns in migrations.items():
            existing = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(%s)" % table).fetchall()
            }
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(
                        "ALTER TABLE %s ADD COLUMN %s %s"
                        % (table, column, definition)
                    )
        legacy_answers = conn.execute(
            "SELECT id, secret_answer FROM items WHERE secret_answer != ''"
        ).fetchall()
        for row in legacy_answers:
            if not _is_secret_answer_hash(row["secret_answer"]):
                conn.execute(
                    "UPDATE items SET secret_answer = ? WHERE id = ?",
                    (_hash_secret_answer(row["secret_answer"]), row["id"]),
                )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_owner_status ON items(owner_id, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_claims_user_status ON claims(user_id, status)"
        )
        conn.commit()
    finally:
        conn.close()


def tracking_id(item_id, status):
    """Human-friendly tracking ID, e.g. CT-L-000007."""
    letter = {"LOST": "L", "FOUND": "F", "RESOLVED": "R"}.get(status, "X")
    return "CT-%s-%06d" % (letter, item_id)


def insert_item(data, owner_id=None):
    secret_answer = data.get("secret_answer", "")
    if secret_answer:
        secret_answer = _hash_secret_answer(secret_answer)
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO items (
                item_name, category, status, location, location_details, item_date,
                description, contact, secret_hint, secret_answer, created_at,
                owner_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["item_name"],
                data["category"],
                data["status"],
                data["location"],
                data.get("location_details", ""),
                data["item_date"],
                data.get("description", ""),
                data.get("contact", ""),
                data["secret_hint"],
                secret_answer,
                datetime.now().isoformat(timespec="seconds"),
                owner_id,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_item(item_id):
    """Return only public fields for a report."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT %s FROM items WHERE id = ? AND is_hidden = 0"
            % PUBLIC_COLUMNS,
            (item_id,),
        ).fetchone()
    finally:
        conn.close()


def get_item_owner_id(item_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT owner_id FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return row["owner_id"] if row else None
    finally:
        conn.close()


def get_user_items(user_id):
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT %s FROM items
            WHERE owner_id = ? AND is_hidden = 0
            ORDER BY id DESC
            """ % PUBLIC_COLUMNS,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def get_user_lost_items(user_id):
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT id, item_name, category, location, item_date
            FROM items
            WHERE owner_id = ? AND status = 'LOST' AND is_hidden = 0
            ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def get_admin_reports():
    """Return report fields safe for staff review, never contact or answers."""
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT %s, is_hidden,
                   EXISTS (
                       SELECT 1 FROM claims
                       WHERE claims.item_id = items.id AND claims.status = 'APPROVED'
                   ) AS has_approved_claim
            FROM items ORDER BY id DESC
            """ % PUBLIC_COLUMNS,
        ).fetchall()
    finally:
        conn.close()


def get_items_by_status(status):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT %s FROM items WHERE status = ? AND is_hidden = 0 ORDER BY id DESC"
            % PUBLIC_COLUMNS,
            (status,),
        ).fetchall()
    finally:
        conn.close()


def get_categories_with_items():
    """Return predefined categories plus any custom categories already stored."""
    placeholders = ",".join("?" for _ in CATEGORIES)
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT category FROM items
            WHERE is_hidden = 0 AND category NOT IN (%s)
            ORDER BY LOWER(category), category
            """ % placeholders,
            tuple(CATEGORIES),
        ).fetchall()
        return CATEGORIES + [row["category"] for row in rows]
    finally:
        conn.close()


def get_items_by_ids(ids):
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT %s FROM items WHERE id IN (%s) AND is_hidden = 0 ORDER BY id DESC"
            % (PUBLIC_COLUMNS, placeholders),
            tuple(ids),
        ).fetchall()
    finally:
        conn.close()


def search_items(query="", category="All", location="All", status="All"):
    sql = "SELECT %s FROM items WHERE 1 = 1" % PUBLIC_COLUMNS
    sql += " AND is_hidden = 0"
    params = []

    if query:
        sql += """
            AND (
                LOWER(item_name) LIKE ?
                OR LOWER(description) LIKE ?
                OR LOWER(COALESCE(location_details, '')) LIKE ?
            )
        """
        like = "%" + query.lower() + "%"
        params.extend([like, like, like])
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
            FROM items WHERE is_hidden = 0
            """
        ).fetchone()
        return {
            "lost": row["lost"] or 0,
            "found": row["found"] or 0,
            "resolved": row["resolved"] or 0,
        }
    finally:
        conn.close()


def check_owned_lost_answer(user_id, item_id, submitted_answer):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT secret_answer FROM items
            WHERE id = ? AND owner_id = ? AND status = 'LOST' AND is_hidden = 0
            """,
            (item_id, user_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not row["secret_answer"]:
        return False
    stored_answer = row["secret_answer"]
    normalized_answer = _normalize_secret_answer(submitted_answer)
    if _is_secret_answer_hash(stored_answer):
        return check_password_hash(
            stored_answer[len(SECRET_ANSWER_HASH_PREFIX):],
            normalized_answer,
        )
    return hmac.compare_digest(
        stored_answer.strip().lower().encode("utf-8"),
        normalized_answer.encode("utf-8"),
    )


def admin_set_item_resolved(item_id):
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        approved_claim = conn.execute(
            """
            SELECT 1 FROM claims
            WHERE item_id = ? AND status = 'APPROVED'
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()
        if approved_claim is None:
            conn.rollback()
            return False
        cursor = conn.execute(
            """
            UPDATE items SET status = 'RESOLVED'
            WHERE id = ? AND status = 'FOUND' AND is_hidden = 0
            """,
            (item_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def moderate_item(item_id, action):
    if action not in ("hide", "restore", "delete"):
        raise ValueError("Invalid report moderation action.")
    conn = get_connection()
    try:
        if action == "delete":
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM claims WHERE item_id = ?", (item_id,))
            cursor = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        else:
            hidden = 1 if action == "hide" else 0
            cursor = conn.execute(
                "UPDATE items SET is_hidden = ? WHERE id = ?", (hidden, item_id)
            )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def create_student_claim(user_id, item_id, evidence, linked_lost_item_id=None):
    """Create a pending claim for a visible found report."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        found_item = conn.execute(
            """
            SELECT id, status, is_hidden, owner_id
            FROM items WHERE id = ?
            """,
            (item_id,),
        ).fetchone()
        if (
            found_item is None
            or found_item["status"] != "FOUND"
            or found_item["is_hidden"]
        ):
            conn.rollback()
            return "item_unavailable"
        if found_item["owner_id"] == user_id:
            conn.rollback()
            return "own_report"

        if linked_lost_item_id is not None:
            owned_lost = conn.execute(
                """
                SELECT id FROM items
                WHERE id = ? AND owner_id = ? AND status = 'LOST' AND is_hidden = 0
                """,
                (linked_lost_item_id, user_id),
            ).fetchone()
            if owned_lost is None:
                conn.rollback()
                return "invalid_lost_report"

        pending_claim = conn.execute(
            """
            SELECT id FROM claims
            WHERE item_id = ? AND user_id = ? AND status IN ('PENDING', 'DISPUTED')
            """,
            (item_id, user_id),
        ).fetchone()
        if pending_claim:
            conn.rollback()
            return "already_pending"

        cursor = conn.execute(
            """
            INSERT INTO claims (
                item_id, user_id, status, evidence, linked_lost_item_id, created_at
            ) VALUES (?, ?, 'PENDING', ?, ?, ?)
            """,
            (
                item_id,
                user_id,
                evidence,
                linked_lost_item_id,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_admin_claims():
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT claims.id, claims.item_id, claims.user_id, claims.status,
                   claims.reason, claims.evidence, claims.linked_lost_item_id,
                   claims.created_at, claims.reviewed_at,
                   users.name AS claimant_name, users.email AS claimant_email,
                   items.item_name, items.status AS item_status,
                   lost_items.item_name AS linked_lost_item_name
            FROM claims
            JOIN users ON users.id = claims.user_id
            JOIN items ON items.id = claims.item_id
            LEFT JOIN items AS lost_items ON lost_items.id = claims.linked_lost_item_id
            ORDER BY CASE claims.status
                WHEN 'PENDING' THEN 0 WHEN 'DISPUTED' THEN 1
                WHEN 'APPROVED' THEN 2 WHEN 'REJECTED' THEN 3 ELSE 4 END,
                claims.id DESC
            """
        ).fetchall()
    finally:
        conn.close()


def get_user_claims(user_id):
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT claims.id, claims.item_id, claims.status, claims.evidence,
                   claims.created_at, claims.reviewed_at, items.item_name,
                   CASE
                       WHEN claims.status = 'APPROVED'
                           AND items.status IN ('FOUND', 'RESOLVED')
                           AND items.is_hidden = 0
                           AND NOT EXISTS (
                               SELECT 1 FROM claims AS other_claim
                               WHERE other_claim.item_id = claims.item_id
                                 AND other_claim.id != claims.id
                                 AND other_claim.status = 'APPROVED'
                           )
                       THEN items.contact
                       ELSE NULL
                   END AS reporter_contact
            FROM claims
            JOIN items ON items.id = claims.item_id
            WHERE claims.user_id = ?
            ORDER BY claims.id DESC
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def review_claim(claim_id, admin_id, decision):
    if decision not in ("APPROVED", "REJECTED"):
        raise ValueError("Invalid claim decision.")
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT claims.item_id, items.status AS item_status, items.is_hidden
            FROM claims
            JOIN items ON items.id = claims.item_id
            WHERE claims.id = ? AND claims.status IN ('PENDING', 'DISPUTED')
            """,
            (claim_id,),
        ).fetchone()
        if row is None:
            conn.rollback()
            return False
        if (
            decision == "APPROVED"
            and (row["item_status"] != "FOUND" or row["is_hidden"])
        ):
            conn.rollback()
            return False
        if decision == "APPROVED":
            already_approved = conn.execute(
                """
                SELECT 1 FROM claims
                WHERE item_id = ? AND id != ? AND status = 'APPROVED'
                LIMIT 1
                """,
                (row["item_id"], claim_id),
            ).fetchone()
            if already_approved:
                conn.rollback()
                return False
        conn.execute(
            """
            UPDATE claims
            SET status = ?, reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (
                decision,
                admin_id,
                datetime.now().isoformat(timespec="seconds"),
                claim_id,
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def dispute_claim(claim_id, user_id):
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE claims SET status = 'DISPUTED'
            WHERE id = ? AND user_id = ? AND status IN ('VERIFIED', 'APPROVED')
            """,
            (claim_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def admin_dispute_claim(claim_id):
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE claims SET status = 'DISPUTED'
            WHERE id = ? AND status IN ('VERIFIED', 'RESOLVED', 'APPROVED')
            """,
            (claim_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_admin_dashboard_stats():
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM items) AS total_reports,
                (SELECT COUNT(*) FROM claims
                 WHERE status IN ('PENDING', 'DISPUTED')) AS pending_claims,
                (SELECT COUNT(*) FROM items WHERE status = 'RESOLVED') AS resolved_items,
                (SELECT COUNT(*) FROM users) AS registered_users
            """
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_admin_users():
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, name, email, role, is_active, created_at FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def set_user_active(user_id, is_active, acting_admin_id):
    if is_active not in (0, 1):
        raise ValueError("Invalid account status.")
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute(
            "SELECT id, role, is_active FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user is None:
            conn.rollback()
            return "not_found"
        if is_active == 0 and user_id == acting_admin_id:
            conn.rollback()
            return "self"
        if (
            is_active == 0
            and user["role"] == "ADMIN"
            and user["is_active"]
        ):
            active_admins = conn.execute(
                "SELECT COUNT(*) AS total FROM users WHERE role = 'ADMIN' AND is_active = 1"
            ).fetchone()["total"]
            if active_admins <= 1:
                conn.rollback()
                return "last_admin"
        conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?", (is_active, user_id)
        )
        conn.commit()
        return "updated"
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
            INSERT INTO users (name, email, password_hash, created_at, role, is_active)
            VALUES (?, ?, ?, ?, 'STUDENT', 1)
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


def create_first_admin(name, email, password):
    """Create an Admin only when no Admin exists; intended for the CLI only."""
    password_hash = generate_password_hash(password)
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing_admin = conn.execute(
            "SELECT 1 FROM users WHERE role = 'ADMIN' LIMIT 1"
        ).fetchone()
        if existing_admin:
            conn.rollback()
            return "admin_exists"
        try:
            conn.execute(
                """
                INSERT INTO users (name, email, password_hash, created_at, role, is_active)
                VALUES (?, ?, ?, ?, 'ADMIN', 1)
                """,
                (
                    name,
                    email.lower().strip(),
                    password_hash,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            return "email_exists"
        conn.commit()
        return "created"
    finally:
        conn.close()


def has_admin_account():
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT 1 FROM users WHERE role = 'ADMIN' LIMIT 1"
        ).fetchone() is not None
    finally:
        conn.close()


def get_user_by_email(email):
    """Return safe account fields, never the password hash."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, email, role, is_active FROM users WHERE email = ?",
            (email.lower().strip(),),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["role"] not in ROLES:
        return None
    return dict(row)


def get_user_by_id(user_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, email, role, is_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["role"] not in ROLES:
        return None
    return dict(row)


def verify_user(email, password):
    """Check credentials.  Returns a safe user dict on success, None on
    failure.  The hash never leaves this function."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, name, email, password_hash, role, is_active
            FROM users WHERE email = ?
            """,
            (email.lower().strip(),),
        ).fetchone()
    finally:
        conn.close()
    if (
        row is None
        or row["role"] not in ROLES
        or not row["is_active"]
    ):
        return None
    if not check_password_hash(row["password_hash"], password):
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "is_active": row["is_active"],
    }
