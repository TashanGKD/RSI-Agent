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


def retry_scene_pixels(image):
    # The composer is below the validated message and icon coordinates. Keep
    # title and message pixels exact without fencing on its blinking caret.
    return pixels(image.crop((0, 0, image.width, image.height - 145)))


def same_scene(driver, window, sha, *, retry=False):
    image = image_for(driver, window)
    value = retry_scene_pixels(image) if retry else pixels(image)
    if value != sha:
        raise ValueError("official recovery scene changed")
    return image


def verify_bubble(image, copy, retry):
    x, y = retry
    cx, cy = copy
    if not (20 <= x and x + 19 <= cx < image.width - 12
            and 88 <= y < image.height - 145 and 88 <= cy < image.height - 145):
        raise ValueError("retry icon and copied message must be in the same message pane")
    icon = image.crop((x - 8, y - 8, x + 9, y + 9))
    red = sum(r >= 210 and g <= 115 and b <= 130 for r, g, b in icon.getdata())
    def light_stroke(pixel):
        r, g, b = pixel
        # Qt may blend the narrow light glyph with the red background.
        return r >= 235 and min(g, b) >= 160 and abs(g - b) <= 30

    stroke = icon.crop((6, 3, 11, 9))
    dot = icon.crop((6, 11, 11, 14))
    stroke_rows = sum(any(light_stroke(stroke.getpixel((x, y))) for x in range(stroke.width))
                      for y in range(stroke.height))
    dot_pixels = sum(light_stroke(pixel) for pixel in dot.getdata())
    if red < 105 or stroke_rows < 4 or dot_pixels < 2:
        raise ValueError("official red failure icon was not proven")

    def outgoing(pixel):
        r, g, b = pixel
        return g >= 200 and g - max(r, b) >= 22

    # The Copy menu must be opened on interactive text in the same bubble.
    # Bind that point to the failure icon by the continuous outgoing left edge.
    edge = next((i for i in range(x + 15, min(x + 76, cx - 2))
                 if all(outgoing(image.getpixel((i + dx, y))) for dx in (0, 1, 2))), None)
    if (edge is None
            or not all(any(outgoing(image.getpixel((edge + dx, row))) for dx in (1, 2, 3, 4))
                       for row in range(min(y, cy), max(y, cy) + 1))
            or sum(outgoing(pixel) for pixel in image.crop((cx-4, cy-4, cx+5, cy+5)).getdata()) < 15):
        raise ValueError("Copy point does not belong to the adjacent outgoing bubble")


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
                "sceneSHA256": retry_scene_pixels(image_for(driver, window)), "failedLocalId": local_id}
    finally:
        c.close()


def bound_window(driver, job, info, extra=()):
    from .lease import birth
    from .navigation import prove_popout
    from .windows import window_identity

    window, baseline = info["window"], info["baseline"]
    if (driver.app_windows() != sorted([*baseline, window, *extra], key=lambda w: w["id"])
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
    verify_bubble(same_scene(driver, window, fields["scene_sha256"], retry=True), copy, retry)
    c = controls(driver)
    try:
        activate(c, window)
        c.require_focus(window)
        same_scene(driver, window, fields["scene_sha256"], retry=True)
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
        verify_bubble(same_scene(driver, window, fields["scene_sha256"], retry=True), copy, retry)
        def schedule(target):
            if failed_bubble(job, attempt, info["account"]) != info["failedLocalId"]:
                raise ValueError("original native bubble changed before retry")
            record(marker, dict(info, retry=retry, copy=copy, menuPoint=target,
                                retrySceneSHA256=fields["scene_sha256"],
                                nativeControl="official-context-menu-resend", scheduledAt=time.time()))

        context_menu(driver, c, global_point(window, copy), "Resend", before_click=schedule)
        return {"state": "retry_scheduled", "automaticReplay": False}
    finally:
        c.close()


# Official Linux client English confirmation body and both buttons, with
# the window frame excluded. No chat text or private pixels are in the digest.
RESEND_CONFIRMATION = "d3cef05ec9e87348e679090b757631029c8711d5d4144ccb052c40cc9128d6f0"


def resend_dialog(driver, job, info):
    import subprocess
    from .windows import window_identity

    expected = [*info["baseline"], info["window"]]
    extra = [w for w in driver.app_windows() if w not in expected]
    if len(extra) != 1:
        raise ValueError("one original resend confirmation is required")
    dialog = extra[0]
    parent = bound_window(driver, job, info, extra=(dialog,))
    if dialog["title"] != "wechat" or (dialog["width"], dialog["height"]) != (283, 148):
        raise ValueError("unexpected official confirmation window")
    identity = window_identity(dialog)
    host = info["host"]
    types = {"_NET_WM_WINDOW_TYPE_UTILITY", "_KDE_NET_WM_WINDOW_TYPE_OVERRIDE",
             "_NET_WM_WINDOW_TYPE_NORMAL"}
    if (identity["class"] != ["wechat", "wechat"] or identity["pid"] != host["pid"]
            or identity["leader"] != host["leader"] or identity["transientFor"] != parent["id"].lower()
            or set(identity["types"]) != types):
        raise ValueError("official resend confirmation does not belong to the original window")
    flags = subprocess.run(["xprop", "-id", dialog["id"], "_NET_WM_STATE"],
                           capture_output=True, text=True, check=True, timeout=3)
    if flags.stdout.strip() != "_NET_WM_STATE(ATOM) = _NET_WM_STATE_MODAL":
        raise ValueError("official resend window is not the active modal kind")
    return dialog, identity


def resend_dialog_image(driver, dialog, sha):
    frame = image_for(driver, dialog)
    if (frame.size != (283, 148) or pixels(frame) != sha
            or pixels(frame.crop((18, 26, 265, 121))) != RESEND_CONFIRMATION):
        raise ValueError("exact official resend prompt and buttons were not proven")
    return frame


def confirm_retry(driver, job, attempt, request, info, scheduled):
    from .forwarding import require_window_focus
    from .recipes import controls

    marker = receipt_path(driver.root, job, "confirmed")
    if marker.exists() or marker.is_symlink():
        return {"state": "confirmation_already_scheduled", "automaticReplay": False}
    if scheduled.get("nativeControl") != "official-context-menu-resend":
        raise ValueError("official original Resend menu selection required")
    dialog, dialog_identity = resend_dialog(driver, job, info)
    sha = request["scene_sha256"]
    resend_dialog_image(driver, dialog, sha)
    c = controls(driver)
    try:
        require_window_focus(c, dialog)
        if failed_bubble(job, attempt, info["account"]) != info["failedLocalId"]:
            raise ValueError("original native failed bubble changed before confirmation")
        if resend_dialog(driver, job, info) != (dialog, dialog_identity):
            raise ValueError("original confirmation window changed")
        resend_dialog_image(driver, dialog, sha)
        require_window_focus(c, dialog)
        record(marker, dict(info, dialog=dialog, dialogIdentity=dialog_identity,
                            confirmationSceneSHA256=sha, confirmationScheduledAt=time.time()))
        c.click(*global_point(dialog, (80, 99)))
        return {"state": "confirmation_scheduled", "automaticReplay": False}
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
    driver.work_class = "business"
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
        if op == "confirm_failed_text_retry":
            if not scheduled:
                raise ValueError("original retry has not reached the official menu")
            return confirm_retry(driver, job, attempt, request, info, record_info)
        return finish(store, driver, job, info, driver.verify(job), retry_clicks=int(scheduled))
