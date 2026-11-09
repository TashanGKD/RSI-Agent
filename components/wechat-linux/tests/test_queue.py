import tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from queue_store import Queue

def event(text='秘书：你好',**kw):
    return dict(account='wxid_fixture_8e822a662c',peer='wxid_fixture_1987fcaa9f',sender='wxid_fixture_1987fcaa9f',epoch='a'*32,local_id=1,server_id=123,kind=1,created=1792869000,text=text,**kw)

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.p=Path(self.t.name)/'q.sqlite';self.q=Queue(self.p,'wxid_fixture_8e822a662c','wxid_fixture_1987fcaa9f',0)
    def tearDown(self):self.q.close();self.t.cleanup()
    def test_foreign_sender_rejected_without_cursor(self):
        e=event();e['sender']='wxid_fixture_4c90539d6a'
        with self.assertRaises(ValueError):self.q.ingest([e],4)
        self.assertEqual(self.q.cursor(),0)
    def test_duplicate_changed_payload_is_rejected(self):
        self.q.ingest([event()],1)
        with self.assertRaises(ValueError):self.q.ingest([event('different')],2)
        self.assertEqual(self.q.cursor(),1)
    def test_oversize_and_invalid_id(self):
        for change in [{'text':'x'*32769},{'local_id':True},{'epoch':'../../passwd'}]:
            e=event();e.update(change)
            with self.assertRaises(ValueError):self.q.ingest([e],9)
        self.assertEqual(self.q.cursor(),0)
    def test_duplicate_and_restart_do_not_requeue(self):
        self.q.ingest([event()],1);self.q.ingest([event()],1)
        j=self.q.next_job();self.q.finish(j['id'],'reply');self.q.close()
        self.q=Queue(self.p,'wxid_fixture_8e822a662c','wxid_fixture_1987fcaa9f',0)
        self.assertIsNone(self.q.next_job());self.assertEqual(self.q.counts()['events'],1)
        self.assertEqual(len(self.q.outbox()),1)
    def test_own_message_never_loops(self):
        e=event();e['sender']='wxid_fixture_8e822a662c'
        self.q.ingest([e],1);self.assertIsNone(self.q.next_job())
    def test_shell_text_is_preserved_as_data(self):
        e=event('秘书：$(touch /tmp/owned); `whoami`')
        self.q.ingest([e],1);self.assertEqual(self.q.next_job()['text'],e['text'])
    def test_unknown_send_not_selected_again(self):
        self.q.ingest([event()],1);j=self.q.next_job();self.q.finish(j['id'],'r')
        out=self.q.outbox()[0];self.q.mark_outbox(out['id'],'unknown',{})
        self.assertEqual(self.q.outbox(),[])
    def test_pre_baseline_does_not_reply(self):
        self.q.close();self.q=Queue(Path(self.t.name)/'fresh.sqlite','wxid_fixture_8e822a662c','wxid_fixture_1987fcaa9f',1792869001)
        self.q.ingest([event()],1);self.assertIsNone(self.q.next_job())
    def test_notice_does_not_complete_job_and_is_deduplicated(self):
        self.q.ingest([event()],1);j=self.q.next_job()
        self.q.notice(j['id'],'queued');self.q.notice(j['id'],'queued')
        self.assertEqual(len(self.q.outbox()),1)
        self.assertIsNotNone(self.q.next_job())
    def test_image_is_not_silently_ignored_or_claimed_read(self):
        e=event('');e['kind']=3
        self.q.ingest([e],1)
        j=self.q.next_job();self.assertIn('未取得附件正文',j['text']);self.assertIn('serverId=123',j['text'])
    def test_same_busy_job_does_not_repeat_notice_ten_minutes_later(self):
        self.q.ingest([event()],1);j=self.q.next_job()
        with patch('queue_store.time.time',return_value=1000):self.q.notice(j['id'],'queued')
        with patch('queue_store.time.time',return_value=2000):self.q.notice(j['id'],'queued')
        self.assertEqual(self.q.counts()['outbox'],{'pending':1})
    def test_text_cannot_overtake_earlier_transcribed_voice(self):
        voice=event('');voice['kind']=34
        later=event('上一条语音照办');later['local_id']=2;later['server_id']=456
        self.q.ingest([voice,later],2)
        ident=self.q.pending_voice()['id'];self.q.voice_text(ident,'earlier voice')
        self.assertEqual(self.q.next_job()['id'],ident)
    def test_reused_local_coordinate_has_two_independent_server_events(self):
        a=event('first');self.q.ingest([a],1)
        b=event('second');b['server_id']=456;b['created']+=1
        self.q.ingest([b],1)
        self.assertEqual(self.q.counts()['events'],2);self.assertEqual(self.q.counts()['jobs'],{'pending':2})
    def test_legacy_identity_and_completed_job_survive_server_migration(self):
        self.q.ingest([event()],1);j=self.q.next_job();self.q.finish(j['id'],'done')
        legacy='wxid_fixture_8e822a662c:wxid_fixture_1987fcaa9f:'+event()['epoch']+':1'
        with self.q.c:
            self.q.c.execute('delete from server_aliases')
            for table in ['events','jobs','outbox']:self.q.c.execute('update '+table+' set id=? where id=?',(legacy,j['id']))
        self.q.close()
        self.q=Queue(self.p,'wxid_fixture_8e822a662c','wxid_fixture_1987fcaa9f',0)
        moved=event();moved['local_id']=9;moved['epoch']='b'*32;moved['created']+=2
        self.q.ingest([moved],9)
        self.assertIsNone(self.q.next_job());self.assertEqual(self.q.counts()['events'],1)
        self.assertEqual(self.q.c.execute('select id from jobs').fetchone()[0],legacy)
    def test_provisional_zero_cannot_execute_then_assigns_once(self):
        e=event();e['server_id']=0;self.q.ingest([e],1);self.assertIsNone(self.q.next_job())
        self.q.ingest([event()],1);self.q.ingest([event()],1)
        self.assertEqual(self.q.counts()['jobs'],{'pending':1})
    def test_legacy_mutable_server_column_does_not_rename_completed_input(self):
        self.q.ingest([event()],1);j=self.q.next_job();self.q.finish(j['id'],'done')
        with self.q.c:
            self.q.c.execute('delete from server_aliases')
            self.q.c.execute('update events set server_id=?',('456',))
        self.q.close();self.q=Queue(self.p,'wxid_fixture_8e822a662c','wxid_fixture_1987fcaa9f',0)
        other=event();other['server_id']=456;other['created']+=1
        self.q.ingest([other],1)
        self.assertEqual(self.q.counts()['jobs'],{'completed':1,'pending':1})
    def test_conflicting_existing_alias_is_not_silently_ignored(self):
        self.q.ingest([event()],1)
        with self.q.c:self.q.c.execute('update server_aliases set server_id=?',('456',))
        self.q.close()
        with self.assertRaises(ValueError):Queue(self.p,'wxid_fixture_8e822a662c','wxid_fixture_1987fcaa9f',0)
        self.q=Queue(Path(self.t.name)/'clean.sqlite','wxid_fixture_8e822a662c','wxid_fixture_1987fcaa9f',0)

if __name__=='__main__':unittest.main()
