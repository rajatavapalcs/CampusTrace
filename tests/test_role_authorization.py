import os
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as campus_app
import database as db


class RoleAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp_dir.name, "test.db")
        db.init_db()
        campus_app.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.student_id = db.create_user("Student", "student@example.edu", "password1")
        self.admin_id = db.create_user("Admin", "admin@example.edu", "password1")
        conn = db.get_connection()
        try:
            conn.execute(
                "UPDATE users SET role = 'ADMIN' WHERE id = ?", (self.admin_id,)
            )
            conn.commit()
        finally:
            conn.close()
        self.item_id = db.insert_item(
            {
                "item_name": "Test item",
                "category": "Electronics",
                "status": "FOUND",
                "location": "Library",
                "item_date": "2026-10-24",
                "description": "",
                "contact": "private@example.edu",
                "secret_hint": "Private question",
                "secret_answer": "Private answer",
            }
        )
        self.client = campus_app.app.test_client()

    def tearDown(self):
        db.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def csrf_token(self, client=None, path="/"):
        client = client or self.client
        response = client.get(path)
        with client.session_transaction() as user_session:
            token = user_session.get("csrf_token")
        if token:
            return token
        match = re.search(
            rb'name="csrf_token" value="([^"]+)"', response.get_data()
        )
        self.assertIsNotNone(match)
        return match.group(1).decode("ascii")

    def login(self, email, client=None):
        client = client or self.client
        token = self.csrf_token(client, "/login")
        return client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": email,
                "password": "password1",
            },
        )

    def test_public_registration_cannot_assign_admin(self):
        token = self.csrf_token(path="/register")
        response = self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "name": "New Student",
                "email": "new@example.edu",
                "password": "password1",
                "confirm_password": "password1",
                "role": "ADMIN",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.get_user_by_email("new@example.edu")["role"], "STUDENT")
        self.assertEqual(self.client.get("/admin").status_code, 403)

    def test_sqlite_rejects_roles_outside_supported_set(self):
        conn = db.get_connection()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE users SET role = 'SUPERUSER' WHERE id = ?",
                    (self.student_id,),
                )
        finally:
            conn.close()

    def test_unauthenticated_access_redirects_to_login(self):
        self.assertEqual(self.client.get("/admin").status_code, 302)
        self.assertEqual(self.client.get("/admin/reports").status_code, 302)
        self.assertEqual(self.client.get("/report/lost").status_code, 302)
        homepage = self.client.get("/").get_data()
        self.assertNotIn(b"Log in to report", homepage)
        self.assertNotIn(b"Create an account", homepage)
        self.assertIn(b"Search Items", homepage)
        self.assertIn(b"Log in", homepage)
        self.assertIn(b"Register", homepage)
        response = self.client.post(
            "/admin/reports/%d/moderate" % self.item_id,
            data={"action": "hide"},
        )
        self.assertEqual(response.status_code, 302)

    def test_history_controls_render_on_public_and_admin_pages(self):
        for path in ("/", "/search"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'id="historyBack"', response.get_data())
            self.assertIn(b'id="historyForward"', response.get_data())
            self.assertIn(b'aria-label="Go back"', response.get_data())
            self.assertIn(b'aria-label="Go forward"', response.get_data())

        self.login("admin@example.edu")
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="historyBack"', response.get_data())
        self.assertIn(b'id="historyForward"', response.get_data())

    def test_student_can_use_student_features_but_cannot_access_admin(self):
        self.login("student@example.edu")
        self.assertEqual(self.client.get("/report/lost").status_code, 200)
        self.assertEqual(self.client.get("/my-reports").status_code, 200)
        home = self.client.get("/").get_data()
        self.assertIn(b"Report Lost", home)
        self.assertNotIn(b">Admin</a>", home)
        self.assertEqual(self.client.get("/admin").status_code, 403)
        self.assertEqual(self.client.get("/admin/reports").status_code, 403)
        self.assertEqual(self.client.get("/admin/claims").status_code, 403)
        self.assertEqual(self.client.get("/admin/users").status_code, 403)

    def test_shared_login_redirects_each_role_to_its_home(self):
        student_client = campus_app.app.test_client()
        student_response = self.login("student@example.edu", student_client)
        self.assertEqual(student_response.status_code, 302)
        self.assertEqual(student_response.headers["Location"], "/")
        self.assertEqual(
            student_client.get("/login").headers["Location"], "/"
        )

        admin_client = campus_app.app.test_client()
        admin_response = self.login("admin@example.edu", admin_client)
        self.assertEqual(admin_response.status_code, 302)
        self.assertEqual(admin_response.headers["Location"], "/admin")
        self.assertEqual(
            admin_client.get("/login").headers["Location"], "/admin"
        )

    def test_admin_navigation_shows_admin_tools_not_student_actions(self):
        self.login("admin@example.edu")
        page = self.client.get("/admin").get_data()
        self.assertIn(b"Admin Dashboard", page)
        self.assertIn(b"Manage Reports", page)
        self.assertIn(b"Review Claims", page)
        self.assertIn(b"Manage Accounts", page)
        self.assertNotIn(b">Report Lost</a>", page)
        self.assertNotIn(b">My Reports</a>", page)

    def test_student_cannot_perform_admin_post_even_with_session_role_value(self):
        self.login("student@example.edu")
        with self.client.session_transaction() as user_session:
            user_session["role"] = "ADMIN"
        response = self.client.post(
            "/admin/reports/%d/moderate" % self.item_id,
            data={"action": "hide"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(db.get_item(self.item_id)["item_name"], "Test item")

    def test_admin_can_access_and_manage_reports(self):
        self.login("admin@example.edu")
        dashboard = self.client.get("/admin")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b">Admin Dashboard</a>", dashboard.get_data())
        self.assertEqual(self.client.get("/admin/reports").status_code, 200)
        self.assertEqual(self.client.get("/admin/claims").status_code, 200)
        self.assertEqual(self.client.get("/admin/users").status_code, 200)

        token = self.csrf_token(path="/admin/reports")
        response = self.client.post(
            "/admin/reports/%d/moderate" % self.item_id,
            data={"csrf_token": token, "action": "hide"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(db.get_item(self.item_id))
        self.assertNotIn(b"Test item", self.client.get("/search").get_data())

    def test_suspended_user_is_removed_from_authenticated_session(self):
        self.login("student@example.edu")
        conn = db.get_connection()
        try:
            conn.execute(
                "UPDATE users SET is_active = 0 WHERE id = ?", (self.student_id,)
            )
            conn.commit()
        finally:
            conn.close()
        response = self.client.get("/my-reports")
        self.assertEqual(response.status_code, 302)

    def test_last_active_admin_cannot_be_suspended(self):
        self.login("admin@example.edu")
        token = self.csrf_token(path="/admin/users")
        response = self.client.post(
            "/admin/users/%d/status" % self.admin_id,
            data={"csrf_token": token, "status": "suspended"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(db.get_user_by_id(self.admin_id)["is_active"])

    def test_first_admin_cli_bootstrap_and_repeat_protection(self):
        bootstrap_path = os.path.join(self.temp_dir.name, "bootstrap.db")
        db.DB_PATH = bootstrap_path
        runner = campus_app.app.test_cli_runner()
        with patch("app.getpass.getpass", side_effect=["securepass1", "securepass1"]):
            result = runner.invoke(
                args=["create-admin"],
                input="First Admin\nfirst-admin@example.edu\n",
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("First Admin account created", result.output)
        self.assertEqual(
            db.get_user_by_email("first-admin@example.edu")["role"], "ADMIN"
        )

        second_result = runner.invoke(args=["create-admin"])
        self.assertEqual(second_result.exit_code, 0, second_result.output)
        self.assertIn("already exists", second_result.output)
        db.DB_PATH = os.path.join(self.temp_dir.name, "test.db")

    def test_admin_views_do_not_expose_contact_or_verification_answer(self):
        self.login("admin@example.edu")
        response = self.client.get("/admin/reports")
        self.assertNotIn(b"private@example.edu", response.get_data())
        self.assertNotIn(b"Private answer", response.get_data())

    def test_claim_review_does_not_store_answer_and_admin_can_resolve(self):
        self.login("student@example.edu")
        token = self.csrf_token(path="/item/%d/claim" % self.item_id)
        response = self.client.post(
            "/item/%d/claim" % self.item_id,
            data={"csrf_token": token, "answer": "incorrect"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Request staff review", response.get_data())

        response = self.client.post(
            "/item/%d/claim/review" % self.item_id,
            data={
                "csrf_token": token,
                "reason": "The owner cannot answer the verification question.",
            },
        )
        self.assertEqual(response.status_code, 302)

        conn = db.get_connection()
        try:
            claim = conn.execute("SELECT * FROM claims").fetchone()
            self.assertEqual(claim["status"], "PENDING")
            self.assertNotIn("answer", claim.keys())
            self.assertNotIn("secret_answer", claim.keys())
        finally:
            conn.close()

        admin_client = campus_app.app.test_client()
        self.login("admin@example.edu", admin_client)
        admin_token = self.csrf_token(admin_client, "/admin/claims")
        self.assertIn(
            b"The owner cannot answer the verification question.",
            admin_client.get("/admin/claims").get_data(),
        )
        response = admin_client.post(
            "/admin/claims/%d/review" % claim["id"],
            data={"csrf_token": admin_token, "decision": "APPROVED"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.get_item(self.item_id)["status"], "RESOLVED")

    def test_verified_claim_can_still_resolve_item(self):
        self.login("student@example.edu")
        token = self.csrf_token(path="/item/%d/claim" % self.item_id)
        response = self.client.post(
            "/item/%d/claim" % self.item_id,
            data={"csrf_token": token, "answer": "  private ANSWER  "},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Verification Successful", response.get_data())

        response = self.client.post(
            "/item/%d/resolve" % self.item_id,
            data={"csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.get_item(self.item_id)["status"], "RESOLVED")

    def test_existing_user_schema_migrates_to_student(self):
        legacy_path = os.path.join(self.temp_dir.name, "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                location TEXT NOT NULL,
                item_date TEXT NOT NULL,
                description TEXT,
                contact TEXT,
                secret_hint TEXT NOT NULL,
                secret_answer TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO users (name, email, password_hash, created_at)
            VALUES ('Legacy', 'legacy@example.edu', 'hash', '2026-01-01');
            """
        )
        conn.close()
        db.DB_PATH = legacy_path
        db.init_db()
        self.assertEqual(db.get_user_by_email("legacy@example.edu")["role"], "STUDENT")


if __name__ == "__main__":
    unittest.main()
