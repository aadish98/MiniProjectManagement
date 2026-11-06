"""Kanban access to the existing task-log tab ("Updated Log 2026") of the lab's Google Sheet.

The sheet keeps its own layout. Columns A–K, as they already are:
  A Project | B Experiment | C Time Estimate | D Start Date | E Projected End Date | F Status |
  G Schematic | H Result | I Link to Data | J Comments/ Improvements | K Notebook Location

The board shows the sheet's own statuses (Planned, Ongoing, Behind, Complete) plus "Unscheduled" for a blank
status. Nothing is renamed or reformatted: only the cells a person actually changes in the app are written,
messy text (multi-line dates, "5-7 days") is shown and kept as typed.

Rows have no ID column, so a task's id is a hash of its Project + Experiment text. That survives rows being
inserted, deleted or re-sorted in the sheet between a read and a write.
"""
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import threading

COLS = ["project", "title", "est", "start", "end", "status", "schematic", "result", "link", "comments", "notebook"]
NCOLS = len(COLS)
LAST_COL = "K"
UNSCHEDULED = "Unscheduled"
STATUSES = [UNSCHEDULED, "Planned", "Ongoing", "Behind", "Complete"]
EDITABLE = set(COLS)
HERE = os.path.dirname(os.path.abspath(__file__))


class TaskError(ValueError):
    """Bad input from the client (HTTP 400)."""


class ProjectExists(TaskError):
    """A new project name that looks like one that is already there (exact: same name ignoring case/punctuation)."""

    def __init__(self, name, exact, similar):
        self.name, self.exact, self.similar = name, exact, similar
        super().__init__(f"'{exact}' already exists" if exact else
                         f"'{name}' looks like an existing project: {', '.join(similar)}")


class NotFound(KeyError):
    """No such task (HTTP 404)."""


def col_letter(i):  # 0-based
    return chr(ord("A") + i)


# ---------- cell parsing (display only; the sheet text is never rewritten unless edited) ----------
_EPOCH = dt.date(1899, 12, 30)
DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})[./](\d{1,2})[./](\d{2,4})|(\d{1,2})/(\d{1,2})(?![\d/])")


def cell_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def date_cell(v):
    """A date cell as shown in the app: real dates become YYYY-MM-DD, everything else stays as typed."""
    if v is None or v == "":
        return ""
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v >= 1000:  # a Sheets/Excel date serial
            return (_EPOCH + dt.timedelta(days=int(v))).isoformat()
        return f"{v:g}"  # "2.16" typed as a number: month.day, left as typed
    return str(v)


def parse_dates(text, year=2026):
    """All dates found in a messy cell, in order. Bare month/day uses `year`; "2.16" style numbers are month.day."""
    out = []
    s = str(text or "")
    if re.fullmatch(r"\d{1,2}\.\d{1,2}", s.strip()):
        m, d = (int(x) for x in s.strip().split("."))
        try:
            return [dt.date(year, m, d)]
        except ValueError:
            return []
    for m in DATE_RE.finditer(s):
        try:
            if m.group(1):
                out.append(dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            elif m.group(4):
                y = int(m.group(6))
                out.append(dt.date(y + 2000 if y < 100 else y, int(m.group(4)), int(m.group(5))))
            else:
                out.append(dt.date(year, int(m.group(7)), int(m.group(8))))
        except ValueError:
            continue
    return out


def parse_hours(est):
    """Hours as a number when the estimate says so plainly ("12.5h", "3hrs", 4); otherwise None."""
    s = str(est or "").strip()
    if not s or re.search(r"\bdays?\b|\bweeks?\b", s, re.I):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours)?\b", s, re.I)
    return float(m.group(1)) if m else None


def est_label(est, hours):
    """Card label: parsed hours ("12.5h"), or the raw text only when it is short enough to read at a glance."""
    if hours is not None:
        return f"{hours:g}h"
    s = " ".join(str(est or "").split())
    return s if len(s) <= 12 else ""


