"""Run:  .venv/bin/python -m unittest discover -s tests -v

SheetsStore is tested against an in-memory stand-in for a gspread worksheet, so cell-level writes, row finding
and date/estimate parsing are covered without Google credentials. Real authentication and network calls are not.
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import openpyxl  # noqa: E402

import app as appmod  # noqa: E402
import store as st  # noqa: E402

SERIAL = lambda iso: (dt.date.fromisoformat(iso) - dt.date(1899, 12, 30)).days
GROUPS = {"order": ["Mouse-omics", "Ethoscope"], "map": {"Mouse-Omics": "Mouse-omics", "Ethoscope": "Ethoscope"}}


def log_row(project="Mouse-Omics", title="Task", est="", start="", end="", status="Planned", **kw):
    r = [project, title, est, start, end, status, "", "", "", "", ""]
    for k, v in kw.items():
        r[st.COLS.index(k)] = v
    return r


class FakeWorksheet:
    """Row 1 is the header; data row i lives at grid[i-2]. Records every write so tests can check what was touched."""

    def __init__(self, rows):
        self.grid = [list(r) for r in rows]
        self.row_count = 1000
        self.log = []

    def get_values(self, rng, value_render_option=None, date_time_render_option=None):
        assert rng == "A2:K" and value_render_option == "UNFORMATTED_VALUE" and date_time_render_option == "SERIAL_NUMBER"
        out = [list(r) for r in self.grid]
        while out and not any(str(x) != "" for x in out[-1]):
            out.pop()
        return out

    def _set(self, row, col, v):
        while len(self.grid) < row - 1:
            self.grid.append([""] * 11)
        self.grid[row - 2][col] = v

    def batch_update(self, data, value_input_option):
        assert value_input_option == "USER_ENTERED"
        for d in data:
            a1 = d["range"]
            self.log.append(a1)
            self._set(int(a1[1:]), ord(a1[0]) - 65, d["values"][0][0])

    def update(self, values, range_name, value_input_option):
        self.log.append(range_name)
        row = int(range_name.split(":")[0][1:])
        while len(self.grid) < row - 1:
            self.grid.append([""] * 11)
        self.grid[row - 2] = list(values[0])

    def insert_row(self, values, index, value_input_option, inherit_from_before):
        assert index == 2 and inherit_from_before is False
        self.log.append("insert@2")
        self.grid.insert(0, list(values))

    def batch_clear(self, ranges):
        for rng in ranges:
            self.log.append("clear " + rng)
            self.grid[int(rng.split(":")[0][1:]) - 2] = [""] * 11

    def add_rows(self, n):
        self.row_count += n


class Logic:
    def test_parsing(self):
        t = {x["title"]: x for x in self.store.list_tasks()}
        a = t["Serial dates"]
        self.assertEqual((a["start"], a["end"], a["due"]), ("2026-10-20", "2026-10-25", "2026-10-25"))
        self.assertEqual(a["status"], "Complete")
        self.assertEqual(a["done"], "2026-10-25")
        self.assertEqual(a["project"], "Mouse-omics")  # grouped for display
        self.assertEqual(a["project_raw"], "Mouse-Omics")  # sheet text untouched
        b = t["Messy"]
        self.assertEqual(b["due"], "2026-03-16")  # last date in a multi-line cell
        self.assertEqual(b["hours"], 12.5)
        self.assertEqual(t["Days est"]["hours"], "")
        self.assertEqual(t["Days est"]["est_label"], "")
        self.assertEqual(t["Blank status"]["status"], "Unscheduled")
        self.assertEqual(t["Month dot"]["due"], "2026-02-18")
        self.assertEqual(t["Latest"]["note"], "[2026-10-28] second note")

    def test_update_writes_only_changed_cells(self):
        tid = self.id_of("Messy")
        self.store.update(tid, {"title": "Messy", "est": "12.5h", "result": "new result"})
        self.assertEqual(self.writes(), ["H"])  # est & title unchanged -> not written

    def test_status_writes_sheet_vocabulary(self):
        tid = self.id_of("Blank status")
        t = self.store.update(tid, {"status": "Ongoing"})
        self.assertEqual(t["status"], "Ongoing")
        t = self.store.update(t["id"], {"status": "Unscheduled"})
        self.assertEqual(self.cell(self.row_of("Blank status"), "F"), "")

    def test_complete_stamps_end_only_when_blank(self):
        blank = self.store.update(self.id_of("Blank status"), {"status": "Complete"})
        self.assertEqual(blank["done"], dt.date.today().isoformat())
        planned = self.store.update(self.id_of("Planned with end"), {"status": "Complete"})
        self.assertEqual(planned["end"], "2026-12-01")  # existing text kept

    def test_project_noop_when_already_that_group(self):
        self.store.update(self.id_of("Messy"), {"project": "Mouse-omics"})
        self.assertEqual(self.writes(), [])
        self.store.update(self.id_of("Messy"), {"project": "Ethoscope"})
        self.assertEqual(self.writes(), ["A"])

    def test_id_survives_row_insertion_between_read_and_write(self):
        tid = self.id_of("Messy")
        self.insert_row_at_top(log_row("Ethoscope", "Brand new row from someone else"))
        self.store.update(tid, {"result": "ok"})
        self.assertEqual(self.cell(self.row_of("Messy"), "H"), "ok")

    def test_title_edit_returns_new_id(self):
        t = self.store.update(self.id_of("Messy"), {"title": "Messy renamed"})
        self.assertIn(t["id"], [x["id"] for x in self.store.list_tasks()])

    def test_duplicate_titles_get_distinct_ids(self):
        ids = [x["id"] for x in self.store.list_tasks() if x["title"] == "Dup"]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        self.store.update(ids[1], {"result": "second"})
        rows = [self.cell(r, "H") for r in (self.row_of("Dup"), self.row_of("Dup", 1))]
        self.assertEqual(rows, ["", "second"])

    def test_create_and_delete(self):
        t = self.store.create({"title": "New one", "project": "Ethoscope", "status": "Ongoing", "est": "4h", "end": "2026-12-05"})
        self.assertEqual((t["status"], t["hours"], t["project"]), ("Ongoing", 4.0, "Ethoscope"))
        self.store.delete(t["id"])
        self.assertNotIn("New one", [x["title"] for x in self.store.list_tasks()])

    def test_rejects_bad_input(self):
        with self.assertRaises(st.TaskError):
            self.store.update(self.id_of("Messy"), {"status": "Done"})
        with self.assertRaises(st.TaskError):
            self.store.create({"title": " ", "project": "Ethoscope"})
        with self.assertRaises(st.NotFound):
            self.store.update("nope", {"result": "x"})


FIXTURE = [
    log_row("Mouse-Omics", "Serial dates", start=SERIAL("2026-10-20"), end=SERIAL("2026-10-25"), status="Complete"),
    log_row("Mouse-Omics", "Messy", est="12.5h", start="02.23.2026\n03.11.26", end="02/25/26\n03.16.26", status="Complete"),
    log_row("Ethoscope", "Days est", est="Implementation: 5-7 days", status="Planned"),
    log_row("Ethoscope", "Blank status", status=""),
    log_row("Ethoscope", "Planned with end", end="2026-12-01"),
    log_row("Ethoscope", "Month dot", start=2.16, end=2.18, status="Complete"),
    log_row("Ethoscope", "Latest", comments="[2026-10-01] first note\n[2026-10-28] second note"),
    log_row("Ethoscope", "Dup"),
    log_row("Ethoscope", "Dup"),
]


class SheetsTests(Logic, unittest.TestCase):
    def setUp(self):
        self.ws = FakeWorksheet(FIXTURE)
        self.store = st.SheetsStore(self.ws, groups=GROUPS)

    def test_configured_projects_listed_even_when_unused(self):
        s = st.SheetsStore(self.ws, groups={"order": [], "map": {}}, extra_projects=["Brand new project"])
        self.assertIn("Brand new project", s.projects())

    def test_new_project_is_allowed_when_distinct(self):
        t = self.store.create({"project": "Zebrafish imaging", "title": "First"})
        self.assertEqual(t["project"], "Zebrafish imaging")
        self.assertIn("Zebrafish imaging", self.store.projects())

    def test_new_project_same_name_is_blocked(self):
        for name in ("ethoscope", "ETHO-SCOPE", " Mouse omics "):
            with self.assertRaises(st.ProjectExists) as cm:
                self.store.create({"project": name, "title": "X"})
            self.assertTrue(cm.exception.exact)
        with self.assertRaises(st.ProjectExists):  # "allow" never overrides an exact duplicate
            self.store.create({"project": "ethoscope", "title": "X", "allow_new_project": True})

    def test_new_project_lookalike_needs_confirmation(self):
        with self.assertRaises(st.ProjectExists) as cm:
            self.store.create({"project": "Ethoscopes", "title": "X"})
        self.assertEqual((cm.exception.exact, cm.exception.similar), (None, ["Ethoscope"]))
        self.assertNotIn("X", [t["title"] for t in self.store.list_tasks()])
        t = self.store.create({"project": "Ethoscopes", "title": "X", "allow_new_project": True})
        self.assertEqual(t["project"], "Ethoscopes")

    def test_existing_project_never_flagged(self):
        self.store.create({"project": "Ethoscope", "title": "Fine"})
        self.store.create({"project": "Mouse-omics", "title": "Fine too"})

    def test_find_similar(self):
        known = ["Tx-omics", "Tx-omics revision", "Mouse-omics", "GABA / vGAT"]
        self.assertEqual(st.find_similar("tx omics", known), ("Tx-omics", ["Tx-omics revision"]))
        self.assertEqual(st.find_similar("Mouse omic", known)[1], ["Mouse-omics"])
        self.assertEqual(st.find_similar("Sleep EEG", known), (None, []))

    def test_new_task_defaults_start_to_today(self):
        import datetime as dt
        self.assertEqual(self.store.create({"project": "Ethoscope", "title": "Fresh"})["start"], dt.date.today().isoformat())

    def id_of(self, title, n=0):
        return [t for t in self.store.list_tasks() if t["title"] == title][n]["id"]

    def row_of(self, title, n=0):
        return [t for t in self.store.list_tasks() if t["title"] == title][n]["row"]

    def cell(self, row, col):
        return self.ws.grid[row - 2][ord(col) - 65]

    def writes(self):
        return [w[0] for w in self.ws.log]

    def insert_row_at_top(self, row):
        self.ws.grid.insert(0, row)

    def test_writes_are_cell_level_and_formula_safe(self):
        self.store.update(self.id_of("Messy"), {"comments": "=HYPERLINK(1)"})
        self.assertEqual(len(self.ws.log), 1)
        self.assertEqual(self.cell(self.row_of("Messy"), "J"), "'=HYPERLINK(1)")

    def test_new_rows_go_to_first_blank_by_default(self):
        before = len(self.ws.grid)
        t = self.store.create({"title": "Appended", "project": "Ethoscope"})
        self.assertEqual(t["row"], before + 2)
        self.assertEqual(self.ws.log[-1], f"A{t['row']}:K{t['row']}")

    def test_new_rows_can_go_on_top(self):
        s = st.SheetsStore(self.ws, groups=GROUPS, new_rows="top")
        t = s.create({"title": "On top", "project": "Ethoscope"})
        self.assertEqual(t["row"], 2)
        self.assertEqual(self.ws.log[-1], "insert@2")

    def test_grows_sheet_when_full(self):
        self.ws.row_count = len(self.ws.grid) + 1
        self.store.create({"title": "overflow", "project": "Ethoscope"})
        self.assertEqual(self.ws.row_count, len(self.ws.grid) + 20)


class XlsxTests(Logic, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "t.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Updated Log 2026"
        ws.append(["Project", "Experiment", "Time Estimate", "Start Date", "Projected End Date", "Status"])
        for r in FIXTURE:
            row = [dt.datetime(1899, 12, 30) + dt.timedelta(days=c) if (isinstance(c, int) and c > 1000) else c for c in r]
            ws.append(row)
        wb.save(self.path)
        self.store = st.XlsxStore(self.path, groups=GROUPS)
        self._before = None

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _ws(self):
        return openpyxl.load_workbook(self.path)["Updated Log 2026"]

    def id_of(self, title, n=0):
        return [t for t in self.store.list_tasks() if t["title"] == title][n]["id"]

    def row_of(self, title, n=0):
        return [t for t in self.store.list_tasks() if t["title"] == title][n]["row"]

    def cell(self, row, col):
        v = self._ws()[f"{col}{row}"].value
        return "" if v is None else v

    def writes(self):
        # compare the file to the original fixture to see which columns changed
        before = openpyxl.Workbook().active
        changed = set()
        ws = self._ws()
        for ri, fx in enumerate(FIXTURE, 2):
            for ci, orig in enumerate(fx):
                now = ws.cell(ri, ci + 1).value
                if isinstance(orig, int) and orig > 1000:
                    continue
                if (now if now is not None else "") != orig and str(now) != str(orig):
                    changed.add(chr(65 + ci))
        return sorted(changed)

    def insert_row_at_top(self, row):
        wb = openpyxl.load_workbook(self.path)
        wb["Updated Log 2026"].insert_rows(2)
        for i, v in enumerate(row):
            wb["Updated Log 2026"].cell(2, i + 1).value = v or None
        wb.save(self.path)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.ws = FakeWorksheet(FIXTURE)
        self.c = appmod.create_app(st.SheetsStore(self.ws, groups=GROUPS), 8765).test_client()
        self.h = {"Host": "127.0.0.1:8765"}

    def test_roundtrip(self):
        r = self.c.get("/api/tasks", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["statuses"], st.STATUSES)
        self.assertIn("Mouse-omics", r.json["projects"])
        tid = [t for t in r.json["tasks"] if t["title"] == "Messy"][0]["id"]
        r = self.c.patch(f"/api/tasks/{tid}", json={"status": "Ongoing"}, headers=self.h)
        self.assertEqual(r.json["task"]["status"], "Ongoing")
        r = self.c.post("/api/tasks", json={"title": "Via api", "project": "Ethoscope"}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        r2 = self.c.delete(f"/api/tasks/{r.json['task']['id']}", json={}, headers=self.h)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(self.c.patch("/api/tasks/zzz", json={"result": "x"}, headers=self.h).status_code, 404)
        self.assertEqual(self.c.patch(f"/api/tasks/{tid}", json={"status": "bad"}, headers=self.h).status_code, 400)

    def test_project_check_and_conflict(self):
        r = self.c.get("/api/projects/check?name=ethoscopes", headers=self.h)
        self.assertEqual((r.json["exact"], r.json["similar"], r.json["known"]), (None, ["Ethoscope"], False))
        self.assertTrue(self.c.get("/api/projects/check?name=Ethoscope", headers=self.h).json["known"])
        r = self.c.post("/api/tasks", json={"title": "x", "project": "ethoscope"}, headers=self.h)
        self.assertEqual((r.status_code, r.json["exact"]), (409, "Ethoscope"))
        r = self.c.post("/api/tasks", json={"title": "x", "project": "Ethoscopes"}, headers=self.h)
        self.assertEqual((r.status_code, r.json["similar"]), (409, ["Ethoscope"]))
        r = self.c.post("/api/tasks", json={"title": "x", "project": "Ethoscopes", "allow_new_project": True}, headers=self.h)
        self.assertEqual(r.status_code, 201)

    def test_blocks_foreign_host_and_origin(self):
        self.assertEqual(self.c.get("/api/tasks", headers={"Host": "evil.example"}).status_code, 403)
        r = self.c.post("/api/tasks", json={"title": "x", "project": "p"}, headers={**self.h, "Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/api/tasks", data="title=x", content_type="text/plain", headers=self.h)
        self.assertEqual(r.status_code, 415)


if __name__ == "__main__":
    unittest.main()
