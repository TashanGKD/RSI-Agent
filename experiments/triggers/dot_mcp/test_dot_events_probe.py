"""Protocol/state checks; these do not impersonate a real Dot subscription."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


spec = importlib.util.spec_from_file_location('dot_probe', Path(__file__).with_name('dot_events_probe.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DotEventsProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {'database': str(Path(self.temp.name) / 'probe.sqlite'),
                       'capability': 'fixture-only', 'bind': '127.0.0.1', 'port': 0}
        self.probe = module.Probe(self.config)
        self.params = {'name': module.EVENT, 'arguments': module.ARGUMENTS,
            'delivery': {'mode': 'webhook', 'url': 'https://example.com/callback',
                         'secret': 'whsec_' + base64.b64encode(b'x'*32).decode()}}

    def tearDown(self):
        self.probe.db.close()
        self.temp.cleanup()

    def test_no_subscription_never_emits(self):
        with self.assertRaisesRegex(ValueError, 'one active real subscription'):
            self.probe.emit()

    def test_persisted_subscription_and_original_event_resume(self):
        deliveries = []
        def deliver(url, secret, identity, value, subscription):
            deliveries.append((identity, value.copy(), subscription))
            return {'challenge': value['challenge']} if value.get('type') == 'verification' else {}
        with patch.object(module, 'callback', side_effect=deliver):
            first = self.probe.rpc('events/subscribe', self.params)
            self.probe.db.close()
            self.probe = module.Probe(self.config)
            self.assertEqual(first['id'], self.probe.rpc('events/subscribe', self.params)['id'])
            event = self.probe.emit()
            self.assertEqual(event['event_id'], self.probe.emit()['event_id'])
        self.assertEqual(len([x for x in deliveries if x[1].get('type') == 'verification']), 1)
        payload = deliveries[1][1]
        self.assertEqual(set(payload), {'eventId', 'name', 'timestamp', 'data', 'cursor'})
        self.assertEqual(deliveries[1], deliveries[2])
        data = payload['data']
        args = {'probe_id': data['probe_id'], 'answer': data['a']*data['b']}
        original = self.probe.rpc('tools/call', {'name': module.TOOL['name'], 'arguments': args})
        self.assertEqual(original, self.probe.rpc('tools/call', {
            'name': module.TOOL['name'], 'arguments': args}))
        with self.assertRaisesRegex(ValueError, 'incorrect'):
            self.probe.rpc('tools/call', {'name': module.TOOL['name'],
                'arguments': dict(args, answer=-1)})
        self.probe.rpc('events/unsubscribe', self.params)
        self.probe.rpc('events/unsubscribe', self.params)
        with self.assertRaisesRegex(ValueError, 'one active real subscription'):
            self.probe.emit()

    def test_filter_and_failed_verification_do_not_create_subscription(self):
        with self.assertRaises(ValueError):
            self.probe.rpc('events/subscribe', dict(self.params, arguments={'experiment': 'wechat'}))
        with patch.object(module, 'callback', return_value={'challenge': 'wrong'}):
            with self.assertRaisesRegex(ValueError, 'challenge failed'):
                self.probe.rpc('events/subscribe', self.params)
        self.assertEqual(self.probe.db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0], 0)

    def test_private_callbacks_are_not_contacted(self):
        secret = self.params['delivery']['secret']
        for url in ('http://example.com/x', 'https://127.0.0.1/x', 'https://example.com:444/x'):
            with self.assertRaises(ValueError):
                module.callback(url, secret, 'event', {}, 'subscription')

    def test_signed_wire_body_and_redirect_rejection(self):
        connection = Mock()
        connection.getresponse.return_value.status = 302
        connection.getresponse.return_value.read.return_value = b'{}'
        value = {'type': 'verification', 'challenge': 'fixture-challenge'}
        with patch.object(module.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8', 443))]), \
                patch.object(module.socket, 'create_connection'), \
                patch.object(module.ssl, 'create_default_context'), \
                patch.object(module, 'HTTPSConnection', return_value=connection):
            with self.assertRaisesRegex(ValueError, 'callback rejected'):
                module.callback('https://example.com/callback', self.params['delivery']['secret'],
                                'fixture-id', value, 'subscription-id')
        args, kwargs = connection.request.call_args
        self.assertEqual(json.loads(args[2]), value)
        headers = kwargs['headers']
        signed = b'fixture-id.' + headers['webhook-timestamp'].encode() + b'.' + args[2]
        expected = base64.b64encode(module.hmac.digest(b'x'*32, signed, 'sha256')).decode()
        self.assertEqual(headers['webhook-signature'], 'v1,' + expected)
        self.assertEqual(headers['X-MCP-Subscription-Id'], 'subscription-id')
        self.assertEqual(connection.request.call_count, 1)

    def test_stateless_http_discovery_and_capability(self):
        server = module.serve(self.config)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            def post(path, value):
                return urlopen(Request(base + path, data=json.dumps(value).encode(),
                                      headers={'Content-Type': 'application/json'}), timeout=3)
            with post('/fixture-only/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'}) as result:
                self.assertIn('events', json.load(result)['result']['capabilities'])
            with post('/fixture-only/mcp', {'jsonrpc': '2.0', 'id': 2, 'method': 'events/list'}) as result:
                self.assertEqual(json.load(result)['result']['events'][0]['name'], module.EVENT)
            with self.assertRaises(HTTPError) as error:
                post('/wrong/mcp', {'jsonrpc': '2.0', 'id': 3, 'method': 'events/list'})
            self.assertEqual(error.exception.code, 404)
            with self.assertRaises(HTTPError) as error:
                post('/fixture-only/mcp', [])
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
