"""Read only three authorized Cockpit account statuses. No network, migration or credential writes."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, base64, copy, datetime, json, os, re, stat, time
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from account_contract import EMAILS, validate_accounts
ROOT = _install.path('monitor.model_accounts.ROOT')
AUTH = _install.path('monitor.model_accounts.AUTH')
STALE_SECONDS = 1200

class ReadError(Exception):
    pass

def stamp(t):
    if type(t) not in [int, float] or not 946684800 <= t < 4102444800:
        return None
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat()

def read_bytes(root, relative, private=False, limit=1000000):
    parts = Path(relative).parts
    if not parts or any((p in ['', '..', '.'] for p in parts)) or Path(relative).is_absolute():
        raise ReadError('unsafe_file')
    for p in [Path(root)] + list(Path(root).parents):
        if p.is_symlink():
            raise ReadError('unsafe_file')
    fds = []
    try:
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds.append(parent)
        for part in parts[:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            fds.append(parent)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        fds.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_size > limit or before.st_mode & 18 or (private and before.st_mode & 63):
            raise ReadError('unsafe_file')
        b = os.read(fd, limit + 1)
        after = os.fstat(fd)
        if len(b) > limit or len(b) != before.st_size or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ReadError('source_unavailable')
        return b
    except ReadError:
        raise
    except FileNotFoundError:
        raise ReadError('account_missing') from None
    except OSError:
        raise ReadError('unsafe_file') from None
    finally:
        for fd in reversed(fds):
            os.close(fd)

def decode_json(raw):

    def pairs(xs):
        d = {}
        for (k, v) in xs:
            if k in d:
                raise ReadError('invalid_json')
            d[k] = v
        return d
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except ReadError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise ReadError('invalid_json') from None

def payload(root, ident, key):
    e = decode_json(read_bytes(root, 'codex_accounts/' + ident + '.json'))
    if not isinstance(e, dict) or type(e.get('version')) is not int or e.get('version') != 1 or (e.get('kind') != 'codex') or (e.get('algorithm') != 'AES-256-GCM') or (e.get('key_id') != 'local-secure-account-storage-v1'):
        raise ReadError('account_unreadable')
    try:
        nonce = base64.b64decode(e['nonce'], validate=True)
        cipher = base64.b64decode(e['ciphertext'], validate=True)
        if len(nonce) != 12:
            raise ValueError()
        d = decode_json(AESGCM(key).decrypt(nonce, cipher, None))
        if not isinstance(d, dict):
            raise ValueError()
        return (d, stamp(e.get('encrypted_at')))
    except Exception:
        raise ReadError('account_unreadable') from None

def projection(d, ident, email, record_at, now):
    if d.get('id') != ident or d.get('email') != email:
        raise ReadError('account_unreadable')
    updated = d.get('usage_updated_at')
    source_at = stamp(updated)
    if source_at and updated > now + 300:
        raise ReadError('account_unreadable')
    requires = d.get('requires_reauth') is True
    status = d.get('authorization_status')
    q = d.get('quota')
    error = d.get('quota_error')
    pending = status in ['pending', 'pending_oauth', 'pending_authorization']
    auth = 'reauthorize' if requires else 'pending' if pending else 'unknown' if error or not source_at else 'valid'
    windows = []
    if isinstance(q, dict):
        for (key, wid) in [('hourly', 'primary'), ('weekly', 'secondary')]:
            present = q.get(key + '_window_present')
            reset = q.get(key + '_reset_time')
            duration = q.get(key + '_window_minutes')
            if present is False or (present is not True and reset is None and (duration is None)):
                continue
            percentage = q.get(key + '_percentage')
            if type(percentage) is not int or not 0 <= percentage <= 100:
                raise ReadError('account_unreadable')
            if duration is not None and (type(duration) is not int or not 1 <= duration <= 527040):
                raise ReadError('account_unreadable')
            reset_at = stamp(reset)
            windows.append({'id': wid, 'remainingPercent': percentage, 'durationMinutes': duration, 'resetAt': reset_at, 'resetPassed': bool(reset_at and reset <= now)})
    plan = (d.get('plan_type') or 'unknown').lower()
    plan = plan if plan in ['pro', 'plus', 'free', 'team', 'business', 'enterprise', 'edu'] else 'unknown'
    subscription = None
    try:
        dt = datetime.datetime.fromisoformat(d.get('subscription_active_until', '').replace('Z', '+00:00'))
        if dt.tzinfo and 2000 <= dt.year <= 2100:
            subscription = dt.astimezone(datetime.timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        pass
    return {'id': ident, 'email': email, 'plan': plan, 'authorization': auth, 'sourceUpdatedAt': source_at, 'recordUpdatedAt': record_at, 'subscriptionUntil': subscription, 'windows': windows, 'quotaError': 'reauthorization_required' if requires else 'quota_read_failed' if error else None, 'stale': not source_at or now - updated > STALE_SECONDS or any((w['resetPassed'] for w in windows)), 'health': {'lastSuccess': stamp(now), 'lastAttempt': stamp(now), 'error': None}}

def read_accounts(previous=None, root=ROOT, now=None, auth_path=AUTH):
    now = time.time() if now is None else now
    when = stamp(now)
    try:
        validate_accounts(previous)
    except (ValueError, TypeError):
        previous = None
    prior = {a['email']: a for a in previous['accounts']} if previous else {}
    rows = []
    key = None
    global_error = None
    identities = {}
    try:
        index = decode_json(read_bytes(root, 'codex_accounts.json', limit=2000000))
        rows = index['accounts']
        if not isinstance(rows, list) or len(rows) > 20000:
            raise ReadError('invalid_index')
        key = base64.b64decode(read_bytes(root, 'secure-account-storage.key', private=True, limit=200).strip(), validate=True)
        if len(key) != 32:
            raise ReadError('storage_key_unavailable')
    except ReadError as e:
        global_error = str(e) if str(e) in ['invalid_json', 'invalid_index', 'unsafe_file'] else 'storage_key_unavailable'
    except Exception:
        global_error = 'invalid_index'
    accounts = []
    for (i, email) in enumerate(EMAILS):
        try:
            if global_error:
                raise ReadError(global_error)
            candidates = [a for a in rows if isinstance(a, dict) and a.get('email') == email]
            if len(candidates) != 1:
                raise ReadError('invalid_index')
            ident = candidates[0].get('id')
            if not isinstance(ident, str) or not re.fullmatch('codex_[a-f0-9]{32}', ident):
                raise ReadError('invalid_account_id')
            (d, record_at) = payload(root, ident, key)
            a = projection(d, ident, email, record_at, now)
            for k in ['user_id', 'account_id']:
                if isinstance(d.get(k), str) and d[k]:
                    identities.setdefault(d[k], []).append(ident)
            del d
        except Exception as e:
            code = str(e) if isinstance(e, ReadError) else 'account_unreadable'
            a = copy.deepcopy(prior.get(email, {'id': 'account-' + str(i + 1), 'email': email, 'plan': 'unknown', 'authorization': 'unknown', 'sourceUpdatedAt': None, 'recordUpdatedAt': None, 'subscriptionUntil': None, 'windows': [], 'quotaError': None, 'stale': True, 'health': {'lastSuccess': None, 'lastAttempt': None, 'error': None}}))
            a['stale'] = True
            a['health'].update(lastAttempt=when, error=code)
        accounts.append(a)
    key = None
    desktop = {'status': 'unknown', 'accountId': None, 'scope': 'local-auth-record'}
    try:
        d = decode_json(read_bytes(Path(auth_path).parent, Path(auth_path).name, private=True))
        current = d.get('tokens', {}).get('account_id')
        matches = set(identities.get(current, []))
        del d
        if len(matches) == 1:
            desktop.update(status='matched', accountId=matches.pop())
    except Exception:
        pass
    policy = {'observeOnly': True, 'switchingEnabled': None, 'apiServiceEnabled': None, 'sourceRefreshMinutes': None}
    for (filename, mapping) in [('config.json', {'codex_auto_switch_enabled': 'switchingEnabled', 'codex_auto_refresh_minutes': 'sourceRefreshMinutes'}), ('codex_local_access.json', {'enabled': 'apiServiceEnabled'})]:
        try:
            d = decode_json(read_bytes(root, filename))
            for (source, target) in mapping.items():
                v = d.get(source)
                if target == 'sourceRefreshMinutes':
                    policy[target] = v if type(v) is int and 1 <= v <= 1440 else None
                else:
                    policy[target] = v if type(v) is bool else None
            del d
        except Exception:
            pass
    return validate_accounts({'schemaVersion': 1, 'observedAt': when, 'accounts': accounts, 'desktopLogin': desktop, 'policy': policy})
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true', help='只读本机三个指定账号，输出白名单状态')
    args = p.parse_args()
    if args.execute:
        print(json.dumps(read_accounts(), ensure_ascii=False))
    else:
        p.print_help()
