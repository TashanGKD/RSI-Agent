import fcntl
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from operations import failed_text_retry as recovery
from operations.public_api import PublicAPI, PublicError
from operations.dispatch import artifact_barrier
from operations.store import Store


class FailedTextRetryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.job = {"id": "a" * 32, "client": "rsi-group", "request_id": "fixture",
                    "state": "unknown", "updated": 1.0, "action": "send_text",
                    "peer": "fixture@chatroom", "payload": {"text": "frozen\noriginal"}}
        self.baseline = {"id": "0x12", "x": 20, "y": 10, "width": 905, "height": 667}
        self.window = {"id": "0x13", "x": 110, "y": 60, "width": 623, "height": 667}
        self.host = {"pid": 601}
        self.info = {"baseline": [self.baseline], "host": self.host, "hostBirth": "700",
                     "window": self.window, "jobId": self.job["id"], "requestId": self.job["request_id"],
                     "peer": self.job["peer"], "oldProcessExited": True, "originalHadNoParkedDraft": True,
                     "textSHA256": recovery.hash_text("frozen\noriginal"),
                     "account": "fixture-account", "failedLocalId": 42}
        self.store = Mock(root=self.root)
        self.driver = Mock(root=self.root)
        self.driver.acquire.return_value = True

    def synthetic_bubble(self):
        img = Image.new("RGB", (623, 667), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle((138, 120, 520, 465), fill=(158, 237, 154))
        draw.ellipse((111, 243, 127, 259), fill=(255, 64, 78))
        draw.rectangle((118, 246, 120, 252), fill="white")
        draw.rectangle((118, 254, 120, 256), fill="white")
        return img

    def test_requires_red_icon_and_same_bubble_adjacency(self):
        img = self.synthetic_bubble()
        recovery.verify_bubble(img, (146, 251), (119, 251))
        for copy, retry in [((146, 300), (119, 251)), ((146, 251), (130, 251)),
                            ((146, 251), (90, 251)), ((-2, 251), (119, 251))]:
            with self.subTest(copy=copy, retry=retry), self.assertRaises(ValueError):
                recovery.verify_bubble(img, copy, retry)

    def test_official_antialiased_failure_glyph_requires_both_stroke_and_dot(self):
        img = self.synthetic_bubble()
        draw = ImageDraw.Draw(img)
        draw.rectangle((117, 246, 121, 256), fill=(250, 73, 85))
        draw.rectangle((118, 246, 119, 251), fill=(250, 214, 214))
        draw.rectangle((118, 254, 119, 255), fill=(250, 175, 175))
        recovery.verify_bubble(img, (146, 251), (119, 251))
        draw.rectangle((117, 253, 122, 257), fill=(250, 73, 85))
        with self.assertRaises(ValueError):
            recovery.verify_bubble(img, (146, 251), (119, 251))

    def test_crash_after_scheduling_never_issues_another_click(self):
        img = self.synthetic_bubble()
        controls = Mock()
        controls.click.side_effect = OSError("simulated crash at the click boundary")
        clipboard = Mock()
        clipboard.wait_for_text.return_value = self.job["payload"]["text"]
        gi = ModuleType("gi")
        gi.require_version = Mock()
        repository = ModuleType("gi.repository")
        repository.Gdk = SimpleNamespace(SELECTION_CLIPBOARD=1)
        repository.Gtk = SimpleNamespace(Clipboard=SimpleNamespace(get=lambda _: clipboard))
        fields = {"copy_point": [146, 251], "retry_point": [119, 251],
                  "scene_sha256": recovery.pixels(img)}
        with (patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}),
              patch.object(recovery, "bound_window", return_value=self.window),
              patch.object(recovery, "same_scene", return_value=img),
              patch.object(recovery, "failed_bubble", return_value=42),
              patch("operations.recipes.activate"),
              patch("operations.recipes.context_menu"),
              patch("operations.recipes.controls", return_value=controls)):
            with self.assertRaises(OSError):
                recovery.click_retry(self.driver, self.job, self.job["payload"], fields, self.info)
            result = recovery.click_retry(self.driver, self.job, self.job["payload"], fields, self.info)
        controls.click.assert_called_once_with(229, 311)
        self.assertEqual(result["state"], "already_scheduled")
        saved = recovery.read_record(recovery.receipt_path(self.root, self.job, "scheduled"))
        self.assertEqual(saved["failedLocalId"], 42)
        self.assertEqual(saved["textSHA256"], self.info["textSHA256"])

    def test_foreign_copied_bubble_cannot_schedule_or_click(self):
        img = self.synthetic_bubble()
        controls = Mock()
        clipboard = Mock()
        clipboard.wait_for_text.return_value = "another message"
        gi = ModuleType("gi")
        gi.require_version = Mock()
        repo = ModuleType("gi.repository")
        repo.Gdk = SimpleNamespace(SELECTION_CLIPBOARD=1)
        repo.Gtk = SimpleNamespace(Clipboard=SimpleNamespace(get=lambda _: clipboard))
        fields = {"copy_point": [146, 251], "retry_point": [119, 251],
                  "scene_sha256": recovery.pixels(img)}
        with (patch.dict(sys.modules, {"gi": gi, "gi.repository": repo}),
              patch.object(recovery, "bound_window", return_value=self.window),
              patch.object(recovery, "same_scene", return_value=img),
              patch("operations.recipes.activate"),
              patch("operations.recipes.context_menu"),
              patch("operations.recipes.controls", return_value=controls)):
            with self.assertRaisesRegex(ValueError, "differs"):
                recovery.click_retry(self.driver, self.job, self.job["payload"], fields, self.info)
        controls.click.assert_not_called()
        self.assertFalse(recovery.receipt_path(self.root, self.job, "scheduled").exists())

    def test_native_failed_row_requires_unique_exact_failure_and_zero_sequence(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE Name2Id(user_name TEXT)")
        db.execute("INSERT INTO Name2Id VALUES ('fixture-account')")
        table = "Msg_" + recovery.hashlib.md5(self.job["peer"].encode()).hexdigest()
        db.execute("CREATE TABLE " + table + "(local_id,server_id,server_seq,status,message_content,"
                   "real_sender_id,local_type,create_time)")
        row = (42, 0, 0, 5, self.job["payload"]["text"], 1, 1, 400)
        db.execute("INSERT INTO " + table + " VALUES (?,?,?,?,?,?,?,?)", row)

        @contextmanager
        def native(_):
            yield db, {"consistency": "committed"}

        module = SimpleNamespace(ACCOUNT="fixture-account", native=native, decode=lambda value: value)
        attempt = dict(self.job["payload"], startedAt=399)
        with patch.dict(sys.modules, {"linux_tool": module}):
            self.assertEqual(recovery.failed_bubble(self.job, attempt, "fixture-account"), 42)
            for col in ("server_id", "server_seq", "status"):
                db.execute("UPDATE " + table + " SET " + col + "=7")
                with self.assertRaises(ValueError):
                    recovery.failed_bubble(self.job, attempt, "fixture-account")
                db.execute("UPDATE " + table + " SET " + col + "=?", (5 if col == "status" else 0,))
            db.execute("INSERT INTO " + table + " VALUES (?,?,?,?,?,?,?,?)", (43, *row[1:]))
            with self.assertRaises(ValueError):
                recovery.failed_bubble(self.job, attempt, "fixture-account")

    def test_executor_contention_cannot_reach_display(self):
        with (self.root / "executor.lock").open("wb") as taken:
            fcntl.flock(taken, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError), recovery.exclusive(self.store, self.driver):
                self.fail("executor lock not respected")
        self.driver.acquire.assert_not_called()

    def test_native_acceptance_requires_cleanup_and_exact_payload(self):
        proof = {"state": "accepted", "nativeStatus": 2, "serverId": "7",
                 "textComparison": {"mode": "exact", "expectedSHA256": self.info["textSHA256"],
                                    "actualSHA256": self.info["textSHA256"]}}
        wrong = dict(proof, textComparison={"mode": "exact", "actualSHA256": "bad"})
        self.assertEqual(recovery.finish(self.store, self.driver, self.job, self.info, wrong)["state"],
                         "retry_waiting_for_native_receipt")
        self.driver.app_windows.return_value = [self.baseline, self.window]
        self.driver._file_helper.return_value.require_empty_editor.side_effect = ValueError("foreign draft")
        controls = Mock()
        with (patch.object(recovery, "bound_window", return_value=self.window),
              patch("operations.lease.birth", return_value="700"),
              patch("operations.windows.window_identity", return_value=self.host),
              patch("operations.recipes.controls", return_value=controls),
              patch("operations.recipes.screen", return_value=self.synthetic_bubble()),
              patch("operations.navigation.popout_binding", return_value={})):
            with self.assertRaisesRegex(ValueError, "foreign draft"):
                recovery.finish(self.store, self.driver, self.job, self.info, proof)
            controls.click.assert_not_called()
            self.store.set_state.assert_not_called()
            self.driver.app_windows.return_value = [self.baseline]
            with self.assertRaises(FileNotFoundError):
                recovery.finish(self.store, self.driver, self.job, self.info, proof)
            recovery.record(recovery.receipt_path(self.root, self.job, "closing"),
                            {"jobId": self.job["id"], "window": self.window, "serverId": "7",
                             "emptyRecoveryEditor": True})
            for tag in ("navigation", "composer", "execution-check", "attempt"):
                recovery.record(self.root / (self.job["id"] + "-" + tag + ".json"), {"fixture": tag})
            self.store.set_state.side_effect = lambda *args, **kwargs: {"result": args[2]}
            result = recovery.finish(self.store, self.driver, self.job, self.info, proof)
        self.assertEqual(result["nativeStatus"], 2)
        self.assertEqual(result["nativeRecoveryClicks"], 1)
        self.assertTrue(result["navigationRestored"])
        self.assertEqual(self.store.set_state.call_args.kwargs["expected"], ("unknown", 1.0))

    def test_proved_retirement_releases_dispatch_without_editing_originals(self):
        s = Store(self.root)
        self.addCleanup(s.close)
        work = {k: self.job[k] for k in ("client", "request_id", "peer", "action", "payload")}
        work["peer"] = "28498732312@chatroom"
        first = s.submit(work)
        second = s.submit(dict(work, request_id="second"))
        artifacts = {}
        for tag, state in (("navigation", "started"), ("composer", "staged"),
                           ("execution-check", "terminal-boundary"), ("attempt", "fixture")):
            path = self.root / (first["id"] + "-" + tag + ".json")
            recovery.record(path, {"state": state})
            artifacts[tag] = path.read_bytes()
        s.set_state(first["id"], "unknown", {"sendClicks": 1})
        self.assertIsNone(s.peek_ready())
        witness = dict(self.info, jobId=first["id"], requestId=first["request_id"],
                       peer=first["peer"], serverId="7",
                       originalArtifacts=recovery.artifact_hashes(self.root, first))
        retired = recovery.receipt_path(self.root, first, "retired")
        recovery.record(retired, witness)
        plan = recovery.receipt_path(self.root, first, "plan")
        recovery.record(plan, {"belongsToRecovery": True})
        s.set_state(first["id"], "succeeded", {"state": "accepted", "serverId": "7",
                                                "nativeStatus": 2, "nativeRecoveryClicks": 1,
                                                "recoveryRetirementSHA256": "bad"})
        self.assertEqual(artifact_barrier(s), "DRAFT_RECOVERY_PENDING")
        result = dict(s.by_id(first["id"])["result"],
                      recoveryRetirementSHA256=recovery.hashlib.sha256(retired.read_bytes()).hexdigest())
        s.set_state(first["id"], "succeeded", result)
        self.assertIsNone(artifact_barrier(s))
        self.assertEqual(s.claim()["id"], second["id"])
        for tag, original_bytes in artifacts.items():
            path = self.root / (first["id"] + "-" + tag + ".json")
            self.assertEqual(path.read_bytes(), original_bytes)

    def test_original_recovery_uses_business_guard_with_an_unknown_queue_head(self):
        request = {"op": "open_failed_text_retry", "client": self.job["client"],
                   "request_id": self.job["request_id"]}
        self.store.get.return_value = self.job

        def require_business_class():
            self.assertEqual(self.driver.work_class, "business")
            return True

        self.driver.acquire.side_effect = require_business_class
        with (patch("operations.driver.NativeDriver", return_value=self.driver),
              patch.object(recovery, "original", return_value=({}, self.info)),
              patch.object(recovery, "failed_bubble", return_value=42),
              patch.object(recovery, "open_bubble", return_value={"state": "ready"})):
            self.assertEqual(recovery.restore(self.store, {"account": "fixture-account"}, request),
                             {"state": "ready"})
        self.driver.acquire.assert_called_once()
        self.driver.release.assert_called_once()

    def test_operations_are_admin_only(self):
        api = PublicAPI(self.root / "state", {"account": "fixture-account", "clients": {}})
        self.addCleanup(api.close)
        for op in ("open_failed_text_retry", "click_failed_text_retry", "finish_failed_text_retry"):
            with self.subTest(op=op), self.assertRaises(PublicError):
                api.call({"op": op, "client": "rsi-group", "request_id": "fixture"})


if __name__ == "__main__":
    unittest.main()
