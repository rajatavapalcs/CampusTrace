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

## Files

```
CampusTrace/
├── app.py            # Flask routes, server-side validation, error handling
├── database.py       # sqlite3 helpers (parameterized queries), seed data
├── matching.py       # calculate_match_score() - transparent scoring, no AI
├── schema.sql        # items table
├── requirements.txt  # Flask
├── templates/        # base, index, report_lost, report_found, search,
│                     # item_details, claim, my_reports, error
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
| GET/POST | `/item/<id>/claim` | Show the secret question, verify the answer server-side |
| POST | `/item/<id>/resolve` | Mark an item RESOLVED (only after verification) |
| GET | `/my-reports` | Items reported from this browser |

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

Private (server-side only): contact details, secret verification question answer.

The secret answer is never rendered into HTML, never sent to JavaScript, and never
exposed through a URL or API. `database.py` selects a fixed list of public columns,
and the answer is compared only inside `check_secret_answer()` (case-insensitive,
whitespace-trimmed).

## Demo scenario

1. Report lost: *Casio fx-991CW Calculator*, Electronics, Physics Lab, 24 Sep 2026,
   secret question "What colour sticker is on the back?", answer "Red".
2. Report found: *Casio Scientific Calculator*, Electronics, Physics Lab, 24 Sep 2026.
3. The found page lists **Reported Lost Items That Match** with a high match percentage.
4. Open **View Details** → **Claim This Item**.
5. Answer the verification question → *Verification Successful*.
6. Mark as **RESOLVED**; the home page statistics update.
