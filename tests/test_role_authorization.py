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
        self.second_student_id = db.create_user(
            "Second Student", "second-student@example.edu", "password1"
        )
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

    def test_password_visibility_controls_render_for_auth_and_secret_answers(self):
        login_page = self.client.get("/login").get_data()
        self.assertIn(b'type="password" id="password"', login_page)
        self.assertIn(b'aria-label="Show password"', login_page)

        register_page = self.client.get("/register").get_data()
        self.assertIn(b'aria-label="Show confirm password"', register_page)
        self.assertEqual(register_page.count(b'data-password-toggle'), 2)

        self.login("student@example.edu")
        lost_page = self.client.get("/report/lost").get_data()
        self.assertIn(b'aria-label="Show secret answer"', lost_page)
        found_page = self.client.get("/report/found").get_data()
        self.assertIn(b'aria-label="Show secret answer"', found_page)
        self.assertIn(b'type="text" id="secret_hint"', found_page)
        claim_page = self.client.get("/item/%d/claim" % self.item_id).get_data()
        self.assertIn(b'id="lost_answer" name="lost_answer"', claim_page)
        self.assertIn(b'aria-label="Show secret answer"', claim_page)

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
        self.assertNotIn(b"Private question", response.get_data())

    def test_lost_report_submission_assigns_owner_and_private_verification(self):
        self.login("student@example.edu")
        token = self.csrf_token(path="/report/lost")
        response = self.client.post(
            "/report/lost",
            data={
                "csrf_token": token,
                "item_name": "Blue backpack",
                "category": "Accessories",
                "location": "Library",
                "item_date": "2026-10-24",
                "description": "Blue canvas bag with a stitched patch.",
                "secret_hint": "What is stitched on the front?",
                "secret_answer": "a patch",
            },
        )
        self.assertEqual(response.status_code, 302)
        lost_id = int(response.headers["Location"].rsplit("/", 1)[-1].split("?")[0])
        self.assertEqual(db.get_item_owner_id(lost_id), self.student_id)
        detail = self.client.get("/item/%d" % lost_id).get_data()
        self.assertNotIn(b"What is stitched on the front?", detail)
        self.assertNotIn(b"a patch", detail)

    def test_found_report_can_store_optional_private_verification_fields(self):
        self.login("student@example.edu")
        db.insert_item(
            {
                "item_name": "Red umbrella",
                "category": "Musical Instrument",
                "status": "LOST",
                "location": "Canteen",
                "item_date": "2026-10-24",
                "description": "Red umbrella left by the entrance.",
                "contact": "",
                "secret_hint": "What is inside the case?",
                "secret_answer": "A violin",
            },
            owner_id=self.student_id,
        )
        form = self.client.get("/report/found").get_data()
        self.assertIn(b"Secret Verification Question", form)
        self.assertIn(b"Secret Verification Answer", form)
        token = self.csrf_token(path="/report/found")
        response = self.client.post(
            "/report/found",
            data={
                "csrf_token": token,
                "item_name": "Red umbrella",
                "category": "Other",
                "custom_category": "Musical Instrument",
                "location": "Canteen",
                "item_date": "2026-10-24",
                "description": "Red umbrella left by the entrance.",
                "secret_hint": "What is inside the case?",
                "secret_answer": "A violin",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"100% Match", response.get_data())
        self.assertIn(b"Musical Instrument", response.get_data())
        conn = db.get_connection()
        try:
            item = conn.execute(
                """
                SELECT id, category, secret_hint, secret_answer FROM items
                WHERE item_name = ? AND status = 'FOUND' ORDER BY id DESC LIMIT 1
                """,
                ("Red umbrella",),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(item["category"], "Musical Instrument")
        self.assertEqual(item["secret_hint"], "What is inside the case?")
        self.assertTrue(item["secret_answer"].startswith(db.SECRET_ANSWER_HASH_PREFIX))
        detail = self.client.get("/item/%d" % item["id"]).get_data()
        self.assertIn(b"Musical Instrument", detail)
        self.assertNotIn(b"What is inside the case?", detail)
        self.assertNotIn(b"A violin", detail)
        search = self.client.get("/search?category=Musical%20Instrument").get_data()
        self.assertIn(b"Red umbrella", search)
        self.assertIn(b"Musical Instrument", search)
        self.assertIn(b"Musical Instrument", self.client.get("/my-reports").get_data())

    def test_custom_lost_category_is_required_and_saved(self):
        self.login("student@example.edu")
        token = self.csrf_token(path="/report/lost")
        report = {
            "csrf_token": token,
            "item_name": "Lost violin",
            "category": "Other",
            "location": "Library",
            "item_date": "2026-10-24",
            "description": "A wooden instrument case.",
            "secret_hint": "What is inside the case?",
            "secret_answer": "A violin",
        }
        missing_custom_category = self.client.post("/report/lost", data=report)
        self.assertEqual(missing_custom_category.status_code, 400)

        report["custom_category"] = "Musical Instrument"
        response = self.client.post("/report/lost", data=report)
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            b"Musical Instrument",
            self.client.get("/search?category=Musical%20Instrument").get_data(),
        )
        conn = db.get_connection()
        try:
            row = conn.execute(
                "SELECT category FROM items WHERE item_name = ?", ("Lost violin",)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["category"], "Musical Instrument")

    def test_report_rejects_invalid_calendar_date_and_location(self):
        self.login("student@example.edu")
        token = self.csrf_token(path="/report/lost")
        report = {
            "csrf_token": token,
            "item_name": "Invalid date test",
            "category": "Electronics",
            "location": "Library",
            "item_date": "2026-02-30",
            "description": "A report with an invalid date.",
            "secret_hint": "Test question",
            "secret_answer": "Test answer",
        }
        invalid_date = self.client.post("/report/lost", data=report)
        self.assertEqual(invalid_date.status_code, 400)

        report["item_date"] = "2026-10-24"
        report["location"] = "Not a campus location"
        invalid_location = self.client.post("/report/lost", data=report)
        self.assertEqual(invalid_location.status_code, 400)
        self.assertEqual(
            db.search_items(query="Invalid date test", status="All"), []
        )

    def test_claim_requires_owned_lost_answer_and_admin_decision_before_resolution(self):
        lost_id = db.insert_item(
            {
                "item_name": "Test item",
                "category": "Electronics",
                "status": "LOST",
                "location": "Library",
                "item_date": "2026-10-24",
                "description": "A test device with a private identifying mark.",
                "contact": "",
                "secret_hint": "Private question",
                "secret_answer": "Private answer",
            },
            owner_id=self.student_id,
        )
        self.login("student@example.edu")
        token = self.csrf_token(path="/item/%d/claim" % self.item_id)

        invalid = self.client.post(
            "/item/%d/claim" % self.item_id,
            data={
                "csrf_token": token,
                "evidence": "It has a private identifying mark.",
                "linked_lost_item_id": lost_id,
                "lost_answer": "wrong answer",
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(db.get_user_claims(self.student_id), [])

        response = self.client.post(
            "/item/%d/claim" % self.item_id,
            data={
                "csrf_token": token,
                "evidence": "It has a private identifying mark.",
                "linked_lost_item_id": lost_id,
                "lost_answer": " private ANSWER ",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.get_item(self.item_id)["status"], "FOUND")
        self.assertIn(b"Pending Admin review", self.client.get("/my-claims").get_data())
        conn = db.get_connection()
        try:
            claim = conn.execute("SELECT * FROM claims").fetchone()
            self.assertEqual(claim["status"], "PENDING")
            self.assertNotIn("secret_answer", claim.keys())
            self.assertEqual(claim["evidence"], "It has a private identifying mark.")
            self.assertEqual(claim["linked_lost_item_id"], lost_id)
        finally:
            conn.close()

        admin_client = campus_app.app.test_client()
        self.login("admin@example.edu", admin_client)
        self.assertFalse(db.admin_set_item_resolved(self.item_id))
        self.assertEqual(db.get_item(self.item_id)["status"], "FOUND")
        admin_token = self.csrf_token(admin_client, "/admin/claims")
        self.assertIn(
            b"It has a private identifying mark.",
            admin_client.get("/admin/claims").get_data(),
        )
        response = admin_client.post(
            "/admin/claims/%d/review" % claim["id"],
            data={"csrf_token": admin_token, "decision": "APPROVED"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.get_item(self.item_id)["status"], "FOUND")
        admin_token = self.csrf_token(admin_client, "/admin/reports")
        response = admin_client.post(
            "/admin/reports/%d/resolve" % self.item_id,
            data={"csrf_token": admin_token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.get_item(self.item_id)["status"], "RESOLVED")

    def test_two_student_demo_workflow_matches_claims_resolves_and_persists(self):
        student_one = campus_app.app.test_client()
        student_two = campus_app.app.test_client()
        self.login("student@example.edu", student_one)
        self.login("second-student@example.edu", student_two)
        lost_token = self.csrf_token(student_one, "/report/lost")
        lost_response = student_one.post(
            "/report/lost",
            data={
                "csrf_token": lost_token,
                "item_name": "Casio fx-991CW Calculator",
                "category": "Electronics",
                "location": "Physics Lab",
                "item_date": "2026-10-24",
                "description": "Black calculator with a red sticker.",
                "location_details": "Second bench by the window",
                "contact": "lost-owner@example.edu",
                "secret_hint": "What colour sticker is on the back?",
                "secret_answer": "Red",
            },
        )
        self.assertEqual(lost_response.status_code, 302)
        lost_id = int(lost_response.headers["Location"].rsplit("/", 1)[-1].split("?")[0])
        self.assertTrue(db.tracking_id(lost_id, "LOST").startswith("CT-L-"))

        found_token = self.csrf_token(student_two, "/report/found")
        found_response = student_two.post(
            "/report/found",
            data={
                "csrf_token": found_token,
                "item_name": "Casio Scientific Calculator",
                "category": "Electronics",
                "location": "Physics Lab",
                "item_date": "2026-10-24",
                "description": "Black scientific calculator with red sticker.",
                "location_details": "Last bench by the window",
                "contact": "found-reporter@example.edu",
            },
        )
        self.assertEqual(found_response.status_code, 200)
        found_id = db.search_items(
            query="Casio Scientific", status="FOUND"
        )[0]["id"]
        import matching

        expected_score = matching.calculate_match_score(
            db.get_item(found_id), db.get_item(lost_id)
        )
        self.assertGreaterEqual(expected_score, matching.MATCH_THRESHOLD)
        self.assertLessEqual(expected_score, 100)
        self.assertIn(
            ("%d%% Match" % expected_score).encode("ascii"),
            found_response.get_data(),
        )
        self.assertIn(b"Casio fx-991CW Calculator", found_response.get_data())
        self.assertIn(b"Second bench by the window", found_response.get_data())
        details = student_two.get("/item/%d" % found_id).get_data()
        self.assertIn(b"Last bench by the window", details)
        self.assertNotIn(b"found-reporter@example.edu", details)
        self.assertNotIn(b"lost-owner@example.edu", details)
        exact_location_search = student_two.get(
            "/search?q=Second%20bench%20by%20the%20window"
        ).get_data()
        self.assertIn(b"Casio fx-991CW Calculator", exact_location_search)

        claim_token = self.csrf_token(student_one, "/item/%d/claim" % found_id)
        claim_response = student_one.post(
            "/item/%d/claim" % found_id,
            data={
                "csrf_token": claim_token,
                "evidence": "My matching lost report identifies the sticker.",
                "linked_lost_item_id": str(lost_id),
                "lost_answer": "  rED  ",
            },
        )
        self.assertEqual(claim_response.status_code, 302)
        self.assertEqual(db.get_item(found_id)["status"], "FOUND")
        self.assertNotIn(
            b"found-reporter@example.edu", student_one.get("/my-claims").get_data()
        )
        self.assertNotIn(
            b"found-reporter@example.edu", student_two.get("/my-claims").get_data()
        )

        admin = campus_app.app.test_client()
        self.login("admin@example.edu", admin)
        claim = db.get_user_claims(self.student_id)[0]
        admin_token = self.csrf_token(admin, "/admin/claims")
        approval = admin.post(
            "/admin/claims/%d/review" % claim["id"],
            data={"csrf_token": admin_token, "decision": "APPROVED"},
        )
        self.assertEqual(approval.status_code, 302)
        self.assertIn(
            b"found-reporter@example.edu",
            student_one.get("/my-claims").get_data(),
        )
        self.assertNotIn(
            b"found-reporter@example.edu", student_two.get("/my-claims").get_data()
        )
        self.assertNotIn(
            b"found-reporter@example.edu",
            student_two.get("/item/%d" % found_id).get_data(),
        )
        admin_token = self.csrf_token(admin, "/admin/reports")
        resolution = admin.post(
            "/admin/reports/%d/resolve" % found_id,
            data={"csrf_token": admin_token},
        )
        self.assertEqual(resolution.status_code, 302)
        self.assertEqual(db.get_item(found_id)["status"], "RESOLVED")
        self.assertEqual(
            len(db.search_items(query="Casio Scientific", status="RESOLVED")), 1
        )
        stats = db.get_stats()
        self.assertEqual(stats["resolved"], 1)
        self.assertEqual(stats["lost"], 1)

        db.init_db()
        self.assertEqual(db.get_item(found_id)["status"], "RESOLVED")
        self.assertTrue(
            db.check_owned_lost_answer(self.student_id, lost_id, "red")
        )

    def test_student_cannot_resolve_a_report_directly(self):
        self.login("student@example.edu")
        token = self.csrf_token(path="/item/%d/claim" % self.item_id)
        response = self.client.post(
            "/item/%d/resolve" % self.item_id,
            data={"csrf_token": token},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(db.get_item(self.item_id)["status"], "FOUND")

    def test_claim_submission_for_own_found_report_is_forbidden(self):
        own_item_id = db.insert_item(
            {
                "item_name": "Own found item",
                "category": "Other",
                "status": "FOUND",
                "location": "Library",
                "item_date": "2026-10-24",
                "description": "Found item posted by this student.",
                "contact": "",
                "secret_hint": "",
                "secret_answer": "",
            },
            owner_id=self.student_id,
        )
        self.login("student@example.edu")
        self.assertEqual(
            self.client.get("/item/%d/claim" % own_item_id).status_code, 403
        )

    def test_rejected_claim_status_is_visible_to_claimant(self):
        self.login("student@example.edu")
        token = self.csrf_token(path="/item/%d/claim" % self.item_id)
        response = self.client.post(
            "/item/%d/claim" % self.item_id,
            data={
                "csrf_token": token,
                "evidence": "I can identify a mark on the item.",
            },
        )
        self.assertEqual(response.status_code, 302)
        claim_id = db.get_user_claims(self.student_id)[0]["id"]

        admin_client = campus_app.app.test_client()
        self.login("admin@example.edu", admin_client)
        token = self.csrf_token(admin_client, "/admin/claims")
        response = admin_client.post(
            "/admin/claims/%d/review" % claim_id,
            data={"csrf_token": token, "decision": "REJECTED"},
        )
        self.assertEqual(response.status_code, 302)
        page = self.client.get("/my-claims").get_data()
        self.assertIn(b"Rejected", page)
        self.assertEqual(db.get_item(self.item_id)["status"], "FOUND")

    def test_admin_cannot_resolve_item_without_approved_claim(self):
        self.login("admin@example.edu")
        self.assertFalse(db.admin_set_item_resolved(self.item_id))
        self.assertEqual(db.get_item(self.item_id)["status"], "FOUND")

    def test_only_one_approved_claim_can_receive_reporter_contact(self):
        first_claim = db.create_student_claim(
            self.student_id, self.item_id, "First claim evidence"
        )
        second_claim = db.create_student_claim(
            self.second_student_id, self.item_id, "Second claim evidence"
        )
        self.assertIsInstance(first_claim, int)
        self.assertIsInstance(second_claim, int)
        self.assertTrue(db.review_claim(first_claim, self.admin_id, "APPROVED"))
        self.assertFalse(db.review_claim(second_claim, self.admin_id, "APPROVED"))
        self.assertIsNone(db.get_user_claims(self.second_student_id)[0]["reporter_contact"])

    def test_search_filters_and_existing_matcher_find_reports(self):
        lost = {
            "id": 10,
            "item_name": "Casio fx-991CW Calculator",
            "category": "Electronics",
            "location": "Physics Lab",
            "item_date": "2026-10-24",
            "description": "Black calculator with a red sticker.",
        }
        found = {
            "id": 11,
            "item_name": "Casio Scientific Calculator",
            "category": "Electronics",
            "location": "Physics Lab",
            "item_date": "2026-10-24",
            "description": "Black scientific calculator with red sticker.",
        }
        import matching

        self.assertTrue(matching.find_matches(found, [lost]))

        db.insert_item(
            {
                "item_name": "Blue backpack",
                "category": "Accessories",
                "status": "LOST",
                "location": "Library",
                "item_date": "2026-10-24",
                "description": "Blue canvas bag.",
                "contact": "",
                "secret_hint": "Patch color?",
                "secret_answer": "Yellow",
            },
            owner_id=self.student_id,
        )
        results = db.search_items(
            query="backpack", category="Accessories", location="Library", status="LOST"
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["item_name"], "Blue backpack")

    def test_matcher_rejects_same_status_and_unrelated_text(self):
        lost = {
            "id": 10,
            "status": "LOST",
            "item_name": "Casio calculator",
            "category": "Electronics",
            "location": "Physics Lab",
            "item_date": "2026-10-24",
            "description": "Black calculator with red sticker",
        }
        unrelated_found = {
            "id": 11,
            "status": "FOUND",
            "item_name": "Green umbrella",
            "category": "Electronics",
            "location": "Physics Lab",
            "item_date": "2026-10-24",
            "description": "Found near the door",
        }
        same_status_lost = dict(lost, id=12, status="FOUND")

        import matching

        self.assertEqual(matching.calculate_match_score(unrelated_found, lost), 50)
        self.assertEqual(matching.find_matches(unrelated_found, [lost]), [])
        self.assertEqual(matching.find_matches(unrelated_found, [same_status_lost]), [])

    def test_matcher_scores_custom_categories_sorts_and_honors_threshold(self):
        found = {
            "id": 20,
            "status": "FOUND",
            "item_name": "Blue Casio Calculator",
            "category": "Musical Instrument",
            "location": "Library",
            "item_date": "2026-10-24",
            "description": "Black calculator with a red sticker",
        }
        strong_lost = dict(
            found,
            id=21,
            status="LOST",
            item_name="Blue Casio Scientific Calculator",
            description="Black calculator and red sticker",
        )
        different_location_and_date = dict(
            found,
            id=22,
            status="LOST",
            item_name="Blue Calculator",
            location="Canteen",
            item_date="2026-10-29",
            description="Black calculator with a scratch",
        )
        unrelated_lost = dict(
            found,
            id=23,
            status="LOST",
            item_name="Green Umbrella",
            description="Found near the stairs",
        )
        same_status = dict(strong_lost, id=24, status="FOUND")

        import matching

        strong_score = matching.calculate_match_score(found, strong_lost)
        medium_score = matching.calculate_match_score(
            found, different_location_and_date
        )
        self.assertGreaterEqual(strong_score, medium_score)
        self.assertLessEqual(strong_score, 100)
        self.assertGreaterEqual(medium_score, 0)
        self.assertEqual(
            [item["id"] for item in matching.find_matches(
                found,
                [different_location_and_date, unrelated_lost, strong_lost, same_status],
            )],
            [21, 22],
        )
        self.assertEqual(
            [item["id"] for item in matching.find_matches(
                found,
                [different_location_and_date, unrelated_lost, strong_lost],
                threshold=80,
            )],
            [21],
        )

    def test_secret_answers_are_hashed_and_legacy_answers_migrate(self):
        lost_id = db.insert_item(
            {
                "item_name": "Private test report",
                "category": "Electronics",
                "status": "LOST",
                "location": "Library",
                "item_date": "2026-10-24",
                "description": "A private answer migration test.",
                "contact": "",
                "secret_hint": "Test question",
                "secret_answer": "Legacy Answer",
            },
            owner_id=self.student_id,
        )
        conn = db.get_connection()
        try:
            conn.execute(
                "UPDATE items SET secret_answer = ? WHERE id = ?",
                ("Legacy Answer", lost_id),
            )
            conn.commit()
        finally:
            conn.close()

        db.init_db()
        conn = db.get_connection()
        try:
            stored_answer = conn.execute(
                "SELECT secret_answer FROM items WHERE id = ?", (lost_id,)
            ).fetchone()["secret_answer"]
        finally:
            conn.close()
        self.assertTrue(stored_answer.startswith(db.SECRET_ANSWER_HASH_PREFIX))
        self.assertNotEqual(stored_answer, "Legacy Answer")
        self.assertTrue(
            db.check_owned_lost_answer(
                self.student_id, lost_id, "  LEGACY ANSWER  "
            )
        )
        self.assertFalse(
            db.check_owned_lost_answer(self.student_id, lost_id, "wrong answer")
        )

    def test_item_details_matches_both_lost_and_found_directions(self):
        lost_id = db.insert_item(
            {
                "item_name": "Casio fx-991CW Calculator",
                "category": "Electronics",
                "status": "LOST",
                "location": "Physics Lab",
                "item_date": "2026-10-24",
                "description": "Black calculator with a red sticker.",
                "contact": "",
                "secret_hint": "What sticker?",
                "secret_answer": "Red",
            },
            owner_id=self.student_id,
        )
        found_id = db.insert_item(
            {
                "item_name": "Casio Scientific Calculator",
                "category": "Electronics",
                "status": "FOUND",
                "location": "Physics Lab",
                "item_date": "2026-10-24",
                "description": "Black scientific calculator with red sticker.",
                "contact": "",
                "secret_hint": "",
                "secret_answer": "",
            },
            owner_id=self.admin_id,
        )
        page = self.client.get("/item/%d" % found_id).get_data()
        self.assertIn(b"Reported Lost Items That Match", page)
        self.assertIn(b"Casio fx-991CW Calculator", page)

        page = self.client.get("/item/%d" % lost_id).get_data()
        self.assertIn(b"Reported Found Items That Match", page)
        self.assertIn(b"Casio Scientific Calculator", page)

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
        conn = db.get_connection()
        try:
            item_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(items)")
            }
        finally:
            conn.close()
        self.assertIn("location_details", item_columns)


if __name__ == "__main__":
    unittest.main()
