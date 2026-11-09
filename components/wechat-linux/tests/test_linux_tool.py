import unittest,tempfile,sqlite3,hashlib
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
import linux_tool

class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.contact=sqlite3.connect(self.path/'contacts');self.contact.row_factory=sqlite3.Row
        self.contact.executescript('create table contact(username text,remark text,nick_name text,alias text,delete_flag int);insert into contact values("owner","Owner","Owner Name","owner_alias",0);insert into contact values("other","Other","Other Name","other_alias",0);insert into contact values("dup1","Duplicate","A","",0);insert into contact values("dup2","Duplicate","B","",0);')
        self.msg=sqlite3.connect(self.path/'messages');self.msg.row_factory=sqlite3.Row
        table='Msg_'+hashlib.md5(b'other').hexdigest();self.table=table
        self.msg.executescript('create table Name2Id(user_name text);insert into Name2Id values("other");insert into Name2Id values("small");create table '+table+'(local_id int,server_id int,local_type int,real_sender_id int,create_time int,sort_seq int,message_content text);insert into '+table+' values(5,123,1,1,100,1000,"hello");')
        self.media=sqlite3.connect(self.path/'media');self.media.row_factory=sqlite3.Row
        self.media.executescript('create table Name2Id(user_name text);insert into Name2Id values("other");create table VoiceInfo(chat_name_id int,svr_id int,local_id int,create_time int,voice_data blob);')
        self.media.execute('insert into VoiceInfo values(1,124,6,101,?)',(b'#!SILK_V3voice',));self.media.commit()
        @contextmanager
        def opened(rel):
            yield {'contact/contact.db':self.contact,'message/message_0.db':self.msg,'message/media_0.db':self.media}[rel],{'consistency':'committed','source':rel}
        self.tool=linux_tool.Tool(opened,account='small')
    def tearDown(self):self.contact.close();self.msg.close();self.media.close();self.tmp.cleanup()
    def test_arbitrary_peer_or_missing_window_rejected(self):
        for r in [{'action':'messages','peer':'../../etc/passwd','start':1,'end':2},{'action':'messages','peer':'other'},{'action':'send_text','peer':'other','text':'x','request_id':'../../x'}]:
            with self.assertRaises(ValueError):self.tool.handle(r)
    def test_duplicate_display_name_refuses_to_guess(self):
        with self.assertRaises(ValueError):self.tool.resolve('Duplicate')
    def test_true_username_over_other_peoples_nickname(self):
        r=self.tool.resolve('other');self.assertEqual(r['username'],'other')
    def test_existing_other_chat_and_media_gap_retained(self):
        r=self.tool.handle({'action':'messages','peer':'other','start':99,'end':102,'limit':10})
        self.assertEqual([x['serverId'] for x in r['messages']],['123','124'])
        self.assertEqual(r['messages'][0]['senderId'],'other')
        self.assertEqual(r['messages'][1]['sourceKind'],'voice_media')
        self.assertIsNone(r['messages'][1]['senderId']);self.assertFalse(r['coverage']['messageMetadataComplete'])
    def test_voice_pair_and_server_id_exact(self):
        r=self.tool.handle({'action':'voice','peer':'other','server_id':'124'})
        self.assertEqual(r['serverId'],'124');self.assertEqual(r['sha256'],hashlib.sha256(b'#!SILK_V3voice').hexdigest())
        with self.assertRaises(ValueError):self.tool.handle({'action':'voice','peer':'owner','server_id':'124'})
    def test_read_native_sticker_keeps_sender_asset_and_receipt_status_together(self):
        self.msg.execute('alter table '+self.table+' add column status integer')
        raw = '<msg><emoji md5="' + 'a' * 32 + '" cdnurl="https://example.invalid/opaque"/></msg>'
        self.msg.execute('insert into '+self.table+' values(8,125,47,2,102,1020,?,2)', (raw,))
        request = {'action':'messages','peer':'other','server_ids':['125']}
        row = self.tool.handle(request)['messages'][0]
        self.assertEqual((row['kind'], row['senderId'], row['serverId']), (47, 'small', '125'))
        self.assertEqual(row['sticker'], {'md5':'a' * 32})
        self.assertEqual(row['nativeStatus'], 2)
        self.assertEqual(row['text'], '')
        self.msg.execute('insert into '+self.table+' values(9,125,47,2,102,1020,?,2)', (raw,))
        self.assertNotIn('sticker', self.tool.handle(request)['messages'][0])
    def test_no_unbounded_account_scan(self):
        with self.assertRaises(ValueError):self.tool.handle({'action':'sessions'})
        with self.assertRaises(ValueError):self.tool.handle({'action':'messages','peer':'other','start':1,'end':999999999,'limit':10})
    def test_duplicate_json_keys_and_oversize(self):
        for raw in ['{"action":"messages","action":"send_text"}','x'*2000000]:
            with self.assertRaises(ValueError):linux_tool.parse_request(raw)
    def test_image_request_validated_before_sender(self):
        for r in [{'action':'send_image','peer':'other','request_id':'a'*64,'image_base64':'../secret'}, {'action':'send_text','peer':'other','request_id':'a'*64,'text':'x'}]:
            with self.assertRaises(ValueError):self.tool.handle(r)
    def test_new_message_partition_is_rejected_before_any_key_access(self):
        p=self.path.resolve()/'profile';d=p/'db_storage/message';d.mkdir(parents=True)
        (d/'message_0.db').write_bytes(b'');(d/'message_1.db').write_bytes(b'')
        with patch('linux_tool.PROFILE',p),patch('linux_tool.secret',side_effect=AssertionError('partition guard must run before key loading')):
            with self.assertRaisesRegex(ValueError,'source rotation'):
                with linux_tool.native('message/message_0.db'):pass
    def test_non_image_request_stops_before_any_ui_action(self):
        with patch('image_client.Controls',side_effect=AssertionError('must not touch display')):
            with self.assertRaises(ValueError):self.tool.handle({'action':'image_prepare','peer':'other','server_id':'123'})