def latest_note(comments):
    s = (comments or "").strip()
    if not s:
        return ""
    lines = s.split("\n")
    idx = [i for i, l in enumerate(lines) if re.match(r"\[\d{4}-\d{2}-\d{2}\]", l.strip())]
    chosen = lines[idx[-1]:] if idx else lines
    return " ".join(l.strip() for l in chosen if l.strip())[:400]


def _safe_text(s):
    """Stop USER_ENTERED from turning typed text into a formula."""
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


# ---------- project names ----------
def _squash(name):
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def clean_project(name):
    return re.sub(r"\s+", " ", str(name or "")).strip()


def find_similar(name, known):
    """Compare a proposed project name with existing ones. Returns (exact, similar):
    exact   = the existing name that is the same ignoring case, spaces and punctuation ("tx omics" == "Tx-omics"), or None;
    similar = other existing names that look related (typos, plurals, one name inside the other)."""
    n = _squash(name)
    if not n:
        return None, []
    exact, similar = None, []
    for k in known:
        kn = _squash(k)
        if not kn:
            continue
        if kn == n:
            exact = exact or k
        elif (min(len(n), len(kn)) >= 3 and (n in kn or kn in n)) or difflib.SequenceMatcher(None, n, kn).ratio() >= 0.8:
            similar.append(k)
    return exact, similar


# ---------- project grouping (display only) ----------
def load_groups(path=None):
    path = path or os.path.join(HERE, "project_groups.json")
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"order": [], "map": {}}


