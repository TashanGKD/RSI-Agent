"""Small public whitelist for the observer's work/sending projection."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import json, re, math

def source_refs(value):
    refs = set()

    def walk(v):
        if isinstance(v, dict):
            for (k, x) in v.items():
                if k == 'evidenceRefs' and isinstance(x, list):
                    refs.update((v for v in x if isinstance(v, str)))
                elif k in ['sourceId', 'proofSourceId', 'eventSourceId'] and isinstance(x, str):
                    refs.add(x)
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(value)
    return refs

def validate_work(work, sources):
    if work is None:
        return
    if set(work) - {'version', 'sampledAt', 'readOnly', 'employees', 'items', 'sending', 'modes', 'discovery', 'error', 'observation', 'deliveryHealth', 'deliveryObligations'}:
        raise ValueError('unknown work envelope field')
    if work.get('readOnly') is not True or work.get('version') != 1:
        raise ValueError('not a read-only work projection')
    people = work.get('employees', [])
    items = work.get('items', [])
    sending = work.get('sending', {}).get('items', [])
    if len(people) > 100 or len(items) > 4000 or len(sending) > 1000:
        raise ValueError('work projection too large')
    if len({p['id'] for p in people}) != len(people) or len({x['id'] for x in items}) != len(items):
        raise ValueError('duplicate employee or item')
    for x in items + sending:
        for k in ['sourceId', 'proofSourceId']:
            if x.get(k) and x[k] not in sources:
                raise ValueError('missing work source')
        for e in x.get('evidence', []):
            if e['id'] not in sources or e['quote'] not in sources[e['id']]['text']:
                raise ValueError('unsupported work quote')
    modes = work.get('modes', {})
    if modes.get('sourceId') not in sources:
        raise ValueError('missing work-mode source')
    refs = [p['modeNotes']['sourceId'] for p in people if p.get('modeNotes')]
    obs = work.get('observation', {})
    refs += [obs['eventSourceId']] if obs.get('eventSourceId') else []
    refs += [r['sourceId'] for r in obs.get('reviews', [])]
    if any((s not in sources for s in refs)):
        raise ValueError('missing system/role source')
    if any((s not in sources for s in source_refs(work))):
        raise ValueError('missing operation source')
    validate_delivery_health(work.get('deliveryHealth'), sources)
    if 'deliveryObligations' in work:
        from delivery_obligations import validate
        validate(work['deliveryObligations'], {p['id']: p['threadId'] for p in people}, sources)
    body = json.dumps(work, ensure_ascii=False)
    if re.search('eyJ[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{8,}\\.|sk-[A-Za-z0-9_-]{16,}|(?i:access_token|refresh_token|password)\\s*[=:]', body):
        raise ValueError('credential in public work projection')

def validate_delivery_health(h, sources):
    if h is None:
        return
    if set(h) != {'version', 'observedAt', 'incidents', 'coverage'} or h['version'] != 1 or type(h['observedAt']) not in (int, float) or (not math.isfinite(h['observedAt'])) or (h['observedAt'] <= 0):
        raise ValueError('invalid delivery envelope')
    if not isinstance(h['coverage'], dict) or h['coverage'].get('bounded') is not True or (not isinstance(h['coverage'].get('gaps'), list)):
        raise ValueError('invalid delivery coverage')
    if not isinstance(h['incidents'], list) or len(h['incidents']) > 1000:
        raise ValueError('delivery count cap')
    required = {'id', 'businessId', 'employee', 'businessTitle', 'ownerThreadId', 'status', 'updatedAt', 'requestIds', 'client', 'reasonCode', 'recoveryOwnerThreadId', 'nativeReceiptVerified', 'evidenceRefs'}
    uuid = '[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'
    ids = set()
    for i in h['incidents']:
        if set(i) != required or i['id'] in ids:
            raise ValueError('invalid delivery fields or duplicate')
        ids.add(i['id'])
        if not re.fullmatch(uuid, i['ownerThreadId']) or (i['recoveryOwnerThreadId'] is not None and (not re.fullmatch(uuid, i['recoveryOwnerThreadId']))):
            raise ValueError('delivery owner UUID')
        if i['status'] not in ['blocked', 'unknown', 'pending', 'resolved', 'not_required'] or type(i['nativeReceiptVerified']) is not bool or (i['nativeReceiptVerified'] and i['status'] != 'resolved'):
            raise ValueError('invalid delivery conclusion')
        if i['status'] == 'resolved' and (not i['nativeReceiptVerified']):
            raise ValueError('resolved without native proof')
        if type(i['updatedAt']) not in (int, float) or not 0 < i['updatedAt'] <= h['observedAt'] + 60:
            raise ValueError('delivery evidence time')
        if not isinstance(i['requestIds'], list) or not 1 <= len(i['requestIds']) <= 20 or any((not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,95}', r) for r in i['requestIds'])):
            raise ValueError('delivery request ID bounds')
        if not isinstance(i['evidenceRefs'], list) or not 1 <= len(i['evidenceRefs']) <= 22 or any((r not in sources for r in i['evidenceRefs'])):
            raise ValueError('missing delivery evidence')
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}', i['reasonCode']):
            raise ValueError('unsafe reason code')
        if len(i['businessTitle']) > 160 or re.search('(?i)password|口令|密码|验证码|token|api.?key|authorization|/Users/', i['businessTitle']):
            raise ValueError('sensitive delivery title')
