"""Same-role aliases share a private peer, but each event retains its binding.

Reject unknown binding IDs, mismatched accounts, and ambiguous unlabelled events.
All ledgers are in-memory; the official queue is mocked, never contacted.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import runtime as r
from test_runtime import binding, event


class SamePeerAliasDispatchTests(unittest.TestCase):
    def pair(self):
        owner = 'wxid_fixture_owner'
        a = dict(binding(), id='old-name', peer=owner, triggerMode='owner_name',
                 ownerId=owner, aliases=['old_name'], handledSources=[])
        b = dict(a, id='new-name', aliases=['new_name'])
        e = dict(event(), peer=owner, atUserIds=[], triggerType='owner_name',
                 namedRecipient='old_name', sourceTextSHA256='a' * 64)
        f = dict(e, serverId='8000105847482291211', namedRecipient='new_name')
        return a, b, e, f

    def assert_pending_only(self, ledger, count):
        self.assertEqual(ledger.c.execute('select count(*) from batches').fetchone()[0], 0)
        self.assertEqual(ledger.c.execute("select count(*) from events where state='pending'").fetchone()[0], count)

    def test_two_aliases_same_peer_prepare_one_batch_preserving_both_bindings(self):
        a, b, e, f = self.pair()
        with patch('runtime.work_acceptance', return_value=None):
            l = r.Ledger(':memory:')
            self.addCleanup(l.close)
            l.ingest(a, e); l.ingest(b, f)
            batch = l.prepare(a, r.pending_events([a, b], l.c), [a, b])
            rows = l.c.execute('select binding,state,batch from events order by rowid').fetchall()
            self.assertEqual([x['binding'] for x in rows], [a['id'], b['id']])
            self.assertTrue(all(x['state'] == 'batched' and x['batch'] == batch['id'] for x in rows))
            self.assertIn('同会话合并2次提醒', batch['body'])

    def test_busy_retained_then_idle_queues_once_for_same_peer_aliases(self):
        a, b, e, f = self.pair()
        l = r.Ledger(':memory:'); self.addCleanup(l.close)
        reply = SimpleNamespace(returncode=0, stdout='Queued message 00000000-0000-4000-8000-479c4f1eb72a for thread ' + a['threadId'] + '.\n')
        with patch('runtime.work_acceptance', return_value=None), patch('runtime.queued', return_value=[]), patch('runtime.subprocess.run', return_value=reply) as submit:
            l.ingest(a, e); l.ingest(b, f)
            with patch('runtime.live', return_value={'status': 'inProgress'}):
                r.dispatch_role([a, b], l)
            submit.assert_not_called(); self.assert_pending_only(l, 2)
            with patch('runtime.live', return_value={'status': 'completed'}):
                r.dispatch_role([a, b], l)
                with patch('runtime.find_native', return_value={'where': 'history', 'id': 'actual-user', 'turnId': 'actual-turn'}):
                    r.dispatch_role([a, b], l)
            submit.assert_called_once()
            self.assertEqual(l.c.execute('select count(*) from batches').fetchone()[0], 1)

    def test_unknown_binding_rejected_without_claiming_real_event(self):
        a, _, e, _ = self.pair()
        l = r.Ledger(':memory:'); self.addCleanup(l.close)
        with patch('runtime.work_acceptance', return_value=None): l.ingest(a, e)
        with self.assertRaises(ValueError): l.prepare(a, [dict(e, _binding='not-registered')], [a])
        self.assert_pending_only(l, 1)

    def test_wrong_account_rejected_without_claiming_real_event(self):
        a, _, e, _ = self.pair()
        l = r.Ledger(':memory:'); self.addCleanup(l.close)
        with patch('runtime.work_acceptance', return_value=None): l.ingest(a, e)
        with self.assertRaises(ValueError): l.prepare(a, [dict(e, _binding=a['id'], account='wxid_fixture_4c90539d6a')], [a])
        self.assert_pending_only(l, 1)

    def test_ambiguous_missing_binding_does_not_pick_last_alias(self):
        a, b, _, f = self.pair()
        l = r.Ledger(':memory:'); self.addCleanup(l.close)
        with patch('runtime.work_acceptance', return_value=None): l.ingest(b, f)
        with self.assertRaises(ValueError): l.prepare(a, [f], [a, b])
        self.assert_pending_only(l, 1)

    def test_unique_single_route_keeps_legacy_unlabelled_event_compatible(self):
        a, _, e, _ = self.pair()
        l = r.Ledger(':memory:'); self.addCleanup(l.close)
        with patch('runtime.work_acceptance', return_value=None): l.ingest(a, e)
        batch = l.prepare(a, [e], [a])
        self.assertEqual(batch['state'], 'prepared')


if __name__ == '__main__': unittest.main()
