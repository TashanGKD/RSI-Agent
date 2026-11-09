"""One bounded thread inside the existing worker; source is immutable intake.

Supplemental receipts/assets never rewrite a submitted manifest or native input.
No credentials/locators in receipts; only current top-level voice items are read.
"""
import argparse
from contextlib import contextmanager,closing
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import time
from urllib.parse import quote
from . import private,media

def digest(raw):return hashlib.sha256(raw).hexdigest()
def item_hash(item):return digest(json.dumps(item,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode())

class OriginalPreserver:
    def __init__(self,workspace,account_id,peer_id,download=None):
        self.root=private.directory(workspace);self.account_id=account_id;self.peer_id=peer_id
        self.preparer=media.MediaPreparer(self.root,download=download)
        self.stop=threading.Event();self.thread=None;self.cursor=0
        self.last={'state':'idle'};self._source_rows(0,1)

    def _source_rows(self,after=0,limit=50,message_id=None):
        p=self.root/'state.sqlite'
        if p.is_symlink():raise ValueError('unsafe original source')
        s=p.stat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_nlink!=1:raise ValueError('unsafe original source')
        with closing(sqlite3.connect('file:'+quote(str(p))+'?mode=ro',uri=True,timeout=1)) as c:
            c.row_factory=sqlite3.Row
            row=c.execute("select value from meta where key='binding'").fetchone()
            if not row or json.loads(row[0])!=[self.account_id,self.peer_id]:raise ValueError('original source binding mismatch')
            if message_id is not None:rows=c.execute('select rowid,id,body,body_hash from incoming where id=?',(message_id,)).fetchall()
            else:rows=c.execute('select rowid,id,body,body_hash from incoming where rowid>? order by rowid limit ?',(after,limit)).fetchall()
        for r in rows:
            if len(r['body'].encode())>4*1024*1024 or digest(r['body'].encode())!=r['body_hash']:raise ValueError('original source integrity failed')
        return rows

    def _item(self,mid,index):
        if not isinstance(mid,str) or not mid or len(mid.encode())>512 or '\0' in mid or type(index) is not int or not 0<=index<20:raise ValueError('invalid original identity')
        rows=self._source_rows(message_id=mid)
        if len(rows)!=1:raise ValueError('original source not found')
        items=json.loads(rows[0]['body'])
        if not isinstance(items,list) or index>=len(items):raise ValueError('original item not found')
        item=items[index]
        if not isinstance(item,dict) or type(item.get('type')) is not int or item['type']!=3 or not isinstance(item.get('voice_item'),dict):raise ValueError('not a current voice item')
        return item

    def receipt_path(self,mid,index):
        if not isinstance(mid,str) or type(index) is not int or not 0<=index<20:raise ValueError('invalid original identity')
        return self.root/'original-receipts'/(digest(mid.encode())+'-item-%02d.json'%index)

    def ensure_pending(self,mid,index,item):
        if self._item(mid,index)!=item:raise ValueError('changed original source')
        p=self.receipt_path(mid,index)
        if p.exists() or p.is_symlink():return self.query(mid,index)
        private.directory(p.parent)
        r={'version':1,'message_id':mid,'item_index':index,'source_item_sha256':item_hash(item),
           'status':'pending','original_audio_obtained':False,'attempts':0,'created_at':time.time()}
        private.write(p,r);return r

    def query(self,mid,index):
        item=self._item(mid,index);p=self.receipt_path(mid,index)
        if not p.exists() and not p.is_symlink():return {'message_id':mid,'item_index':index,'status':'pending','original_audio_obtained':False,'receipt_created':False}
        r=private.read(p)
        if r.get('version')!=1 or r.get('message_id')!=mid or r.get('item_index')!=index or r.get('source_item_sha256')!=item_hash(item) or r.get('status') not in ('pending','fetching','saved','failed'):raise ValueError('original receipt identity mismatch')
        if type(r.get('attempts')) is not int or not 0<=r['attempts']<=3 or ('candidate' in r and not isinstance(r['candidate'],dict)):raise ValueError('invalid original receipt')
        candidate=r.get('candidate')
        if candidate is not None and (not isinstance(candidate.get('path'),str) or type(candidate.get('size')) is not int or not 0<candidate['size']<=media.MAX_ITEM_BYTES or not isinstance(candidate.get('sha256'),str) or len(candidate['sha256'])!=64):raise ValueError('invalid original candidate')
        if not isinstance(r.get('history',[]),list):raise ValueError('invalid original receipt history')
        if r.get('retry_at') is not None and (type(r['retry_at']) not in (int,float) or not math.isfinite(r['retry_at']) or r['retry_at']<0):raise ValueError('invalid original retry time')
        if r['status']=='saved':
            try:self._verify_asset(mid,index,r)
            except (ValueError,OSError):return {**r,'status':'failed','original_audio_obtained':False,'code':'saved_original_integrity_failed'}
        return r

    def _verify_asset(self,mid,index,r):
        target=self.root/'media'/digest(mid.encode())
        allowed=(target/('item-%02d-original.audio'%index),target/'originals'/('item-%02d.audio'%index))
        if r.get('path') not in [str(p) for p in allowed]:raise ValueError('unmanaged original asset')
        raw=media._regular_bytes(Path(r['path']),media.MAX_ITEM_BYTES)
        if len(raw)!=r.get('size') or digest(raw)!=r.get('sha256'):raise ValueError('original hash mismatch')
        return raw

    def _save(self,mid,index,r,**changes):
        r={**r,**changes,'updated_at':time.time()}
        history=r.get('history',[])[-7:]+[{'at':r['updated_at'],'status':r['status'],'code':r.get('code')}]
        r['history']=history;private.write(self.receipt_path(mid,index),r)
        self.last={'state':r['status'],'message_id_sha256':digest(mid.encode()),'item_index':index,'code':r.get('code'),'at':r['updated_at']}
        return r

    @contextmanager
    def _lock(self,name):
        fd=os.open(self.root/name,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            s=os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_nlink!=1 or s.st_mode&0o077:raise ValueError('unsafe original lock')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);yield
        finally:os.close(fd)

    def _budget(self,target,size=0):
        usage=self.preparer._usage()
        message=sum(p.stat().st_size for p in target.rglob('*') if p.is_file())
        if size>media.MAX_ITEM_BYTES or message+size+65536>media.MAX_MESSAGE_BYTES or usage+size+65536>media.MAX_WORKSPACE_BYTES:raise media.MediaFailure('media_budget_exceeded')

    def _reuse(self,mid,index):
        target=self.root/'media'/digest(mid.encode());manifest=target/'manifest.json'
        if manifest.exists() or manifest.is_symlink():
            m=private.read(manifest)
            if m.get('message_id')!=mid:raise ValueError('manifest identity mismatch')
            for a in m.get('assets',[]):
                if a.get('kind')=='voice-original' and a.get('path')==str(target/('item-%02d-original.audio'%index)):
                    self._verify_asset(mid,index,a);return a
        return None

    def _fetch(self,mid,index,item,r):
        target=private.directory(self.root/'media'/digest(mid.encode()))
        try:
            # This lock is short; never hold the shared media lock over network.
            with self._lock('media/.lock'):
                reused=self._reuse(mid,index)
                if reused:
                    self._save(mid,index,r,status='saved',original_audio_obtained=True,reused=True,
                               path=reused['path'],size=reused['size'],sha256=reused['sha256'],saved_at=time.time());return
                if r.get('candidate') and Path(r['candidate'].get('path','')).exists():
                    self._verify_asset(mid,index,r['candidate'])
                    self._save(mid,index,r,status='saved',original_audio_obtained=True,recovered=True,**r['candidate'],saved_at=time.time());return
                if r.get('attempts',0)>=3:
                    self._save(mid,index,r,status='failed',code='attempts_exhausted',original_audio_obtained=False,retryable=False);return
                self._budget(target)
            r=self._save(mid,index,r,status='fetching',original_audio_obtained=False,attempts=r.get('attempts',0)+1,fetch_started_at=time.time())
            self.preparer.voice_deadline=time.monotonic()+20
            raw=self.preparer._download(item['voice_item'],3)
            if self.stop.is_set():
                self._save(mid,index,r,status='pending',code='worker_stopping',original_audio_obtained=False);return
            if self._item(mid,index)!=item:raise ValueError('changed original source')
            with self._lock('media/.lock'):
                self._budget(target,len(raw))
                path=private.directory(target/'originals')/('item-%02d.audio'%index)
                candidate={'path':str(path),'size':len(raw),'sha256':digest(raw)}
                r=self._save(mid,index,r,candidate=candidate)
                if path.exists() or path.is_symlink():
                    # Never overwrite or delete an existing original.
                    self._verify_asset(mid,index,candidate)
                else:
                    fd,tmp=tempfile.mkstemp(prefix='.original-',dir=path.parent)
                    try:
                        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                        os.link(tmp,path,follow_symlinks=False)
                    finally:os.unlink(tmp)
                    parent=os.open(path.parent,os.O_RDONLY)
                    try:os.fsync(parent)
                    finally:os.close(parent)
                self._verify_asset(mid,index,candidate)
                self._save(mid,index,r,status='saved',original_audio_obtained=True,reused=False,**candidate,saved_at=time.time())
        except BlockingIOError:
            self._save(mid,index,r,status='pending',code='media_busy',original_audio_obtained=False)
        except (media.MediaFailure,OSError,ValueError) as exc:
            code='media_budget_exceeded' if str(exc)=='media_budget_exceeded' else 'unapproved_cdn_url' if isinstance(exc,media.MediaFailure) and 'unapproved CDN' in str(exc) else 'original_integrity_failed' if isinstance(exc,ValueError) and not isinstance(exc,media.MediaFailure) else 'download_failed'
            retryable=code=='download_failed' and r.get('attempts',0)<3
            self._save(mid,index,r,status='failed',code=code,original_audio_obtained=False,retryable=retryable,retry_at=time.time()+60 if retryable else None)

    def sweep_once(self):
        """Inspect at most 50 persisted rows and fetch at most one voice item."""
        try:
            with self._lock('originals.lock'):
                rows=self._source_rows(self.cursor)
                if not rows:self.cursor=0;return False
                for row in rows:
                    items=json.loads(row['body'])
                    for index,item in enumerate(items[:20]):
                        if not isinstance(item,dict) or type(item.get('type')) is not int or item['type']!=3:continue
                        r=self.ensure_pending(row['id'],index,item)
                        if r['status']=='saved':continue
                        if r['status']=='failed' and (not r.get('retryable') or time.time()<r.get('retry_at',0)):continue
                        self._fetch(row['id'],index,item,r);return True
                    self.cursor=row['rowid']
                return False
        except BlockingIOError:return False

    def start(self):
        if self.thread is not None:return
        def loop():
            while not self.stop.is_set():
                try:self.sweep_once()
                except (ValueError,OSError,sqlite3.Error):self.last={'state':'source_or_receipt_attention','at':time.time()}
                self.stop.wait(1)
        self.thread=threading.Thread(target=loop,name='clawbot-originals',daemon=True);self.thread.start()

    def summary(self):return dict(self.last)

    def close(self,timeout=1):
        self.stop.set()
        if self.thread:self.thread.join(timeout=max(0,min(1,timeout)))

def main():
    p=argparse.ArgumentParser(description='Read one original-audio preservation receipt. No downloads or model calls.')
    p.add_argument('--workspace');p.add_argument('--message-id');p.add_argument('--item-index',type=int)
    a=p.parse_args()
    if not a.workspace or not a.message_id or a.item_index is None:p.print_help();return
    root=private.directory(a.workspace);cfg=private.read(root/'account.json')
    print(json.dumps(OriginalPreserver(root,cfg['account_id'],cfg['peer_id']).query(a.message_id,a.item_index),ensure_ascii=False))

if __name__=='__main__':main()
