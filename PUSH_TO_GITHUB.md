# How to Put CampusTrace on GitHub (Step by Step)

Follow this once. It takes about 5 minutes.

## Before you start

1. **Create a GitHub account** (if you don't have one): https://github.com/signup
2. **Install Git** on your computer:
   - Windows: https://git-scm.com/download/win (just keep clicking Next)
   - Mac: open Terminal and type `git --version` — if it asks to install, click Install
3. **Have Python installed** so you can run the app: https://www.python.org/downloads/

## Step 1 — Unzip the project

Unzip `CampusTrace.zip` anywhere on your computer, for example into a folder
called `CampusTrace` on your Desktop.

## Step 2 — Create an empty repository on GitHub

1. Go to https://github.com/new (you must be logged in)
2. **Repository name:** `CampusTrace`
3. Leave it **Public** (so your project teammates and teacher can see it)
4. Do **NOT** tick "Add a README file", ".gitignore", or "license"
   (your project already has these)
5. Click **Create repository**
6. Keep that page open — you will need the web address on the next step

## Step 3 — Upload the project (copy-paste these)

Open a terminal:

- **Windows:** right-click inside your `CampusTrace` folder → "Git Bash Here"
  (or open Command Prompt and type `cd` then drag the folder into the window)
- **Mac:** open Terminal, type `cd ` (with a space), drag the `CampusTrace`
  folder into the window, press Enter

Now paste these lines one at a time, pressing Enter after each:

```bash
git init
git add .
git commit -m "CampusTrace: college Lost & Found app"
```

Next, connect it to the repository you made in Step 2.
Replace `YOUR-USERNAME` with your GitHub username:

```bash
git remote add origin https://github.com/YOUR-USERNAME/CampusTrace.git
git branch -M main
git push -u origin main
```

> The first time you push, a GitHub window may pop up asking you to sign in.
> Click **Sign in with your browser** and allow it. That's normal.

## Step 4 — Check it worked

Refresh https://github.com/YOUR-USERNAME/CampusTrace — you should see
`app.py`, `README.md`, the `templates/` and `static/` folders, and all the
other files. Done!

## What each command does (in plain English)

| Command | What it means |
| --- | --- |
| `git init` | "Start tracking this folder with Git" |
| `git add .` | "Stage every file to be uploaded" (the .gitignore automatically leaves out the database file and Python cache) |
| `git commit -m "..."` | "Save a snapshot with this message" |
| `git remote add origin ...` | "Connect my folder to my GitHub repository" |
| `git push -u origin main` | "Upload everything to GitHub" |

## If something goes wrong

- **"error: remote origin already exists"** — you already connected it once.
  Just run the `git push -u origin main` line again.
- **"rejected" when pushing** — the GitHub repo isn't empty. Easiest fix:
  delete the repo on GitHub (repo page → Settings → Delete), then redo Step 2
  without ticking any boxes.
- **"git is not recognized"** — Git isn't installed. Go back to "Before you
  start" and install it, then reopen the terminal.
- **Want to upload changes later?** After editing files, run the same three
  commands: `git add .` → `git commit -m "describe your change"` → `git push`.

## After pushing: run the app (for anyone cloning it)

```bash
git clone https://github.com/YOUR-USERNAME/CampusTrace.git
cd CampusTrace
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser.
