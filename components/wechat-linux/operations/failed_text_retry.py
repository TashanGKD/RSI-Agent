"""Explicit admin recovery of one failed native text bubble after a client restart."""

import fcntl
import hashlib
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from types import SimpleNamespace


def receipt_path(root, job, phase):
    if not re.fullmatch("[0-9a-f]{32}", job["id"]):
        raise ValueError("invalid internal request identity")
    return root / (job["id"] + "-native-retry-" + phase + ".json")


def pending(root, job):
    path = receipt_path(root, job, "plan")
    return path.exists() or path.is_symlink()


def read_record(path):
    mode = path.lstat()
    if (not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.getuid()
            or mode.st_mode & 0o077 or mode.st_size > 30000):
        raise ValueError("private recovery evidence required")
    return json.loads(path.read_text())


def record(path, data):
    raw = json.dumps(data, ensure_ascii=False).encode()
    if len(raw) > 30000:
        raise ValueError("recovery evidence exceeds budget")
    # An incomplete record after interruption is deliberately still a fence.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def hash_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def original(store, job, account):
    from . import composer, navigation
    from .lease import birth

    result = job.get("result") or {}
    if (job["state"] != "unknown" or job["action"] != "send_text"
            or not job["peer"].endswith("@chatroom") or result.get("sendClicks") != 1):
        raise ValueError("one original uncertain group text attempt required")
    active = store.active()
    if not active or active["id"] != job["id"] or active["updated"] != job["updated"]:
        raise ValueError("original no longer owns the queue")
    phases = dict(store.c.execute(
        "SELECT state, count(*) FROM events WHERE job_id=? AND state IN "
        "('confirmed', 'executing') GROUP BY state", (job["id"],)))
    if phases != {"confirmed": 1, "executing": 1}:
        raise ValueError("one original execution required")
    attempt = read_record(store.root / (job["id"] + "-attempt.json"))
    execution = read_record(store.root / (job["id"] + "-execution-check.json"))
    text = job["payload"]["text"]
    if (attempt.get("peer") != job["peer"] or attempt.get("action") != "send_text"
            or attempt.get("text") != text or attempt.get("clickScheduled") is not True
            or execution.get("state") != "terminal-boundary"):
        raise ValueError("original attempt identity changed")
    nav = navigation.load(store.root, job)
    draft = composer.load(store.root, job)
    if (not nav or nav.get("state") != "started" or not nav.get("processBirth")
            or nav.get("search") or nav.get("ownPopout") or nav.get("protectedDraft")
            or birth(nav["mainIdentity"]["pid"]) == nav["processBirth"]
            or not draft or draft.get("state") != "staged"
            or draft.get("priorChars") != 0 or draft.get("priorText") not in ("", None)):
        raise ValueError("retired navigation and empty original draft not proven")
    return attempt, {
        "jobId": job["id"], "requestId": job["request_id"], "account": account,
        "peer": job["peer"], "textSHA256": hash_text(text),
        "originalUpdated": job["updated"], "oldProcessExited": True,
        "originalHadNoParkedDraft": True,
    }


def failed_bubble(job, attempt, account):
    from linux_tool import ACCOUNT, decode, native

    if ACCOUNT != account:
        raise ValueError("native account changed")
    table = "Msg_" + hashlib.md5(job["peer"].encode()).hexdigest()
    with native("message/message_0.db") as (db, receipt):
        if receipt.get("consistency") != "committed":
            raise ValueError("committed native snapshot required")
        sender = db.execute("SELECT rowid FROM Name2Id WHERE user_name=?", (account,)).fetchone()
        if not sender:
            raise ValueError("native sender missing")
        rows = db.execute(
            "SELECT local_id, server_id, server_seq, status, message_content FROM " + table
            + " WHERE real_sender_id=? AND local_type=1 AND create_time>=? LIMIT 101",
            (sender[0], int(attempt["startedAt"]) - 1),
        ).fetchall()
    if len(rows) > 100:
        raise ValueError("native candidates exceed budget")
    prefix = account + ":\n"
    exact = [row for row in rows if decode(row["message_content"]).removeprefix(prefix) == attempt["text"]]
    if (len(exact) != 1 or exact[0]["status"] != 5 or exact[0]["server_id"] != 0
            or exact[0]["server_seq"] != 0 or exact[0]["local_id"] <= 0):
        raise ValueError("unique failed unsynchronized native message not proven")
    return exact[0]["local_id"]


