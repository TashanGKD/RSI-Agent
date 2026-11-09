"""Offline cross-layer regression: authenticated intake through native submission and reply."""
import base64,hashlib,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from bridge.store import Store
from bridge.media import MediaPreparer
from bridge.native_runner import NativeRunner,THREAD
from bridge.private import write,read
from bridge.worker import Worker
from bridge.api import TransportError

class PipelineTests(unittest.TestCase):
    # Periodic read-only visibility checks must not consume submit/poll fixtures.
    # Otherwise these tests depend on whether the suite has been running >2 sec.
    def visibility(self):
        return {'state':'initialized','after_turn_id':'fixture-head','turns':[]}

    def test_raw_native_final_reply_with_unknown_delivery_is_not_resent_after_restart(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();os.chmod(root,0o700);write(root/'native-context.json',{'thread_id':THREAD})
            store=Store(root/'state.sqlite','bot','peer',all_messages=True)
            raw='  秘书：hello\nhttps://example.com/  '
            msg={'message_id':'raw-final','from_user_id':'peer','to_user_id':'bot','message_type':1,'message_state':2,'context_token':'fixture','item_list':[{'type':1,'text_item':{'text':raw}}]}
            calls=[];states=iter([{'state':'not_found'},{'state':'queued','queue_id':'q'},{'state':'completed','turn_id':'t','native_message_id':'n','reply':'one final'}])
            def execute(argv,**kwargs):
                body=json.loads(kwargs['input']);calls.append(body)
                return SimpleNamespace(stdout=json.dumps(self.visibility() if body['action']=='visible' else next(states)),returncode=0)
            class API:
                sent=0
                def poll(self,*a,**kw):return{'msgs':[msg],'get_updates_buf':'c'}
                def send_text(self,*a):self.sent+=1;raise TransportError('accepted but reply lost')
            api=API();worker=Worker(store,api,NativeRunner(root,execute=execute))
            worker.cycle();worker.cycle();self.assertEqual(api.sent,1);self.assertEqual(store.snapshot()['outbox'],{'unknown':1})
            store.close();store=Store(root/'state.sqlite','bot','peer',all_messages=True);self.addCleanup(store.close);store.recover_running()
            def completed_execute(argv,**kwargs):
                self.assertEqual(json.loads(kwargs['input'])['action'],'visible','completed job must not poll or submit again')
                return SimpleNamespace(stdout=json.dumps(self.visibility()),returncode=0)
            worker=Worker(store,api,NativeRunner(root,execute=completed_execute))
            worker.runner.check=lambda:True;worker.cycle()
            self.assertEqual(api.sent,1);self.assertEqual(store.snapshot()['outbox'],{'unknown':1})
            self.assertEqual([c['prompt'] for c in calls if c['action']=='submit'],[raw])

    def test_real_quota_failure_reaches_same_native_context_and_text_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();os.chmod(root,0o700);write(root/'native-context.json',{'thread_id':THREAD})
            store=Store(root/'state.sqlite','bot','peer',all_messages=True);self.addCleanup(store.close)
            calls=[]
            def execute(argv,**kw):
                body=json.loads(kw['input']);calls.append(body)
                return SimpleNamespace(stdout=json.dumps(self.visibility() if body['action']=='visible' else {'state':'not_found'} if body['action']=='poll' else {'state':'queued','queue_id':'q'}),returncode=0)
            class API:
                messages=[]
                def poll(self,*a,**kw):return{'msgs':self.messages,'get_updates_buf':'c'}
            api=API();worker=Worker(store,api,NativeRunner(root,execute=execute,media_preparer=MediaPreparer(root)))
            for mid,items in [('plain',[{'type':1,'text_item':{'text':'查询资料'}}]),('image',[{'type':2,'image_item':{}}])]:
                api.messages=[{'message_id':mid,'from_user_id':'peer','to_user_id':'bot','message_type':1,'message_state':2,'item_list':items}]
                with patch('bridge.media.MAX_WORKSPACE_BYTES',0):
                    result=worker.cycle()
                self.assertEqual(result['state'],'waiting_for_native_conversation')
                # Leave this queued fixture intact; complete just its local store job to test next intake.
                job=store.claim_job();store.complete_job(job['id'],'fixture')
            submits=[c for c in calls if c['action']=='submit'];self.assertEqual(len(submits),2)
            self.assertEqual(submits[0]['prompt'],'查询资料')
            self.assertEqual(submits[1]['prompt'],'')
            self.assertEqual(read(Path(submits[1]['metadata_path']))['code'],'media workspace size limit exceeded')
            self.assertNotIn('manifest_path',submits[1])

    def test_restart_reuses_media_and_keeps_url_file_audio_image_in_same_native_request(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve();os.chmod(root,0o700)
            write(root/'native-context.json',{'thread_id':THREAD})
            store=Store(root/'state.sqlite','bot','peer',all_messages=True)
            self.addCleanup(store.close)
            key=b'x'*16;encoded=base64.b64encode(key).decode();downloads=[];calls=[]
            png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
            raw={'image':png,'voice':b'\x00\x00'*2400,'file':'供测试的原始文件'.encode()}
            def download(url,limit):
                downloads.append(url);kind=url.rsplit('=',1)[1]
                return AES.new(key,AES.MODE_ECB).encrypt(pad(raw[kind],16))
            def media(kind):return{'encrypt_query_param':kind,'aes_key':encoded}
            items=[{'type':1,'text_item':{'text':'秘书：理解这批资料和 https://example.com/ ，不用新增业务待办'}},
                   {'type':2,'image_item':{'media':media('image')}},
                   {'type':3,'voice_item':{'media':media('voice'),'encode_type':1,'sample_rate':24000}},
                   {'type':4,'file_item':{'media':media('file'),'file_name':'../../测试.txt','len':str(len(raw['file'])),'md5':hashlib.md5(raw['file']).hexdigest()}}]
            msg={'message_id':'fixture-mixed','from_user_id':'peer','to_user_id':'bot','message_type':1,'message_state':2,'context_token':'test-only','item_list':items}
            states=iter([{'state':'not_found'},{'state':'queued','queue_id':'q'}, {'state':'completed','turn_id':'t','reply':'四类资料已接收'}])
            def execute(argv,**kwargs):
                body=json.loads(kwargs['input']);calls.append(body)
                return SimpleNamespace(stdout=json.dumps(self.visibility() if body['action']=='visible' else next(states)),returncode=0)
            class API:
                def __init__(self):self.sent=[]
                def poll(self,*args,**kwargs):return{'msgs':[msg],'get_updates_buf':'cursor'}
                def send_text(self,*args):self.sent.append(args);return{'ret':0}
            api=API();prep=MediaPreparer(root,download=download)
            worker=Worker(store,api,NativeRunner(root,execute=execute,media_preparer=prep))
            with patch('bridge.voice_text.local_asr',return_value={'text':'测试语音','model':'fixture'}):
                self.assertEqual(worker.cycle()['state'],'waiting_for_native_conversation')
            worker.runner=NativeRunner(root,execute=execute,media_preparer=MediaPreparer(root,download=lambda *_:self.fail('no repeated download')))
            self.assertEqual(worker.cycle()['generated'],1)
            submitted=[c for c in calls if c['action']=='submit'];self.assertEqual(len(submitted),1)
            self.assertIn(items[0]['text_item']['text'],submitted[0]['prompt'])
            self.assertEqual(submitted[0]['prompt'].count('测试语音'),1)
            self.assertIn('https://example.com/',submitted[0]['prompt'])
            manifest=read(Path(submitted[0]['manifest_path']))
            self.assertEqual([i['type'] for i in manifest['inputs']],['localImage','localAudio'])
            self.assertEqual({a['kind'] for a in manifest['assets']},{'image-original','voice-original','voice-wav','file'})
            self.assertEqual(len(downloads),3);self.assertEqual(len(api.sent),1)
            self.assertEqual(store.snapshot()['jobs'],{'completed':1})
