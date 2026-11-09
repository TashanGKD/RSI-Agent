"""Nonce-only MCP Events endpoint; never reads WeChat or runs host commands.

The private configuration contains bind, port, capability and database paths.
Connect /<capability>/mcp as a custom MCP server, then subscribe from a Dot.
Only the operator's `emit` command creates a fixture; no public emit tool exists.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import hmac
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import ssl
import time
from urllib.parse import urlsplit


EVENT = 'rsi.trigger_probe'
ARGUMENTS = {'experiment': 'dot-nonce-v1'}
EVENT_SCHEMA = {'name': EVENT, 'description':
    'An operator-created arithmetic fixture. No WeChat data or execution authority.',
    'delivery': ['webhook'], 'inputSchema': {'type': 'object', 'properties': {
        'experiment': {'type': 'string', 'enum': ['dot-nonce-v1']}},
        'required': ['experiment'], 'additionalProperties': False},
    'payloadSchema': {'type': 'object', 'properties': {
        'probe_id': {'type': 'string'}, 'a': {'type': 'integer'}, 'b': {'type': 'integer'}},
        'required': ['probe_id', 'a', 'b'], 'additionalProperties': False}}
TOOL = {'name': 'complete_trigger_probe', 'description':
    'Record a subscribed arithmetic fixture result: answer = a * b. '
    'Writes only this experiment receipt; does not send a WeChat message.',
    'inputSchema': {'type': 'object', 'properties': {
        'probe_id': {'type': 'string'}, 'answer': {'type': 'integer'}},
        'required': ['probe_id', 'answer'], 'additionalProperties': False},
    'annotations': {'readOnlyHint': False, 'destructiveHint': False,
                    'idempotentHint': True, 'openWorldHint': False}}


class CallbackError(ValueError):
    pass


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def callback(url, secret, identity, value, subscription_id):
    """Signed, verified HTTPS to a pinned public IP; never follows redirects."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.port not in (None, 443) \
            or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('callback must be a public HTTPS URL on port 443')
    addresses = list({item[4][0] for item in socket.getaddrinfo(
        parsed.hostname, 443, type=socket.SOCK_STREAM)})
    if not addresses or not all(ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('non-public callback address refused')
    if not secret.startswith('whsec_'):
        raise ValueError('invalid webhook signing secret')
    key = base64.b64decode(secret[6:], validate=True)
    if not 24 <= len(key) <= 64:
        raise ValueError('invalid webhook signing secret length')
    body = json.dumps(value, separators=(',', ':')).encode()
    signed_at = str(int(time.time()))
    signature = base64.b64encode(hmac.digest(
        key, identity.encode() + b'.' + signed_at.encode() + b'.' + body, 'sha256')).decode()
    connection = HTTPSConnection(parsed.hostname, timeout=10)
    raw_socket = socket.create_connection((addresses[0], 443), timeout=10)
    try:
        connection.sock = ssl.create_default_context().wrap_socket(
            raw_socket, server_hostname=parsed.hostname)
        connection.request('POST', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''),
            body, headers={'Content-Type': 'application/json', 'webhook-id': identity,
                'webhook-timestamp': signed_at, 'webhook-signature': 'v1,' + signature,
                'X-MCP-Subscription-Id': subscription_id})
        response = connection.getresponse()
        data = response.read(262145)
        if not 200 <= response.status < 300 or len(data) > 262144:
            raise ValueError('callback rejected or response too large')
        return json.loads(data) if data else {}
    finally:
        connection.close()
        raw_socket.close()


