"""Attach-only adapter; new input stays raw, identity and media stay private."""
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import time
from pathlib import Path
from .private import directory,read,write

NODE='node'
PORT=Path(__file__).with_name('native_port.mjs')
THREAD=os.environ.get('SECRETARY_THREAD_ID','00000000-0000-4000-8000-001c36bddfee')

class NativePending(Exception):
    pass

class NativeRunner:
    native=True
    def __init__(self,workspace,execute=subprocess.run,media_preparer=None):
        self.root=directory(workspace);self.execute=execute;self.media_preparer=media_preparer
        self.journals=directory(self.root/'native-requests')
        cfg=read(self.root/'native-context.json')
        if cfg.get('thread_id')!=THREAD:raise ValueError('native conversation binding mismatch')
        self.enabled=cfg.get('enabled',True)

    def invoke(self,body):
        try:
            # OS lock releases on process death; never reset another caller's request.
            fd=os.open(self.root/'native-port.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
            with os.fdopen(fd,'rb') as lock:
                info=os.fstat(lock.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077:
                    raise ValueError('unsafe native lock')
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise NativePending('native_port_busy') from None
                r=self.execute([NODE,str(PORT),str(self.root/'native-context.json')],input=json.dumps(body,ensure_ascii=False),
                    text=True,capture_output=True,shell=False,timeout=45)
                if len(r.stdout)>300000:raise NativePending('native_response_too_large')
                result=json.loads(r.stdout)
                if not isinstance(result,dict):raise ValueError()
                return result
        except (subprocess.TimeoutExpired,ValueError,OSError):
            raise NativePending('native_connection_unavailable') from None

    def _failure_receipt(self,job,saved):
        root=directory(self.root/'native-receipts')
        path=root/(hashlib.sha256(job['id'].encode()).hexdigest()+'.json')
        value={'version':1,'message_id':job['id'],'source':'ClawBot','status':'failed',
               'code':saved['media_error'],'read_status':'unread','original_items_retained':True}
        write(path,value)
        saved.update(metadata_path=str(path),metadata_hash=hashlib.sha256(path.read_bytes()).hexdigest())

    def reply(self,job):
        self.timing={}
        if not self.enabled:raise NativePending('native_connection_disabled')
        key=hashlib.sha256(job['id'].encode()).hexdigest();client='weixin-'+key
        journal=self.journals/(key+'.json')
        raw=job.get('raw_text',job['text'])
        if not isinstance(raw,str):raise ValueError('invalid original text')
        if journal.exists():
            saved=read(journal)
        else:
            saved={'version':4,'input_format':'raw-v2','state':'new','client_id':client,'message_id':job['id'],
                   'prompt_hash':hashlib.sha256(raw.encode()).hexdigest()}
        legacy=saved.get('version',1)<2
        expected=job['text'] if legacy else raw
        if saved.get('client_id')!=client or saved.get('message_id')!=job['id'] or saved['prompt_hash']!=hashlib.sha256(expected.encode()).hexdigest():
            raise ValueError('changed native request')
        items_hash=hashlib.sha256(json.dumps(job.get('items',[]),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if saved.get('items_hash',items_hash)!=items_hash:raise ValueError('changed native message attachments')
        self.timing={k:saved.get(k) for k in ('received_at','prepared_at','queued_at','native_started_at','native_completed_at')}
        if saved['state']=='completed':return saved['reply']
        prompt=job['text'] if legacy else raw
        modern=saved.get('version',1)>=3
        if modern:
            from .voice_text import prompt as voice_prompt
            # Validate before I/O. Already-submitted v1/v2 prompts remain pinned.
            if 'prepared_prompt' not in saved:voice_prompt(raw,job.get('items',[]),compact=saved['version']>=4)
            prompt=saved.get('prepared_prompt',raw)
        if saved['state']=='new' and not saved.get('prepared_at'):
            saved['items_hash']=items_hash
            if job.get('received_at') is not None:saved['received_at']=job['received_at']
            transcripts=[]
            needs_media=any(i.get('type')!=1 or i.get('ref_msg') for i in job.get('items',[]) if isinstance(i,dict))
            if needs_media:
                from .media import MediaPreparer,MediaFailure
                if self.media_preparer is None:self.media_preparer=MediaPreparer(self.root)
                try:
                    if saved.get('media_error'):raise MediaFailure(saved['media_error'])
                    if modern and any(type(i.get('type')) is int and i['type']==3 for i in job['items']):
                        prepared=self.media_preparer.prepare(job['id'],job['items'],voice_text=True)
                    else:prepared=self.media_preparer.prepare(job['id'],job['items'])
                    saved.update(manifest_path=prepared['manifest_path'],manifest_hash=prepared['manifest_hash'])
                    transcripts=prepared.get('voice_transcripts',[])
                except MediaFailure as exc:
                    saved['media_error']=str(exc)[:512]
                    self._failure_receipt(job,saved)
            if modern:
                prompt=voice_prompt(raw,job.get('items',[]),transcripts,compact=saved['version']>=4)
                saved['prepared_prompt']=prompt
                saved['prepared_prompt_hash']=hashlib.sha256(prompt.encode()).hexdigest()
            saved['prepared_at']=time.time()
            write(journal,saved)
        if modern and hashlib.sha256(prompt.encode()).hexdigest()!=saved.get('prepared_prompt_hash'):
            raise ValueError('changed prepared native input')
        self.timing.update({k:saved.get(k) for k in self.timing})
        identity={'client_id':client,'wx_message_id':job['id'],'input_format':'legacy-v1' if legacy else 'raw-v2'}
        known={field:saved.get(field) for field in ('anchor_turn_id','turn_id','queue_id','native_message_id')}
        result=self.invoke({'action':'poll',**identity,**known,'allow_new':saved['state']=='new'})
        if result.get('state')=='not_found' and saved['state']=='new':
            saved['state']='submitting';saved['anchor_turn_id']=result.get('head_turn_id');write(journal,saved)
            submit={'action':'submit',**identity,'prompt':prompt,'anchor_turn_id':saved.get('anchor_turn_id')}
            for field in ('manifest_path','manifest_hash','metadata_path','metadata_hash'):
                if saved.get(field):submit[field]=saved[field]
            result=self.invoke(submit)
        state=result.get('state')
        if state=='media_rejected':
            # Guaranteed by the port before RPC or creation of a submission mapping.
            saved.update(state='new',media_error='managed_attachment_validation_failed')
            saved.pop('manifest_path',None);saved.pop('manifest_hash',None)
            self._failure_receipt(job,saved);write(journal,saved)
            raise NativePending('media_rejected_before_submission')
        for field in ('queue_id','turn_id','native_message_id','queued_at','native_started_at','native_completed_at'):
            if result.get(field):saved[field]=result[field]
        self.timing.update({k:saved.get(k) for k in self.timing})
        if state in ('completed','failed'):
            reply=result.get('reply')
            if not isinstance(reply,str) or not reply:raise NativePending('native_final_answer_missing')
            if len(reply.encode())>30000:
                reply=reply.encode()[:29000].decode('utf8','ignore')+'\n\n（答复较长，其余内容可在同一个Codex对话查看。）'
            saved.update(state='completed',reply=reply,native_state=state)
            # The immutable prepared prompt is needed only until reconciliation
            # finishes; retain its hash and mapping without doubling reply size.
            saved.pop('prepared_prompt',None)
            write(journal,saved);return reply
        if state in ('queued','running'):saved['state']=state
        elif saved['state']=='submitting':saved['state']='uncertain'
        saved['last_native_state']=state or 'native_waiting';write(journal,saved)
        raise NativePending(state or 'native_waiting')

    def check(self):
        if not self.enabled:return False
        try:return self.invoke({'action':'inspect'}).get('state')=='connected'
        except NativePending:return False

    def visible_scan(self, after):
        if not self.enabled:raise NativePending('native_connection_disabled')
        result=self.invoke({'action':'visible','after_turn_id':after})
        if result.get('state') not in ('initialized','scanned'):raise NativePending('visible_history_unavailable')
        for turn in result.get('turns',[]):
            client=turn.get('client_id')
            turn['job_id']=None
            if isinstance(client,str) and client.startswith('weixin-'):
                key=client.removeprefix('weixin-')
                if len(key)!=64 or any(ch not in '0123456789abcdef' for ch in key):raise ValueError('invalid visible source identity')
                journal=read(self.journals/(key+'.json'))
                if journal.get('client_id')!=client or journal.get('turn_id')!=turn.get('turn_id') or hashlib.sha256(journal.get('message_id','').encode()).hexdigest()!=key:raise ValueError('visible source identity mismatch')
                turn['job_id']=journal['message_id']
        return result

    def outgoing_source(self, item):
        if not self.enabled or item.get('kind')!='text':return None
        result=self.invoke({'action':'verify_outgoing','text':item['text']})
        if result.get('state')!='verified':raise NativePending('visible_source_unavailable')
        return result.get('source')