@contextmanager
def exclusive(store, driver):
    fd = os.open(store.root / "executor.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not driver.acquire():
            raise ValueError("official display is busy")
        try:
            yield
        finally:
            driver.release()
    finally:
        os.close(fd)


def point(raw, window):
    if (not isinstance(raw, list) or len(raw) != 2 or any(type(v) is not int for v in raw)
            or not 0 <= raw[0] < window["width"] or not 0 <= raw[1] < window["height"]):
        raise ValueError("expected integer point relative to the exact window")
    return raw


def image_for(driver, window):
    from .recipes import screen

    x, y = window["x"], window["y"]
    return screen(driver).crop((x, y, x + window["width"], y + window["height"])).convert("RGB")


def pixels(image):
    return hashlib.sha256(image.tobytes()).hexdigest()


def same_scene(driver, window, sha):
    image = image_for(driver, window)
    if pixels(image) != sha:
        raise ValueError("official recovery scene changed")
    return image


def verify_bubble(image, copy, retry):
    x, y = retry
    cx, cy = copy
    if not (20 <= x < cx < image.width - 12 and 88 <= y < image.height - 145
            and 19 <= cx - x <= 95 and abs(cy - y) <= 3):
        raise ValueError("retry icon and copied message are not adjacent")
    icon = image.crop((x - 8, y - 8, x + 9, y + 9))
    red = sum(r >= 210 and g <= 115 and b <= 130 for r, g, b in icon.getdata())
    white = sum(min(rgb) >= 237 for rgb in icon.crop((6, 3, 11, 14)).getdata())
    bubble = image.crop((cx - 2, cy - 2, cx + 3, cy + 3))
    green = sum(g >= 200 and g - max(r, b) >= 22 for r, g, b in bubble.getdata())
    if red < 105 or white < 5 or green < 16:
        raise ValueError("official red failure icon beside the outgoing bubble was not proven")


def global_point(window, pos):
    return window["x"] + pos[0], window["y"] + pos[1]


def open_bubble(driver, job, fields, identity, local_id):
    from .lease import birth
    from .navigation import prove_popout, title_point
    from .recipes import activate, controls, screen
    from .selectors import selected_chat_row
    from .windows import window_identity

    approval = fields["recipient_absence_sha256"]
    if not isinstance(approval, str) or not re.fullmatch("[0-9a-f]{64}", approval):
        raise ValueError("recipient-side absence evidence digest required")
    plan = receipt_path(driver.root, job, "plan")
    if pending(driver.root, job):
        raise ValueError("one original recovery navigation already exists")
    baseline = driver.app_windows()
    if len(baseline) != 1 or baseline[0]["title"] != "Weixin":
        raise ValueError("fresh official main window must be the only window")
    main = baseline[0]
    pos = point(fields["select"], main)
    if not (75 <= pos[0] < 295 and 90 <= pos[1] < main["height"] - 50):
        raise ValueError("expected a visible native conversation row")
    host = window_identity(main)
    born = birth(host["pid"])
    if not born or host["class"] != ["wechat", "wechat"]:
        raise ValueError("new official process identity not proven")
    title = driver.tool().resolve(job["peer"])["displayName"]
    if driver.name_peer(title) != job["peer"]:
        raise ValueError("official group title is ambiguous")
    c = controls(driver)
    try:
        activate(c, main)
        c.require_focus(main)
        same_scene(driver, main, fields["scene_sha256"])
        if driver.app_windows() != baseline:
            raise ValueError("official window set changed")
        data = dict(identity, baseline=baseline, host=host, hostBirth=born, select=pos,
                    selectSceneSHA256=fields["scene_sha256"], failedLocalId=local_id,
                    recipientAbsenceSHA256=approval, openedAt=time.time())
        record(plan, data)
        c.click(*global_point(main, pos))
        c.wait(450)
        c.require_focus(main)
        if driver.app_windows() != baseline or birth(host["pid"]) != born:
            raise ValueError("official window changed during row selection")
        x, y = main["x"], main["y"]
        bounds = [x + 70, y + 82, x + 300, y + main["height"] - 17]
        chosen = title_point(selected_chat_row(screen(driver), bounds))
        if abs(chosen[1] - (y + pos[1])) > 23:
            raise ValueError("same visible recipient row has not stabilized")
        c.click(*chosen)
        c.click(*chosen)
        for wait in (150, 250, 500):
            c.wait(wait)
            windows = driver.app_windows()
            if windows != baseline:
                break
        new = [w for w in windows if w not in baseline]
        if len(new) != 1 or len(windows) != 2 or main not in windows:
            raise ValueError("one owned official chat popout not proven")
        window = new[0]
        window_id = window_identity(window)
        prove_popout(window, title, window_id, host)
        record(receipt_path(driver.root, job, "window"), dict(data, window=window, windowIdentity=window_id))
        return {"state": "retry_window_ready", "window": window,
                "sceneSHA256": pixels(image_for(driver, window)), "failedLocalId": local_id}
    finally:
        c.close()


def bound_window(driver, job, info):
    from .lease import birth
    from .navigation import prove_popout
    from .windows import window_identity

    window, baseline = info["window"], info["baseline"]
    if (driver.app_windows() != sorted([*baseline, window], key=lambda w: w["id"])
            or window_identity(baseline[0]) != info["host"]
            or birth(info["host"]["pid"]) != info["hostBirth"]
            or window_identity(window) != info["windowIdentity"]):
        raise ValueError("exact recovery window or process changed")
    title = driver.tool().resolve(job["peer"])["displayName"]
    if driver.name_peer(title) != job["peer"]:
        raise ValueError("exact recovery group no longer proven")
    prove_popout(window, title, info["windowIdentity"], info["host"])
    return window


def click_retry(driver, job, attempt, fields, info):
    import secrets
    from .recipes import activate, context_menu, controls

    marker = receipt_path(driver.root, job, "scheduled")
    if marker.exists() or marker.is_symlink():
        return {"state": "already_scheduled", "automaticReplay": False}
    window = bound_window(driver, job, info)
    copy, retry = point(fields["copy_point"], window), point(fields["retry_point"], window)
    verify_bubble(same_scene(driver, window, fields["scene_sha256"]), copy, retry)
    c = controls(driver)
    try:
        activate(c, window)
        c.require_focus(window)
        same_scene(driver, window, fields["scene_sha256"])
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gtk
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(secrets.token_hex(24), -1)
        driver.active_window = window
        context_menu(driver, c, global_point(window, copy), "Copy")
        if clipboard.wait_for_text() != attempt["text"]:
            raise ValueError("official bubble Copy differs from the frozen original")
        c.require_focus(bound_window(driver, job, info))
        verify_bubble(same_scene(driver, window, fields["scene_sha256"]), copy, retry)
        if failed_bubble(job, attempt, info["account"]) != info["failedLocalId"]:
            raise ValueError("original native bubble changed before retry")
        record(marker, dict(info, retry=retry, copy=copy,
                            retrySceneSHA256=fields["scene_sha256"], scheduledAt=time.time()))
        c.click(*global_point(window, retry))
        return {"state": "retry_scheduled", "automaticReplay": False}
    finally:
        c.close()


def immutable_record(path, data):
    if path.exists() or path.is_symlink():
        if read_record(path) != data:
            raise ValueError("original recovery record changed")
        return
    record(path, data)


def artifact_hashes(root, job):
    def sha(tag):
        path = root / (job["id"] + "-" + tag + ".json")
        read_record(path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {kind: sha(kind) for kind in ("navigation", "composer", "execution-check", "attempt")}


def retired_artifact(store, path, kind):
    # Only the exact journals covered by the verified recovery result may
    # stop fencing dispatch. The original files are preserved byte for byte.
    job_id = path.name.removesuffix("-" + kind + ".json")
    if not re.fullmatch("[0-9a-f]{32}", job_id):
        return False
    receipt = receipt_path(store.root, {"id": job_id}, "retired")
    if not receipt.is_file():
        return False
    try:
        evidence = read_record(receipt)
        job = store.by_id(job_id)
        proof = (job or {}).get("result") or {}
        return bool(job and job["state"] == "succeeded" and evidence["jobId"] == job_id
                    and evidence["requestId"] == job["request_id"] and evidence["peer"] == job["peer"]
                    and evidence["textSHA256"] == hash_text(job["payload"]["text"])
                    and evidence["oldProcessExited"] is True
                    and evidence["originalHadNoParkedDraft"] is True
                    and proof.get("recoveryRetirementSHA256") == hashlib.sha256(receipt.read_bytes()).hexdigest()
                    and proof.get("nativeStatus") == 2 and proof.get("nativeRecoveryClicks") in (0, 1)
                    and proof.get("serverId") == evidence["serverId"]
                    and evidence["originalArtifacts"][kind] == hashlib.sha256(path.read_bytes()).hexdigest())
    except (KeyError, OSError, TypeError, ValueError):
        return False


def finish(store, driver, job, info, proof, retry_clicks=1):
    from .lease import birth
    from .navigation import popout_binding
    from .recipes import activate, controls, screen

    text = proof.get("textComparison") or {}
    if (proof.get("state") != "accepted" or proof.get("nativeStatus") != 2
            or not proof.get("serverId") or text.get("mode") != "exact"
            or text.get("actualSHA256") != info["textSHA256"]
            or text.get("expectedSHA256") != info["textSHA256"]):
        return {"state": "retry_waiting_for_native_receipt", "automaticReplay": False}
    baseline = info["baseline"]
    windows = driver.app_windows()
    closing = receipt_path(driver.root, job, "closing")
    close_evidence = {"jobId": job["id"], "window": info["window"], "serverId": proof["serverId"],
                      "emptyRecoveryEditor": True}
    c = controls(driver)
    try:
        if windows != baseline:
            window = bound_window(driver, job, info)
            activate(c, window)
            c.require_focus(bound_window(driver, job, info))
            cfg = popout_binding(driver.registered_binding(job["peer"]), window, screen(driver))
            driver._file_helper().require_empty_editor(
                SimpleNamespace(cfg=cfg, ui=SimpleNamespace(screenshot=lambda: screen(driver))))
            immutable_record(closing, close_evidence)
            c.click(*global_point(window, (window["width"] - 16, 14)))
            for wait in (150, 250, 500):
                c.wait(wait)
                if driver.app_windows() == baseline:
                    break
        if read_record(closing) != close_evidence:
            raise ValueError("owned empty window close was not proven")
        from .windows import window_identity
        if (driver.app_windows() != baseline or window_identity(baseline[0]) != info["host"]
                or birth(info["host"]["pid"]) != info["hostBirth"]):
            raise ValueError("recovery window cleanup not proven")
        activate(c, baseline[0])
        c.require_focus(baseline[0])
    finally:
        c.close()
    retired = receipt_path(driver.root, job, "retired")
    immutable_record(retired, {k: info[k] for k in (
        "jobId", "requestId", "peer", "textSHA256", "oldProcessExited", "originalHadNoParkedDraft"
    )} | {"serverId": proof["serverId"], "originalArtifacts": artifact_hashes(driver.root, job)})
    final = dict(proof, sendClicks=1, originalSendClicks=1, nativeRecoveryClicks=retry_clicks,
                 recoveryRetirementSHA256=hashlib.sha256(retired.read_bytes()).hexdigest(),
                 navigationRestored=True, draftRestored=True, oldProcessExited=True,
                 navigationRecoveryPending=False, draftRecoveryPending=False, postActionPending=False)
    saved = store.set_state(job["id"], "succeeded", final, expected=(job["state"], job["updated"]))
    if saved["result"] != final:
        raise ValueError("original result changed")
    return {"state": "succeeded", "nativeStatus": 2, "originalSendClicks": 1,
            "nativeRecoveryClicks": retry_clicks, "navigationRestored": True, "draftRestored": True,
            "receiptBindsBody": True}


def restore(store, policy, request):
    from .driver import NativeDriver

    driver = NativeDriver(store.root, policy)
    with exclusive(store, driver):
        job = store.get(request["client"], request["request_id"])
        if job["state"] == "succeeded" and (job.get("result") or {}).get("recoveryRetirementSHA256"):
            return {"state": "already_succeeded", "automaticReplay": False}
        attempt, identity = original(store, job, policy["account"])
        driver.fast_versions(job)
        op = request["op"]
        if op == "open_failed_text_retry":
            return open_bubble(driver, job, request, identity, failed_bubble(job, attempt, policy["account"]))
        info = read_record(receipt_path(store.root, job, "window"))
        if any(info.get(k) != v for k, v in identity.items()):
            raise ValueError("retry evidence does not bind the same original")
        if op == "click_failed_text_retry":
            return click_retry(driver, job, attempt, request, info)
        path = receipt_path(store.root, job, "scheduled")
        scheduled = path.exists() or path.is_symlink()
        if scheduled:
            record_info = read_record(path)
            if any(record_info.get(k) != v for k, v in info.items()):
                raise ValueError("scheduled retry does not match the original recovery")
        return finish(store, driver, job, info, driver.verify(job), retry_clicks=int(scheduled))
