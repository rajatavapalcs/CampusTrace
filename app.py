"""CampusTrace - college Lost & Found web app (Flask + SQLite3)."""

import os
import re
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import database as db
from matching import find_matches, pretty_date

app = Flask(__name__)
# Use an environment variable in production; fall back to a dev-only default.
app.secret_key = os.environ.get(
    "CAMPUSTRACE_SECRET_KEY", "campustrace-local-demo-key"
)

REQUIRED_FIELDS = {
    "item_name": "Item name",
    "category": "Category",
    "location": "Location",
    "item_date": "Date",
    "secret_hint": "Secret verification question",
    "secret_answer": "Secret verification answer",
}

# Simple email regex for server-side validation
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
#  Auth helpers
# ---------------------------------------------------------------------------

def login_required(view_func):
    """Decorator that redirects to the login page when the visitor is not
    logged in.  The originally requested URL is preserved via ``next``."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access that page.", "error")
            return redirect(url_for("login", next=request.url))
        return view_func(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_user():
    """Make current-user info available in every template."""
    if "user_id" in session:
        return {
            "current_user": {
                "id": session["user_id"],
                "name": session.get("user_name", ""),
                "email": session.get("user_email", ""),
            }
        }
    return {"current_user": None}


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
    data = {
        "item_name": (request.form.get("item_name") or "").strip(),
        "category": (request.form.get("category") or "").strip(),
        "location": (request.form.get("location") or "").strip(),
        "item_date": (request.form.get("item_date") or "").strip(),
        "description": (request.form.get("description") or "").strip(),
        "contact": (request.form.get("contact") or "").strip(),
        "secret_hint": (request.form.get("secret_hint") or "").strip(),
        "secret_answer": (request.form.get("secret_answer") or "").strip(),
        "status": status,
    }

    errors = [label for field, label in REQUIRED_FIELDS.items() if not data[field]]
    if data["category"] and data["category"] not in db.CATEGORIES:
        errors.append("Category")
    if data["location"] and data["location"] not in db.LOCATIONS:
        errors.append("Location")
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
    if "user_id" in session:
        return redirect(url_for("home"))

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
        session["user_id"] = user_id
        session["user_name"] = name
        session["user_email"] = email.lower().strip()
        flash("Account created successfully. Welcome, %s!" % name, "success")
        return redirect(url_for("home"))

    return render_template("register.html", form_name="", form_email="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("home"))

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

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]
        flash("Welcome back, %s!" % user["name"], "success")

        # honour ?next= redirect
        next_url = request.args.get("next") or request.form.get("next") or ""
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("home"))

    return render_template(
        "login.html",
        form_email="",
        next=request.args.get("next", ""),
    )


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
        tracking_id=db.tracking_id,
        **common_context()
    )


@app.route("/item/<int:item_id>")
def item_details(item_id):
    item = db.get_item(item_id)
    if item is None:
        abort(404)
    matches = None
    if item["status"] == "FOUND":
        matches = find_matches(item, db.get_items_by_status("LOST"))
    return render_template(
        "item_details.html",
        item=item,
        matches=matches,
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
        item_id = db.insert_item(data)
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

        item_id = db.insert_item(data)
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
    item = db.get_item(item_id)
    if item is None:
        abort(404)

    verified = False
    if request.method == "POST":
        answer = request.form.get("answer") or ""
        if db.check_secret_answer(item_id, answer):
            verified = True
            session["verified_%d" % item_id] = True
            flash("Verification Successful.", "success")
        else:
            flash("The verification answer does not match.", "error")

    return render_template(
        "claim.html",
        item=item,
        verified=verified or session.get("verified_%d" % item_id, False),
        tracking_id=db.tracking_id(item["id"], item["status"]),
        **common_context()
    )


@app.route("/item/<int:item_id>/resolve", methods=["POST"])
@login_required
def resolve(item_id):
    item = db.get_item(item_id)
    if item is None:
        abort(404)
    if not session.get("verified_%d" % item_id, False):
        flash("Please verify ownership before resolving this item.", "error")
        return redirect(url_for("claim", item_id=item_id))
    db.mark_resolved(item_id)
    remember_report(item_id)
    flash("Item marked as RESOLVED.", "success")
    return redirect(url_for("item_details", item_id=item_id))


@app.route("/my-reports")
@login_required
def my_reports():
    items = db.get_items_by_ids(session.get("my_items", []))
    return render_template(
        "my_reports.html",
        items=items,
        tracking_id=db.tracking_id,
        **common_context()
    )


# ---------------------------------------------------------------------------
#  Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", message="We couldn't find that page or item."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", message="Something went wrong. Please try again."), 500


if __name__ == "__main__":
    db.init_db()
    db.seed_sample_data()
    app.run(debug=True)
