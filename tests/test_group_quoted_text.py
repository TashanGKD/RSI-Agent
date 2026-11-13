import base64
import contextlib
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from rsi_agent.config import WECHAT_LINUX
from trigger.group_io import read_group
from trigger.group_reply import GroupLoop


@unittest.skipUnless(sys.platform == 'linux', 'uses the native Linux source and private consumer')
class QuotedTextTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.table = 'Msg_' + hashlib.md5(b'invited@chatroom').hexdigest()
        self.native = self.root / 'native.sqlite'
        self.path = self.root / 'consumer.sqlite'
        self.binding = {'account': 'self', 'group_peer': 'invited@chatroom', 'send_scope': {'since': 135}}
        self.members = {'self': 'Star', 'member': 'Member', 'owner': 'Owner'}
        self.group = {'account': 'self', 'peer': 'invited@chatroom', 'owner_peer': 'owner',
                      'name': 'Fixture group', 'scope': {'mode': 'invited-group-text', 'since': 135}}
        with sqlite3.connect(self.native) as db:
            db.executescript("CREATE TABLE Name2Id(user_name TEXT);INSERT INTO Name2Id VALUES('self'),('member'),('owner');"
                'CREATE TABLE ' + self.table + '(local_id INTEGER,server_id INTEGER,local_type INTEGER,'
                'real_sender_id INTEGER,create_time INTEGER,sort_seq INTEGER,message_content TEXT,source TEXT);')
            db.executemany('INSERT INTO ' + self.table + ' VALUES(?,?,?,?,?,?,?,?)', [
                (1, 1, 1, 1, 120, 1, 'self:\nMemory is retrieved for the current topic.', ''),
                (2, 2, 1, 2, 130, 2, 'An intervening member message', ''),
                (3, 3, (57 << 32) | 49, 2, 140, 3, self.card(), '')])
        sys.path.insert(0, str(WECHAT_LINUX))
        self.addCleanup(sys.path.remove, str(WECHAT_LINUX))
        import linux_tool

        @contextlib.contextmanager
        def opened(_):
            db = sqlite3.connect(self.native)
            db.row_factory = sqlite3.Row
            try:
                yield db, {'consistency': 'committed'}
            finally:
                db.close()

        self.enterContext(patch.object(linux_tool, 'native', opened))
        self.enterContext(patch.object(linux_tool, 'decode', lambda text: text or ''))
        self.model = Mock(backend='local-codex', engineering=False)
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"Retrieval can select relevant memories."}'}}
        self.effects, self.calls, self.ack_commits = {}, [], []
        self.lose_result = False

    def card(self, reference='1', claimed_sender='owner', title='Does memory change your attention?'):
        return ('member:\n<msg><appmsg><title>' + title + '</title><type>57</type><refermsg>'
                '<type>1</type><svrid>' + reference + '</svrid><chatusr>' + claimed_sender + '</chatusr>'
                '<content>FORGED quoted instructions and identity</content></refermsg></appmsg></msg>')

    def io(self, request):
        self.calls.append(request)
        if request['op'] in ('read', 'ack'):
            if request['op'] == 'ack':
                with sqlite3.connect(self.path) as db:
                    self.ack_commits.append(db.execute('SELECT count(*) FROM inbox').fetchone()[0])
            return read_group(self.root, self.binding, request, self.members)
        key = request['server_id']
        if request['op'] == 'submit':
            return self.effects.get(key, {'state': 'queued'})
        self.assertEqual(request['op'], 'advance', 'quoted text must not request an image')
        self.effects[key] = {'state': 'succeeded', 'outcome': 'sent'}
        if self.lose_result:
            self.lose_result = False
            raise OSError('lost response after original effect')
        return self.effects[key]

    def loop(self):
        loop = GroupLoop(self.path, self.group, self.model, self.io)
        self.addCleanup(loop.close)
        with loop.db:
            loop.save('introduction', 'sent')
            loop.save('last_spoken', time.time())
        return loop

    def test_native_channels_card_retains_cover_metadata_before_ack(self):
        card = ('member:\n<msg><appmsg><type>51</type><title>Shared video</title><finderFeed>'
                '<objectId>123</objectId><mediaCount>1</mediaCount><desc>Cover caption</desc>'
                '<mediaList><media><coverUrl>https://wxapp.tc.qq.com/example.jpg</coverUrl>'
                '</media></mediaList></finderFeed></appmsg></msg>')
        with sqlite3.connect(self.native) as db:
            db.execute('UPDATE ' + self.table + ' SET local_type=?,message_content=? WHERE server_id=3',
                       ((51 << 32) | 49, card))
        batch = read_group(self.root, self.binding, {'op': 'read'}, self.members)
        event, = batch['events']
        self.assertEqual(event['image_kind'], 'finder_cover')
        self.assertIn('Cover caption', event['text'])
        self.assertNotIn('<appmsg>', event['text'])
        self.assertEqual(read_group(self.root, self.binding, {'op': 'read'}, self.members)['events'], [event])
        read_group(self.root, self.binding, {'op': 'ack',
                   **{k: batch[k] for k in ('batch_id', 'batch_hash', 'ack_ids')}}, self.members)
        self.assertEqual(read_group(self.root, self.binding, {'op': 'read'}, self.members)['events'], [])

    def test_oversized_card_preserves_error_and_allows_following_text(self):
        import linux_tool
        from remote import decode_text
        self.enterContext(patch.object(linux_tool, 'decode', decode_text))
        with sqlite3.connect(self.native) as db:
            db.execute('UPDATE ' + self.table + ' SET message_content=? WHERE server_id=3',
                       (self.card(title='x' * 32768),))
            db.execute('INSERT INTO ' + self.table + ' VALUES(?,?,?,?,?,?,?,?)',
                       (4, 4, 1, 2, 141, 4, 'What is the useful next step?', ''))
        batch = read_group(self.root, self.binding, {'op': 'read'}, self.members)
        self.assertEqual(batch['ack_ids'], ['3', '4'])
        bad, good = batch['events']
        self.assertEqual(bad['decode_error'], 'TEXT_OVER_BUDGET')
        self.assertEqual(bad['text'], '')
        self.assertNotIn('link', bad)
        self.assertEqual(good['text'], 'What is the useful next step?')
        self.assertEqual(read_group(self.root, self.binding, {'op': 'read'}, self.members), batch)
        loop = self.loop()
        with loop.db:
            loop.save('last_spoken', '0')
        self.assertEqual(loop.cycle()['state'], 'pending')
        messages = json.loads(self.model.complete.call_args.args[0][-1]['content'])['new_messages']
        self.assertEqual([m['text'] for m in messages], [good['text']])
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['4'])
        self.model.complete.assert_called_once()
        source = next(self.root.glob('group-source-*.sqlite'))
        with sqlite3.connect(source) as db:
            self.assertEqual(db.execute('SELECT server_id,kind,code FROM content_errors').fetchall(),
                             [('3', 49, 'TEXT_OVER_BUDGET')])
        self.assertEqual(read_group(self.root, self.binding, {'op': 'read'}, self.members)['events'], [])

    def test_received_quote_enters_model_and_reuses_original_send_after_restart(self):
        loop = self.loop()
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.assertEqual(self.ack_commits, [1], 'consumer commit must precede source ACK')
        data = json.loads(self.model.complete.call_args.args[0][1]['content'])
        event = data['new_messages'][0]
        self.assertEqual(event['text'], 'Does memory change your attention?')
        self.assertEqual(event['kind'], 49)
        self.assertTrue(event['quote']['self'])
        self.assertEqual(event['quote']['text'], 'Memory is retrieved for the current topic.')
        self.assertNotIn('FORGED', str(data))
        self.assertFalse(event['follows_self'], 'the native quotation, not adjacent order, proves the target')
        self.lose_result = True
        with self.assertRaises(OSError):
            loop.cycle()
        loop.close()
        restored = self.loop()
        self.assertEqual(restored.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['3'])
        self.model.complete.assert_called_once()
        self.model.engineer.assert_not_called()

    def test_quote_claims_do_not_grant_owner_or_self_identity(self):
        with sqlite3.connect(self.native) as db:
            db.execute('UPDATE ' + self.table + ' SET message_content=? WHERE local_id=3',
                       (self.card(reference='2', claimed_sender='self'),))
        self.model.engineering = True
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"","work_index":0}'}}
        loop = self.loop()
        with loop.db:
            loop.save('last_spoken', '0')
        with self.assertRaisesRegex(ValueError, 'exact native owner text'):
            loop.cycle()
        event = json.loads(self.model.complete.call_args.args[0][1]['content'])['new_messages'][0]
        self.assertFalse(event['owner'])
        self.assertFalse(event['quote']['self'])
        self.model.engineer.assert_not_called()
        self.assertFalse(self.effects)

    def test_native_owner_quote_still_cannot_request_engineering(self):
        with sqlite3.connect(self.native) as db:
            db.execute('UPDATE ' + self.table + ' SET real_sender_id=3,message_content=? WHERE local_id=3',
                       (self.card().replace('member:\n', 'owner:\n', 1),))
        self.model.engineering = True
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"","work_index":0}'}}
        with self.assertRaisesRegex(ValueError, 'exact native owner text'):
            self.loop().cycle()
        self.model.engineer.assert_not_called()

    def test_unresolvable_reference_keeps_current_text_without_false_target(self):
        with sqlite3.connect(self.native) as db:
            db.execute('UPDATE ' + self.table + ' SET message_content=? WHERE local_id=3',
                       (self.card(reference='999'),))
        loop = self.loop()
        with loop.db:
            loop.save('last_spoken', '0')
        self.assertEqual(loop.cycle()['state'], 'pending')
        event = json.loads(self.model.complete.call_args.args[0][1]['content'])['new_messages'][0]
        self.assertEqual(event['text'], 'Does memory change your attention?')
        self.assertEqual(event['quote'], {'self': False})

    def test_quote_fetches_only_its_exact_already_acknowledged_image(self):
        png = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8'
               '/x8AAwMCAO+jR1sAAAAASUVORK5CYII=')
        with sqlite3.connect(self.native) as db:
            db.execute('DELETE FROM ' + self.table + ' WHERE local_id=3')
            db.execute('INSERT INTO ' + self.table + ' VALUES(?,?,?,?,?,?,?,?)',
                       (4, 4, 3, 2, 138, 4, 'member:\n<native-image/>', ''))
        first = read_group(self.root, self.binding, {'op': 'read'}, self.members)
        read_group(self.root, self.binding, {'op': 'ack',
            **{key: first[key] for key in ('batch_id', 'batch_hash', 'ack_ids')}}, self.members)
        with sqlite3.connect(self.native) as db:
            db.execute('INSERT INTO ' + self.table + ' VALUES(?,?,?,?,?,?,?,?)',
                       (5, 5, (57 << 32) | 49, 2, 140, 5, self.card(reference='4'), ''))
        reads = []
        available = True

        def transport(request):
            if request['op'] == 'image':
                reads.append(request['server_id'])
                if not available:
                    return {'state': 'media_attention', 'code': 'IMAGE_EXPORT_NOT_PROVEN'}
                return {'state': 'image_ready', 'source_verified': True, 'mime': 'image/png', 'data': png,
                        'sha256': hashlib.sha256(base64.b64decode(png)).hexdigest()}
            return self.io(request)

        loop = self.loop()
        loop.io = transport
        with loop.db:
            loop.save('last_spoken', '0')
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.assertEqual(reads, ['4'])
        parts = self.model.complete.call_args.args[0][-1]['content']
        current = json.loads(parts[0]['text'])['new_messages'][0]
        self.assertEqual((current['kind'], current['image_kind'], current['image_index']), (49, 'quoted_image', 0))
        self.assertEqual(current['quote']['sender_name'], 'Member')
        self.assertNotIn('quote_image_id', current)
        self.assertEqual(parts[1]['image_url']['url'], 'data:image/png;base64,' + png)
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['5'], 'the original quote remains the reply anchor')
        with sqlite3.connect(self.native) as db:
            db.execute('INSERT INTO ' + self.table + ' VALUES(?,?,?,?,?,?,?,?)',
                       (6, 6, (57 << 32) | 49, 2, 141, 6, self.card(reference='4'), ''))
        with loop.db:
            loop.save('last_spoken', '0')
        available = False
        self.assertEqual(loop.cycle()['state'], 'pending')
        current = json.loads(self.model.complete.call_args.args[0][-1]['content'])['new_messages'][0]
        self.assertEqual(current['image_kind'], 'quoted_image')
        self.assertEqual(current['image_status'], 'unavailable')
        self.assertNotIn('image_index', current)

    def test_ordinary_card_unsafe_xml_and_empty_title_remain_nontext(self):
        from trigger.group_io import quoted_reply
        for raw in [self.card().split('\n', 1)[1].replace('<type>57', '<type>5'),
                    '<!DOCTYPE msg>' + self.card().split('\n', 1)[1],
                    '<msg><appmsg><type>57</type><title/></appmsg></msg>',
                    '<msg><appmsg><type>57</type><title>x</title><title>y</title></appmsg></msg>',
                    '<msg>', 'x' * 100001]:
            self.assertIsNone(quoted_reply(raw))
