"""Explicit resident native small-account bridge, single owner and persistent queue."""
import argparse,fcntl,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
from queue_store import Queue
from remote import ACCOUNT,PEER
from privacy import model_text

REUSE=Path('/opt/secretary-workbench/clawbot')
SHARED=Path('/var/lib/secretary-clawbot')
PRIVATE_ROOT=Path('/home/operator/Library/Application Support/TashanNativeWeixinBridge')

def validate_workspace(value):
    root=Path(value)
    if root!=PRIVATE_ROOT:raise ValueError('only the explicitly paired private workspace is supported')
    for x in [root,*root.parents]:
        if x.is_symlink():raise ValueError('symlink workspace')
    return root

def remote(body,run=subprocess.run):
    # The remote command is fixed; all user content is JSON stdin, never shell code.
    r=run(['/usr/bin/ssh','-oBatchMode=yes','-oConnectTimeout=10','-oServerAliveInterval=10',
        '-oServerAliveCountMax=2','secretary-wechat-host','python3 /var/lib/secretary-wechat/native-v2/remote.py --execute'],
        input=json.dumps(body,ensure_ascii=False),text=True,capture_output=True,timeout=35)
    if len(r.stdout.encode())>2000000:raise ValueError('oversized source response')
    if r.returncode:raise ConnectionError('AUP source or GUI unavailable')
    result=json.loads(r.stdout)
    if not isinstance(result,dict) or result.get('state')=='error':raise ConnectionError('AUP adapter unavailable')
    if body.get('action')=='read' and result.get('api_version')!=2:raise ConnectionError('AUP source protocol version mismatch')
    return result

def cycle(q,runner,call=remote,voice_root=None):
    source=call({'action':'read','after':q.cursor()})
    q.ingest(source['events'],source['cursor'])
    if source.get('api_version')==2 and source.get('batch_id'):
        committed=q.committed_server_ids(source['events'])
        if committed!=source['ack_ids']:raise ValueError('captured source batch identities differ')
        call({'action':'ack','batch_id':source['batch_id'],'batch_hash':source['batch_hash'],'ack_ids':committed})
    health=source.get('health',{})
    if health.get('native_client_active') is False:
        call({'action':'recover'})
        return {'state':'starting_native_wechat','counts':q.counts(),'health':health}
    if source.get('has_more') or (source.get('api_version')==2 and source['events']):
        return {'state':'catching_up_source','counts':q.counts(),'health':health}
    state='listening';job=q.next_job()
    if voice_root is not None:
        from voice import ready_to_attempt
        e=next((v for v in q.pending_voices() if ready_to_attempt(v,voice_root)),None)
        if e:
            from voice import transcribe
            text=transcribe(e,voice_root,call)
            if text:
                q.voice_text(e['id'],'【普通小号收到本人的微信语音；以下为本地自动转写，未经人工核听，专名和金额须核实。真实来源：'+e['id']+'；serverId='+str(e['server_id'])+'】\n'+text)
                job=q.next_job()
            else:
                state='voice_reading_attention'
                q.notice(e['id'],'语音消息已在本地保存，但这次自动转写尚未完成。原始消息和定位都保留了，恢复后会继续，不会根据语音占位猜测内容。')
    if job:
        missing=q.earlier_unread_voice(job)
        if missing:
            state='voice_reading_attention'
            q.notice(missing['id'],'前一条语音尚未成功转写，后面的消息已保存。为避免误解“照上一条做”等指令，我先保留顺序，恢复读取后继续处理。')
            job=None
    provisional=q.provisional_before(source.get('provisional',[]),job)
    if provisional:
        state='source_identity_attention'
        job=None
    if job:
        sys.path.insert(0,str(REUSE));from bridge.native_runner import NativePending
        try:
            safe_job={**job,'text':model_text(job['text'])}
            reply=runner.reply(safe_job);q.finish(job['id'],reply);state='reply_ready'
        except NativePending:
            state='waiting_for_secretary'
            if time.time()-job['created']>10:
                q.notice(job['id'],'已收到，消息已保存并排入同一个秘书对话。当前对话还有工作在处理，完成后会在这里回你。')
        except Exception:
            q.fail(job['id'],'native_generation_attention');state='generation_attention'
    for item in q.uncertain():
        result=call({'action':'delivery','request_id':hashlib.sha256(item['id'].encode()).hexdigest()})
        if result.get('state')=='accepted':
            q.mark_outbox(item['id'],'accepted',{**result,'readonly_reconciliation':True,'resend_performed':False})
            if not state.endswith('attention'):state='delivery_reconciled'
    out=q.outbox()
    if out:
        item=out[0];rid=hashlib.sha256(item['id'].encode()).hexdigest()
        # AUP journals the ID BEFORE touching UI. Repeated requests only reconcile.
        result=call({'action':'send','text':item['text'],'request_id':rid})
        if result.get('state')=='accepted':
            q.mark_outbox(item['id'],'accepted',result)
            if not state.endswith('attention') and state!='waiting_for_secretary':state='reply_sent'
        elif result.get('state')=='unknown':q.mark_outbox(item['id'],'unknown',result);state='delivery_attention'
        elif result.get('state')=='blocked_by_uncertain_send':state='delivery_attention'
        else:state='waiting_for_wechat_transport'
    if health.get('paired_window_ready') is False:state='wechat_window_attention'
    return {'state':state,'counts':q.counts(),'source_has_more':source.get('has_more',False),'source_protocol':source.get('api_version'),'health':health}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace');p.add_argument('--execute',action='store_true');p.add_argument('--once',action='store_true')
    p.add_argument('--since',type=float);p.add_argument('--seconds',type=int,default=3600)
    a=p.parse_args()
    if not a.execute:p.print_help();return
    raise SystemExit('Ordinary WeChat model listener retired. Use Secretary/tools/wechat_linux.py for explicit on-demand tools; ClawBot owns direct dialogue.')
    if not a.workspace or not Path(a.workspace).is_absolute():p.error('explicit absolute private workspace required')
    if not 1<=a.seconds<=86400:p.error('seconds must be 1..86400')
    root=validate_workspace(a.workspace)
    root.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(root,0o700)
    os.umask(0o077)
    fd=os.open(root/'worker.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    sys.path.insert(0,str(REUSE));from bridge.native_runner import NativeRunner
    runner=NativeRunner(SHARED)
    q=Queue(root/'queue.sqlite',ACCOUNT,PEER,a.since if a.since is not None else time.time())
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    end=time.monotonic()+a.seconds;last=None;failures=0;last_log=0
    try:
        while not stopped and time.monotonic()<end:
            began=time.time()
            try:status=cycle(q,runner,voice_root=root);failures=0
            except (ConnectionError,subprocess.TimeoutExpired,OSError,ValueError):
                failures+=1;status={'state':'connection_attention','counts':q.counts(),'failure_count':failures}
            status.update(at=time.time(),started=began)
            temp=root/'status.tmp';temp.write_text(json.dumps(status,ensure_ascii=False));os.chmod(temp,0o600);temp.replace(root/'status.json')
            marker=json.dumps({k:v for k,v in status.items() if k not in ('at','started')},sort_keys=True)
            if marker!=last or time.time()-last_log>300:
                print(json.dumps(status),flush=True);last=marker;last_log=time.time()
            if a.once:break
            pause=min(60,2**min(failures,6)) if failures else 2
            until=min(end,time.monotonic()+pause)
            while not stopped and time.monotonic()<until:time.sleep(min(0.5,until-time.monotonic()))
    finally:q.close();os.close(fd)

if __name__=='__main__':main()
