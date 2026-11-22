"""Publish every new public astronomy item to privately bound WeChat groups each evening."""
import argparse
import base64
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from receiver.desktop_reply import save_once
from trigger.group_text import split_text

FEED = "https://ucas.sitianai.com/astrohot/api/v1/items"
BEIJING = timezone(timedelta(hours=8))
COVER_BYTES = 10_000_000

REMOTE = r"""
import base64
import hashlib
import json
from pathlib import Path
import sys

data = json.load(sys.stdin)
sys.path[:0] = [data['release'], data['python_path']]
from rsi_agent.config import WECHAT_LINUX, load
from trigger.group_admission import catalog
from trigger.reply_io import advance

config = load(data['installation'])
if not config['wechat']['operations_enabled']:
    raise ValueError('WeChat operations are disabled')
snapshot = catalog(data['installation'], data['binding'])
if snapshot['account'] != data['account']:
    raise ValueError('Native account changed')
sys.path.insert(0, str(WECHAT_LINUX))
from operations.cli import load_config
from operations.driver import Policy

root = Path(config['wechat']['runtime_root']) / 'operations-state'
policy = load_config(root / 'config.json')
if policy['account'] != data['account'] or not (root / 'queue.sqlite').is_file():
    raise ValueError('Native operations binding changed')

def job_for(group, index, text):
    key = '\0'.join((data['account'], group['peer'], data['day'], str(index)))
    return {'client': 'rsi-group', 'request_id': 'astro-news-' + hashlib.sha256(key.encode()).hexdigest(),
            'peer': group['peer'], 'action': 'send_text', 'execution_mode': 'verified_fast',
            'payload': {'text': text}}

def cover_job(group, asset):
    key = '\0'.join((data['account'], group['peer'], data['day'], 'cover'))
    return {'client': 'rsi-group', 'request_id': 'astro-news-' + hashlib.sha256(key.encode()).hexdigest(),
            'peer': group['peer'], 'action': 'send_image', 'execution_mode': 'verified_fast',
            'payload': {'asset': asset}}

for group in data['groups']:
    matches = [g for g in snapshot['groups'] if g['name'] == group['name']]
    if len(matches) != 1:
        raise ValueError('Group name is missing or ambiguous')
    native = matches[0]
    if (native['peer'] != group['peer'] or not all(native[k] for k in
            ('self_present', 'owner_present', 'addressable'))):
        raise ValueError('Native recipient changed')
    Policy(policy).check(job_for(group, 1, 'scope check'))

if data['mode'] == 'check':
    print(json.dumps({'state': 'ready', 'groups': [g['name'] for g in data['groups']]}))
    sys.exit(0)

from operations.public_api import PublicAPI
api = PublicAPI(root, policy)
receipts = []
try:
    cover = data.get('cover')
    asset = None
    if cover:
        raw = base64.b64decode(cover['data'], validate=True)
        if hashlib.sha256(raw).hexdigest() != cover['sha256'] or len(raw) != cover['bytes']:
            raise ValueError('Cover bytes differ from the frozen digest')
        if data['mode'] == 'send':
            asset = api.call({'op': 'upload', 'client': 'rsi-group', 'name': cover['name'],
                              'sha256': cover['sha256'], 'data': cover['data']})['id']
        else:
            from operations.assets import descriptor
            asset = descriptor('rsi-group', cover['name'], cover['bytes'], cover['sha256'])
    for group in data['groups']:
        items = [(index, job_for(group, index, text), text) for index, text in enumerate(data['parts'], 1)]
        if cover:
            items.insert(0, (0, cover_job(group, asset), None))
        for index, job, text in items:
            identity = {k: job[k] for k in ('client', 'request_id')}
            try:
                original = api.s.get(identity['client'], identity['request_id'])
            except KeyError:
                if data['mode'] == 'status':
                    original = None
                else:
                    api.call({'op': 'submit', 'job': job})
                    original = api.s.get(identity['client'], identity['request_id'])
            receipt = {'group': group['name'], 'part': index, 'state': 'not_submitted'}
            receipts.append(receipt)
            if original is None:
                continue
            if any(original[k] != job[k] for k in ('peer', 'action', 'payload')):
                raise ValueError('Original native job differs from the frozen digest')
            if data['mode'] == 'send' and (original['state'] in ('queued', 'confirmed') or
                    (original['state'] == 'awaiting_confirmation'
                     and not (original.get('preview') or {}).get('reviewRequired'))):
                try:
                    advance(api, original, policy)
                except BlockingIOError:
                    pass  # Another request owns the display; read the original below.
            row = api.call({'op': 'get', **identity, 'wait_seconds': 0})
            proof = row.get('result') or {}
            if text is None:
                # One unique new native image after the single click, bound to the frozen bytes.
                actual = None
                accepted = (row['state'] == 'succeeded' and proof.get('state') == 'accepted'
                            and row['peer'] == group['peer'] and row['action'] == 'send_image'
                            and proof.get('sendClicks') == 1 and bool(proof.get('serverId'))
                            and proof.get('payloadSha256') == cover['sha256'])
            else:
                compare = proof.get('textComparison') or {}
                actual = compare.get('actualText')
                sha = hashlib.sha256(text.encode()).hexdigest()
                accepted = (row['state'] == 'succeeded' and proof.get('state') == 'accepted'
                            and row['peer'] == group['peer'] and row['action'] == 'send_text'
                            and proof.get('nativeStatus') == 2 and proof.get('sendClicks') == 1
                            and compare.get('expectedSHA256') == sha
                            and (actual == text or (text.endswith('\n') and actual == text[:-1]
                                 and compare.get('mode') == 'single_terminal_lf_removed')))
            receipt.update(state='sent' if accepted else row['outcome']['status'],
                           code=proof.get('code'), native_state=row['state'])
            if accepted and text is None:
                receipt.update(sha256=cover['sha256'], server_id=proof['serverId'])
            elif accepted:
                receipt['text'] = actual
            elif receipt['state'] == 'sent':
                receipt['state'] = 'unknown'
            cleanup = any(proof.get(k) for k in ('navigationRecoveryPending',
                          'draftRecoveryPending', 'postActionPending'))
            if cleanup:
                receipt['cleanup_pending'] = True
            if data['mode'] == 'send' and (not accepted or cleanup):
                print(json.dumps({'state': 'check_original', 'receipts': receipts}))
                sys.exit(0)
    state = 'sent' if receipts and all(r['state'] == 'sent' for r in receipts) else 'unsettled'
    print(json.dumps({'state': state, 'receipts': receipts}))
finally:
    api.close()
"""


