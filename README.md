# CampusTrace

**Find it. Report it. Return it.**

A college campus Lost & Found web app built for a Design Thinking project.

## Technology

- Python 3 + Flask (backend and routing)
- SQLite3 via Python's built-in `sqlite3` module
- Jinja2 templates
- HTML5 + plain CSS3 + vanilla JavaScript

No React, no TypeScript, no Tailwind/Bootstrap, no cloud services, no AI APIs.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000

`database.db` is created automatically on first run, and sample data is
inserted once (never duplicated on later starts).

## Roles and admin access

Public registration always creates a **Student** account. Existing accounts are
migrated as Students on the next startup. The application does not provide a
public role-change page or accept a role from a registration form.

Initialize the first Admin using trusted command-line access to the machine
hosting the application's SQLite database:

```powershell
flask --app app create-admin
```

The command prompts privately for a name, email, and password; it creates no
hardcoded credentials and refuses to create another Admin once one exists.
Keep shell/database access restricted to trusted operators. Admin role changes
are not available through public routes. The Admin dashboard provides report
moderation, claim review, account suspension/reactivation, and statistics.

Admins can hide and restore reports or permanently delete a report and its
associated claim records. Hidden reports are omitted from public search,
matches, details, and public statistics. Lost-item reports require a private
verification question and answer; found-item reporters may optionally provide
their own private question and answer, which do not change ownership
verification. Secret questions and answers are never included in public report
data. New reports are associated with their authenticated reporter, while old
reports keep an unknown owner rather than being assigned incorrectly.

Reports may use any of the predefined categories or enter a custom category
when selecting **Other**. Custom categories are stored on the report and are
available in the search category filter. Both report forms also accept an
optional exact-location detail; it appears in searches, item details, reports,
and matching cards.

Students submit a private written evidence description to claim a found item.
They may link one of their own active lost reports; if linked, its answer is
verified server-side and is not stored with the claim or shown to reviewers.
Secret answers are hashed in SQLite, and existing plain-text answers are safely
upgraded during database initialization.
Claims remain Pending until an Admin approves or rejects them. Only an
approved claim can view the Found reporter's contact in that claimant's
`/my-claims` page; contact remains hidden from public pages, other students,
and pending or rejected claimants. Only an Admin can mark the item returned.
Students can track their claim statuses at `/my-claims`; they cannot resolve
reports directly. Matches are shown from either the lost or found report using
the existing scoring system.

Both roles use the existing shared login page. By default, successful Student
login redirects to the public/student homepage, while successful Admin login
redirects to the Admin dashboard. A safe same-role `next` destination is
preserved for login-required deep links.

Account roles and active status are checked against SQLite on every request.
Suspended accounts cannot log in or continue using authenticated routes.
Self-suspension and suspension of the last active Admin are blocked. The
Admin-only management endpoints also require a session CSRF token.

Set `CAMPUSTRACE_SECRET_KEY` to a strong secret in the deployment environment.
The app refuses to start on Render without it; local development uses a
random, process-local key. On Render, the SQLite database (including role
assignments and account status) must be on persistent storage if it needs to
survive instance replacement.

## Files

```
CampusTrace/
├── app.py            # Flask routes, server-side validation, error handling
├── database.py       # sqlite3 helpers (parameterized queries), seed data
├── matching.py       # calculate_match_score() - transparent scoring, no AI
├── schema.sql        # items, users, and claim records
├── requirements.txt  # Flask
├── templates/        # base, index, report_lost, report_found, search,
│                     # item_details, claim, my_reports, admin pages, error
└── static/
    ├── css/style.css
    └── js/script.js
```

## Routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Home with live statistics from SQLite |
| GET/POST | `/report/lost` | Report a lost item |
| GET/POST | `/report/found` | Report a found item, then show matching lost reports |
| GET | `/search` | Search with category, location and status filters |
| GET | `/item/<id>` | Item details + tracking ID |
| GET/POST | `/item/<id>/claim` | Submit private evidence for an Admin-reviewed found-item claim |
| POST | `/item/<id>/resolve` | Student resolution is forbidden; Admin resolution requires an approved claim |
| GET | `/my-reports` | Items owned by the signed-in student, plus legacy browser reports |
| GET | `/my-claims` | Claim status tracking for the signed-in student |
| GET | `/admin` | Admin dashboard and aggregate statistics |
| GET | `/admin/reports` | Review, hide, restore, resolve, or delete reports |
| GET | `/admin/claims` | Review pending, disputed, approved, and rejected claims |
| GET | `/admin/users` | Suspend or reactivate accounts |

- `PUSH_TO_GITHUB.md` — step-by-step guide to upload this project to GitHub

## Matching algorithm

`calculate_match_score(found_item, lost_item)` in `matching.py`:

| Factor | Weight |
| --- | --- |
| Item name word similarity | 40 |
| Same category | 20 |
| Same campus location | 20 |
| Date proximity | 10 |
| Description word similarity | 10 |
| **Maximum** | **100** |

Only matches scoring **40 or more** are shown, sorted highest first.
The percentage is a *similarity score between two reports*, not a probability
that the item belongs to anyone.

## Privacy design

Public: item name, match percentage, category, location, date, description, status.

Private: contact details; lost-report verification questions and answers; and
claim evidence. Claim answers are only compared server-side when the claimant
links a lost report they own. Admin claim review can access the written claim
evidence but not the private question or answer.

The secret question and answer are never rendered on public pages, sent to
JavaScript, exposed through a URL, or included in Admin query results.
`database.py` selects a fixed list of public columns, and the answer comparison
uses an owner-scoped query without returning the answer to Flask templates.

## Demo scenario

1. Report lost: *Casio fx-991CW Calculator*, Electronics, Physics Lab, 24 Sep 2026,
   secret question "What colour sticker is on the back?", answer "Red".
2. Report found: *Casio Scientific Calculator*, Electronics, Physics Lab, 24 Sep 2026.
3. The found page lists **Reported Lost Items That Match** with a high match percentage.
4. Sign in as the student who reported the lost calculator, open the found item's details, and choose **Claim This Item**.
5. Submit private ownership evidence. Optionally link the lost report and enter its verification answer; it is checked privately and never saved.
6. An Admin reviews the evidence and approves the claim, then separately marks the item returned. The home page statistics update.
