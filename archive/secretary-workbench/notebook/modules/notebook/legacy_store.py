"""Versioned secretary notebook with preserved human and AI decisions."""
import hashlib
import html
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STATES = ["等对方", "待判断", "待处理", "进行中", "暂缓", "交给AI处理", "已完成", "已结束", "稍后提醒"]
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
BLOCKED_SOURCE_SUFFIXES = {".html", ".htm", ".js", ".py", ".sh", ".sqlite3", ".db"}


# Re-export shared failures for old callers; shared contracts do not depend on storage.
from contracts.errors import ValidationError, ConflictError


def utcnow():
    return datetime.now(timezone.utc)


def stamp():
    return utcnow().isoformat()


def validate_id(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValidationError("事项编号无效")
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValidationError("JSON字段重复")
            result[k] = v
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValidationError("数值无效")))
    except (ValueError, RecursionError) as exc:
        raise ValidationError("请求不是有效JSON") from exc


class Store:
    def __init__(self, db_file, source_file):
        self.db_file = Path(db_file).expanduser().resolve()
        self.source_file = Path(source_file).expanduser().resolve()
        self.root = self.source_file.parent
        self.db_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, source_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY REFERENCES tasks(id), state TEXT NOT NULL, note TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL, source_hash TEXT NOT NULL,
                    reminder_kind TEXT, reminder_at TEXT, reminder_timezone TEXT, fired_at TEXT);
                CREATE TABLE IF NOT EXISTS history (
                    seq INTEGER PRIMARY KEY, id TEXT NOT NULL, at TEXT NOT NULL,
                    state TEXT NOT NULL, note TEXT NOT NULL, reminder TEXT);
                CREATE INDEX IF NOT EXISTS history_task ON history(id, seq);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS progress_updates (
                    event_id TEXT PRIMARY KEY, id TEXT NOT NULL REFERENCES tasks(id),
                    payload TEXT NOT NULL, imported_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS progress_task ON progress_updates(id, event_id);
                CREATE TABLE IF NOT EXISTS source_versions (
                    id TEXT NOT NULL, source_hash TEXT NOT NULL, payload TEXT NOT NULL,
                    imported_at TEXT NOT NULL, PRIMARY KEY(id, source_hash));
            """)
        self.db_file.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.db_file), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def safe_path(self, path):
        try:
            resolved = Path(path).resolve(strict=True)
            resolved.relative_to(self.root)
            if not resolved.is_file() or resolved.stat().st_size > 5 * 1024 * 1024:
                return None
            return resolved
        except (OSError, ValueError, TypeError, RuntimeError):
            return None

    def read_text(self, path, limit=2 * 1024 * 1024):
        p = self.safe_path(path)
        if p is None or p.stat().st_size > limit:
            return ""
        try:
            return p.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            return ""

    def normalized(self, row):
        if not isinstance(row, dict):
            raise ValidationError("主表事项结构无效")
        rid = validate_id(row.get("recordId"))
        text = self.read_text(row.get("evidenceFile", ""))
        evidence = []
        # Quotes are stored text; never evaluate the Markdown or HTML.
        for match in re.finditer(r"<pre>(.*?)</pre>", text, re.S):
            quote = html.unescape(match.group(1)).strip()
            if quote.startswith("{") and ('"messageId"' in quote or '"serverId"' in quote or '"lineStart"' in quote):
                continue
            prior = text[:match.start()]
            bold = re.findall(r"\*\*(.+?)\*\*", prior)
            sender = bold[-1] if bold else "已存原文"
            evidence.append({"sender": sender, "text": quote})
        if not evidence and text:
            evidence = [{"sender": "已存事项依据", "text": text}]
        links = []
        for target in re.findall(r"\]\(<?([^)>]+)>?\)", text):
            target = re.sub(r":\d+$", "", html.unescape(target.strip()))
            p = self.safe_path(target)
            if p and p.suffix.lower() not in BLOCKED_SOURCE_SUFFIXES:
                if str(p) not in [item["path"] for item in links]:
                    links.append({"label": p.name, "path": str(p)})
        status = str(row.get("status") or "待判断")
        suggestion = status if status in STATES else ("待处理" if status == "待行动" else "待判断")
        proposed = row.get("proposedDisplayAt") or row.get("proposedAt") or "待核实"
        if isinstance(proposed, dict):
            proposed = proposed.get("earliestExplicitMessage") or "待核实"
        requirement = str(row.get("timeRequirement") or "时间待定")
        deadline = None
        # Only a primary explicit full date, not an arbitrary date mentioned in history.
        explicit = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日", requirement)
        if explicit:
            try:
                deadline = date(*map(int, explicit.groups())).isoformat()
            except ValueError:
                pass
        elif rid == "MAIN-A01":
            # This curated record explicitly separates the promised handoff after this label.
            handoff = re.search(r"交名单[：:]\s*(\d{1,2})月(\d{1,2})日", requirement)
            if handoff and re.match(r"^\d{4}-", str(proposed)):
                try:
                    deadline = date(int(str(proposed)[:4]), *map(int, handoff.groups())).isoformat()
                except ValueError:
                    pass
        party = str(row.get("counterparty") or "待判断")
        payload = dict(
            id=rid, title=str(row.get("action") or "待判断"), counterparty=party,
            people=list(dict.fromkeys(x.strip() for x in re.split(r"[／/、，]", party) if x.strip())),
            proposedAt=row.get("proposedAt"), proposedDisplayAt=str(proposed)[:10],
            timeRequirement=requirement,
            deadlineDate=deadline, sourceStatus=status,
            lastKnownState=str(row.get("lastKnownState") or "当前进展待判断"),
            suggestedState=suggestion, category=str(row.get("category") or "待判断"),
            evidence=evidence, links=links,
        )
        related = row.get("relatedRecordIds", [])
        if not isinstance(related, list) or len(related) > 100:
            raise ValidationError("关联事项结构无效")
        related = [validate_id(value) for value in related]
        if rid in related or len(set(related)) != len(related):
            raise ValidationError("关联事项不能重复或指向自己")
        # Do not change old payload hashes merely by introducing this field.
        if related:
            payload["relatedRecordIds"] = related
        updates = self.validate_progress(row.get("progressUpdates", []))
        if updates:
            payload["progressUpdates"] = updates
        return payload

    def validate_progress(self, updates):
        if not isinstance(updates, list) or len(updates) > 1000:
            raise ValidationError("进展记录结构无效或数量过多")
        result = []
        allowed = {"id", "at", "sourceTime", "author", "body", "suggestedState", "sources", "state"}
        def timestamp(value):
            if not isinstance(value, str) or len(value) > 60:
                raise ValidationError("进展时间需包含有效时区")
            try:
                when = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if when.tzinfo is None:
                    raise ValueError("missing offset")
                when.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                raise ValidationError("进展时间需包含有效时区")
            return value
        for event in updates:
            if not isinstance(event, dict) or not {"id", "at", "author", "body"} <= set(event) or set(event) - allowed:
                raise ValidationError("进展字段不完整或包含未知字段")
            eid = validate_id(event["id"])
            if event["author"] != "AI":
                raise ValidationError("导入进展仅能以AI身份追加")
            body = event["body"]
            if not isinstance(body, str) or not body.strip() or len(body) > 16000:
                raise ValidationError("进展正文需为1至16000字")
            state = event.get("suggestedState")
            if state is not None and state not in STATES:
                raise ValidationError("进展建议状态无效")
            applied_state = event.get("state")
            if "state" in event:
                if not isinstance(applied_state, str) or applied_state not in STATES or applied_state == "稍后提醒":
                    raise ValidationError("AI处理状态无效；提醒时间需本人选择")
                applied_at = datetime.fromisoformat(timestamp(event["at"]).replace("Z", "+00:00"))
                if applied_at > utcnow() + timedelta(minutes=5):
                    raise ValidationError("AI处理时间不能在未来")
            sources = event.get("sources", [])
            if not isinstance(sources, list) or len(sources) > 100:
                raise ValidationError("进展来源结构无效或数量过多")
            clean_sources = []
            for source in sources:
                if not isinstance(source, dict) or set(source) - {"label", "path", "quote"}:
                    raise ValidationError("进展来源字段无效")
                label, quote = source.get("label"), source.get("quote", "")
                if not isinstance(label, str) or not label.strip() or len(label) > 500 or not isinstance(quote, str) or len(quote) > 32000:
                    raise ValidationError("进展来源标题或引文无效")
                clean = dict(label=label, quote=quote)
                target = source.get("path")
                if target is not None:
                    if not isinstance(target, str) or not target or len(target) > 4096 or "\x00" in target:
                        raise ValidationError("进展来源路径无效")
                    p = Path(target)
                    path = self.safe_path(p if p.is_absolute() else self.root / p)
                    if path is None or path.suffix.lower() in BLOCKED_SOURCE_SUFFIXES:
                        raise ValidationError("进展来源必须是资料目录内的安全文件")
                    clean["path"] = str(path)
                elif not quote.strip():
                    raise ValidationError("无来源文件时需提供原文引文")
                clean_sources.append(clean)
            if "state" in event and not clean_sources:
                raise ValidationError("AI状态变更需附原文依据")
            source_time = event.get("sourceTime")
            result.append(dict(id=eid, at=timestamp(event["at"]), author="AI", body=body,
                               sourceTime=timestamp(source_time) if source_time is not None else None,
                               suggestedState=state, sources=clean_sources))
            # Keep earlier immutable event serialization byte-for-byte equivalent.
            if "state" in event:
                result[-1]["state"] = applied_state
        return result

    def refresh(self):
        if self.source_file.stat().st_size > 16 * 1024 * 1024:
            raise ValidationError("主表超过读取上限")
        data = strict_json(self.source_file.read_text())
        rows = data.get("records") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) > 5000:
            raise ValidationError("主表结构无效")
        normalized = [self.normalized(row) for row in rows]
        ids = [r["id"] for r in normalized]
        if len(set(ids)) != len(ids):
            raise ValidationError("主表含重复事项编号")
        all_ids = set(ids)
        if any(set(row.get("relatedRecordIds", [])) - all_ids for row in normalized):
            raise ValidationError("关联事项不存在于主表，整批更新未保存")
        changes = dict(added=0, changed=0, retained=0)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Backfill pre-timeline imports, including tasks absent from this batch.
            db.execute("""INSERT OR IGNORE INTO source_versions(id,source_hash,payload,imported_at)
                          SELECT id,source_hash,payload,? FROM tasks""", (stamp(),))
            old_active = {r['id'] for r in db.execute("SELECT id FROM tasks WHERE active=1")}
            for position, payload in enumerate(normalized):
                raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                digest = hashlib.sha256(raw.encode()).hexdigest()
                old = db.execute("SELECT source_hash,active,payload FROM tasks WHERE id=?", (payload["id"],)).fetchone()
                if old is not None:
                    db.execute("INSERT OR IGNORE INTO source_versions VALUES(?,?,?,?)",
                               (payload["id"], old["source_hash"], old["payload"], stamp()))
                if old is None:
                    db.execute("INSERT INTO tasks(id,payload,source_hash,position) VALUES(?,?,?,?)",
                               (payload["id"], raw, digest, position))
                    changes["added"] += 1
                else:
                    changed = old["source_hash"] != digest or not old["active"]
                    db.execute("UPDATE tasks SET payload=?,source_hash=?,revision=revision+?,position=?,active=1 WHERE id=?",
                               (raw, digest, int(changed), position, payload["id"]))
                    changes["changed" if changed else "retained"] += 1
                db.execute("INSERT OR IGNORE INTO source_versions VALUES(?,?,?,?)",
                           (payload["id"], digest, raw, stamp()))
                for event in payload.get("progressUpdates", []):
                    event_raw = json.dumps(event, ensure_ascii=False, sort_keys=True)
                    prior = db.execute("SELECT id,payload FROM progress_updates WHERE event_id=?", (event["id"],)).fetchone()
                    if prior is not None:
                        if prior["id"] != payload["id"] or prior["payload"] != event_raw:
                            raise ConflictError("进展编号已有不同内容，整批更新未保存：" + event["id"])
                    else:
                        db.execute("INSERT INTO progress_updates VALUES(?,?,?,?)",
                                   (event["id"], payload["id"], event_raw, stamp()))
            for removed_id in old_active - set(ids):
                db.execute("UPDATE tasks SET active=0,revision=revision+1 WHERE id=?", (removed_id,))
            meta = dict(asOf=data.get("asOf", "待核实"), scope=data.get("scope", {}),
                        purpose=data.get("purpose", ""), count=len(rows), importedAt=stamp(),
                        coverageText=self.read_text(self.root / "阅读覆盖与缺口.md", 256000))
            db.execute("INSERT OR REPLACE INTO metadata VALUES('snapshot',?)", (json.dumps(meta, ensure_ascii=False),))
        return changes

    def _task(self, row):
        payload = json.loads(row["payload"])
        payload.pop("evidence", None)
        payload.pop("links", None)
        payload.pop("progressUpdates", None)
        reminder = None
        if row["reminder_at"]:
            reminder = dict(kind=row["reminder_kind"], at=row["reminder_at"],
                            timezone=row["reminder_timezone"], firedAt=row["fired_at"])
        ai = json.loads(row["ai_state_event"]) if row["ai_state_event"] else None
        ai_current = ai is not None and (not row["confirmed_at"] or
            datetime.fromisoformat(ai["at"].replace("Z", "+00:00")) >
            datetime.fromisoformat(row["confirmed_at"].replace("Z", "+00:00")))
        current_state = ai["state"] if ai_current else row["state"] or payload["suggestedState"]
        if current_state != "稍后提醒":
            reminder = None
        payload.update(selectedState=current_state,
                       confirmed=bool(row["confirmed_at"]), note=row["note"] or "",
                       revision=row["revision"], confirmedAt=row["confirmed_at"], reminder=reminder,
                       sourceChanged=bool(not row['active'] or (row["decision_hash"] and row["decision_hash"] != row["source_hash"])),
                       active=bool(row["active"]), progressCount=row['progress_count'], lastProgressAt=row['last_progress_at'],
                       stateUpdatedBy="AI" if ai_current else "我" if row["confirmed_at"] else None,
                       stateUpdatedAt=ai["at"] if ai_current else row["confirmed_at"])
        return payload

    SELECT = """SELECT t.*,d.state,d.note,d.confirmed_at,d.source_hash AS decision_hash,
        d.reminder_kind,d.reminder_at,d.reminder_timezone,d.fired_at,
        (SELECT count(*) FROM progress_updates p WHERE p.id=t.id) AS progress_count,
        (SELECT json_extract(p.payload,'$.at') FROM progress_updates p WHERE p.id=t.id
            ORDER BY julianday(json_extract(p.payload,'$.at')) DESC LIMIT 1) AS last_progress_at,
        (SELECT p.payload FROM progress_updates p WHERE p.id=t.id AND json_extract(p.payload,'$.state') IS NOT NULL
            ORDER BY julianday(json_extract(p.payload,'$.at')) DESC,p.rowid DESC LIMIT 1) AS ai_state_event
        FROM tasks t LEFT JOIN decisions d ON t.id=d.id"""

    def tasks(self):
        with self.connect() as db:
            return [self._task(r) for r in db.execute(self.SELECT + " ORDER BY t.position,t.id")]

    def task(self, rid):
        validate_id(rid)
        with self.connect() as db:
            row = db.execute(self.SELECT + " WHERE t.id=?", (rid,)).fetchone()
            if row is None:
                raise KeyError(rid)
            return self._task(row)

    def meta(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='snapshot'").fetchone()
            return json.loads(row["value"]) if row else {}

    def _source_links(self, db, rid, raw):
        links = list(raw["links"])
        for row in db.execute("SELECT payload FROM progress_updates WHERE id=? ORDER BY event_id", (rid,)):
            for source in json.loads(row["payload"])["sources"]:
                if source.get("path") and not any(link["path"] == source["path"] for link in links):
                    links.append(dict(label=source["label"], path=source["path"]))
        return links

    def detail(self, rid):
        task = self.task(rid)
        with self.connect() as db:
            raw = json.loads(db.execute("SELECT payload FROM tasks WHERE id=?", (rid,)).fetchone()["payload"])
            history = []
            timeline = []
            for h in db.execute("SELECT * FROM history WHERE id=? ORDER BY seq DESC", (rid,)):
                entry = dict(at=h["at"], state=h["state"], note=h["note"], reminder=json.loads(h["reminder"]) if h["reminder"] else None)
                history.append(entry)
                timeline.append(dict(entry, id="human-" + str(h["seq"]), author="我", body=h["note"], sourceTime=None, suggestedState=None, sources=[]))
            links = self._source_links(db, rid, raw)
            for p in db.execute("SELECT payload FROM progress_updates WHERE id=? ORDER BY event_id", (rid,)):
                event = json.loads(p["payload"])
                sources = []
                for source in event["sources"]:
                    item = dict(label=source["label"], quote=source["quote"])
                    if source.get("path"):
                        index = next(i for i, link in enumerate(links) if link["path"] == source["path"])
                        item["url"] = "/api/tasks/" + rid + "/sources/" + str(index)
                    sources.append(item)
                event["sources"] = sources
                timeline.append(event)
            timeline.sort(key=lambda event: datetime.fromisoformat(event["at"].replace("Z", "+00:00")).astimezone(timezone.utc), reverse=True)
        related = []
        with self.connect() as db:
            for related_id in raw.get("relatedRecordIds", []):
                row = db.execute(self.SELECT + " WHERE t.id=?", (related_id,)).fetchone()
                if row is not None:
                    item = self._task(row)
                    related.append({key:item[key] for key in ("id", "title", "selectedState", "active")})
        return dict(task=task, evidence=raw["evidence"], relatedTasks=related,
                    sourceLinks=[{"label": link["label"], "url": "/api/tasks/" + rid + "/sources/" + str(i)} for i, link in enumerate(links)],
                    history=history, timeline=timeline)

    def source(self, rid, index):
        self.task(rid)
        with self.connect() as db:
            payload = json.loads(db.execute("SELECT payload FROM tasks WHERE id=?", (rid,)).fetchone()["payload"])
            links = self._source_links(db, rid, payload)
        try:
            if type(index) is not int or index < 0:
                raise IndexError(index)
            path = self.safe_path(links[index]["path"])
        except (IndexError, TypeError):
            path = None
        if path is None or path.suffix.lower() in BLOCKED_SOURCE_SUFFIXES:
            raise KeyError("source")
        return path

    def validate_reminder(self, obj, task):
        if not isinstance(obj, dict) or set(obj) != {"kind", "at", "timezone"}:
            raise ValidationError("请选择提醒时间")
        if not isinstance(obj["kind"], str) or obj["kind"] not in {"day1", "day2", "day3", "day7", "deadline", "custom"}:
            raise ValidationError("提醒选项无效")
        if not isinstance(obj["at"], str) or len(obj["at"]) > 60 or not isinstance(obj["timezone"], str) or len(obj["timezone"]) > 120:
            raise ValidationError("提醒时间无效")
        try:
            when = datetime.fromisoformat(obj["at"].replace("Z", "+00:00"))
            zone = ZoneInfo(obj["timezone"])
            if when.tzinfo is None:
                raise ValueError("missing offset")
            when = when.astimezone(timezone.utc)
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            raise ValidationError("提醒需包含有效时间及时区")
        existing = task.get("reminder")
        unchanged = existing and when == datetime.fromisoformat(existing["at"]) and obj["kind"] == existing["kind"] and obj["timezone"] == existing["timezone"]
        if not unchanged and (when <= utcnow() or when > utcnow() + timedelta(days=3660)):
            raise ValidationError("请选择未来的提醒时间")
        if obj["kind"] == "deadline":
            deadline = task.get("deadlineDate")
            if not deadline:
                raise ValidationError("截止日期尚不明确，请选择具体提醒时间")
            if when.astimezone(zone).date() != date.fromisoformat(deadline) - timedelta(days=1):
                raise ValidationError("提醒日期应为截止日期前一天")
        return dict(kind=obj["kind"], at=when.isoformat(), timezone=obj["timezone"],
                    firedAt=existing["firedAt"] if unchanged else None)

    def confirm(self, rid, obj):
        validate_id(rid)
        if not isinstance(obj, dict) or set(obj) != {"state", "note", "expectedRevision", "reminder"}:
            raise ValidationError("提交字段不完整或包含未知字段")
        if obj["state"] not in STATES:
            raise ValidationError("处理选项无效")
        if not isinstance(obj["note"], str) or len(obj["note"]) > 4000:
            raise ValidationError("备注最多4000字")
        if type(obj["expectedRevision"]) is not int or obj["expectedRevision"] < 0:
            raise ValidationError("事项版本无效")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(self.SELECT + " WHERE t.id=?", (rid,)).fetchone()
            if row is None:
                raise KeyError(rid)
            if row["revision"] != obj["expectedRevision"]:
                raise ConflictError("这条事项已更新；请先核对最新记录再确认")
            task = self._task(row)
            if not task['active']:
                raise ValidationError("该事项已不在当前批次，可查看保留的历史记录")
            reminder = None
            if obj["state"] == "稍后提醒":
                reminder = self.validate_reminder(obj["reminder"], task)
            elif obj["reminder"] is not None:
                raise ValidationError("只有稍后提醒选项能提交提醒")
            when = stamp()
            db.execute("""INSERT INTO decisions(id,state,note,confirmed_at,source_hash,
                reminder_kind,reminder_at,reminder_timezone,fired_at) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET state=excluded.state,note=excluded.note,
                confirmed_at=excluded.confirmed_at,source_hash=excluded.source_hash,
                reminder_kind=excluded.reminder_kind,reminder_at=excluded.reminder_at,
                reminder_timezone=excluded.reminder_timezone,fired_at=excluded.fired_at""",
                (rid, obj["state"], obj["note"], when, row["source_hash"],
                 reminder["kind"] if reminder else None, reminder["at"] if reminder else None,
                 reminder["timezone"] if reminder else None, reminder["firedAt"] if reminder else None))
            db.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (rid,))
            db.execute("INSERT INTO history(id,at,state,note,reminder) VALUES(?,?,?,?,?)",
                       (rid, when, obj["state"], obj["note"], json.dumps(reminder, ensure_ascii=False) if reminder else None))
        return self.task(rid)

    def due_reminders(self):
        return [t for t in self.tasks() if t['active'] and t["confirmed"] and t["reminder"] and
                not t["reminder"]["firedAt"] and datetime.fromisoformat(t["reminder"]["at"]) <= utcnow()]

    def ack_reminder(self, rid):
        validate_id(rid)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM decisions WHERE id=?", (rid,)).fetchone()
            if row is None:
                raise KeyError(rid)
            if not row["reminder_at"] or datetime.fromisoformat(row["reminder_at"]) > utcnow():
                raise ValidationError("提醒尚未到时")
            if not row["fired_at"]:
                db.execute("UPDATE decisions SET fired_at=? WHERE id=?", (stamp(), rid))
                db.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (rid,))
        return self.task(rid)
