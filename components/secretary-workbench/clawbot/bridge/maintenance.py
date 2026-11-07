"""Explicit, lock-held reconciliation; never infers intent or sends messages."""
import hashlib
import json
from pathlib import Path
import time
from .private import directory,read
from .store import Store,_hash,_json
from .worker import process_lock
from .native_runner import THREAD

def cover_in_main(workspace,plan,*,execute=False):
    if not execute:return {'state':'dry_run','network_send':False,'native_submission':False}
    root=directory(workspace)
    with process_lock(root):
        cfg=read(root/'account.json');native=read(root/'native-context.json')
        if native.get('thread_id')!=THREAD:raise ValueError('wrong main conversation')
        binding=_hash(_json([cfg['account_id'],cfg['peer_id']]))
        if plan.get('binding_sha256')!=binding or plan.get('main_thread_id')!=THREAD:raise ValueError('maintenance binding mismatch')
        audit_path=Path(plan.get('audit_path',''))
        if not audit_path.is_absolute():raise ValueError('private native audit required')
        audit=read(audit_path)
        if hashlib.sha256(audit_path.read_bytes()).hexdigest()!=plan.get('audit_sha256'):raise ValueError('native audit changed')
        checked=audit.get('checked_at')
        if type(checked) not in (int,float) or not 0<=time.time()-checked<=300 or audit.get('queue_complete') is not True or audit.get('main_thread_id')!=THREAD or not isinstance(audit.get('queue'),list):raise ValueError('fresh complete native queue audit required')
        snapshots={}
        for source in plan.get('sources',[]):
            mid=source.get('message_id');key=_hash(mid) if isinstance(mid,str) else ''
            if any(q.get('clientUserMessageId')=='weixin-'+key for q in audit['queue']):raise ValueError('source is still in native queue')
            journal=root/'native-requests'/(key+'.json');link=root/'native-links'/(key+'.json')
            snapshot={'state':'no_native_request_created'}
            if journal.exists() or journal.is_symlink():
                j=read(journal)
                if j.get('message_id')!=mid or j.get('client_id')!='weixin-'+key or j.get('turn_id') or j.get('native_message_id') or j.get('last_native_state')!='submission_unknown':raise ValueError('native request needs independent reconciliation')
                snapshot={k:j.get(k) for k in ['version','state','last_native_state','queue_id','anchor_turn_id','turn_id','native_message_id','prompt_hash','items_hash']}
                snapshot['journal_sha256']=hashlib.sha256(journal.read_bytes()).hexdigest()
            if link.exists() or link.is_symlink():
                value=read(link)
                if value.get('wx_message_id')!=mid or value.get('client_id')!='weixin-'+key or value.get('thread_id')!=THREAD or value.get('turn_id') or value.get('native_message_id'):raise ValueError('native mapping requires independent reconciliation')
                snapshot['link_sha256']=hashlib.sha256(link.read_bytes()).hexdigest()
            snapshots[mid]=snapshot
        store=Store(root/'state.sqlite',cfg['account_id'],cfg['peer_id'],all_messages=True)
        try:
            result=store._cover_in_main(plan,snapshots)
            # Independent SQL readback, not an optimistic in-memory return.
            result['records']=[store.coverage_record(s['message_id']) for s in plan['sources']]
            if any(r is None for r in result['records']):raise RuntimeError('maintenance readback missing')
            return result
        finally:store.close()
