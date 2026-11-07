import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

try:
    from store import Store, ValidationError, ConflictError
except ImportError:
    Store = None


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Store, "Store implementation is required")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "evidence").mkdir()
        self.md = self.source / "evidence" / "T-1.md"
        self.md.write_text('**通知者甲 · 邮件**\n\n<pre>请于10月23日前邮件反馈题目。</pre>\n')
        self.data = {"asOf": "fixture", "purpose": "not all unfinished", "scope": {"from": "2026-08-01"}, "records": [
            {"recordId": "T-1", "action": "反馈题目", "counterparty": "通知者甲／为自己", "proposedDisplayAt": "2026-10-16", "timeRequirement": "期限待核实", "status": "待判断", "evidenceFile": str(self.md)},
            {"recordId": "T-2", "action": "等资料", "counterparty": "李老师", "status": "等对方", "evidenceFile": str(self.md)}
        ]}
        self.source_file = self.source / "main.json"
        self.write_source()
        self.store = Store(self.root / "state.sqlite3", self.source_file)
        self.store.refresh()

    def write_source(self):
        self.source_file.write_text(json.dumps(self.data, ensure_ascii=False))

    def payload(self, state="待处理", **kw):
        return dict(state=state, note="测试备注", expectedRevision=0, reminder=None, **kw)

    def test_reject_unknown_state_without_writing(self):
        with self.assertRaises(ValidationError):
            self.store.confirm("T-1", self.payload("DROP TABLE tasks"))
        self.assertFalse(self.store.task("T-1")["confirmed"])

    def test_reject_oversized_note(self):
        p = self.payload()
        p["note"] = "中" * 4001
        with self.assertRaises(ValidationError):
            self.store.confirm("T-1", p)

    def test_reject_unknown_fields_and_bad_revision(self):
        p = self.payload()
        p["path"] = "../../secret"
        with self.assertRaises(ValidationError):
            self.store.confirm("T-1", p)
        p = self.payload()
        p["expectedRevision"] = True
        with self.assertRaises(ValidationError):
            self.store.confirm("T-1", p)

    def test_reject_traversal_and_symlink_evidence(self):
        for task_id in ["../secret", "T-1/../../", "T-1\x00"]:
            with self.assertRaises((ValidationError, KeyError)):
                self.store.task(task_id)
        outside = self.root / "private.txt"
        outside.write_text("SECRET")
        escape = self.source / "evidence" / "escape.md"
        escape.symlink_to(outside)
        self.data["records"][0]["evidenceFile"] = str(escape)
        self.write_source()
        self.store.refresh()
        detail = self.store.detail("T-1")
        self.assertNotIn("SECRET", json.dumps(detail))

    def test_confirmation_and_refresh_preserve_decision(self):
        t = self.store.confirm("T-1", self.payload("等对方"))
        self.assertTrue(t["confirmed"])
        self.assertEqual(t["selectedState"], "等对方")
        self.assertEqual(t["note"], "测试备注")
        self.store.refresh()
        self.assertEqual(len(self.store.tasks()), 2)
        self.data["records"][0]["action"] = "题目有新要求"
        self.write_source()
        self.store.refresh()
        t = self.store.task("T-1")
        self.assertEqual(t["selectedState"], "等对方")
        self.assertTrue(t["sourceChanged"])
        reopened = Store(self.root / "state.sqlite3", self.source_file)
        self.assertEqual(reopened.task("T-1")["note"], "测试备注")
        with self.assertRaises(ConflictError):
            reopened.confirm("T-1", self.payload("已完成"))

    def test_reject_unknown_deadline_and_past_or_naive_reminders(self):
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        for reminder in [
            {"kind": "deadline", "at": future, "timezone": "America/New_York"},
            {"kind": "custom", "at": "2020-01-01T09:00:00+00:00", "timezone": "UTC"},
            {"kind": "custom", "at": "2099-01-01T09:00:00", "timezone": "UTC"},
            {"kind": "custom", "at": future, "timezone": "../../invalid"}
        ]:
            p = self.payload("稍后提醒")
            p["reminder"] = reminder
            with self.assertRaises(ValidationError):
                self.store.confirm("T-1", p)

    def test_reminders_idempotent_and_completion_cancels(self):
        p = self.payload("稍后提醒")
        p["reminder"] = {"kind": "day1", "at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), "timezone": "America/New_York"}
        t = self.store.confirm("T-1", p)
        at = t["reminder"]["at"]
        p["expectedRevision"] = t["revision"]
        self.assertEqual(self.store.confirm("T-1", p)["reminder"]["at"], at)
        with self.store.connect() as db:
            db.execute("UPDATE decisions SET reminder_at=? WHERE id=?", ("2000-01-01T00:00:00+00:00", "T-1"))
        self.assertEqual(len(self.store.due_reminders()), 1)
        self.store.ack_reminder("T-1")
        self.assertEqual(len(self.store.due_reminders()), 0)
        t = self.store.task("T-1")
        p = self.payload("已完成")
        p["expectedRevision"] = t["revision"]
        self.assertIsNone(self.store.confirm("T-1", p)["reminder"])

    def test_source_and_html_are_text_only(self):
        self.md.write_text('**陌生人**\n<pre>&lt;script&gt;alert(1)&lt;/script&gt;</pre>')
        self.store.refresh()
        detail = self.store.detail("T-1")
        self.assertIn("<script>", detail["evidence"][0]["text"])
        self.assertEqual(self.store.source_file.read_text(), self.source_file.read_text())

    def test_deadline_tracks_authoritative_source_changes(self):
        self.data['records'][0]['recordId'] = 'MAIN-SM-MAIL-TOPIC'
        self.data['records'][0]['timeRequirement'] = '2027年10月25日前（未给具体时刻）'
        self.write_source()
        self.store.refresh()
        self.assertEqual(self.store.task('MAIN-SM-MAIL-TOPIC')['deadlineDate'], '2027-10-25')
        self.data['records'][0]['timeRequirement'] = '具体截止时间待通知'
        self.write_source()
        self.store.refresh()
        self.assertIsNone(self.store.task('MAIN-SM-MAIL-TOPIC')['deadlineDate'])

    def test_removed_source_archives_and_suppresses_reminder(self):
        p = self.payload('稍后提醒')
        p['reminder'] = {'kind':'day1', 'at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(), 'timezone':'UTC'}
        t = self.store.confirm('T-1', p)
        old_revision = t['revision']
        with self.store.connect() as db:
            db.execute('UPDATE decisions SET reminder_at=? WHERE id=?', ('2000-01-01T00:00:00+00:00','T-1'))
        self.data['records'] = self.data['records'][1:]
        self.write_source()
        self.store.refresh()
        t = self.store.task('T-1')
        self.assertFalse(t['active'])
        self.assertGreater(t['revision'], old_revision)
        self.assertEqual(self.store.due_reminders(), [])
        p = self.payload()
        p['expectedRevision'] = t['revision']
        with self.assertRaises(ValidationError): self.store.confirm('T-1', p)

    def progress(self, event_id="CHECK-1", **changes):
        event = dict(id=event_id, at="2026-10-21T10:00:00Z", sourceTime="2026-10-20T09:00:00+00:00",
                     author="AI", body="已核对新资料，仍待对方反馈。", suggestedState="等对方",
                     sources=[dict(label="会议原文", path=str(self.md), quote="请于10月23日前邮件反馈题目。")])
        event.update(changes)
        return event

    def import_progress(self, *events):
        self.data["records"][0]["progressUpdates"] = list(events)
        self.write_source()
        return self.store.refresh()

    def test_list_exposes_record_count_without_changing_human_state(self):
        self.store.confirm('T-1', self.payload('已完成'))
        self.import_progress(self.progress())
        task = self.store.task('T-1')
        self.assertEqual(task['progressCount'], 1)
        self.assertEqual(task['lastProgressAt'], '2026-10-21T10:00:00Z')
        self.assertEqual(task['selectedState'], '已完成')
        self.import_progress()
        self.assertEqual(self.store.task('T-1')['progressCount'], 1)

    def test_progress_rejects_traversal_symlink_and_forbidden_source(self):
        outside = self.root / "secret.txt"
        outside.write_text("SECRET")
        escape = self.source / "evidence" / "escape.txt"
        escape.symlink_to(outside)
        executable = self.source / "evidence" / "bad.html"
        executable.write_text("<script>bad()</script>")
        for path in ["../secret.txt", str(escape), str(executable), "\x00bad"]:
            with self.subTest(path=path), self.assertRaises(ValidationError):
                self.import_progress(self.progress(sources=[dict(label="bad", path=path, quote="quoted")]))
        self.assertEqual(self.store.task("T-1")["revision"], 0)

    def test_progress_rejects_invalid_fields(self):
        for changes in [dict(id="../event"), dict(author="我"), dict(at="2026-10-21"),
                        dict(sourceTime="unknown"), dict(suggestedState="delete"), dict(body=""),
                        dict(body="中" * 16001), dict(sources="not an array"), dict(extra="ignored")]:
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                self.import_progress(self.progress(**changes))
        self.assertEqual(self.store.task("T-1")["revision"], 0)

    def test_progress_is_immutable_and_conflict_rolls_back_every_change(self):
        self.import_progress(self.progress())
        before_meta = self.store.meta()
        before_task = self.store.task("T-1")
        self.data["asOf"] = "must roll back"
        self.data["records"][1]["action"] = "must roll back too"
        self.data["records"][1]["progressUpdates"] = [self.progress("ROLLBACK-NEW")]
        self.data["records"][0]["progressUpdates"] = [self.progress(body="overwrite")]
        self.data["records"].reverse()
        self.write_source()
        with self.assertRaises(ConflictError):
            self.store.refresh()
        self.assertEqual(self.store.meta(), before_meta)
        self.assertEqual(self.store.task("T-1"), before_task)
        self.assertEqual(self.store.task("T-2")["title"], "等资料")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM progress_updates").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM source_versions WHERE id='T-2'").fetchone()[0], 1)
        self.assertEqual(self.store.detail("T-1")["timeline"][0]["body"], self.progress()["body"])

    def test_progress_preserves_human_decision_and_is_retry_safe(self):
        p = self.payload("稍后提醒")
        p["reminder"] = dict(kind="day1", at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(), timezone="UTC")
        human = self.store.confirm("T-1", p)
        with self.store.connect() as db:
            decision_before = dict(db.execute("SELECT * FROM decisions WHERE id='T-1'").fetchone())
            history_before = [dict(r) for r in db.execute("SELECT * FROM history")]
        changes = self.import_progress(self.progress())
        self.assertEqual(changes["changed"], 1)
        current = self.store.task("T-1")
        for field in ["selectedState", "note", "reminder", "confirmedAt"]:
            self.assertEqual(current[field], human[field])
        self.assertTrue(current["sourceChanged"])
        revision = current["revision"]
        self.store.refresh()
        self.assertEqual(self.store.task("T-1")["revision"], revision)
        with self.store.connect() as db:
            self.assertEqual(dict(db.execute("SELECT * FROM decisions WHERE id='T-1'").fetchone()), decision_before)
            self.assertEqual([dict(r) for r in db.execute("SELECT * FROM history")], history_before)
            self.assertEqual(db.execute("SELECT count(*) FROM progress_updates").fetchone()[0], 1)
        detail = self.store.detail("T-1")
        self.assertEqual({e["author"] for e in detail["timeline"]}, {"我", "AI"})
        self.assertEqual(len(detail["history"]), 1)
        ai = next(e for e in detail["timeline"] if e["author"] == "AI")
        self.assertEqual(ai["sourceTime"], self.progress()["sourceTime"])
        self.assertEqual(ai["suggestedState"], "等对方")
        link_index = int(ai["sources"][0]["url"].rsplit("/", 1)[-1])
        self.assertEqual(self.store.source("T-1", link_index), self.md.resolve())
        self.assertNotIn("path", ai["sources"][0])

    def test_progress_history_survives_omission_and_source_versions_are_preserved(self):
        self.import_progress(self.progress())
        self.data["records"][0].pop("progressUpdates")
        self.data["records"][0]["action"] = "最新描述"
        self.write_source()
        self.store.refresh()
        self.assertEqual(len(self.store.detail("T-1")["timeline"]), 1)
        with self.store.connect() as db:
            versions = list(db.execute("SELECT source_hash,payload FROM source_versions WHERE id='T-1'"))
        self.assertEqual(len(versions), 3)
        self.assertEqual(len({v["source_hash"] for v in versions}), 3)
        self.assertIn("反馈题目", {json.loads(v["payload"])["title"] for v in versions})
        self.assertIn("最新描述", {json.loads(v["payload"])["title"] for v in versions})
        self.assertEqual(self.store.source("T-1", int(self.store.detail("T-1")["timeline"][0]["sources"][0]["url"].rsplit("/",1)[-1])), self.md.resolve())

    def test_timeline_contains_all_human_history_and_sorts_instants(self):
        with self.store.connect() as db:
            for index in range(105):
                db.execute("INSERT INTO history(id,at,state,note) VALUES(?,?,?,?)",
                           ("T-1", "2026-10-20T10:00:00Z", "待处理", str(index)))
        self.import_progress(self.progress(at="2026-10-20T08:00:00-04:00"),
                             self.progress("CHECK-2", at="2026-10-20T13:00:00Z", sourceTime=None, sources=[]))
        detail = self.store.detail("T-1")
        self.assertEqual(len(detail["history"]), 105)
        self.assertEqual(len(detail["timeline"]), 107)
        self.assertEqual([e["id"] for e in detail["timeline"][:2]], ["CHECK-2", "CHECK-1"])

    def test_progress_xss_is_stored_as_text_and_quote_only_is_allowed(self):
        value = '<img src=x onerror="bad()">'
        self.import_progress(self.progress(body=value, sources=[dict(label=value, quote=value)]))
        event = self.store.detail("T-1")["timeline"][0]
        self.assertEqual(event["body"], value)
        self.assertEqual(event["sources"], [dict(label=value, quote=value)])

    def test_duplicate_event_ids_are_idempotent_but_cannot_move_to_another_task(self):
        event = self.progress()
        self.import_progress(event, event)
        self.assertEqual(len(self.store.detail("T-1")["timeline"]), 1)
        self.data["records"][1]["progressUpdates"] = [event]
        self.write_source()
        with self.assertRaises(ConflictError):
            self.store.refresh()
        self.assertEqual(self.store.detail("T-2")["timeline"], [])

    def test_upgrade_preserves_removed_legacy_source_payload(self):
        with self.store.connect() as db:
            # Simulate the pre-timeline schema's existing tasks before first refresh.
            db.execute("DELETE FROM source_versions")
        self.data["records"] = self.data["records"][1:]
        self.write_source()
        self.store.refresh()
        with self.store.connect() as db:
            old = db.execute("SELECT payload FROM source_versions WHERE id='T-1'").fetchone()
        self.assertEqual(json.loads(old["payload"])["title"], "反馈题目")


if __name__ == "__main__":
    unittest.main()
