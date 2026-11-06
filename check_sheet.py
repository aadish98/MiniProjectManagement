"""Check that this install can reach the configured Google Sheet and that the tab has the layout the board expects.

    .venv/bin/python check_sheet.py

Prints plain-language results and what to do about each problem. Read-only: it never writes to the sheet.
Never prints the contents of service_account.json.
"""
import json
import os
import re
import sys

import store as st

HERE = os.path.dirname(os.path.abspath(__file__))
HEADERS = ["Project", "Experiment", "Time Estimate", "Start Date", "Projected End Date", "Status",
           "Schematic", "Result", "Link to Data", "Comments/ Improvements", "Notebook Location"]


def norm(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


def fail(msg, fix):
    print(f"\nPROBLEM: {msg}\n  What to do: {fix}")
    sys.exit(1)


def main():
    cfg_path = os.path.join(HERE, "config.json")
    if not os.path.exists(cfg_path):
        fail("config.json is missing.", "Copy config.example.json to config.json and paste your Google Sheet link into 'spreadsheet'.")
    cfg = json.load(open(cfg_path))
    if not cfg.get("spreadsheet") or cfg["spreadsheet"].startswith("PASTE"):
        fail("config.json has no sheet link yet.", "Paste your Google Sheet's URL into 'spreadsheet' in config.json.")
    key = cfg.get("service_account_file", "service_account.json")
    key = key if os.path.isabs(key) else os.path.join(HERE, key)
    if not os.path.exists(key):
        fail(f"The key file {os.path.basename(key)} is not in this folder.", "Make your free key (see 'A. Make your free key' in SETUP_GUIDE.md), save it as service_account.json and put it in this folder.")

    import gspread
    try:
        gc = gspread.service_account(filename=key)
        sp = cfg["spreadsheet"]
        sh = gc.open_by_url(sp) if sp.startswith("http") else gc.open_by_key(sp)
    except gspread.exceptions.SpreadsheetNotFound:
        fail("Google says the sheet was not found.", "Re-copy the link from the browser address bar, and make sure the sheet is shared with the key's email.")
    except gspread.exceptions.APIError as e:
        code = getattr(getattr(e, "response", None), "status_code", "?")
        if code == 403:
            fail("Permission denied (403).", "Share your Google Sheet with the key's email as Editor (ask your agent for the email). If that is already done, turn on the Google Sheets API in Google Cloud: APIs & Services > Library > Google Sheets API > Enable.")
        fail(f"Google returned an error ({code}).", "Check the sheet link in config.json. If it still fails, show this message to your agent.")
    except Exception as e:  # network, bad key file
        fail(f"Could not connect: {type(e).__name__}: {e}", "Check your internet connection and that service_account.json is the unmodified key file.")
    print(f"OK  connected to sheet: {sh.title}")

    tab = cfg.get("worksheet", "Updated Log 2026")
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        fail(f'There is no tab called "{tab}". Tabs in this sheet: {", ".join(w.title for w in sh.worksheets())}.',
             'Set "worksheet" in config.json to the name of your task tab (exact spelling).')
    print(f"OK  found tab: {tab}")

    head = ws.row_values(1)
    bad = [(i, want, head[i] if i < len(head) else "(empty)") for i, want in enumerate(HEADERS)
           if i >= len(head) or norm(head[i])[:5] != norm(want)[:5]]
    if bad:
        print("WARN  Row 1 does not match the expected column order. The board reads columns by position (A to K):")
        for i, want, got in bad:
            print(f"        column {st.col_letter(i)} should be '{want}', but is '{got}'")
        print("  What to do: rearrange the columns, or start from notebook_template.csv (File > Import in Google Sheets).")
    else:
        print("OK  columns A to K match the expected layout")

    s = st.SheetsStore(ws, groups={"order": [], "map": {}})
    tasks = s.list_tasks()
    print(f"OK  {len(tasks)} task row(s) read; projects seen: {', '.join(s.projects()) or '(none yet)'}")
    odd = sorted({t['status'] for t in tasks if t['status'] not in st.STATUSES})
    if odd:
        print(f"WARN  unrecognised status values (shown as-is): {', '.join(odd)}. Use one of: {', '.join(st.STATUSES[1:])}")
    if not tasks and not cfg.get("projects"):
        print("NOTE  the sheet has no tasks, so no projects exist yet. Add your project names to \"projects\" in config.json (a list), e.g. [\"Thesis\", \"Pilot study\"].")
    print("\nAll checks done." + (" Fix the WARN lines above, then run the board." if bad or odd else " Run the board: double-click run.command."))


if __name__ == "__main__":
    main()
