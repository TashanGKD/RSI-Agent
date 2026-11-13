"""Publish the public astronomy feed to two privately bound WeChat groups."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
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

REMOTE = r"""
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
    for group in data['groups']:
        for index, text in enumerate(data['parts'], 1):
            job = job_for(group, index, text)
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
            if accepted:
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


def cutoff():
    return datetime.now(BEIJING).replace(hour=10, minute=0, second=0, microsecond=0)


def feed_items(load, end):
    params = {"mode": "all", "window": "7d", "by": "timeline", "limit": 50}
    start = end - timedelta(days=1)
    seen = set()
    for _ in range(20):
        page = load(params.copy())
        for item in page["items"]:
            discovered = datetime.fromisoformat(item["discoveredAt"].replace("Z", "+00:00"))
            if start <= discovered < end:
                yield item
        cursor = page["page"]["nextCursor"]
        if not page["page"]["hasMore"]:
            return
        if not cursor or cursor in seen:
            raise ValueError("Invalid feed pagination")
        seen.add(cursor)
        params["cursor"] = cursor
    raise ValueError("Feed pagination did not complete")


def fetch(params):
    request = Request(FEED + "?" + urlencode(params), headers={"Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def render(items, day):
    parts, urls, titles = [], set(), set()
    for item in items:
        url = item["links"]["original"]
        title = " ".join(item["title"].split())
        title_key = re.sub(r"\W", "", title.casefold())
        if (urlsplit(url).scheme not in ("https", "http") or not urlsplit(url).hostname
                or not title_key or url in urls or title_key in titles):
            continue
        if len(parts) >= 4:
            break
        source = item["source"]["name"].split(" · ", 1)[0].strip()
        timestamp = item.get("publishedAt")
        published = (datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(BEIJING)
                     .strftime("%m-%d") if timestamp else "日期未标注")
        header = f"天文科技早报｜{day}" if not parts else "天文科技早报"
        body = f"{header}\n{title}\n{source}｜{published}"
        summary = " ".join((item.get("summary") or "").split())
        sentence = re.match(r".+?[。！？](?:[”’」』])?|.+$", summary)
        if sentence:
            candidate = f"{body}\n{sentence.group()}\n{url}"
            if len(split_text(candidate)) == 1:
                body += "\n" + sentence.group()
        bubbles = split_text(f"{body}\n{url}")
        if len(bubbles) != 1:
            continue
        urls.add(url)
        titles.add(title_key)
        parts.extend(bubbles)
    return parts


def remote(settings, mode, day, parts):
    operator = json.loads(Path(settings["operator"]).read_text(encoding="utf-8-sig"))
    ssh, host = operator["ssh"], operator["remote"]
    data = {"release": settings.get("release", host["current"]), "python_path": host["python_path"],
            "installation": host["private_config"], "binding": host["owner_binding"],
            "account": settings["account"], "groups": settings["groups"],
            "mode": mode, "day": day, "parts": parts}
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=8", "-i", ssh["identity_file"], ssh["user"] + "@" + ssh["host"],
               shlex.join(["runuser", "-u", "wechat-gui", "--", "/usr/bin/python3", "-B", "-c", REMOTE])]
    result = subprocess.run(command, input=json.dumps(data).encode(), capture_output=True, timeout=175)
    if result.returncode:
        raise OSError("Native group operation did not return a receipt")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "preview", "send", "status"))
    parser.add_argument("config", type=Path)
    parser.add_argument("--day", help="Read the original receipt for this Beijing date")
    args = parser.parse_args()
    settings = json.loads(args.config.read_bytes())
    groups = settings["groups"]
    if len(groups) != 2 or len({g["peer"] for g in groups}) != 2:
        parser.error("Two distinct private group bindings required")

    end = cutoff()
    day = end.date().isoformat()
    if args.day:
        if args.mode != "status":
            parser.error("--day is only available for status")
        day = datetime.strptime(args.day, "%Y-%m-%d").date().isoformat()
    path = args.config.parent / ("astro-news-" + day + ".json")
    if args.mode == "check":
        result = remote(settings, "check", day, [])
    elif args.mode == "preview":
        result = {"state": "preview", "day": day, "parts": render(feed_items(fetch, end), day)}
    elif args.mode == "send" and datetime.now(BEIJING) < end:
        result = {"state": "not_due", "day": day}
    else:
        if args.mode == "send" and not path.exists():
            parts = render(feed_items(fetch, end), day)
            try:
                save_once(path, {"day": day, "parts": parts})
            except ValueError:
                if not path.is_file():
                    raise
        parts = json.loads(path.read_bytes())["parts"] if path.exists() else []
        result = (remote(settings, args.mode, day, parts) if parts
                  else {"state": "no_news" if path.exists() else "not_submitted", "day": day})
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["state"] in ("ready", "preview", "sent", "not_due", "no_news") else 2


if __name__ == "__main__":
    raise SystemExit(main())
