import contextlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from rsi_agent.config import WECHAT_LINUX
from trigger.group_admission import catalog, put, refresh
from trigger.group_context import group_configs
from trigger.group_reply import sync_groups, run


@unittest.skipUnless(sys.platform == 'linux', 'native Linux ownership and worker locks')
class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.runtime = self.root / 'native'
        self.runtime.mkdir(mode=0o700)
        self.registry = self.root / 'groups.json'
        self.owner_config = {'installation': str(self.root / 'installation.json'),
            'binding': str(self.root / 'owner-binding.json'), 'model': 'fixture-model'}
        put(self.root / 'installation.json', {'version': 1, 'wechat': {
            'account': 'self', 'runtime_root': str(self.runtime)}})
        put(self.root / 'owner.json', self.owner_config)
        put(self.registry, {'groups': []})
        self.policy = {'enabled': True, 'owner_config': str(self.root / 'owner.json'),
            'account': 'self', 'owner_peer': 'owner', 'since': 100, 'last_checked': 110,
            'initial_groups': ['old@chatroom']}
        put(self.root / 'admission.json', self.policy)
        self.snapshot = {'account': 'self', 'owner_peer': 'owner', 'reply_model_binding': 'fixture',
            'checked_at': 120, 'groups': [self.group('old'), self.group('new'),
                self.group('outsider', owner_present=False), self.group('ambiguous', addressable=False)]}

    def group(self, name, **changes):
        return dict({'peer': name + '@chatroom', 'name': name, 'display_name': name,
            'addressable': True, 'self_present': True, 'owner_present': True}, **changes)

    def refresh(self):
        response = types.SimpleNamespace(returncode=0, stdout=json.dumps(self.snapshot))
        identity = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
        with patch('trigger.group_admission.subprocess.run', return_value=response), \
                patch('pwd.getpwnam', return_value=identity):
            return refresh(self.registry)

    def test_only_new_native_owner_shared_group_is_admitted_once(self):
        old_target = {'old@chatroom': {'header_sha256': 'original-calibration'}}
        put(self.runtime / 'tool-targets.json', old_target)
        result = self.refresh()
        self.assertEqual(result['added'], 1)
        self.assertEqual(result['waiting_owner'], 1)
        self.assertEqual(result['unaddressable'], 1)
        configs = group_configs(self.registry)
        self.assertEqual(len(configs), 1)
        config = configs[0]
        binding = json.loads(Path(config['binding']).read_text())
        self.assertEqual(binding['group_peer'], 'new@chatroom')
        self.assertEqual(binding['send_scope']['since'], 110)
        self.assertFalse(binding['send_scope']['introduction'])
        self.assertNotIn('invited_by_owner', binding)
        targets = json.loads((self.runtime / 'tool-targets.json').read_text())
        self.assertEqual(targets['old@chatroom'], old_target['old@chatroom'])
        self.assertEqual(set(targets['new@chatroom']), {'peer', 'displayName', 'paired_account'})
        before = [Path(config['binding']).read_bytes(), Path(config['state'], 'config.json').read_bytes()]
        self.assertEqual(self.refresh()['added'], 0)
        self.assertEqual(before, [Path(config['binding']).read_bytes(), Path(config['state'], 'config.json').read_bytes()])
        self.assertEqual(len(group_configs(self.registry)), 1)

    def test_no_policy_does_not_probe_or_change_the_existing_registry(self):
        (self.root / 'admission.json').unlink()
        before = self.registry.read_bytes()
        with patch('trigger.group_admission.subprocess.run') as native:
            self.assertIsNone(refresh(self.registry))
            native.assert_not_called()
        self.assertEqual(before, self.registry.read_bytes())

    def test_expanded_policy_admits_native_groups_and_isolates_friend_registry(self):
        self.policy.update(conversation_since=115, friend_bootstrap={'peer': 'friend', 'server_id': '42'})
        put(self.root / 'admission.json', self.policy)
        self.snapshot['friends'] = [{'peer': 'friend', 'display_name': 'Native remark'}]
        result = self.refresh()
        self.assertEqual((result['added'], result['friends_added']), (3, 1))
        self.assertEqual(len(group_configs(self.registry)), 3)
        [config] = group_configs(self.registry.with_name('friends.json'), 'friends')
        binding = json.loads(Path(config['binding']).read_text())
        self.assertEqual((binding['owner_peer'], binding['friend_peer']), ('owner', 'friend'))
        self.assertEqual(binding['send_scope'],
                         {'mode': 'friend-private-chat', 'since': 115, 'greeting': True, 'bootstrap_server_id': '42'})
        self.assertEqual(self.refresh()['friends_added'], 0)

    def test_native_friend_catalog_rejects_pending_deleted_and_ambiguous_contacts(self):
        from trigger.group_admission import friend_catalog
        sys.path.insert(0, str(WECHAT_LINUX))
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE contact(username,nick_name,remark,alias,local_type,flag,delete_flag)')
        db.executemany('INSERT INTO contact VALUES(?,?,?,?,?,?,?)', [
            ('friend', 'Teacher', '', '', 1, 1, 0),
            ('pending', 'Pending', '', '', 1, 0, 0),
            ('deleted', 'Deleted', '', '', 1, 1, 1),
            ('ambiguous', 'Duplicate', '', '', 1, 1, 0),
            ('other', 'Duplicate', '', '', 1, 0, 0),
            ('room@chatroom', 'Room', '', '', 1, 1, 0),
            ('owner', 'Owner', '', '', 1, 1, 0),
        ])
        self.assertEqual(friend_catalog(db, {'account': 'self', 'owner_peer': 'owner'}),
                         [{'peer': 'friend', 'display_name': 'Teacher'}])

    def test_owner_identity_change_cannot_admit_a_group(self):
        self.snapshot['owner_peer'] = 'same-nickname-different-native-id'
        before = self.registry.read_bytes()
        with self.assertRaisesRegex(ValueError, 'owner/account changed'):
            self.refresh()
        self.assertEqual(before, self.registry.read_bytes())

    def test_native_catalog_uses_member_ids_without_reading_messages(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.executescript('CREATE TABLE contact(id INTEGER,username TEXT,nick_name TEXT,remark TEXT,alias TEXT,is_in_chat_room INTEGER);'
            'CREATE TABLE chat_room(id INTEGER,username TEXT);CREATE TABLE chatroom_member(room_id INTEGER,member_id INTEGER);')
        db.executemany('INSERT INTO contact VALUES(?,?,?,?,?,?)', [
            (1, 'self', 'Self', '', '', 0), (2, 'owner', 'Owner', '', '', 0),
            (3, 'stranger', 'Owner', '', '', 0), (4, 'good@chatroom', 'Good', '', '', 1),
            (5, 'spoof@chatroom', 'Spoof', '', '', 1)])
        db.executemany('INSERT INTO chat_room VALUES(?,?)', [(10, 'good@chatroom'), (11, 'spoof@chatroom')])
        db.executemany('INSERT INTO chatroom_member VALUES(?,?)', [(10, 1), (10, 2), (11, 1), (11, 3)])
        reads = []
        @contextlib.contextmanager
        def native(path):
            reads.append(path)
            yield db, {'consistency': 'committed', 'gap': False}
        who = {'account': 'self', 'owner_peer': 'owner', 'reply_model_binding': 'fixture'}
        with patch.dict(sys.modules, {'linux_tool': types.SimpleNamespace(native=native)}), \
                patch('trigger.reply_io.binding', return_value=who), patch.dict(os.environ):
            snapshot = catalog(self.root / 'installation.json', 'unused-private-binding')
        groups = {g['peer']: g for g in snapshot['groups']}
        self.assertTrue(groups['good@chatroom']['owner_present'])
        self.assertFalse(groups['spoof@chatroom']['owner_present'])
        self.assertEqual(reads, ['contact/contact.db'])

    def test_new_group_native_identity_seed_requires_fresh_search_before_input(self):
        self.refresh()
        sys.path.insert(0, str(WECHAT_LINUX))
        from operations.driver import NativeDriver
        from operations.recipes import selected
        @contextlib.contextmanager
        def native(_):
            db = Mock()
            db.execute.return_value.fetchone.return_value = (1,)
            yield db, {'consistency': 'committed'}
        module = types.SimpleNamespace(native=native, ACCOUNT='self', secret=lambda p: Path(p).read_text())
        put(self.runtime / 'native-ui.json', {'paired_account': 'self'})
        with patch.dict(sys.modules, {'linux_tool': module}), patch('operations.driver.BASE', self.runtime):
            driver = NativeDriver(self.runtime / 'operations', {'account': 'self'})
            driver.check_current_policy = Mock(return_value={'account': 'self'})
            target = {'username': 'new@chatroom', 'displayName': 'new', 'contactEvidence': {'consistency': 'committed'}}
            driver.tool = Mock(return_value=types.SimpleNamespace(resolve=Mock(return_value=target)))
            driver.name_peer = Mock(return_value='new@chatroom')
            job = {'id': 'a' * 32, 'peer': 'new@chatroom', 'client': 'rsi-group'}
            self.assertEqual(len(driver.fast_versions(job)), 3)
            driver.app_windows = Mock(return_value=[])
            driver.navigation_job_id = job['id']
            with patch('operations.recipes.main_window', return_value={}), \
                    patch('operations.recipes.controls'), patch('operations.recipes.activate'), \
                    patch('operations.recipes.screen'), \
                    patch('operations.navigation.search_named', return_value='fresh native proof required') as search:
                self.assertEqual(selected(driver, job), 'fresh native proof required')
            self.assertEqual(search.call_args.args[1]['peer'], 'new@chatroom')
            self.assertNotIn('header_sha256', search.call_args.args[3])

    def test_dynamic_loading_keeps_existing_original_pending_reply(self):
        workers = {}
        def cleanup():
            for _, loop, fd in workers.values():
                loop.close()
                os.close(fd)
        self.addCleanup(cleanup)
        configs = []
        for name in ('a', 'b'):
            folder = self.root / name
            folder.mkdir(mode=0o700)
            configs.append({'state': str(folder), 'model': 'fixture', 'name': name})
        def transport(config):
            name = config['name']
            return Mock(return_value={'account': 'self', 'peer': name + '@chatroom', 'name': name,
                'scope': {'mode': 'invited-group-text', 'since': 100, 'introduction': False}, 'enabled': True})
        with patch('trigger.backend.load_model', return_value=Mock(backend='fixture')), \
                patch('trigger.group_reply.GroupTransport', side_effect=transport):
            sync_groups(workers, configs[:1])
            first = workers[configs[0]['state']][1]
            with first.db:
                first.db.execute('INSERT INTO inbox(id,created,text,reply,state) VALUES(?,?,?,?,?)',
                    ('original', 120, 'original input', 'already generated reply', 'pending'))
            sync_groups(workers, configs)
        self.assertEqual(len(workers), 2)
        self.assertIs(workers[configs[0]['state']][1], first)
        self.assertEqual(first.db.execute('SELECT id,reply,state FROM inbox').fetchone()[:],
                         ('original', 'already generated reply', 'pending'))

    def test_auto_group_uses_binding_scope_as_expiry_cutoff(self):
        state = self.root / 'worker-auto'
        state.mkdir(mode=0o700)
        config = {'state': str(state), 'model': 'fixture', 'name': 'auto'}
        workers = {}
        def cleanup():
            for _, loop, fd in workers.values():
                loop.close()
                os.close(fd)
        self.addCleanup(cleanup)
        with patch('trigger.group_reply.GroupTransport', return_value=Mock(return_value={
                'account': 'self', 'peer': 'auto@chatroom', 'name': 'auto',
                'scope': {'mode': 'invited-group-text', 'since': 123, 'introduction': False},
                'enabled': True})), \
             patch('trigger.backend.load_model', return_value=Mock(backend='fixture')):
            sync_groups(workers, [config])
        self.assertEqual(workers[str(state)][1].recycle_since, 123)

    def test_running_worker_loads_second_group_without_restart(self):
        configs = []
        for name in ('a', 'b'):
            state = self.root / ('worker-' + name)
            state.mkdir(mode=0o700)
            configs.append({'state': str(state), 'model': 'fixture', 'name': name})
        desired, handled, handlers = [configs[0]], [], {}
        def make_loop(path, group, model, transport):
            result = Mock(model=model, io=transport)
            def cycle():
                handled.append(group['name'])
                desired[:] = configs
                return {'state': 'idle', 'counts': {}}
            result.cycle.side_effect = cycle
            return result
        sleeps = []
        def sleep(_):
            sleeps.append(1)
            if len(sleeps) >= 12:
                handlers[__import__('signal').SIGTERM]()
        with patch('trigger.group_reply.group_configs', side_effect=lambda _: desired[:]), \
                patch('trigger.group_reply.GroupLoop', side_effect=make_loop), \
                patch('trigger.group_reply.GroupTransport', side_effect=lambda c: Mock(return_value=dict(c, enabled=True))), \
                patch('trigger.backend.load_model', return_value=types.SimpleNamespace(backend='fixture', model='fixture')), \
                patch('trigger.group_admission.refresh'), \
                patch('trigger.group_reply.signal.signal', side_effect=lambda sig, fn: handlers.update({sig: fn})), \
                patch('trigger.group_reply.time.sleep', side_effect=sleep):
            self.assertEqual(run(str(self.registry), 'run')['state'], 'stopped')
        self.assertEqual(handled, ['a', 'a', 'b'])


if __name__ == '__main__':
    unittest.main()
