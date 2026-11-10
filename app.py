"""CampusTrace - college Lost & Found web app (Flask + SQLite3)."""

import hmac
import getpass
import os
import re
import secrets
from datetime import datetime
from functools import wraps
from urllib.parse import urlsplit

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import database as db
from matching import find_matches, pretty_date

app = Flask(__name__)
secret_key = os.environ.get("CAMPUSTRACE_SECRET_KEY")
if not secret_key and os.environ.get("RENDER"):
    raise RuntimeError("CAMPUSTRACE_SECRET_KEY must be set on Render.")
app.secret_key = secret_key or secrets.token_hex(32)

REQUIRED_FIELDS = {
    "item_name": "Item name",
    "category": "Category",
    "location": "Location",
    "item_date": "Date",
    "description": "Description",
}

# Simple email regex for server-side validation
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
AUTHENTICATED_POST_ENDPOINTS = {
    "report_lost",
    "report_found",
    "claim",
    "dispute_own_claim",
    "resolve",
    "admin_moderate_report",
    "admin_resolve_report",
    "admin_review_claim",
    "admin_dispute_claim",
    "admin_set_user_status",
}


# ---------------------------------------------------------------------------
#  Auth helpers
# ---------------------------------------------------------------------------

def login_required(view_func):
    """Decorator that redirects to the login page when the visitor is not
    logged in.  The originally requested URL is preserved via ``next``."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if g.current_user is None:
            flash("Please log in to access that page.", "error")
            return redirect(url_for("login", next=request.full_path))
        return view_func(*args, **kwargs)
    return wrapper


def admin_required(view_func):
    """Allow only an active Admin account, resolved from SQLite per request."""
    @wraps(view_func)
    @login_required
    def wrapper(*args, **kwargs):
        if g.current_user["role"] != "ADMIN":
            abort(403)
        return view_func(*args, **kwargs)
    return wrapper


def role_home(user):
    """Return the default landing page for an authenticated role."""
    if user["role"] == "ADMIN":
        return url_for("admin_dashboard")
    return url_for("home")


def safe_login_destination(user, next_url):
    """Preserve same-site deep links without crossing role landing areas."""
    parsed_url = urlsplit(next_url)
    if (
        parsed_url.scheme
        or parsed_url.netloc
        or not parsed_url.path.startswith("/")
        or parsed_url.path.startswith("//")
        or "\\" in parsed_url.path
    ):
        return role_home(user)
    admin_path = parsed_url.path == "/admin" or parsed_url.path.startswith("/admin/")
    if user["role"] == "ADMIN" and admin_path:
        return next_url
    if user["role"] == "STUDENT" and not admin_path:
        return next_url
    return role_home(user)


@app.before_request
def load_request_user():
    g.current_user = None
    user_id = session.get("user_id")
    if user_id is not None:
        user = db.get_user_by_id(user_id)
        if user is None:
            session.clear()
        elif not user["is_active"]:
            session.clear()
            flash("This account has been suspended.", "error")
        else:
            g.current_user = user

    if request.method == "POST":
        endpoint = request.endpoint or ""
        if (
            endpoint in AUTHENTICATED_POST_ENDPOINTS
            and g.current_user is None
        ):
            return
        if (
            endpoint.startswith("admin_")
            and g.current_user is not None
            and g.current_user["role"] != "ADMIN"
        ):
            return
        expected = session.get("csrf_token", "")
        submitted = request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected, submitted):
            abort(400)
    else:
        session.setdefault("csrf_token", secrets.token_urlsafe(32))


@app.context_processor
def inject_user():
    """Make current-user info available in every template."""
    return {
        "current_user": g.get("current_user"),
        "csrf_token": session.get("csrf_token", ""),
    }


# ---------------------------------------------------------------------------
#  Template filter & common helpers (unchanged)
# ---------------------------------------------------------------------------

@app.template_filter("nice_date")
def nice_date_filter(value):
    return pretty_date(value)


def common_context():
    return {
        "categories": db.CATEGORIES,
        "locations": db.LOCATIONS,
        "statuses": db.STATUSES,
    }


def read_form(status):
    """Trim input and validate on the server. Returns (data, errors)."""
    category_option = (request.form.get("category") or "").strip()
    custom_category = (request.form.get("custom_category") or "").strip()
    data = {
        "item_name": (request.form.get("item_name") or "").strip(),
        "category": custom_category if category_option == "Other" else category_option,
        "category_option": category_option,
        "custom_category": custom_category,
        "location": (request.form.get("location") or "").strip(),
        "location_details": (request.form.get("location_details") or "").strip(),
        "item_date": (request.form.get("item_date") or "").strip(),
        "description": (request.form.get("description") or "").strip(),
        "contact": (request.form.get("contact") or "").strip(),
        "secret_hint": (request.form.get("secret_hint") or "").strip(),
        "secret_answer": (request.form.get("secret_answer") or "").strip(),
        "status": status,
    }

    fields = dict(REQUIRED_FIELDS)
    if status == "LOST":
        fields.update(
            {
                "secret_hint": "Secret verification question",
                "secret_answer": "Secret verification answer",
            }
        )
    errors = [label for field, label in fields.items() if not data[field]]
    if category_option not in db.CATEGORIES:
        errors.append("Category")
    elif category_option == "Other":
        if not custom_category:
            errors.append("Custom category")
        elif len(custom_category) > 80:
            errors.append("Custom category must be 80 characters or fewer.")
    elif custom_category:
        errors.append("Custom category")

    if status == "FOUND" and bool(data["secret_hint"]) != bool(data["secret_answer"]):
        errors.append("Enter both the secret verification question and answer, or leave both blank.")

    limits = {
        "item_name": 120,
        "description": 1000,
        "contact": 200,
        "location_details": 200,
        "secret_hint": 160,
        "secret_answer": 120,
    }
    for field, maximum in limits.items():
        if len(data[field]) > maximum:
            errors.append("%s must be %d characters or fewer." % (field.replace("_", " ").title(), maximum))
    if data["location"] and data["location"] not in db.LOCATIONS:
        errors.append("Location")
    try:
        datetime.strptime(data["item_date"], "%Y-%m-%d")
    except ValueError:
        errors.append("Date must be a valid calendar date.")
    return data, errors


def remember_report(item_id):
    my_items = session.get("my_items", [])
    if item_id not in my_items:
        my_items.append(item_id)
        session["my_items"] = my_items


# ---------------------------------------------------------------------------
#  Auth routes
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if g.current_user is not None:
        return redirect(role_home(g.current_user))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        # --- server-side validation ---
        errors = []
        if not name:
            errors.append("Name is required.")
        if len(name) > 120:
            errors.append("Name must be 120 characters or fewer.")
        if not email:
            errors.append("Email is required.")
        elif not _EMAIL_RE.match(email):
            errors.append("Please enter a valid email address.")
        if not password:
            errors.append("Password is required.")
        elif len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template(
                "register.html", form_name=name, form_email=email
            ), 400

        # --- attempt to create the user ---
        user_id = db.create_user(name, email, password)
        if user_id is None:
            flash("An account with that email already exists.", "error")
            return render_template(
                "register.html", form_name=name, form_email=email
            ), 400

        # auto-login after registration
        session.clear()
        session["user_id"] = user_id
        flash("Account created successfully. Welcome, %s!" % name, "success")
        return redirect(url_for("home"))

    return render_template("register.html", form_name="", form_email="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user is not None:
        return redirect(role_home(g.current_user))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""

        errors = []
        if not email:
            errors.append("Email is required.")
        if not password:
            errors.append("Password is required.")

        if errors:
            for err in errors:
                flash(err, "error")
            return render_template("login.html", form_email=email), 400

        user = db.verify_user(email, password)
        if user is None:
            flash("Invalid email or password.", "error")
            return render_template("login.html", form_email=email), 400

        session.clear()
        session["user_id"] = user["id"]
        flash("Welcome back, %s!" % user["name"], "success")

        next_url = request.args.get("next") or request.form.get("next") or ""
        return redirect(safe_login_destination(user, next_url))

    return render_template(
        "login.html",
        form_email="",
        next=request.args.get("next", ""),
    )


@app.cli.command("create-admin")
def create_first_admin():
    """Create the first Admin through trusted local/instance CLI access."""
    db.init_db()
    if db.has_admin_account():
        print("An Admin account already exists; no changes were made.")
        return
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip()
    password = getpass.getpass("Admin password (minimum 8 characters): ")
    confirm = getpass.getpass("Confirm admin password: ")

    if not name or len(name) > 120:
        print("Admin name must be between 1 and 120 characters.")
        return
    if not _EMAIL_RE.match(email):
        print("Enter a valid email address.")
        return
    if len(password) < 8 or password != confirm:
        print("Passwords must match and be at least 8 characters.")
        return

    result = db.create_first_admin(name, email, password)
    if result == "admin_exists":
        print("An Admin account already exists; no changes were made.")
    elif result == "email_exists":
        print("That email already belongs to an account; no changes were made.")
    else:
        print("First Admin account created. You can now log in.")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
#  Public routes (unchanged)
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html", stats=db.get_stats(), **common_context())


@app.route("/search")
def search():
    query = (request.args.get("q") or "").strip()
    category = request.args.get("category") or "All"
    location = request.args.get("location") or "All"
    status = request.args.get("status") or "All"

    results = db.search_items(query, category, location, status)
    return render_template(
        "search.html",
        results=results,
        query=query,
        selected_category=category,
        selected_location=location,
        selected_status=status,
        search_categories=db.get_categories_with_items(),
        tracking_id=db.tracking_id,
        **common_context()
    )


@app.route("/item/<int:item_id>")
def item_details(item_id):
    item = db.get_item(item_id)
    if item is None:
        abort(404)
    matches = None
    match_status = {"FOUND": "LOST", "LOST": "FOUND"}.get(item["status"])
    if match_status:
        matches = find_matches(item, db.get_items_by_status(match_status))
    return render_template(
        "item_details.html",
        item=item,
        matches=matches,
        match_status=match_status,
        can_claim=(
            g.current_user is not None
            and g.current_user["role"] == "STUDENT"
            and item["status"] == "FOUND"
            and db.get_item_owner_id(item_id) != g.current_user["id"]
        ),
        just_reported=request.args.get("reported") == "1",
        tracking_id=db.tracking_id(item["id"], item["status"]),
        **common_context()
    )


# ---------------------------------------------------------------------------
#  Protected routes — login required
# ---------------------------------------------------------------------------

@app.route("/report/lost", methods=["GET", "POST"])
@login_required
def report_lost():
    if request.method == "POST":
        data, errors = read_form("LOST")
        if errors:
            flash("Please complete all required fields.", "error")
            return render_template(
                "report_lost.html", form=data, **common_context()
            ), 400
        item_id = db.insert_item(data, g.current_user["id"])
        remember_report(item_id)
        flash("Lost item reported successfully.", "success")
        return redirect(url_for("item_details", item_id=item_id, reported=1))
    return render_template("report_lost.html", form={}, **common_context())


@app.route("/report/found", methods=["GET", "POST"])
@login_required
def report_found():
    if request.method == "POST":
        data, errors = read_form("FOUND")
        if errors:
            flash("Please complete all required fields.", "error")
            return render_template(
                "report_found.html", form=data, matches=None, **common_context()
            ), 400

        item_id = db.insert_item(data, g.current_user["id"])
        remember_report(item_id)
        found_item = db.get_item(item_id)
        matches = find_matches(found_item, db.get_items_by_status("LOST"))

        flash("Your item has been reported successfully.", "success")
        return render_template(
            "report_found.html",
            form={},
            matches=matches,
            reported_item=found_item,
            tracking_id=db.tracking_id(item_id, "FOUND"),
            **common_context()
        )
    return render_template(
        "report_found.html", form={}, matches=None, **common_context()
    )


@app.route("/item/<int:item_id>/claim", methods=["GET", "POST"])
@login_required
def claim(item_id):
    if g.current_user["role"] != "STUDENT":
        abort(403)
    item = db.get_item(item_id)
    if item is None or item["status"] != "FOUND":
        abort(404)

    if db.get_item_owner_id(item_id) == g.current_user["id"]:
        abort(403)

    lost_reports = db.get_user_lost_items(g.current_user["id"])
    if request.method == "POST":
        evidence = (request.form.get("evidence") or "").strip()
        linked_lost_id_raw = (request.form.get("linked_lost_item_id") or "").strip()
        answer = (request.form.get("lost_answer") or "").strip()
        errors = []
        linked_lost_id = None
        if not evidence or len(evidence) > 1200:
            errors.append("Evidence must be between 1 and 1200 characters.")
        if linked_lost_id_raw:
            try:
                linked_lost_id = int(linked_lost_id_raw)
            except ValueError:
                errors.append("Select a valid lost report.")
            if linked_lost_id is not None and not answer:
                errors.append("Enter the answer for your selected lost report.")
            elif linked_lost_id is not None and not db.check_owned_lost_answer(
                g.current_user["id"], linked_lost_id, answer
            ):
                errors.append("The lost report or its verification answer is invalid.")
        elif answer:
            errors.append("Select your lost report before entering its verification answer.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "claim.html",
                item=item,
                lost_reports=lost_reports,
                form_evidence=evidence,
                selected_lost_report=linked_lost_id_raw,
                tracking_id=db.tracking_id(item["id"], item["status"]),
                **common_context()
            ), 400

        result = db.create_student_claim(
            g.current_user["id"], item_id, evidence, linked_lost_id
        )
        if isinstance(result, int):
            flash("Claim submitted. It is pending Admin review.", "success")
            return redirect(url_for("my_claims"))
        messages = {
            "item_unavailable": "This found item is no longer available for claims.",
            "own_report": "You cannot claim a found report you submitted.",
            "invalid_lost_report": "Select one of your own active lost reports.",
            "already_pending": "You already have a pending claim for this item.",
        }
        flash(messages.get(result, "The claim could not be submitted."), "error")
        return redirect(url_for("claim", item_id=item_id))

    return render_template(
        "claim.html",
        item=item,
        lost_reports=lost_reports,
        form_evidence="",
        selected_lost_report="",
        tracking_id=db.tracking_id(item["id"], item["status"]),
        **common_context()
    )


@app.route("/claims/<int:claim_id>/dispute", methods=["POST"])
@login_required
def dispute_own_claim(claim_id):
    if not db.dispute_claim(claim_id, g.current_user["id"]):
        abort(404)
    flash("Your claim has been flagged for staff review.", "success")
    destination = "admin_claims" if g.current_user["role"] == "ADMIN" else "my_reports"
    return redirect(url_for(destination))


@app.route("/item/<int:item_id>/resolve", methods=["POST"])
@login_required
def resolve(item_id):
    abort(403, description="Only an Admin can resolve a report after reviewing its claim.")


@app.route("/my-reports")
@login_required
def my_reports():
    items_by_id = {
        item["id"]: item
        for item in db.get_items_by_ids(session.get("my_items", []))
    }
    items_by_id.update(
        {item["id"]: item for item in db.get_user_items(g.current_user["id"])}
    )
    items = sorted(items_by_id.values(), key=lambda item: item["id"], reverse=True)
    return render_template(
        "my_reports.html",
        items=items,
        tracking_id=db.tracking_id,
        **common_context()
    )


@app.route("/my-claims")
@login_required
def my_claims():
    if g.current_user["role"] != "STUDENT":
        abort(403)
    return render_template("my_claims.html", claims=db.get_user_claims(g.current_user["id"]))


# ---------------------------------------------------------------------------
#  Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template(
        "admin_dashboard.html", stats=db.get_admin_dashboard_stats()
    )


@app.route("/admin/reports")
@admin_required
def admin_reports():
    return render_template(
        "admin_reports.html",
        reports=db.get_admin_reports(),
        tracking_id=db.tracking_id,
    )


@app.route("/admin/reports/<int:item_id>/moderate", methods=["POST"])
@admin_required
def admin_moderate_report(item_id):
    action = request.form.get("action", "")
    if action not in ("hide", "restore", "delete"):
        abort(400)
    if not db.moderate_item(item_id, action):
        abort(404)
    messages = {
        "hide": "Report hidden from public listings.",
        "restore": "Report restored to public listings.",
        "delete": "Report and associated claim records permanently deleted.",
    }
    flash(messages[action], "success")
    return redirect(url_for("admin_reports"))


@app.route("/admin/reports/<int:item_id>/resolve", methods=["POST"])
@admin_required
def admin_resolve_report(item_id):
    if not db.admin_set_item_resolved(item_id):
        abort(404)
    flash("Item marked as RESOLVED.", "success")
    return redirect(url_for("admin_reports"))


@app.route("/admin/claims")
@admin_required
def admin_claims():
    return render_template("admin_claims.html", claims=db.get_admin_claims())


@app.route("/admin/claims/<int:claim_id>/review", methods=["POST"])
@admin_required
def admin_review_claim(claim_id):
    decision = request.form.get("decision", "")
    if decision not in ("APPROVED", "REJECTED"):
        abort(400)
    if not db.review_claim(claim_id, g.current_user["id"], decision):
        abort(404)
    flash(
        "Claim approved. An Admin may now mark the item returned."
        if decision == "APPROVED"
        else "Claim rejected.",
        "success",
    )
    return redirect(url_for("admin_claims"))


@app.route("/admin/claims/<int:claim_id>/dispute", methods=["POST"])
@admin_required
def admin_dispute_claim(claim_id):
    if not db.admin_dispute_claim(claim_id):
        abort(404)
    flash("Claim flagged for review.", "success")
    return redirect(url_for("admin_claims"))


@app.route("/admin/users")
@admin_required
def admin_users():
    return render_template(
        "admin_users.html",
        users=db.get_admin_users(),
        current_user_id=g.current_user["id"],
    )


@app.route("/admin/users/<int:user_id>/status", methods=["POST"])
@admin_required
def admin_set_user_status(user_id):
    status = request.form.get("status", "")
    if status not in ("active", "suspended"):
        abort(400)
    result = db.set_user_active(
        user_id,
        1 if status == "active" else 0,
        g.current_user["id"],
    )
    messages = {
        "updated": "Account status updated.",
        "not_found": None,
        "self": "You cannot suspend your own account.",
        "last_admin": "The last active Admin account cannot be suspended.",
    }
    if result == "not_found":
        abort(404)
    flash(messages[result], "success" if result == "updated" else "error")
    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
#  Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", message="We couldn't find that page or item."), 404


@app.errorhandler(400)
def bad_request(_error):
    return render_template("error.html", message="This request could not be validated."), 400


@app.errorhandler(403)
def forbidden(_error):
    return render_template(
        "error.html", message="You don't have permission to access this page or action."
    ), 403


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", message="Something went wrong. Please try again."), 500


if __name__ == "__main__":
    db.init_db()
    db.seed_sample_data()
    app.run()
