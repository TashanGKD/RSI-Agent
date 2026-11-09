"""Small source-identity receipts only, no message bodies, task state or queue."""
import os,sqlite3,time
from pathlib import Path
from receive_source import sid

class Metadata:
    def __init__(self,path):
        path=Path(path)
        if path.is_symlink():raise ValueError('symlink metadata receipt file')
        if not path.exists():fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        if path.stat().st_mode&0o077 or path.stat().st_uid!=os.getuid():raise ValueError('private identity receipts required')
        self.c=sqlite3.connect(path)
        self.c.execute('create table if not exists observed(peer text,server_id text,sender text,source text,stored_at real,primary key(peer,server_id))')
    def close(self):self.c.close()
    def get(self,peer,server):
        r=self.c.execute('select sender,source,stored_at from observed where peer=? and server_id=?',(peer,sid(server))).fetchone()
        return {'senderId':r[0],'senderEvidence':r[1],'evidenceStoredAt':r[2]} if r else None
    def remember(self,peer,server,sender,source):
        from linux_tool import require_peer
        require_peer(peer);require_peer(sender);server=sid(server)
        if not isinstance(source,str) or len(source)>160:raise ValueError('bounded identity source required')
        old=self.get(peer,server)
        if old and old['senderId']!=sender:raise ValueError('source identity conflict; retained prior evidence')
        if old:return
        if self.c.execute('select count(*) from observed').fetchone()[0]>=10000:raise ValueError('metadata receipt cap reached; explicit maintenance needed')
        with self.c:self.c.execute('insert into observed values(?,?,?,?,?)',(peer,server,sender,source,time.time()))
