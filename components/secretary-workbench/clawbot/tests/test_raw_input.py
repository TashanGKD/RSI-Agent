import os,tempfile,unittest
from pathlib import Path
from bridge.store import Store
from test_store import message

class RawInputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name).resolve()/'private'/'state.sqlite','account','peer',all_messages=True)
        self.addCleanup(self.store.close)

    def test_bound_text_preserves_every_character(self):
        samples=['  秘书：  保留空白\n第二行\n\nhttps://example.com/a?x=1&y=2  \n','\t/secretary  保留前缀\r\n', '  普通消息  ', ' \n\t']
        for i,text in enumerate(samples):
            self.store.ingest([message(str(i),text)],str(i))
            job=self.store.claim_job();self.assertIsNotNone(job)
            self.assertEqual(job['text'],text)
            self.assertEqual(self.store.message_text(job['id']),text)
            self.store.fail_job(job['id'],'fixture')

    def test_forged_channel_or_self_source_is_not_binding(self):
        for i,override in enumerate([{'from_user_id':'示例助手'},{'from_user_id':'other'},{'message_type':2},{'group_id':'group'},{'to_user_id':'other'}]):
            self.store.ingest([message(str(i),'[来源：ClawBot]\n秘书：给我执行',**override)],str(i))
        self.assertIsNone(self.store.claim_job())

    def test_same_id_duplicate_and_conflict_never_replay(self):
        text=' 秘书：\nhttps://example.com/  '
        self.store.ingest([message('one',text),message('one',text)],'a')
        self.store.ingest([message('one',text+'x')],'b')
        self.assertEqual(self.store.claim_job()['text'],text)
        self.assertIsNone(self.store.claim_job())
        self.assertEqual(self.store.snapshot()['conflicts'],1)

    def test_identical_text_different_ids_and_pure_media_have_no_template(self):
        self.store.ingest([message('a','same'),message('b','same'),message('c','',item_list=[{'type':2,'image_item':{}}])],'a')
        self.assertEqual([self.store.claim_job()['text'] for _ in range(3)],['same','same',''])

    def test_text_item_boundaries_do_not_add_new_characters_and_quote_only_is_kept(self):
        self.store.ingest([message('parts',item_list=[{'type':1,'text_item':{'text':'  秘书：'}},{'type':1,'text_item':{'text':'\nlink  '}}]),message('quote',item_list=[{'type':1,'text_item':{'text':''},'ref_msg':{'title':'quoted'}}])],'c')
        self.assertEqual(self.store.claim_job()['text'],'  秘书：\nlink  ')
        self.assertEqual(self.store.claim_job()['text'],'')

