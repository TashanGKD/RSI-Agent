import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
from crypto import decrypt_file
from crypto import _page
from playback import PlaybackUnavailable, noop_checkpoint
from security import decode_content, qid, safe_path, xml_root

DEFAULT_ROOT=Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'


def database_files(root):
    for attempt in range(3):
        try:return [p for p in Path(root).rglob('*.db') if not p.is_symlink()]
        except InterruptedError:
            if attempt==2:raise


@contextmanager
def read_db(path):
    con=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    con.row_factory=sqlite3.Row
    try:yield con
    finally:con.close()


def columns(con, table):
    return [r[1] for r in con.execute('PRAGMA table_info('+qid(table)+')')]


def snapshot_stamp(paths):
    result=[]
    for p in paths:
        if not p.exists():result.append(None);continue
        st=p.stat();header=None
        if str(p).endswith('-shm'):
            with p.open('rb') as f:header=f.read(96)
        result.append((st.st_size,st.st_mtime_ns,st.st_ctime_ns,header))
    return result


def rendered(kind, raw):
    text=re.sub(r'^[A-Za-z0-9_@.\-]+:\n','',raw,count=1)
    if kind==1: return text,{}
    metadata={}
    if text.lstrip().startswith('<'):
        root=xml_root(text)
        if root is not None:
            for tag in ('title','des','url','md5','filename','fileext','filelength','duration','voicelength'):
                node=root.find('.//'+tag)
                if node is not None and node.text: metadata[tag]=node.text
            for tag in ('voicemsg','img','videomsg','emoji'):
                node=root.find('.//'+tag)
                if node is not None: metadata.update(node.attrib)
            typ=root.find('.//appmsg/type')
            if typ is not None:metadata['type']=typ.text or ''
            ref=root.find('.//refermsg')
            if ref is not None:metadata['quote']={'name':ref.findtext('displayname',''),'text':ref.findtext('content','')}
    labels={3:'图片',34:'语音',43:'视频',47:'表情',48:'位置',42:'名片',49:'链接 / 文件 / 引用',50:'通话',10000:'系统消息'}
    title=metadata.get('title') or metadata.get('des')
    if kind==10000: title=re.sub('<[^>]+>','',text)
    return title or labels.get(kind, f'消息类型 {kind}'),metadata


