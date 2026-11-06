# MiniProjectManagement

A task board for your lab notebook Google Sheet. See your tasks as a board, a timeline (Gantt) or a weekly report, all in your browser.
It runs on your own computer. Your data stays in your Google Sheet.

**To set it up, follow [SETUP_GUIDE.md](SETUP_GUIDE.md).** An AI agent (Cursor or Claude Code) does the technical work for you.

## For developers
- Python 3.10+. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- Copy `config.example.json` to `config.json`, put your Google service-account key at `service_account.json`, then `.venv/bin/python check_sheet.py` and `.venv/bin/python app.py`.
- Tests: `.venv/bin/python -m unittest discover -s tests`
- The server only answers requests from `127.0.0.1`. It reads and writes columns A to K of one tab.
- Never commit `service_account.json`, `config.json` or `project_groups.json` (they are in `.gitignore`).
