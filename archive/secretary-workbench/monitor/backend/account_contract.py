"""Strict public account-status contract; contains no credential loading."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import copy, datetime, re
EMAILS = tuple(_install.setting('monitor.account_contract', 'EMAILS', []))
ERRORS = {None, 'invalid_account_id', 'invalid_index', 'account_missing', 'account_unreadable', 'unsafe_file', 'storage_key_unavailable', 'invalid_json', 'source_unavailable'}

def iso(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('invalid account time')
    d = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is None or not 2000 <= d.year <= 2100:
        raise ValueError('invalid account time')
    return value

def exact(v, keys):
    if not isinstance(v, dict) or set(v) != set(keys.split()):
        raise ValueError('unexpected account fields')

def validate_accounts(data):
    exact(data, 'schemaVersion observedAt accounts desktopLogin policy')
    if data['schemaVersion'] != 1:
        raise ValueError('account schema unsupported')
    iso(data['observedAt'])
    if not isinstance(data['accounts'], list) or len(data['accounts']) != len(EMAILS):
        raise ValueError('account scope mismatch')
    emails = []
    ids = []
    for a in data['accounts']:
        exact(a, 'id email plan authorization sourceUpdatedAt recordUpdatedAt subscriptionUntil windows quotaError stale health')
        if not isinstance(a['id'], str) or not re.fullmatch('codex_[a-f0-9]{32}|account-[123]', a['id']):
            raise ValueError('invalid public account id')
        if a['email'] not in EMAILS:
            raise ValueError('unapproved account')
        emails.append(a['email'])
        ids.append(a['id'])
        if a['plan'] not in ['pro', 'plus', 'free', 'team', 'business', 'enterprise', 'edu', 'unknown']:
            raise ValueError('invalid plan')
        if a['authorization'] not in ['valid', 'pending', 'reauthorize', 'unknown']:
            raise ValueError('invalid authorization')
        if a['quotaError'] not in [None, 'reauthorization_required', 'quota_read_failed']:
            raise ValueError('invalid quota error')
        if type(a['stale']) is not bool:
            raise ValueError('invalid stale state')
        for k in ['sourceUpdatedAt', 'recordUpdatedAt', 'subscriptionUntil']:
            if a[k] is not None:
                iso(a[k])
        exact(a['health'], 'lastSuccess lastAttempt error')
        for k in ['lastSuccess', 'lastAttempt']:
            if a['health'][k] is not None:
                iso(a['health'][k])
        if a['health']['error'] not in ERRORS:
            raise ValueError('unsafe account error')
        if not isinstance(a['windows'], list) or len(a['windows']) > 2:
            raise ValueError('invalid windows')
        seen = []
        for w in a['windows']:
            exact(w, 'id remainingPercent durationMinutes resetAt resetPassed')
            seen.append(w['id'])
            if w['id'] not in ['primary', 'secondary']:
                raise ValueError('invalid window id')
            if type(w['remainingPercent']) is not int or not 0 <= w['remainingPercent'] <= 100:
                raise ValueError('invalid account percent')
            if w['durationMinutes'] is not None and (type(w['durationMinutes']) is not int or not 1 <= w['durationMinutes'] <= 527040):
                raise ValueError('invalid window duration')
            if w['resetAt'] is not None:
                iso(w['resetAt'])
            if type(w['resetPassed']) is not bool:
                raise ValueError('invalid reset state')
        if len(seen) != len(set(seen)):
            raise ValueError('duplicate windows')
    if set(emails) != set(EMAILS) or len(ids) != len(set(ids)):
        raise ValueError('duplicate accounts')
    exact(data['desktopLogin'], 'status accountId scope')
    d = data['desktopLogin']
    if d['status'] not in ['matched', 'unknown'] or d['scope'] != 'local-auth-record' or (d['accountId'] is not None and d['accountId'] not in ids):
        raise ValueError('invalid desktop mapping')
    if (d['status'] == 'matched') != (d['accountId'] is not None):
        raise ValueError('inconsistent desktop mapping')
    exact(data['policy'], 'observeOnly switchingEnabled apiServiceEnabled sourceRefreshMinutes')
    p = data['policy']
    if p['observeOnly'] is not True:
        raise ValueError('account monitor must be read-only')
    for k in ['switchingEnabled', 'apiServiceEnabled']:
        if p[k] is not None and type(p[k]) is not bool:
            raise ValueError('invalid account policy')
    if p['sourceRefreshMinutes'] is not None and (type(p['sourceRefreshMinutes']) is not int or not 1 <= p['sourceRefreshMinutes'] <= 1440):
        raise ValueError('invalid refresh interval')
    return data

def unavailable_accounts(previous, when):
    try:
        validate_accounts(previous)
    except (ValueError, TypeError):
        previous = None
    accounts = []
    for (i, email) in enumerate(EMAILS):
        old = next((a for a in previous['accounts'] if a['email'] == email), None) if previous else None
        a = copy.deepcopy(old) if old else {'id': 'account-' + str(i + 1), 'email': email, 'plan': 'unknown', 'authorization': 'unknown', 'sourceUpdatedAt': None, 'recordUpdatedAt': None, 'subscriptionUntil': None, 'windows': [], 'quotaError': None, 'stale': True, 'health': {'lastSuccess': None, 'lastAttempt': None, 'error': None}}
        a['stale'] = True
        a['health'].update(lastAttempt=when, error='source_unavailable')
        accounts.append(a)
    return validate_accounts({'schemaVersion': 1, 'observedAt': when, 'accounts': accounts, 'desktopLogin': {'status': 'unknown', 'accountId': None, 'scope': 'local-auth-record'}, 'policy': {'observeOnly': True, 'switchingEnabled': None, 'apiServiceEnabled': None, 'sourceRefreshMinutes': None}})