def window(day):
    """The evening batch covers items discovered in the 24 hours before 20:30 Beijing time."""
    end = datetime.combine(day, time(20, 30), tzinfo=BEIJING)
    return end - timedelta(days=1), end


def feed_items(load, start, end):
    params = {"mode": "all", "window": "7d", "by": "timeline", "limit": 50}
    found, cursors = {}, set()
    for _ in range(20):
        page = load(params.copy())
        for item in page["items"]:
            discovered = datetime.fromisoformat(item["discoveredAt"].replace("Z", "+00:00"))
            link = item["links"]["original"]
            if start <= discovered < end and urlsplit(link).scheme in ("https", "http"):
                found.setdefault(link, (discovered, item))
        if not page["page"]["hasMore"]:
            return [item for _, item in sorted(found.values(), key=lambda pair: pair[0])]
        cursor = page["page"]["nextCursor"]
        if not cursor or cursor in cursors:
            break
        cursors.add(cursor)
        params["cursor"] = cursor
    raise ValueError("The full feed could not be verified")


def fetch(params):
    request = Request(FEED + "?" + urlencode(params), headers={"Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def render(items, day):
    """One bubble per item, keeping title, source, date, optional lead and link together."""
    parts, seen = [], set()
    for item in items:
        title = " ".join(item["title"].split())
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        source = item["source"]["name"].split(" · ", 1)[0].split("（", 1)[0].strip()
        stamp = item.get("publishedAt")
        published = (datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(BEIJING)
                     .strftime("%m-%d") if stamp else None)
        attribution = f"{source}｜{published}" if published else source
        link = item["links"]["original"]
        summary = " ".join((item.get("summary") or "").split())
        full = f"{title}\n{attribution}\n{summary}\n{link}"
        parts.append(full if summary and len(split_text(full)) == 1 else f"{title}\n{attribution}\n{link}")
    if parts:
        parts[0] = f"天文科技晚报｜{day.month} 月 {day.day} 日（{len(parts)} 条）\n\n{parts[0]}"
    if any(len(part.encode("utf-8")) > 6000 for part in parts):
        raise ValueError("A source entry exceeds the native text limit")
    return parts


def cover_asset(path, state, day):
    """Freeze one static PNG or JPEG overview image beside the day's draft."""
    from PIL import Image
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= COVER_BYTES:
        raise ValueError("The cover image must be 1 byte to 10 MB")
    with Image.open(io.BytesIO(raw)) as image:
        kind = image.format
        if kind not in ("PNG", "JPEG") or getattr(image, "n_frames", 1) != 1:
            raise ValueError("A static PNG or JPEG cover is required")
        image.verify()
    name = f"evening-{day}-cover." + ("png" if kind == "PNG" else "jpg")
    target = state / name
    if target.exists() and target.read_bytes() != raw:
        raise ValueError("A different cover is already frozen for this day")
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(raw)
        temporary.replace(target)
    return {"name": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def frozen_cover(state, cover):
    raw = (state / cover["name"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != cover["sha256"] or len(raw) != cover["bytes"]:
        raise ValueError("The frozen cover image changed")
    return dict(cover, data=base64.b64encode(raw).decode())


def remote(settings, mode, key, parts, cover=None):
    operator = json.loads(Path(settings["operator"]).read_text(encoding="utf-8-sig"))
    ssh, host = operator["ssh"], operator["remote"]
    data = {"release": host["current"], "python_path": host["python_path"],
            "installation": host["private_config"], "binding": host["owner_binding"],
            "account": settings["account"], "groups": settings["groups"],
            "mode": mode, "day": key, "parts": parts, "cover": cover}
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=8", "-i", ssh["identity_file"], ssh["user"] + "@" + ssh["host"],
               shlex.join(["runuser", "-u", "wechat-gui", "--", "/usr/bin/python3", "-B", "-c", REMOTE])]
    # Each native send takes about ten seconds; wait for the whole ordered batch.
    timeout = 60 + 20 * (len(parts) + bool(cover)) * len(settings["groups"])
    result = subprocess.run(command, input=json.dumps(data).encode(), capture_output=True, timeout=timeout)
    if result.returncode:
        raise OSError("Native group operation did not return a receipt")
    return json.loads(result.stdout)


def run(settings, state, mode, day, now, cover_path=None):
    key = f"{day}-evening"
    if mode == "check":
        return remote(settings, "check", key, [])
    draft = state / f"evening-{day}-dispatch.json"
    if mode == "status" and not draft.exists():
        return {"state": "not_submitted", "day": day.isoformat()}
    start, end = window(day)
    if mode == "run" and now < end:
        return {"state": "not_due", "day": day.isoformat()}
    batch = (json.loads(draft.read_bytes()) if draft.exists()
             else {"day": key, "parts": render(feed_items(fetch, start, end), day)})
    if batch["day"] != key:
        raise ValueError("The frozen batch key differs")
    if cover_path is not None:
        if mode != "run":
            raise ValueError("A cover is frozen only by run")
        cover = cover_asset(cover_path, state, day)
        if draft.exists() and batch.get("cover") != cover:
            raise ValueError("The day's draft is already frozen with a different cover")
        batch["cover"] = cover
    parts = batch["parts"]
    if mode == "preview":
        return {"state": "preview", "day": day.isoformat(), "parts": parts}
    if mode == "run":
        save_once(draft, batch)
    if not parts:
        return {"state": "no_news", "day": day.isoformat()}
    cover = frozen_cover(state, batch["cover"]) if batch.get("cover") else None
    current = remote(settings, "status", key, parts, cover)
    if mode == "run" and any(row["state"] == "not_submitted" for row in current["receipts"]):
        if all(row["state"] in ("sent", "not_submitted") and not row.get("cleanup_pending")
               for row in current["receipts"]):
            remote(settings, "send", key, parts, cover)
            current = remote(settings, "status", key, parts, cover)
    names = [group["name"] for group in settings["groups"]]
    expected = {(name, index) for name in names for index in range(0 if cover else 1, len(parts) + 1)}
    proven = {(row["group"], row["part"]) for row in current["receipts"]
              if row["state"] == "sent" and not row.get("cleanup_pending")
              and (row.get("sha256") == cover["sha256"] if row["part"] == 0 and cover
                   else row["part"] > 0 and row.get("text") == parts[row["part"] - 1])}
    current["state"] = ("sent" if proven == expected and len(current["receipts"]) == len(expected)
                        else "unsettled")
    current["day"] = day.isoformat()
    receipt = state / f"evening-{day}-receipts.json"
    temporary = receipt.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(receipt)
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "preview", "status", "run"))
    parser.add_argument("config", type=Path)
    parser.add_argument("--state", type=Path, help="Directory for frozen drafts and receipts; defaults to the config directory")
    parser.add_argument("--day", type=date.fromisoformat, help="Beijing date of the batch")
    parser.add_argument("--cover", type=Path, help="Static PNG/JPEG top overview, frozen and sent before the text items")
    args = parser.parse_args()
    settings = json.loads(args.config.read_bytes())
    if not settings["groups"] or len({group["peer"] for group in settings["groups"]}) != len(settings["groups"]):
        parser.error("Distinct private group bindings required")
    now = datetime.now(BEIJING)
    result = run(settings, args.state or args.config.parent, args.mode, args.day or now.date(), now, args.cover)
    print(json.dumps(result, ensure_ascii=True))
    return 2 if result["state"] == "unsettled" else 0


if __name__ == "__main__":
    raise SystemExit(main())