class BaseStore:
    label = "store"
    native_dates = False

    def __init__(self, groups=None, new_rows="first_blank", extra_projects=()):
        self.extra_projects = list(extra_projects or [])
        self.lock = threading.RLock()
        self.groups = groups if groups is not None else load_groups()
        self.new_rows = new_rows

    # -- backend hooks --
    def read_rows(self):
        """[(sheet_row, [11 raw values])] for rows that hold a task (Project or Experiment filled)."""
        raise NotImplementedError

    def write_cells(self, row, cells):
        """cells: {col_index: text}"""
        raise NotImplementedError

    def write_new_row(self, values, rows):
        raise NotImplementedError

    def clear_row(self, row):
        raise NotImplementedError

    # -- conversion --
    def group_of(self, raw):
        return self.groups.get("map", {}).get(raw, raw)

    def projects(self, rows=None):
        order = list(self.groups.get("order", []))
        order += [p for p in self.extra_projects if p not in order]
        seen = set(order)
        for _, v in (rows if rows is not None else self.read_rows()):
            g = self.group_of(cell_text(v[0]).strip())
            if g and g not in seen:
                order.append(g)
                seen.add(g)
        return order

    def check_project(self, name, rows=None):
        """(exact, similar, is_known) for a proposed project name, against everything the board already knows."""
        name = clean_project(name)
        rows = rows if rows is not None else self.read_rows()
        shown = self.projects(rows)
        raw = {cell_text(v[0]).strip() for _, v in rows} | set(self.groups.get("map", {}))
        known = name in shown or name in raw
        # raw spellings the sheet already uses count as existing too, reported under the name the board shows for them
        pool = list(shown) + [self.group_of(r) for r in raw if r and self.group_of(r) not in shown]
        pool += [k for k in raw if k and k not in pool]
        exact, similar = find_similar(name, pool)
        if exact:
            exact = self.group_of(exact)
        similar = list(dict.fromkeys(self.group_of(x) for x in similar if self.group_of(x) != exact))
        return exact, similar, known

    @staticmethod
    def _padded(values):
        return (list(values) + [""] * NCOLS)[:NCOLS]

    def _tasks(self, rows):
        out, seen = [], {}
        for row_no, raw in rows:
            v = self._padded(raw)
            project_raw, title = cell_text(v[0]).strip(), cell_text(v[1]).strip()
            base = hashlib.sha1(f"{project_raw}\n{title}".encode()).hexdigest()[:10]
            n = seen.get(base, 0) + 1
            seen[base] = n
            status = cell_text(v[5]).strip()
            status = status if status in STATUSES else (UNSCHEDULED if not status else status)
            end_raw, start_raw = date_cell(v[4]), date_cell(v[3])
            dates = parse_dates(end_raw)
            hours = parse_hours(cell_text(v[2]))
            due = dates[-1].isoformat() if dates else ""
            out.append(dict(
                id=base if n == 1 else f"{base}-{n}", row=row_no,
                project=self.group_of(project_raw), project_raw=project_raw, title=title, status=status,
                est=cell_text(v[2]), hours=hours if hours is not None else "", est_label=est_label(cell_text(v[2]), hours),
                start=start_raw, end=end_raw, due=due, done=due if status == "Complete" else "",
                schematic=cell_text(v[6]), result=cell_text(v[7]), link=cell_text(v[8]),
                comments=cell_text(v[9]), note=latest_note(cell_text(v[9])), notebook=cell_text(v[10]),
            ))
        return out

    # -- operations --
    def list_tasks(self):
        with self.lock:
            return self._tasks(self.read_rows())

    def _locate(self, rows, task_id):
        for t, (row_no, raw) in zip(self._tasks(rows), rows):
            if t["id"] == task_id:
                return row_no, self._padded(raw), t
        raise NotFound(task_id)

    def _clean(self, payload):
        p = {k: ("" if payload[k] is None else str(payload[k])) for k in payload if k in EDITABLE}
        if "status" in p and p["status"] not in STATUSES:
            raise TaskError(f"status must be one of {STATUSES}")
        if "title" in p and not p["title"].strip():
            raise TaskError("title is required")
        return p

    def update(self, task_id, patch):
        with self.lock:
            rows = self.read_rows()
            row_no, raw, current = self._locate(rows, task_id)
            p = self._clean(patch)
            cells = {}
            for field, value in p.items():
                i = COLS.index(field)
                if field == "project":
                    if value == current["project"] or value == current["project_raw"]:
                        continue  # already shows as that project; leave the sheet's own label alone
                elif field == "status":
                    value = "" if value == UNSCHEDULED else value
                    if value == cell_text(raw[5]).strip():
                        continue
                elif value == (current[field] if field in ("start", "end") else cell_text(raw[i])):
                    continue
                cells[i] = value
            if p.get("status") == "Complete" and not str(current["end"]).strip() and 4 not in cells:
                cells[4] = dt.date.today().isoformat()
            if cells:
                self.write_cells(row_no, {i: _safe_text(v) for i, v in cells.items()})
                for i, v in cells.items():
                    raw[i] = v
            return self._tasks([(row_no, raw)])[0] | {"id": self._id_in_context(rows, row_no, raw)}

    def _id_in_context(self, rows, row_no, raw):
        merged = [(r, raw if r == row_no else v) for r, v in rows]
        for t in self._tasks(merged):
            if t["row"] == row_no:
                return t["id"]

    def create(self, payload):
        with self.lock:
            rows = self.read_rows()
            p = self._clean(payload)
            if not p.get("title", "").strip():
                raise TaskError("title is required")
            p["project"] = clean_project(p.get("project", ""))
            if not p["project"]:
                raise TaskError("project is required")
            if len(p["project"]) > 80:
                raise TaskError("project name is too long (80 characters max)")
            exact, similar, known = self.check_project(p["project"], rows)
            if not known and (exact or (similar and not payload.get("allow_new_project"))):
                raise ProjectExists(p["project"], exact, similar)
            p.setdefault("status", "Planned")
            p.setdefault("start", dt.date.today().isoformat())
            vals = [""] * NCOLS
            for field, value in p.items():
                vals[COLS.index(field)] = "" if (field == "status" and value == UNSCHEDULED) else _safe_text(value)
            if p["status"] == "Complete" and not vals[4]:
                vals[4] = dt.date.today().isoformat()
            row_no = self.write_new_row(vals, rows)
            shown = [(r + 1 if (self.new_rows == "top" and r >= 2) else r, v) for r, v in rows]
            shown.append((row_no, vals))
            for t in self._tasks(sorted(shown, key=lambda x: x[0])):
                if t["row"] == row_no:
                    return t

    def delete(self, task_id):
        with self.lock:
            row_no, _, _ = self._locate(self.read_rows(), task_id)
            self.clear_row(row_no)


