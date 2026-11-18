"""Store evaluation tasks and their immutable run reports in SQLite."""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from evaluate import compare_reports


class TaskConflict(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class TaskStore:
    def __init__(self, path: Path, score):
        self.path = path
        self.score = score
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    sequence INTEGER PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks (id),
                    version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    UNIQUE (task_id, version)
                );
            """)

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            yield db

    def submit(self, task_id, run, title=None):
        if task_id in {".", ".."} or run.subject_version in {".", ".."}:
            raise ValueError("Task and version must be addressable path segments.")
        recorded = encode(run.model_dump(mode="json"))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            first = db.execute(
                "SELECT * FROM runs WHERE task_id = ? ORDER BY sequence LIMIT 1", (task_id,)
            ).fetchone()
            if title is not None and task:
                if title != task["title"] or recorded != first["input_json"]:
                    raise TaskConflict("task_id_in_use")
                return self.receipt(task_id, first), False
            if title is None and not task:
                raise KeyError("task_not_found")
            existing = self.run_row(db, task_id, run.subject_version)
            if existing:
                if recorded != existing["input_json"]:
                    raise TaskConflict("version_in_use")
                return self.receipt(task_id, existing), False

            report = self.score(run)
            if first:
                baseline = json.loads(first["report_json"])
                if any(baseline[key] != report[key] for key in (
                    "dataset_id", "dataset_version", "dataset_sha256", "conditions_id", "scoring_version",
                    "material_registry_sha256",
                )):
                    raise TaskConflict("evaluation_conditions_changed")
            if task is None:
                db.execute("INSERT INTO tasks VALUES (?, ?, ?)", (task_id, title, now))
            db.execute(
                "INSERT INTO runs (task_id, version, created_at, input_json, report_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, run.subject_version, now, recorded, encode(report)),
            )
            return self.receipt(task_id, self.run_row(db, task_id, run.subject_version)), True

    @staticmethod
    def run_row(db, task_id, version):
        return db.execute(
            "SELECT * FROM runs WHERE task_id = ? AND version = ?", (task_id, version)
        ).fetchone()

    @staticmethod
    def receipt(task_id, row):
        return {
            "task_id": task_id,
            "workbench_path": f"/workbench?task={task_id}",
            "created_at": row["created_at"],
            "report": json.loads(row["report_json"]),
        }

    def report(self, task_id, version):
        with self.connection() as db:
            row = self.run_row(db, task_id, version)
            if row is None:
                raise KeyError("run_not_found")
            return self.receipt(task_id, row)

    def comparison(self, task_id, before, after):
        with self.connection() as db:
            old = self.run_row(db, task_id, before)
            new = self.run_row(db, task_id, after)
            if old is None or new is None:
                raise KeyError("run_not_found")
            if old["sequence"] >= new["sequence"]:
                raise TaskConflict("comparison_order")
            return compare_reports(json.loads(old["report_json"]), json.loads(new["report_json"]))

    def detail(self, task_id):
        with self.connection() as db:
            task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise KeyError("task_not_found")
            runs = db.execute(
                "SELECT version, created_at, json_extract(report_json, '$.status') AS status "
                "FROM runs WHERE task_id = ? ORDER BY sequence", (task_id,)
            ).fetchall()
            return {**dict(task), "runs": [dict(row) for row in runs]}

    def list_tasks(self, offset):
        with self.connection() as db:
            rows = db.execute("""
                SELECT t.id, t.title, r.version, r.created_at AS updated_at,
                    json_extract(r.report_json, '$.status') AS status,
                    (SELECT COUNT(*) FROM runs WHERE task_id = t.id) AS run_count
                FROM tasks t JOIN runs r ON r.sequence = (
                    SELECT MAX(sequence) FROM runs WHERE task_id = t.id
                )
                ORDER BY r.sequence DESC LIMIT 51 OFFSET ?
            """, (offset,)).fetchall()
        return {"tasks": [dict(row) for row in rows[:50]], "has_more": len(rows) > 50}
