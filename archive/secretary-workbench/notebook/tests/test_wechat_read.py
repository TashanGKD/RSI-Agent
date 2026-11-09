"""No private data: synthetic fixtures for read-only bounded WeChat export."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'tools/wechat_read.py'

class ReadTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TOOL.exists(), 'independent read tool not implemented')
        spec = importlib.util.spec_from_file_location('wechat_read', TOOL)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_reject_account_traversal(self):
        with self.assertRaises(ValueError):
            self.m.validate_account('../wxid_fixture_519164fabd')

    def test_reject_existing_or_symlink_output(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d).resolve()/'existing.jsonl'; p.write_text('preserve')
            with self.assertRaises(FileExistsError):
                with self.m.exclusive_output(p): pass
            self.assertEqual(p.read_text(), 'preserve')
            p2=Path(d).resolve()/'link.jsonl';p2.symlink_to(p)
            with self.assertRaises(FileExistsError):
                with self.m.exclusive_output(p2): pass

    def test_reject_over_budget_before_copy_and_cleanup_unstable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); source=root/'message.db'; source.write_bytes(b'fixture')
            target=root/'scratch';target.mkdir()
            with self.assertRaises(ValueError):
                self.m.snapshot(source,target,1,lambda:None)
            self.assertEqual(list(target.iterdir()),[])
            calls=[]
            def mutate():
                calls.append(1)
                if len(calls)==2:source.write_bytes(b'changed fixture')
            with self.assertRaises(ValueError):
                self.m.snapshot(source,target,100,mutate)
            self.assertEqual(list(target.iterdir()),[])

    def test_window_all_kinds_stable_ids_and_missing_asr(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()/'fixture.db';con=sqlite3.connect(p)
            con.execute('CREATE TABLE Name2Id(user_name TEXT)')
            con.execute('INSERT INTO Name2Id VALUES(?)',('someone',))
            chat=self.m.hashlib.md5(b'someone').hexdigest()
            con.execute('CREATE TABLE Msg_'+chat+'(local_id INTEGER,server_id INTEGER,create_time INTEGER,local_type INTEGER,message_content TEXT,real_sender_id INTEGER)')
            for row in [(1,99,9,1,'before',1),(2,100,10,1,'hello',1),(3,0,11,34,'<msg><voicemsg voicelength="500"/></msg>',1),(4,101,12,49,'<msg><appmsg><title>attachment</title><type>6</type></appmsg></msg>',1),(5,102,13,1,'end',1)]:
                con.execute('INSERT INTO Msg_'+chat+' VALUES(?,?,?,?,?,?)',row)
            con.commit();con.close()
            rows=list(self.m.read_messages(p,'message/message_0.db','wxid_fixture_fbdcf7da1d',10,13,{'someone':'Person'},{},{},lambda:None))
            self.assertEqual(len(rows),3)
            self.assertEqual(rows[0]['conversationName'],'Person')
            self.assertTrue(rows[1]['needsASR'])
            self.assertIn('message/message_0.db',rows[1]['stableId'])
            self.assertTrue(rows[2]['needsContentRead'])
            self.assertNotIn('before',str(rows))

    def test_voice_lookup_uses_native_identity(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()/'voices.db'; c=sqlite3.connect(p)
            c.execute('CREATE TABLE voice_transcripts(account_key TEXT,conversation TEXT,server_id INTEGER,text TEXT,PRIMARY KEY(account_key,conversation,server_id))')
            c.execute('INSERT INTO voice_transcripts VALUES(?,?,?,?)',('wxid_fixture_fbdcf7da1d','someone',100,'synthetic transcript'))
            c.commit();c.close()
            with self.m.VoiceLookup(p) as lookup:
                self.assertEqual(lookup.get(('wxid_fixture_fbdcf7da1d','someone','100')),'synthetic transcript')
                self.assertIsNone(lookup.get(('wxid_fixture_fbdcf7da1d','someone','999')))

    def test_voice_followup_rejects_unbound_or_nonvoice_rows(self):
        path=TOOL.with_name('wechat_voice.py')
        self.assertTrue(path.exists(),'voice tool missing')
        spec=importlib.util.spec_from_file_location('wechat_voice',path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        for row in [dict(kind=34,serverId='0',nativeChat='someone',account=self.m.ACCOUNT),dict(kind=1,serverId='2',nativeChat='someone',account=self.m.ACCOUNT),dict(kind=34,serverId='2',nativeChat='../escape',account='../escape')]:
            with self.assertRaises(ValueError):mod.validate_voice(row)

    def test_asr_runner_reuses_existing_artifacts_and_cleans(self):
        path=TOOL.with_name('wechat_voice.py');spec=importlib.util.spec_from_file_location('voice_runner_test',path)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();original=root/'original';cli=root/'cli';original.mkdir();cli.mkdir()
            for name in ['VoiceSmoke.dll','VoiceSmoke.deps.json','VoiceSmoke.runtimeconfig.json','WechatUiCollector.dll']:(original/name).write_bytes(b'synthetic')
            (cli/'runtimes').mkdir();(cli/'System.Text.Json.dll').write_bytes(b'existing dependency')
            with mod.asr_runner(original,cli) as runner:
                self.assertTrue(runner.exists());scratch=runner.parent
                self.assertTrue((scratch/'System.Text.Json.dll').is_symlink())
                self.assertEqual((scratch/'WechatUiCollector.dll').read_bytes(),b'synthetic')
            self.assertFalse(scratch.exists())
            self.assertEqual((cli/'System.Text.Json.dll').read_bytes(),b'existing dependency')

    def test_reject_non_utc_reversed_or_overlong_window(self):
        for start,end in [('2026-10-21','2026-10-22'),('2026-10-22T00:00:00Z','2026-10-21T00:00:00Z'),('2026-01-01T00:00:00Z','2026-10-01T00:00:00Z')]:
            with self.assertRaises(ValueError):self.m.window(start,end)

if __name__=='__main__':unittest.main()