class Probe:
    def __init__(self, config):
        self.config = config
        path = Path(config['database'])
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        path.chmod(0o600)
        self.db.execute('CREATE TABLE IF NOT EXISTS subscriptions (id TEXT PRIMARY KEY, data TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS probes '
                        '(id TEXT PRIMARY KEY, event TEXT, state TEXT, reply TEXT)')
        self.db.commit()

    def rpc(self, method, params):
        if method == 'initialize':
            return {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}, 'events': {}},
                    'serverInfo': {'name': 'rsi-trigger-lab', 'version': '0.1.0'}}
        if method == 'ping':
            return {}
        if method == 'tools/list':
            return {'tools': [TOOL]}
        if method == 'events/list':
            return {'events': [EVENT_SCHEMA]}
        if method == 'events/subscribe':
            if params.get('name') != EVENT or params.get('arguments') != ARGUMENTS:
                raise ValueError('only the dot-nonce-v1 fixture can be subscribed')
            delivery = params['delivery']
            if delivery.get('mode') != 'webhook':
                raise ValueError('webhook delivery required')
            ttl = params.get('ttlMs', 3600000)
            if ttl is None:
                ttl = 3600000
            if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0:
                raise ValueError('positive ttlMs required')
            identity = hashlib.sha256((self.config['capability'] + delivery['url'] +
                EVENT + json.dumps(ARGUMENTS, sort_keys=True)).encode()).hexdigest()
            old = self.db.execute('SELECT data FROM subscriptions WHERE id=?', (identity,)).fetchone()
            previous = json.loads(old[0]) if old else {}
            verified_until = previous.get('verified_until', 0)
            if previous.get('verified_until', 0) <= time.time() or previous.get('secret') != delivery['secret']:
                challenge = secrets.token_hex(24)
                try:
                    verification = callback(delivery['url'], delivery['secret'],
                        'verify_' + secrets.token_hex(16),
                        {'type': 'verification', 'challenge': challenge}, identity)
                except (ValueError, OSError) as error:
                    raise CallbackError('callback verification failed') from error
                if not hmac.compare_digest(str(verification.get('challenge', '')), challenge):
                    raise CallbackError('callback challenge failed')
                verified_until = time.time() + 600
            expires = time.time() + min(ttl / 1000, 3600)
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO subscriptions VALUES (?,?)',
                    (identity, json.dumps(dict(delivery, expires=expires, verified_until=verified_until))))
            return {'id': identity, 'refreshBefore': timestamp(expires),
                    'cursor': None, 'truncated': False}
        if method == 'events/unsubscribe':
            if params.get('name') != EVENT or params.get('arguments') != ARGUMENTS:
                raise ValueError('unknown event or arguments')
            identity = hashlib.sha256((self.config['capability'] + params['delivery']['url'] +
                EVENT + json.dumps(ARGUMENTS, sort_keys=True)).encode()).hexdigest()
            with self.db:
                self.db.execute('DELETE FROM subscriptions WHERE id=?', (identity,))
            return {}
        if method == 'tools/call' and params.get('name') == TOOL['name']:
            args = params['arguments']
            if set(args) != {'probe_id', 'answer'} or type(args['answer']) is not int:
                raise ValueError('probe_id and integer answer required')
            row = self.db.execute('SELECT event,state,reply FROM probes WHERE id=?',
                                  (args['probe_id'],)).fetchone()
            if row is None:
                raise ValueError('unknown fixture; never create one from a tool call')
            data = json.loads(row[0])['data']
            if args['answer'] != data['a'] * data['b']:
                raise ValueError('incorrect fixture answer')
            reply = row[2] or json.dumps({'accepted': True, 'probe_id': args['probe_id'],
                                         'completed_at': timestamp(time.time())})
            with self.db:
                self.db.execute("UPDATE probes SET state='completed',reply=? WHERE id=?",
                                (reply, args['probe_id']))
            return {'content': [{'type': 'text', 'text': reply}], 'structuredContent': json.loads(reply)}
        raise ValueError('unsupported method')

    def emit(self):
        subscriptions = [(identity, json.loads(data)) for identity, data in
                         self.db.execute('SELECT id,data FROM subscriptions')
                         if json.loads(data)['expires'] > time.time()]
        if len(subscriptions) != 1:
            raise ValueError('exactly one active real subscription required before emit')
        identity, delivery = subscriptions[0]
        row = self.db.execute("SELECT id,event FROM probes WHERE state!='completed'").fetchone()
        if row:
            event = json.loads(row[1])
        else:
            probe_id = 'probe_' + secrets.token_hex(16)
            event = {'eventId': probe_id, 'name': EVENT, 'timestamp': timestamp(time.time()),
                     'data': {'probe_id': probe_id, 'a': secrets.randbelow(900) + 100,
                              'b': secrets.randbelow(900) + 100}, 'cursor': None}
            with self.db:
                self.db.execute('INSERT INTO probes VALUES (?,?,?,NULL)',
                                (probe_id, json.dumps(event), 'pending'))
        callback(delivery['url'], delivery['secret'], event['eventId'], event, identity)
        with self.db:
            self.db.execute("UPDATE probes SET state='webhook_accepted' "
                            "WHERE id=? AND state='pending'", (event['eventId'],))
        return {'event_id': event['eventId'], 'webhook_accepted': True,
                'dot_completed': False, 'wechat_transport': False}


def serve(config):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Capability URL and webhook secrets do not enter access logs.

        def do_GET(self):
            self.send_error(405)

        def do_POST(self):
            if not secrets.compare_digest(self.path, '/' + config['capability'] + '/mcp'):
                self.send_error(404)
                return
            if self.headers.get('Origin', 'https://chatgpt.com') != 'https://chatgpt.com':
                self.send_error(403)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise ValueError('invalid request size')
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError('object required')
                if request.get('jsonrpc') != '2.0':
                    raise ValueError('JSON-RPC 2.0 required')
            except (ValueError, TypeError):
                self.send_error(400)
                return
            if 'id' not in request:
                self.send_response(202)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            probe = Probe(config)
            try:
                result = probe.rpc(request['method'], request.get('params', {}))
                reply = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
            except CallbackError:
                reply = {'jsonrpc': '2.0', 'id': request['id'], 'error': {
                    'code': -32015, 'message': 'CallbackEndpointError',
                    'data': {'reason': 'verification_failed'}}}
            except (ValueError, KeyError, TypeError, OSError) as error:
                reply = {'jsonrpc': '2.0', 'id': request['id'], 'error': {
                    'code': -32602, 'message': str(error)}}
            finally:
                probe.db.close()
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return HTTPServer((config['bind'], config['port']), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['serve', 'emit', 'status'])
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.action == 'serve':
        serve(config).serve_forever()
    else:
        probe = Probe(config)
        if args.action == 'emit':
            result = probe.emit()
        else:
            result = {'subscriptions': probe.db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0],
                      'probes': dict(probe.db.execute('SELECT state,COUNT(*) FROM probes GROUP BY state')),
                      'wechat_transport': False}
        print(json.dumps(result))
        probe.db.close()


if __name__ == '__main__':
    main()