class Library:
    def __init__(self,state,source=DEFAULT_ROOT,checkpoint=noop_checkpoint):
        self.checkpoint=checkpoint
        self._account_cache=None;self._conversation_cache={}
        self.state=Path(state);self.source=Path(source)
        self.state.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(self.state,0o700)
        self.index=self.state/'index.db';self.init()

    @contextmanager
    def connect(self):
        con=sqlite3.connect(self.index,timeout=30);con.row_factory=sqlite3.Row
        con.execute('PRAGMA busy_timeout=30000')
        try:
            with con:yield con
        finally:con.close()

    def init(self):
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS conversations(account TEXT,id TEXT,username TEXT,name TEXT,kind TEXT,PRIMARY KEY(account,id));
            CREATE TABLE IF NOT EXISTS messages(account TEXT,chat TEXT,source TEXT,local_id TEXT,server_id TEXT,time INTEGER,sender TEXT,sender_id TEXT,kind INTEGER,text TEXT,raw TEXT,metadata TEXT,PRIMARY KEY(account,chat,source,local_id));
            CREATE INDEX IF NOT EXISTS message_time ON messages(account,chat,time,local_id);
            CREATE INDEX IF NOT EXISTS account_time ON messages(account,time);
            CREATE INDEX IF NOT EXISTS account_kind_time ON messages(account,kind,time);
            CREATE TABLE IF NOT EXISTS coverage(account TEXT,path TEXT,status TEXT,error TEXT,bytes INTEGER,updated INTEGER,PRIMARY KEY(account,path));
            CREATE VIRTUAL TABLE IF NOT EXISTS message_search USING fts5(text,tokenize='trigram');
            CREATE TRIGGER IF NOT EXISTS message_insert AFTER INSERT ON messages BEGIN INSERT INTO message_search(rowid,text) VALUES(new.rowid,new.text); END;
            CREATE TRIGGER IF NOT EXISTS message_update AFTER UPDATE ON messages BEGIN DELETE FROM message_search WHERE rowid=old.rowid; INSERT INTO message_search(rowid,text) VALUES(new.rowid,new.text); END;
            CREATE TRIGGER IF NOT EXISTS message_delete AFTER DELETE ON messages BEGIN DELETE FROM message_search WHERE rowid=old.rowid; END;
            ''')
        os.chmod(self.index,0o600)

    def account_path(self,account):
        if not re.fullmatch(r'[A-Za-z0-9_\-]+',account): raise ValueError('invalid account')
        path=safe_path(self.source,account)
        if not (path/'db_storage').is_dir(): raise ValueError('account does not exist')
        return path

    def accounts(self):
        if self._account_cache and time.monotonic()-self._account_cache[0]<30:return self._account_cache[1]
        result=[]
        if self.source.exists():
            for a in sorted(self.source.iterdir()):
                if a.is_symlink() or not (a/'db_storage').is_dir(): continue
                warning=''
                try:dbs=database_files(a/'db_storage');byte_count=sum(x.stat().st_size for x in dbs)
                except OSError:dbs=[];byte_count=0;warning='微信目录暂时不可访问，已保存记录仍可浏览'
                with self.connect() as c:
                    count=c.execute('SELECT count(*) FROM messages WHERE account=?',(a.name,)).fetchone()[0]
                    known=[dict(r) for r in c.execute('SELECT path,status,bytes FROM coverage WHERE account=?',(a.name,))]
                present={str(p.relative_to(a/'db_storage')) for p in dbs}
                if warning:present={r['path'] for r in known}
                imported=sum(r['status']=='ready' and r['path'] in present for r in known)
                archived=sum(r['status'] in ('ready','decrypted') and r['path'] not in present for r in known)
                result.append({'id':a.name,'label':a.name,'databases':len(present),'bytes':byte_count if not warning else sum(r['bytes'] for r in known),'messages':count,'ready':imported,'archived':archived,'warning':warning})
        result=sorted(result,key=lambda a:a['bytes'],reverse=True);self._account_cache=(time.monotonic(),result)
        return result

    def coverage(self,account):
        root=self.account_path(account)
        with self.connect() as c: known={r['path']:dict(r) for r in c.execute('SELECT * FROM coverage WHERE account=?',(account,))}
        result=[]
        present=set()
        for p in sorted(database_files(root/'db_storage')):
            if p.is_symlink():continue
            rel=str(p.relative_to(root/'db_storage'))
            present.add(rel)
            result.append(known.get(rel,{'path':rel,'status':'locked','error':'尚未取得密钥','bytes':p.stat().st_size}))
        for rel,row in known.items():
            if rel not in present and row['status'] in ('ready','decrypted'):
                result.append({**row,'status':'archived','error':'源数据库已不在微信目录；保留本阅读器此前保存的历史记录'})
            elif rel not in present and row['status'] in ('locked','error'):
                result.append(row)
        return result

    def mark(self,account,rel,status,error='',size=0):
        self._account_cache=None;self._conversation_cache.clear()
        with self.connect() as c: c.execute('INSERT OR REPLACE INTO coverage VALUES(?,?,?,?,?,?)',(account,rel,status,error,size,int(time.time())))

    def clear_source(self,account,rel):
        self._account_cache=None;self._conversation_cache.clear()
        with self.connect() as c:c.execute('DELETE FROM messages WHERE account=? AND source=?',(account,rel))

    def keys_cover(self,account,config):
        try:
            root=self.account_path(account);cfg=json.loads(Path(config).read_text())
            if Path(cfg.get('db_root','')).resolve()!=root.resolve():return False
            sources=list((root/'db_storage').rglob('*.db'))
            if not sources:return False
            for source in sources:
                self.checkpoint()
                try:
                    safe_path(root,str(source.relative_to(root)))
                    if source.is_symlink():return False
                    with source.open('rb') as f:page=f.read(4096)
                    salt=page[:16];key=bytes.fromhex(cfg.get('keys',{}).get(salt.hex(),''))
                    if len(key)!=32:
                        rel=str(source.relative_to(root/'db_storage'))
                        required=re.fullmatch(r'(?:contact/contact|session/session|hardlink/hardlink|head_image/head_image|message/(?:message_[0-9]+|biz_message_[0-9]+|media_[0-9]+|message_resource))\.db',rel)
                        if required:return False
                        continue
                    mac_key=hashlib.pbkdf2_hmac('sha512',key,bytes(x^0x3a for x in salt),2,32)
                    _page(page,key,mac_key,1)
                finally:
                    self.checkpoint()
            return True
        except PlaybackUnavailable:
            raise
        except (OSError,ValueError,TypeError):return False

    def import_keys(self,account,config_path,progress=lambda s:None,contacts_only=False):
        root=self.account_path(account);config_path=Path(config_path)
        if config_path.stat().st_mode & 0o077: raise ValueError('密钥文件权限必须为 0600')
        cfg=json.loads(config_path.read_text())
        if Path(cfg.get('db_root','')).resolve()!=root.resolve(): raise ValueError('密钥账号与所选账号不一致')
        keys=cfg.get('keys',{})
        plain=self.state/'accounts'/account/'decrypted';plain.mkdir(parents=True,exist_ok=True,mode=0o700)
        snapshot=self.state/'accounts'/account/'snapshot';snapshot.mkdir(parents=True,exist_ok=True,mode=0o700)
        eligible_sources=set()
        for source in sorted((root/'db_storage').rglob('*.db')):
            rel=str(source.relative_to(root/'db_storage'));dest=safe_path(plain,rel);snap=safe_path(snapshot,rel)
            if contacts_only and rel!='contact/contact.db':continue
            self.checkpoint()
            try:
                try:
                    safe_path(root,str(source.relative_to(root)))
                    if source.is_symlink():raise ValueError('数据库不能是符号链接')
                except ValueError as e:
                    self.mark(account,rel,'error',str(e));continue
                with source.open('rb') as f: salt=f.read(16).hex()
                keyhex=keys.get(salt)
                if not keyhex:
                    self.mark(account,rel,'locked','缺少此数据库的密钥',source.stat().st_size);continue
                progress('解密 '+rel)
                try:
                    if not re.fullmatch('[a-fA-F0-9]{64}',keyhex): raise ValueError('invalid key format')
                    pair=[source,Path(str(source)+'-wal'),Path(str(source)+'-shm')]
                    for p in pair:
                        safe_path(root,str(p.relative_to(root)))
                        if p.is_symlink():raise ValueError('数据库及日志不能是符号链接')
                    before=snapshot_stamp(pair)
                    snap.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    for p,suffix in zip(pair,('','-wal','-shm')):
                        self.checkpoint()
                        target=Path(str(snap)+suffix)
                        if p.exists(): shutil.copyfile(p,target);os.chmod(target,0o600)
                        else: target.unlink(missing_ok=True)
                        self.checkpoint()
                    after=snapshot_stamp(pair)
                    if before!=after: raise ValueError('复制期间数据库发生变化，请退出微信后重新导入')
                    decrypt_file(snap,dest,bytes.fromhex(keyhex),checkpoint=self.checkpoint)
                    self.mark(account,rel,'decrypted','',source.stat().st_size)
                    eligible_sources.add(rel)
                except PlaybackUnavailable:
                    raise
                except Exception as e:
                    self.mark(account,rel,'error',str(e),source.stat().st_size)
            finally:
                self.checkpoint()
        progress('建立会话与全文索引')
        self.import_plain(account,plain,progress,contacts_only=contacts_only,eligible_sources=eligible_sources)
        progress('导入结束；查看逐数据库覆盖情况')

    def _rows(self,rows):
        for number,row in enumerate(rows):
            if number%500==0:self.checkpoint()
            yield row

    def import_plain(self,account,plain,progress=lambda message:None,contacts_only=False,*,eligible_sources=None):
        plain=Path(plain);names={};users=set()
        # Refreshes index only copies verified in this invocation; direct resume keeps all saved sources.
        contact=plain/'contact/contact.db'
        contact_eligible=eligible_sources is None or 'contact/contact.db' in eligible_sources
        if contact_eligible and contact.exists():
            self.checkpoint()
            with read_db(contact) as c:
                tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ('contact','stranger','chat_room'):
                    if table not in tables:continue
                    cols=columns(c,table)
                    if 'username' not in cols: continue
                    for r in self._rows(c.execute('SELECT * FROM '+qid(table))):
                        u=decode_content(r['username']);users.add(u)
                        display=next((decode_content(r[x]).strip() for x in ('remark','nick_name','alias') if x in cols and r[x]),u)
                        names.setdefault(u,display)
            self.checkpoint()
        if contacts_only:
            if not contact_eligible:return
            if not contact.exists():raise ValueError('没有已验证的联系人副本')
            self.mark(account,'contact/contact.db','ready','',contact.stat().st_size)
            return
        session=plain/'session/session.db'
        if session.exists() and (eligible_sources is None or 'session/session.db' in eligible_sources):
            self.checkpoint()
            with read_db(session) as c:
                for table, in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                    cols=columns(c,table)
                    if 'username' in cols:
                        for r in self._rows(c.execute('SELECT * FROM '+qid(table))):
                            u=decode_content(r['username']);users.add(u)
                            if 'session_title' in cols and r['session_title']:names.setdefault(u,decode_content(r['session_title']))
            self.checkpoint()
        dbfiles=sorted((plain/'message').glob('message_[0-9]*.db'))+sorted((plain/'message').glob('biz_message_[0-9]*.db'))
        if eligible_sources is not None:
            dbfiles=[db for db in dbfiles if str(db.relative_to(plain)) in eligible_sources]
        # Name2Id fills in identities even when contacts are missing.
        for db in dbfiles:
            self.checkpoint()
            with read_db(db) as c:
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='Name2Id'").fetchone():
                    users.update(decode_content(r[0]) for r in self._rows(c.execute('SELECT user_name FROM Name2Id')))
            self.checkpoint()
        md5map={hashlib.md5(u.encode()).hexdigest():u for u in users}
        for db in dbfiles:
            rel=str(db.relative_to(plain))
            self.checkpoint()
            progress('更新聊天记录：'+db.name)
            try:
                with read_db(db) as c, self.connect() as out:
                    out.execute('CREATE TEMP TABLE reader_seen(chat TEXT,local_id TEXT,PRIMARY KEY(chat,local_id)) WITHOUT ROWID')
                    idmap={}
                    if c.execute("SELECT 1 FROM sqlite_master WHERE name='Name2Id'").fetchone():
                        idmap={r[0]:decode_content(r[1]) for r in self._rows(c.execute('SELECT rowid,user_name FROM Name2Id'))}
                    tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
                    for table in tables:
                        if not re.fullmatch('Msg_[a-fA-F0-9]{32}',table):continue
                        chat=table[4:];u=md5map.get(chat,chat);name=names.get(u,u)
                        kind='group' if u.endswith('@chatroom') else ('official' if u.startswith('gh_') else 'direct')
                        out.execute('INSERT OR REPLACE INTO conversations VALUES(?,?,?,?,?)',(account,chat,u,name,kind))
                        cols=columns(c,table)
                        if not {'local_type','create_time','message_content'}.issubset(cols): raise ValueError('未知消息表结构：'+table)
                        for r in self._rows(c.execute('SELECT rowid AS _rid,* FROM '+qid(table))):
                            raw=decode_content(r['message_content']);k=(r['local_type'] or 0)&0xffffffff
                            text,meta=rendered(k,raw)
                            sender=idmap.get(r['real_sender_id'],'') if 'real_sender_id' in cols else ''
                            if not sender:
                                match=re.match(r'^([A-Za-z0-9_@.\-]+):\n',raw)
                                sender=match.group(1) if match else u
                            mine=account.rsplit('_',1)[0]
                            label='我' if sender==mine else names.get(sender,sender)
                            local=str(r['local_id'] if 'local_id' in cols else r['_rid'])
                            server=next((str(r[x]) for x in ('server_id','msg_svr_id','svr_id') if x in cols),'')
                            out.execute('INSERT OR IGNORE INTO reader_seen VALUES(?,?)',(chat,local))
                            out.execute('''INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(account,chat,source,local_id) DO UPDATE SET
                                server_id=excluded.server_id,time=excluded.time,sender=excluded.sender,sender_id=excluded.sender_id,kind=excluded.kind,text=excluded.text,raw=excluded.raw,metadata=excluded.metadata
                                WHERE messages.server_id IS NOT excluded.server_id OR messages.time IS NOT excluded.time OR messages.sender IS NOT excluded.sender OR messages.sender_id IS NOT excluded.sender_id OR messages.kind IS NOT excluded.kind OR messages.text IS NOT excluded.text OR messages.raw IS NOT excluded.raw OR messages.metadata IS NOT excluded.metadata''',(account,chat,rel,local,server,int(r['create_time'] or 0),label,sender,k,text,raw,json.dumps(meta,ensure_ascii=False)))
                    self.checkpoint()
                    out.execute('DELETE FROM messages WHERE account=? AND source=? AND NOT EXISTS(SELECT 1 FROM reader_seen WHERE reader_seen.chat=messages.chat AND reader_seen.local_id=messages.local_id)',(account,rel))
                self.mark(account,rel,'ready','',db.stat().st_size)
            except PlaybackUnavailable:
                raise
            except Exception as e:
                # The source transaction already rolled back; retain its saved index.
                self.mark(account,rel,'error',str(e),db.stat().st_size)
            self.checkpoint()
        for db in (contact,session):
            if db.exists() and (eligible_sources is None or str(db.relative_to(plain)) in eligible_sources):
                self.mark(account,str(db.relative_to(plain)),'ready','',db.stat().st_size)

    def conversations(self,account,q=''):
        key=(account,q);cached=self._conversation_cache.get(key)
        if cached and time.monotonic()-cached[0]<60:return cached[1]
        with self.connect() as c:
            result=[dict(r) for r in c.execute('SELECT c.*,count(m.rowid) AS count,min(m.time) AS first,max(m.time) AS last,(SELECT text FROM messages p INDEXED BY message_time WHERE p.account=c.account AND p.chat=c.id ORDER BY p.time DESC,p.rowid DESC LIMIT 1) AS preview FROM conversations c JOIN messages m ON c.account=m.account AND c.id=m.chat WHERE c.account=? AND c.name LIKE ? GROUP BY c.account,c.id ORDER BY last DESC',(account,'%'+q+'%'))]
        self._conversation_cache[key]=(time.monotonic(),result);return result

    def messages(self,account,chat='',q='',offset=0,limit=80,start=0,end=0):
        clauses=['m.account=?'];args=[account]
        if chat:clauses.append('m.chat=?');args.append(chat)
        if q:
            if len(q)>200:raise ValueError('search too long')
            if len(q)>=3:
                clauses.append('m.rowid IN (SELECT rowid FROM message_search WHERE message_search MATCH ?)');args.append('"'+q.replace('"','""')+'"')
            else:clauses.append('m.text LIKE ?');args.append('%'+q+'%')
        if start:clauses.append('m.time>=?');args.append(start)
        if end:clauses.append('m.time<?');args.append(end)
        where=' AND '.join(clauses)
        limit=max(1,min(int(limit),200));offset=None if offset is None else max(0,min(int(offset),10000000))
        with self.connect() as c:
            total=c.execute('SELECT count(*) FROM messages m WHERE '+where,args).fetchone()[0]
            if offset is None:offset=max(0,total-limit)
            page='SELECT m.rowid AS id FROM messages m'+(' INDEXED BY message_time' if chat else '')+' WHERE '+where+' ORDER BY m.time,m.rowid LIMIT ? OFFSET ?'
            rows=c.execute('SELECT m.rowid AS id,m.*,c.name AS chat_name FROM ('+page+') page JOIN messages m ON m.rowid=page.id LEFT JOIN conversations c ON c.account=m.account AND c.id=m.chat ORDER BY m.time,m.rowid',args+[limit,offset]).fetchall()
            result=[]
            for r in rows:
                item=dict(r);item.pop('raw',None);item['metadata']=json.loads(item['metadata'])
                if item['kind']==49:item['metadata'].update(rendered(49,r['raw'])[1])
                item['is_self']=item['sender_id']==account.rsplit('_',1)[0];result.append(item)
            return {'items':result,'total':total,'offset':offset,'limit':limit}

    def message(self,mid):
        with self.connect() as c:
            row=c.execute('SELECT m.rowid AS id,m.*,c.username FROM messages m JOIN conversations c ON c.account=m.account AND c.id=m.chat WHERE m.rowid=?',(mid,)).fetchone()
            if not row:raise ValueError('message not found')
            return dict(row)
