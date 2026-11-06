#!/bin/bash
# Double-click to start the board (macOS). Edits config.json to change the sheet.
cd "$(dirname "$0")"
exec ./.venv/bin/python app.py
