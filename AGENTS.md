# Instructions for AI agents (Cursor, Claude Code)

This is a task board over one person's Google Sheet. The person using you is probably **not technical**.
Talk in plain, short sentences. No jargon. One step at a time. Say what you are about to do, then do it. Ask only for what you need.

## Hard rules
- Never print, open, copy, upload, commit or summarise `service_account.json`. To show its email, print only `client_email`:
  `python3 -c "import json;print(json.load(open('service_account.json'))['client_email'])"`
- Never edit the person's Google Sheet yourself. Only the board app writes to it.
- Only change files in this folder. Do not change `store.py`, `app.py` or `static/index.html` unless asked.

## Setup: "set up my task board"
Do these in order. If you are blocked, tell the person exactly what you need.
1. **Python 3.10+.** Check with `python3 --version`. If it is missing or older, send them to https://www.python.org/downloads/ to install the latest,
   then continue. If `.venv` is missing: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (Windows: `.venv\Scripts\python`).
2. **Key file.** Check that `service_account.json` exists in this folder (existence only). If not, walk them through "A. Make your free key" in
   `SETUP_GUIDE.md`, one click at a time. Tell them it is free and needs no card.
3. **Their sheet.** Ask for the sheet link and the tab name. The first row must be the 11 columns in `SETUP_GUIDE.md`.
   If they have no sheet, tell them to import `notebook_template.csv` into a new Google Sheet.
4. **Share.** Show them the key's email. Tell them: click **Share** in Google Sheets, add that email as **Editor**.
5. **Config.** `cp config.example.json config.json`. Set `spreadsheet` (their link), `worksheet` (tab name) and `projects` (ask for 2 to 5 names).
   Then `cp project_groups.example.json project_groups.json`.
6. **Check.** Run `.venv/bin/python check_sheet.py`. Fix each PROBLEM using its "What to do" line. Repeat until clean.
7. **Run.** `.venv/bin/python app.py`, then tell them to open http://127.0.0.1:8765. Next time they double-click `run.command` (Mac).
8. **Try it together.** Click **+ New task**, fill it in, see the row appear in their sheet, then open the card and click **Clear this row** twice.

## Later questions
- **Start it again:** Mac: double-click `run.command`. Windows: run `.venv\Scripts\python app.py` in this folder (offer to make a desktop shortcut).
  Keep that window open while using the board. Close it to stop.
- **Windows:** use `python` instead of `python3`, and `.venv\Scripts\python` instead of `.venv/bin/python`. Use `copy` instead of `cp`.
- **Get the newest version:** download the ZIP again from the GitHub page and copy over the new files, but keep their own `service_account.json`,
  `config.json` and `project_groups.json`. (If they use git: `git pull`.) Then re-run `pip install -r requirements.txt` in the `.venv`.

## What the board does (explain simply if asked)
- Views: **Board**, **Gantt** (timeline) and **Weekly report**.
- A new task needs a name, project, status, hours, start date and end date.
- New project: in the form choose **Add a new project**. If the name matches or looks like an existing one, the board warns them and offers the existing name.
- A card with a red dashed outline is missing something. The **Needs fixing** button shows only those.
- It only touches columns A to K of one tab and refreshes every 30 seconds. If a row is edited in two places, the last save wins.

## Problems
Run `.venv/bin/python check_sheet.py` first. The table in `SETUP_GUIDE.md` covers the usual ones.
