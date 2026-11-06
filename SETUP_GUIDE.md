# Set up your task board

A task board in your browser, connected to **your own Google Sheet**. Takes about 15 minutes. An AI agent does the technical parts.

## You need
- A Google account and a Google Sheet for your tasks
- Cursor or Claude Code (the agent)

## Steps
1. **Download:** go to https://github.com/aadish98/MiniProjectManagement, click **Code > Download ZIP**, and unzip it on your Desktop.
2. **Open the folder** in Cursor (File > Open Folder), or run `claude` in a terminal inside it.
3. **Paste this to the agent:**
   ```
   Set up my task board. Follow AGENTS.md. I'm not technical, so explain simply, one step at a time.
   ```
4. **Answer the agent.** It will ask for your sheet link, tab name and project names, and guide you through the two Google steps below.
5. **Open** http://127.0.0.1:8765. Next time, double-click `run.command` (Mac).

## The two Google steps (the agent will guide you)
**A. Make your free key** (once, about 5 minutes; no card or payment needed)
1. Go to https://console.cloud.google.com and click **New Project**.
2. Open **APIs & Services > Library**, search **Google Sheets API**, click **Enable**.
3. Open **IAM & Admin > Service Accounts > Create service account**. Pick any name, then click **Done**.
4. Click the new account, then **Keys > Add key > Create new key > JSON**. A file downloads.
5. Rename it `service_account.json` and move it into the board folder.

> The key file is like a password. Never email, upload or share it.
> If a work or school account blocks this, use a personal Gmail account for this step.

**B. Share your sheet with the key.** In your Google Sheet click **Share** and add the key's email (the agent will show it) as **Editor**.

## Your sheet
Use any sheet whose first row is these 11 columns, in this order:

`Project | Experiment | Time Estimate | Start Date | Projected End Date | Status | Schematic | Result | Link to Data | Comments/ Improvements | Notebook Location`

No sheet yet? Create a blank one and use **File > Import > Upload** with `notebook_template.csv` (choose **Replace current sheet**).

## Using the board
- **+ New task** adds a task. Drag cards between columns, or use the arrow on a card.
- **Gantt** shows tasks on a timeline. **Weekly report** gives text you can copy.
- In the New task form, pick **Add a new project** to make a project. The board warns you if the name looks like one you already have.
- A card with a **red dashed outline** is missing something. Click it to see what.
- Edit a given row in the sheet **or** the board, not both at once.

## If something goes wrong
Ask the agent: "Run the check and fix what it finds."

| You see | Do this |
|---|---|
| Permission denied | Share the sheet with the key's email (step B) |
| Sheet not found | Copy the link from your browser again |
| Tab not found | Tell the agent the exact tab name |
| Sheets API disabled | Enable it (key step 2) |
| "Address already in use" | The board is already running. Close the other window |
| Project list empty | Tell the agent your project names |
