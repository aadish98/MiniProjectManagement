"""Mini Project Management: a local kanban board over the lab task-log tab of a Google Sheet.

    python app.py                      # uses config.json (Google Sheet)
    python app.py --demo path.xlsx     # works on a throwaway copy of an .xlsx, no Google needed
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import threading
import webbrowser

from flask import Flask, jsonify, request, send_from_directory

import store as st

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config():
    path = os.path.join(HERE, "config.json")
    if not os.path.exists(path):
        sys.exit("No config.json found yet. Follow SETUP_GUIDE.md (an AI agent can do it for you).")
    with open(path) as f:
        return json.load(f)


def make_store(args, cfg):
    if args.demo:
        work = os.path.join(tempfile.mkdtemp(prefix="mpm-demo-"), "Tasks-demo.xlsx")
        shutil.copy(args.demo, work)
        print(f"Demo mode: editing a throwaway copy at {work}")
        return st.XlsxStore(work, new_rows="first_blank", extra_projects=cfg.get("projects"))
    key = cfg["service_account_file"]
    key = key if os.path.isabs(key) else os.path.join(HERE, key)
    return st.SheetsStore.connect(cfg["spreadsheet"], key, cfg.get("worksheet", "Updated Log 2026"),
                                  new_rows=cfg.get("new_rows", "first_blank"), extra_projects=cfg.get("projects"))


def create_app(store, port):
    app = Flask(__name__, static_folder=None)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    @app.before_request
    def guard():
        # Only this machine's browser may talk to the API (blocks DNS rebinding and cross-site writes).
        if request.host not in allowed_hosts:
            return jsonify(error="bad host"), 403
        if request.method != "GET":
            origin = request.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                return jsonify(error="bad origin"), 403
            if not request.is_json:
                return jsonify(error="expected JSON"), 415

    @app.errorhandler(st.TaskError)
    def bad(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(st.ProjectExists)
    def dupe(e):
        return jsonify(error=str(e), exact=e.exact, similar=e.similar, name=e.name), 409

    @app.errorhandler(st.NotFound)
    def missing(e):
        return jsonify(error=f"no task {e.args[0]}"), 404

    @app.errorhandler(Exception)
    def boom(e):
        app.logger.exception("request failed")
        return jsonify(error=f"{type(e).__name__}: {e}"), 502

    @app.get("/")
    def index():
        return send_from_directory(os.path.join(HERE, "static"), "index.html")

    @app.get("/api/tasks")
    def list_tasks():
        return jsonify(tasks=store.list_tasks(), projects=store.projects(), statuses=st.STATUSES, source=store.label,
                       synced=dt.datetime.now().isoformat(timespec="seconds"))

    @app.get("/api/projects/check")
    def check_project():
        name = st.clean_project(request.args.get("name"))
        exact, similar, known = store.check_project(name)
        return jsonify(name=name, exact=exact, similar=similar, known=known)

    @app.post("/api/tasks")
    def create():
        return jsonify(task=store.create(request.get_json())), 201

    @app.patch("/api/tasks/<task_id>")
    def update(task_id):
        return jsonify(task=store.update(task_id, request.get_json()))

    @app.delete("/api/tasks/<task_id>")
    def delete(task_id):
        store.delete(task_id)
        return jsonify(ok=True)

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", metavar="XLSX", help="run against a temporary copy of this workbook instead of Google")
    ap.add_argument("--port", type=int)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    cfg = {} if args.demo else load_config()
    port = args.port or cfg.get("port", 8765)
    store = make_store(args, cfg)
    app = create_app(store, port)
    url = f"http://127.0.0.1:{port}"
    print(f"Mini Project Management on {url}  ({store.label})")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