# ---------- Google Sheets ----------
class SheetsStore(BaseStore):
    label = "Google Sheet"

    def __init__(self, worksheet, **kw):
        super().__init__(**kw)
        self.ws = worksheet

    @classmethod
    def connect(cls, spreadsheet, service_account_file, worksheet, **kw):
        import gspread
        gc = gspread.service_account(filename=service_account_file)
        sh = gc.open_by_url(spreadsheet) if spreadsheet.startswith("http") else gc.open_by_key(spreadsheet)
        try:
            ws = sh.worksheet(worksheet)
        except gspread.WorksheetNotFound:
            names = ", ".join(w.title for w in sh.worksheets())
            raise SystemExit(f'Tab "{worksheet}" not found in "{sh.title}". Tabs there: {names}. Fix "worksheet" in config.json.')
        return cls(ws, **kw)

    def read_rows(self):
        data = self.ws.get_values(f"A2:{LAST_COL}", value_render_option="UNFORMATTED_VALUE",
                                  date_time_render_option="SERIAL_NUMBER")
        return [(i + 2, v) for i, v in enumerate(data)
                if any(cell_text(c).strip() for c in (v[:2] if v else []))]

    def write_cells(self, row, cells):
        self.ws.batch_update([{"range": f"{col_letter(i)}{row}", "values": [[v]]} for i, v in cells.items()],
                             value_input_option="USER_ENTERED")

    def write_new_row(self, values, rows):
        if self.new_rows == "top":
            self.ws.insert_row(values, 2, value_input_option="USER_ENTERED", inherit_from_before=False)
            return 2
        used = {r for r, _ in rows}
        r = 2
        while r in used:
            r += 1
        if r > self.ws.row_count:
            self.ws.add_rows(20)
        self.ws.update(values=[values], range_name=f"A{r}:{LAST_COL}{r}", value_input_option="USER_ENTERED")
        return r

    def clear_row(self, row):
        self.ws.batch_clear([f"A{row}:{LAST_COL}{row}"])


# ---------- local xlsx (demo) ----------
class XlsxStore(BaseStore):
    label = "local xlsx (demo)"

    def __init__(self, path, sheet="Updated Log 2026", **kw):
        super().__init__(**kw)
        self.path, self.sheet = path, sheet

    def _open(self):
        import openpyxl
        wb = openpyxl.load_workbook(self.path)
        return wb, wb[self.sheet]

    def read_rows(self):
        _, ws = self._open()
        out = []
        for r in range(2, ws.max_row + 1):
            v = [ws.cell(r, c).value for c in range(1, NCOLS + 1)]
            if any(cell_text(c).strip() for c in v[:2]):
                out.append((r, v))
        return out

    def write_cells(self, row, cells):
        wb, ws = self._open()
        for i, v in cells.items():
            ws.cell(row, i + 1).value = v if v != "" else None
        wb.save(self.path)

    def write_new_row(self, values, rows):
        wb, ws = self._open()
        if self.new_rows == "top":
            ws.insert_rows(2)
            r = 2
        else:
            used = {x for x, _ in rows}
            r = 2
            while r in used:
                r += 1
        for i, v in enumerate(values):
            ws.cell(r, i + 1).value = v if v != "" else None
        wb.save(self.path)
        return r

    def clear_row(self, row):
        wb, ws = self._open()
        for c in range(1, NCOLS + 1):
            ws.cell(row, c).value = None
        wb.save(self.path)
