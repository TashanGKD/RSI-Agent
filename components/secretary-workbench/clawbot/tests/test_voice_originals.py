"""Deferred originals: immutable bound source, no-clobber assets, bounded thread.

Breaking inputs: unbound store, corrupted source/receipt, hostile CDN, path swap.
Every source here is an isolated synthetic fixture, not phone evidence.
"""
import base64,hashlib,json,os,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from bridge.store import Store
from bridge.private import read,write
from bridge.media import MediaPreparer,MediaFailure
try:
    from bridge.originals import OriginalPreserver
except ImportError:OriginalPreserver=None

KEY=b'k'*16;RAW=b'original-encoded-audio-fixture'
def item():return {'type':3,'voice_item':{'text':'  测试转写\n','media':{'aes_key':base64.b64encode(KEY).decode(),'full_url':'https://novac2c.cdn.weixin.qq.com/c2c/download'}}}

class OriginalsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(OriginalPreserver,'deferred original preserver missing')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.root.chmod(0o700)
        self.s=Store(self.root/'state.sqlite','bot','owner',all_messages=True);self.addCleanup(self.s.close)
        self.items=[item()];self.s.ingest([{'message_id':'fixture','from_user_id':'owner','to_user_id':'bot','message_type':1,'message_state':2,'context_token':'ctx','item_list':self.items}],'c')
        self.prep=MediaPreparer(self.root)
        self.manifest=self.prep.prepare('fixture',self.items,voice_text=True)
        self.before=Path(self.manifest['manifest_path']).read_bytes()
    def keeper(self,download=None):
        return OriginalPreserver(self.root,'bot','owner',download=download or (lambda *a,**k:AES.new(KEY,AES.MODE_ECB).encrypt(pad(RAW,16))))
    def test_download_saves_queryable_exact_bytes_without_changing_manifest(self):
        k=self.keeper();k.sweep_once();r=k.query('fixture',0)
        self.assertEqual(r['status'],'saved');self.assertEqual(Path(r['path']).read_bytes(),RAW)
        self.assertEqual(r['sha256'],hashlib.sha256(RAW).hexdigest());self.assertEqual(r['message_id'],'fixture')
        self.assertEqual(Path(self.manifest['manifest_path']).read_bytes(),self.before)
        k=self.keeper(lambda *a,**k:self.fail('saved original must not download twice'));k.sweep_once()
        self.assertEqual(k.query('fixture',0)['status'],'saved')
    def test_slow_download_does_not_block_text_prepare_or_worker_reply(self):
        entered=threading.Event();release=threading.Event()
        def slow(*a,**kw):entered.set();release.wait(2);return AES.new(KEY,AES.MODE_ECB).encrypt(pad(RAW,16))
        k=self.keeper(slow);k.start();self.addCleanup(lambda:(release.set(),k.close()))
        self.assertTrue(entered.wait(1));start=time.monotonic()
        self.assertEqual(k.query('fixture',0)['status'],'fetching')
        MediaPreparer(self.root).prepare('other',[item()],voice_text=True)
        from bridge.worker import Worker
        class Native:
            native=True
            def reply(self,j):return 'reply while download blocked'
        class API:
            sent=False
            def send_text(api,*a):api.sent=True;return {}
            def poll(api,*a,**kw):return {'msgs':[],'get_updates_buf':'c'}
        api=API();result=Worker(self.s,api,Native()).cycle()
        self.assertEqual(result['generated'],1);self.assertTrue(api.sent)
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
        for mid,kind,content in [('concurrent-image',2,png),('concurrent-file',4,b'fresh document')]:
            obj={'media':item()['voice_item']['media']}
            obj.update({'file_name':'fixture.txt','len':str(len(content))} if kind==4 else {})
            prepared=MediaPreparer(self.root,download=lambda *a:AES.new(KEY,AES.MODE_ECB).encrypt(pad(content,16))).prepare(mid,[{'type':kind,{2:'image_item',4:'file_item'}[kind]:obj}])
            m=read(Path(prepared['manifest_path']))
            self.assertEqual(m['items'][0]['status'],'ready');self.assertEqual(Path(m['assets'][0]['path']).read_bytes(),content)
        self.assertLess(time.monotonic()-start,.5)
        self.assertFalse(release.is_set());release.set()
        deadline=time.monotonic()+1
        while time.monotonic()<deadline and k.query('fixture',0)['status']!='saved':time.sleep(.01)
        k.close()
        self.assertEqual(k.query('fixture',0)['status'],'saved')
    def test_failure_and_budget_are_real_gaps_not_saved(self):
        k=self.keeper(lambda *a,**kw:(_ for _ in ()).throw(OSError('secret locator must not be logged')))
        k.sweep_once();r=k.query('fixture',0)
        self.assertEqual(r['status'],'failed');self.assertNotIn('path',r)
        self.assertNotIn('secret',json.dumps(r))
        with patch('bridge.media.MAX_WORKSPACE_BYTES',0):
            other=self.keeper(lambda *a,**kw:self.fail('quota must reject before network'));other.sweep_once()
        # Existing failed receipt is retained; a fresh source exercises quota.
        self.s.ingest([{'message_id':'quota','from_user_id':'owner','message_type':1,'message_state':2,'item_list':[item()]}],'c')
        with patch('bridge.media.MAX_WORKSPACE_BYTES',0):other.sweep_once()
        q=other.query('quota',0);self.assertEqual(q['status'],'failed');self.assertEqual(q['code'],'media_budget_exceeded')
    def test_existing_original_reused_and_hash_checked_without_network(self):
        # A normal previously prepared original is reusable, not re-downloaded.
        obj=self.root/'media'/hashlib.sha256(b'fixture').hexdigest();p=obj/'item-00-original.audio';p.write_bytes(RAW);p.chmod(0o600)
        m=read(Path(self.manifest['manifest_path']));m['assets']=[{'path':str(p),'size':len(RAW),'sha256':hashlib.sha256(RAW).hexdigest(),'kind':'voice-original'}]
        write(Path(self.manifest['manifest_path']),m)
        k=self.keeper(lambda *a,**kw:self.fail('existing bytes must be reused'));k.sweep_once()
        self.assertEqual(k.query('fixture',0)['status'],'saved');self.assertTrue(k.query('fixture',0)['reused'])
        p.write_bytes(b'corrupt')
        self.assertEqual(k.query('fixture',0)['status'],'failed')
    def test_fetching_receipt_recovers_after_restart_without_claiming_saved(self):
        k=self.keeper();k.ensure_pending('fixture',0,self.items[0])
        r=k.query('fixture',0);self.assertEqual(r['status'],'pending')
        receipt=k.receipt_path('fixture',0);r.update(status='fetching',attempts=1);write(receipt,r)
        other=self.keeper();self.assertEqual(other.query('fixture',0)['status'],'fetching')
        other.sweep_once();self.assertEqual(other.query('fixture',0)['status'],'saved')
    def test_crash_after_publish_reconciles_candidate_without_network(self):
        k=self.keeper();k.ensure_pending('fixture',0,self.items[0]);r=k.query('fixture',0)
        path=self.root/'media'/hashlib.sha256(b'fixture').hexdigest()/'originals/item-00.audio'
        path.parent.mkdir(mode=0o700);path.write_bytes(RAW);path.chmod(0o600)
        r.update(status='fetching',attempts=3,candidate={'path':str(path),'size':len(RAW),'sha256':hashlib.sha256(RAW).hexdigest()});write(k.receipt_path('fixture',0),r)
        other=self.keeper(lambda *a,**kw:self.fail('published candidate must be recovered'));other.sweep_once()
        self.assertTrue(other.query('fixture',0)['recovered']);self.assertEqual(other.query('fixture',0)['status'],'saved')
    def test_third_interrupted_attempt_is_not_retried_forever(self):
        k=self.keeper();k.ensure_pending('fixture',0,self.items[0]);r=k.query('fixture',0)
        r.update(status='fetching',attempts=3);write(k.receipt_path('fixture',0),r)
        other=self.keeper(lambda *a,**kw:self.fail('retry cap'));other.sweep_once()
        self.assertEqual(other.query('fixture',0)['status'],'failed');self.assertFalse(other.query('fixture',0)['retryable'])
    def test_changed_receipt_types_and_candidate_escape_are_rejected(self):
        k=self.keeper();k.ensure_pending('fixture',0,self.items[0]);r=k.query('fixture',0)
        write(k.receipt_path('fixture',0),dict(r,attempts='0'))
        with self.assertRaises(ValueError):k.query('fixture',0)
        write(k.receipt_path('fixture',0),dict(r,candidate={'path':None}))
        with self.assertRaises(ValueError):k.query('fixture',0)
        outside=self.root/'outside';outside.write_bytes(RAW);outside.chmod(0o600)
        write(k.receipt_path('fixture',0),dict(r,candidate={'path':str(outside),'size':len(RAW),'sha256':hashlib.sha256(RAW).hexdigest()}))
        k.sweep_once();self.assertEqual(k.query('fixture',0)['status'],'failed');self.assertEqual(outside.read_bytes(),RAW)
    def test_commit_rechecks_workspace_message_and_item_budget(self):
        k=self.keeper()
        target=self.root/'media'/hashlib.sha256(b'fixture').hexdigest()
        for field in ['MAX_WORKSPACE_BYTES','MAX_MESSAGE_BYTES','MAX_ITEM_BYTES']:
            with patch('bridge.media.'+field,1):
                with self.assertRaises(MediaFailure):k._budget(target,2)
    def test_bounded_scan_closes_readonly_sqlite_connection(self):
        import sqlite3
        k=self.keeper();connect=sqlite3.connect;connections=[]
        def tracked(*a,**kw):
            c=connect(*a,**kw);connections.append(c);return c
        with patch('bridge.originals.sqlite3.connect',side_effect=tracked):k._source_rows()
        for c in connections:
            with self.assertRaises(sqlite3.ProgrammingError):c.execute('select 1')
    def test_wrong_binding_and_changed_source_are_rejected(self):
        with self.assertRaises(ValueError):OriginalPreserver(self.root,'bot','impostor')
        k=self.keeper(lambda *a,**kw:self.fail('corrupt source must not download'))
        self.s.db.execute("update incoming set body='[]' where id='fixture'")
        with self.assertRaises(ValueError):k.sweep_once()
    def test_hostile_url_and_symlink_receipt_do_not_escape(self):
        bad=item();bad['voice_item']['media']['full_url']='https://evil.test/a'
        self.s.ingest([{'message_id':'evil','from_user_id':'owner','message_type':1,'message_state':2,'item_list':[bad]}],'c')
        k=self.keeper();k.sweep_once();k.sweep_once()
        self.assertEqual(k.query('evil',0)['status'],'failed')
        receipt=k.receipt_path('fixture',0);receipt.unlink();receipt.symlink_to(self.root/'outside')
        with self.assertRaises(ValueError):k.query('fixture',0)
    def test_close_is_bounded_and_fetching_recovers(self):
        entered=threading.Event();release=threading.Event()
        def slow(*a,**kw):entered.set();release.wait(2);return AES.new(KEY,AES.MODE_ECB).encrypt(pad(RAW,16))
        k=self.keeper(slow);k.start();self.assertTrue(entered.wait(1))
        start=time.monotonic();k.close(timeout=.02);self.assertLess(time.monotonic()-start,.2)
        self.assertEqual(k.query('fixture',0)['status'],'fetching')
        release.set();k.close();self.assertEqual(k.query('fixture',0)['status'],'pending')
        other=self.keeper();other.sweep_once();self.assertEqual(other.query('fixture',0)['status'],'saved')
