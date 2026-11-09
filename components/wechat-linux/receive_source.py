"""Durable, bounded source batches; stable server IDs, ACK after consumer commit.

The native database remains read-only. This receipt DB is owned by the adapter.
"""
import hashlib,json,os,re,sqlite3,time,uuid
from pathlib import Path

def sid(value):
    if type(value) is int:
        if not -(2**63)<=value<2**64 or value==0:raise ValueError('nonzero native server identity required')
        return str(value&0xffffffffffffffff)
    if not isinstance(value,str) or not re.fullmatch('[1-9][0-9]{0,19}',value) or int(value)>=2**64:raise ValueError('invalid server identity')
    return value

class SourceInbox:
    def __init__(self,path,native,table,account,peer,decode,epoch,stamp=None,only_incoming=False,incoming_senders=None,event_context=None):
        path=Path(path)
        if path.is_symlink():raise ValueError('symlink receipt database refused')
        if not path.exists():
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600);os.close(fd)
        if path.stat().st_mode&0o077:raise ValueError('private source receipts required')
        if not re.fullmatch(r'Msg_[A-Za-z0-9_]+',table):raise ValueError('unsafe fixed native table')
        self.c=sqlite3.connect(path,timeout=5);self.c.row_factory=sqlite3.Row
        self.native=native;self.table=table;self.account=account;self.peer=peer;self.decode=decode;self.epoch=epoch;self.stamp=stamp;self.only_incoming=only_incoming
        self.incoming_senders=None if incoming_senders is None else set(incoming_senders)-{account}
        self.event_context=event_context
        if self.incoming_senders is not None and (not only_incoming or not self.incoming_senders or len(self.incoming_senders)>1000):raise ValueError('bounded nonself group senders required')
        self.c.executescript('''CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS acked(server_id TEXT PRIMARY KEY,at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,hash TEXT NOT NULL,events TEXT NOT NULL,ids TEXT NOT NULL,state TEXT NOT NULL,at REAL NOT NULL,has_more INTEGER NOT NULL);''')
        binding=json.dumps([account,peer,only_incoming]);old=self.c.execute("select v from meta where k='binding'").fetchone()
        if old and old[0]!=binding:raise ValueError('source receipt binding mismatch')
        with self.c:self.c.execute("insert or ignore into meta values('binding',?)",(binding,))
    def close(self):self.c.close()
    def _response(self,r):
        events=json.loads(r['events'])
        return {'api_version':2,'batch_id':r['id'],'batch_hash':r['hash'],'ack_ids':json.loads(r['ids']),
            'events':events,'cursor':max((e['local_id'] for e in events),default=0),'has_more':bool(r['has_more']),'provisional':self._provisional()}
    def _provisional(self):
        row=self.c.execute("select v from meta where k='provisional'").fetchone()
        return json.loads(row[0]) if row else []
    def _empty(self):return {'api_version':2,'events':[],'cursor':0,'has_more':False,'provisional':self._provisional()}
    def read(self):
        self.c.execute('BEGIN IMMEDIATE')
        n=None
        try:
            old=self.c.execute("select * from batches where state='pending' order by at limit 1").fetchone()
            if old:
                result=self._response(old);self.c.commit();return result
            signature=self.stamp() if self.stamp else None
            cached=self.c.execute("select v from meta where k='empty_stamp'").fetchone()
            if signature is not None and cached:
                saved=json.loads(cached[0])
                if saved['signature']==signature and time.time()-saved['checked']<60:
                    self.c.commit();return self._empty()
            n=self.native()
            if n.row_factory is None:n.row_factory=sqlite3.Row
            n.execute('BEGIN')
            names=[self.account,self.peer] if self.incoming_senders is None else [self.account,*sorted(self.incoming_senders)]
            ids={int(r[0]):r[1] for r in n.execute('select rowid,user_name from Name2Id where user_name in ('+','.join('?' for _ in names)+')',names)}
            if self.account not in ids.values() or (self.incoming_senders is None and set(ids.values())!={self.account,self.peer}):raise ValueError('paired identities unavailable')
            if self.incoming_senders is None:allowed=tuple(k for k,v in ids.items() if not self.only_incoming or v==self.peer)
            else:allowed=tuple(k for k,v in ids.items() if v in self.incoming_senders)
            if not allowed:self.c.commit();return self._empty()
            rows=n.execute('select local_id,server_id,local_type,real_sender_id,create_time,sort_seq from '+self.table+
                ' where real_sender_id in ('+','.join('?' for _ in allowed)+') order by create_time,sort_seq,local_id,server_id limit 100001',allowed).fetchall()
            if len(rows)>100000:raise ValueError('paired metadata catalog exceeds bounded review limit')
            provisional=[{'local_id':int(r['local_id']),'created':int(r['create_time'] or 0),'sort_seq':int(r['sort_seq'] or 0),'sender':ids[r['real_sender_id']],'kind':int(r['local_type'])&0xffffffff} for r in rows if not r['server_id'] and int(r['local_type'])&0xffffffff in (1,3,34,42,43,47,48,49)]
            self.c.execute("insert or replace into meta values('provisional',?)",(json.dumps(provisional),))
            known={r[0] for r in self.c.execute('select server_id from acked')}
            unseen=[];selected=set()
            for r in rows:
                if not r['server_id']:continue
                key=sid(r['server_id'])
                if key not in known and key not in selected:
                    unseen.append(r);selected.add(key)
            if not unseen:
                if signature is not None and self.stamp()==signature:
                    self.c.execute("insert or replace into meta values('empty_stamp',?)",(json.dumps({'signature':signature,'checked':time.time()}),))
                self.c.commit();return self._empty()
            events=[];size=0
            for meta in unseen[:128]:
                # Same read transaction and exact scanned server ID, never a reused local coordinate.
                matches=n.execute('select * from '+self.table+' where server_id=?',(meta['server_id'],)).fetchall()
                if not matches:raise ValueError('discovered server identity disappeared before capture')
                row=next((x for x in matches if x['real_sender_id']==meta['real_sender_id'] and x['local_type']==meta['local_type']),None)
                if row is None:raise ValueError('conflicting native server identity')
                kind=int(row['local_type'])&0xffffffff
                logical={(x['real_sender_id'],int(x['local_type'])&0xffffffff,self.decode(x['message_content']) if int(x['local_type'])&0xffffffff==1 else '') for x in matches}
                if len(logical)!=1:raise ValueError('same native server identity has conflicting bodies')
                e={'account':self.account,'peer':self.peer,'sender':ids[row['real_sender_id']],'epoch':self.epoch,
                   'local_id':int(row['local_id']),'server_id':int(sid(row['server_id'])),'kind':kind,
                   'created':int(row['create_time']),'sort_seq':int(row['sort_seq'] or 0),
                   'text':self.decode(row['message_content']) if kind==1 else ''}
                if self.event_context:
                    extra=self.event_context(row,e)
                    if set(extra)&set(e):raise ValueError('source identity/context collision')
                    e.update(extra)
                encoded=json.dumps(e,ensure_ascii=False,sort_keys=True)
                if len(encoded.encode())>40000:raise ValueError('source event exceeds body cap')
                if events and size+len(encoded.encode())>1000000:break
                size+=len(encoded.encode());events.append(e)
            raw=json.dumps(events,ensure_ascii=False,sort_keys=True);digest=hashlib.sha256(raw.encode()).hexdigest()
            token=uuid.uuid4().hex;keys=[str(e['server_id']) for e in events]
            self.c.execute("insert into batches values(?,?,?,?,?,?,?)",(token,digest,raw,json.dumps(keys),'pending',time.time(),int(len(unseen)>len(events))))
            result=self._response(self.c.execute('select * from batches where id=?',(token,)).fetchone())
            self.c.commit();return result
        except BaseException:self.c.rollback();raise
        finally:
            if n is not None:
                n.rollback()
                n.close()
    def ack(self,batch,content_hash,identities):
        if not isinstance(batch,str) or not re.fullmatch('[a-f0-9]{32}',batch):raise ValueError('invalid batch identity')
        if not isinstance(content_hash,str) or not re.fullmatch('[a-f0-9]{64}',content_hash):raise ValueError('invalid batch hash')
        if not isinstance(identities,list) or not 1<=len(identities)<=128:raise ValueError('invalid bounded ACK')
        keys=[sid(v) for v in identities]
        if len(set(keys))!=len(keys):raise ValueError('duplicate ACK identities')
        with self.c:
            row=self.c.execute('select * from batches where id=?',(batch,)).fetchone()
            if not row or row['hash']!=content_hash or keys!=json.loads(row['ids']):raise ValueError('ACK differs from captured batch')
            if row['state']=='acked':return {'state':'acked','duplicate':True}
            for key in keys:self.c.execute('insert or ignore into acked values(?,?)',(key,time.time()))
            self.c.execute("update batches set state='acked',events='[]' where id=?",(batch,))
        return {'state':'acked','count':len(keys)}
