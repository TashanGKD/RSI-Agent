"""Explicit worker loop with one owner, durable delivery, and no unsafe resend."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import signal
import time
from pathlib import Path
from .api import WeixinAPI, APIError, TransportError
from .private import directory, read, write
from .store import Store
from .runner import CodexRunner
from .native_runner import NativeRunner,NativePending


@contextmanager
def process_lock(root):
    root=directory(root)
    fd=os.open(root/'worker.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('worker already active') from None
        yield
    finally:os.close(fd)


class Worker:
    def __init__(self,store,api,runner,originals=None):
        self.store=store;self.api=api;self.runner=runner
        self.last_native_check=0
        self.originals=originals
        self.last_visible_check=0

    def flush_one(self):
        context=self.store.context()
        if not context:return {'state':'waiting_for_inbound_context'}
        item=self.store.claim_outbox()
        if not item:return {'state':'idle'}
        try:
            if (item['kind']=='text' and getattr(self.runner,'native',False)
                    and self.store.needs_visible_source(item['id'])):
                source=self.runner.outgoing_source(item)
                if not source:
                    self.store.finish_outbox(item['id'],'failed',{'reason':'visible_source_missing','network_send':False})
                    return {'state':'visible_source_missing','outbox_id':item['id']}
                canonical=self.store.bind_visible_source(item['id'],source)
                if canonical!=item['id']:
                    self.store.finish_outbox(item['id'],'failed',{'reason':'duplicate_visible_source','canonical_outbox_id':canonical})
                    return {'state':'duplicate_suppressed','outbox_id':item['id']}
            requested_at=time.time()
            if item['kind']=='text':
                result=self.api.send_text(self.store.peer_id,item['text'],context,item['client_id'])
            else:
                result=self.api.send_image(self.store.peer_id,item['path'],context,item['client_id'],expected_sha256=item['sha256'])
            receipt={'api_accepted':True,'phone_delivery_verified':False,'client_id':item['client_id'],
                     'send_requested_at':requested_at,'api_accepted_at':time.time()}
            if self.store.visible_source(item['id']):receipt['native_source']=self.store.visible_source(item['id'])
            mid=result.get('message_id')
            mid_text=str(mid) if type(mid) in (str,int) else ''
            if 0<len(mid_text)<=512 and mid_text.isascii() and mid_text.isprintable():receipt['server_message_id']=mid_text
            self.store.finish_outbox(item['id'],'accepted',receipt)
            return {'state':'api_accepted','outbox_id':item['id']}
        except TransportError:
            self.store.finish_outbox(item['id'],'unknown',{'reason':'network_result_unknown','automatic_retry':False})
            return {'state':'send_unknown','outbox_id':item['id']}
        except APIError as exc:
            uncertain=exc.code in ('invalid-response','missing-result','invalid-code') or str(exc.code).startswith('http-5')
            self.store.finish_outbox(item['id'],'unknown' if uncertain else 'failed',{'reason':'api_error','code':exc.code,'automatic_retry':False})
            if exc.code==-14:raise
            return {'state':'send_unknown' if uncertain else 'send_rejected','code':exc.code,'outbox_id':item['id']}
        except (ValueError,OSError):
            self.store.finish_outbox(item['id'],'failed',{'reason':'local_validation_failed','automatic_retry':False})
            return {'state':'send_validation_failed','outbox_id':item['id']}
        except NativePending:
            self.store.defer_outbox(item['id']);return {'state':'waiting_for_visible_source','outbox_id':item['id']}

    def cycle(self,timeout=35):
        changes={'stored':0,'queued':0,'conflicts':0}
        timing={}
        source_error=None
        visible_sync=None
        native=getattr(self.runner,'native',False)
        visible_enabled=native and hasattr(self.runner,'visible_scan')
        if visible_enabled and time.monotonic()-self.last_visible_check>=2:
            self.last_visible_check=time.monotonic()
            try:visible_sync=self.store.apply_visible_scan(self.runner.visible_scan(self.store.visible_checkpoint()))
            except (NativePending,ValueError,OSError):visible_sync={'state':'unavailable','checkpoint_unchanged':True}
        before=self.store.snapshot()
        backlog=before['jobs'].get('pending',0) or (before['outbox'].get('pending',0) and before['has_context'])
        if not backlog:
            try:
                response=self.api.poll(self.store.cursor(),timeout=min(timeout,3) if visible_enabled else timeout)
                timing['poll_completed_at']=time.time()
                changes=self.store.ingest(response['msgs'],response['get_updates_buf'])
            except (TransportError,APIError):
                if not backlog:raise
                source_error='source_unavailable'
        generated=0;state='ready';native_wait_reason=None
        job=self.store.claim_job()
        if job:
            try:
                timing['runner_attempt_started_at']=time.time()
                if native:
                    job['items']=self.store.message_items(job['id'])
                    job['raw_text']=self.store.message_text(job['id'])
                    job['received_at']=self.store.message_received_at(job['id'])
                    reply=self.runner.reply(job)
                else:
                    reply=self.runner(job['text'],self.store.recent_dialogue(before_job_id=job['id']))
                self.store.complete_job(job['id'],reply);generated=1
            except NativePending as exc:
                native_wait_reason=str(exc)[:160]
                self.store.defer_job(job['id'],native_wait_reason or 'waiting_for_native');state='waiting_for_native_conversation'
            except Exception:
                if getattr(self.runner,'native',False):
                    # A corrupt/unknown native receipt can follow an accepted
                    # submission. Keep it reconcilable; never advise replay.
                    native_wait_reason='native_request_validation_failed'
                    self.store.defer_job(job['id'],native_wait_reason)
                    state='waiting_for_native_conversation'
                else:
                    self.store.fail_job(job['id'],'reply_generation_failed',retryable=False)
                    self.store.enqueue_text('本次自动回复未完成，消息已记录。请稍后重发，或在Codex查看通道状态。','error:'+hashlib.sha256(job['id'].encode()).hexdigest())
                    state='reply_failed'
            finally:
                timing['runner_attempt_finished_at']=time.time()
                if native:
                    timing.update(getattr(self.runner,'timing',{}))
                    timing['message_id_sha256']=hashlib.sha256(job['id'].encode()).hexdigest()
        elif native and time.monotonic()-self.last_native_check>=60:
            self.last_native_check=time.monotonic()
            if not self.runner.check():state='waiting_for_native_conversation'
        timing['send_started_at']=time.time()
        sent=self.flush_one() if not source_error else {'state':'waiting_for_transport'}
        timing['send_finished_at']=time.time()
        if native and backlog:
            # Reconcile and deliver existing work before a potentially blocking
            # source poll; still collect newer inbound while a turn is running.
            try:
                response=self.api.poll(self.store.cursor(),timeout=1)
                timing['poll_completed_at']=time.time()
                changes=self.store.ingest(response['msgs'],response['get_updates_buf'])
            except (TransportError,APIError):source_error='source_unavailable'
        if state=='ready' and sent['state'] in ('send_unknown','send_rejected','send_validation_failed'):state='delivery_attention'
        return {'state':source_error or state,'ingest':changes,'generated':generated,'delivery':sent,'timing':timing,'counts':self.store.snapshot(),
                **({'original_audio':self.originals.summary()} if self.originals else {}),
                **({'visible_sync':visible_sync} if visible_sync else {}),
                **({'native_wait_reason':native_wait_reason} if native_wait_reason else {})}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace');p.add_argument('--execute',action='store_true');p.add_argument('--once',action='store_true')
    p.add_argument('--seconds',type=int,default=3600)
    a=p.parse_args()
    if not a.execute:p.print_help();return
    if not a.workspace:p.error('explicit private workspace required')
    if not 1<=a.seconds<=86400:p.error('seconds must be 1..86400')
    root=directory(a.workspace);cfg=read(root/'account.json')
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    with process_lock(root):
        if not (root/'native-context.json').exists():raise RuntimeError('same secretary context is not configured')
        s=Store(root/'state.sqlite',cfg['account_id'],cfg['peer_id'],all_messages=True);s.recover_running()
        runner=NativeRunner(root)
        from .originals import OriginalPreserver
        originals=OriginalPreserver(root,cfg['account_id'],cfg['peer_id']);originals.start()
        worker=Worker(s,WeixinAPI(cfg['base_url'],cfg['token']),runner,originals)
        failures=0;end=time.monotonic()+a.seconds;last_logged=0;empty_fast=0
        try:
            while not stopped and time.monotonic()<end:
                started=time.time()
                try:
                    result=worker.cycle();failures=0
                    receipt={'at':time.time(),'started':started,**result}
                except APIError as exc:
                    failures+=1;receipt={'at':time.time(),'state':'session_expired' if exc.code==-14 else 'api_failure','code':exc.code,'counts':s.snapshot()}
                except (TransportError,ValueError,OSError):
                    failures+=1;receipt={'at':time.time(),'state':'source_unavailable','counts':s.snapshot()}
                receipt['implementation']='same-dialogue-visible-sync-v4.3'
                write(root/'status.json',receipt)
                changed=receipt.get('generated',0) or receipt.get('ingest',{}).get('stored',0) or receipt.get('delivery',{}).get('state') not in (None,'idle','waiting_for_inbound_context')
                if a.once or changed or failures or time.time()-last_logged>300:
                    print(json.dumps(receipt,ensure_ascii=False),flush=True);last_logged=time.time()
                if a.once:break
                empty_fast=empty_fast+1 if not changed and time.time()-started<2 else 0
                pending=receipt.get('counts',{}).get('jobs',{}).get('pending',0) or receipt.get('counts',{}).get('outbox',{}).get('pending',0)
                pause=3600 if receipt['state']=='session_expired' else min(300,2**min(failures,8)) if failures else 1 if pending or hasattr(runner,'visible_scan') else min(15,1+empty_fast)
                wait_end=min(end,time.monotonic()+pause)
                while not stopped and time.monotonic()<wait_end:time.sleep(min(1,wait_end-time.monotonic()))
        finally:
            originals.close(timeout=1)
            s.close()


if __name__=='__main__':main()
