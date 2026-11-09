#!/usr/bin/env python3
"""Bounded, explicit local WeChat read; never runs the collector or updates tasks."""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import sys
import tempfile
import time

ACCOUNT = os.environ.get('WECHAT_MAC_ACCOUNT_ID','wxid_fixture_owner')
NATIVE = Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
ARCHIVE = Path.home()/'Library/Application Support/WechatCollectorMac/archive'
FOUNDATION = Path(os.environ.get('WECHAT_MAC_FOUNDATION','/opt/external-adapters/mac-foundation'))
BUDGET = 1_200_000_000
OUTPUT_CAP = 80_000_000
RECORDS = Path.home()/'Library/Application Support/WechatCollectorMac/records.db'
SOURCE_RE = re.compile(r'(?:biz_)?message_[0-9]+\.db\Z')


def codec():
    # Only pure decoding functions: Library.import_keys/import_plain never called.
    if str(FOUNDATION) not in sys.path:sys.path.insert(0,str(FOUNDATION))
    from crypto import decrypt_file
    from security import decode_content, qid
    from library import rendered
    return decrypt_file,decode_content,qid,rendered


def validate_account(account):
    if not re.fullmatch(r'wxid_[A-Za-z0-9_]+',account):raise ValueError('invalid account')
    return account


def window(start,end):
    def parse(s):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',s):raise ValueError('UTC timestamps required')
        return int(datetime.strptime(s,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp())
    a,b=parse(start),parse(end)
    if b<=a or b-a>31*86400:raise ValueError('window must be positive and at most 31 days')
    return a,b


def utc(ts=None):
    return datetime.fromtimestamp(ts if ts is not None else time.time(),timezone.utc).isoformat().replace('+00:00','Z')


def no_symlinks(path):
    path=Path(path).absolute()
    for p in (path,*path.parents):
        if p.is_symlink():raise ValueError('symlink path rejected')
    return path


@contextmanager
def exclusive_output(path):
    path=Path(path).absolute()
    # O_EXCL rejects existing files and final symlinks before opening.
    for parent in path.parents:no_symlinks(parent)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:yield f


def stamp(paths):
    result=[]
    for p in paths:
        no_symlinks(p)
        if not p.exists():result.append(None);continue
        st=p.stat()
        if not p.is_file():raise ValueError('nonregular database component')
        header=None
        if p.name.endswith('-shm'):
            with p.open('rb') as f:header=f.read(96).hex()
        result.append({'size':st.st_size,'mtimeNs':st.st_mtime_ns,'ctimeNs':st.st_ctime_ns,'inode':st.st_ino,'header':header})
    return result


def pair(source):return [source,Path(str(source)+'-wal'),Path(str(source)+'-shm')]


def digest(path,checkpoint=lambda:None):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while True:
            checkpoint();data=f.read(1024*1024)
            if not data:break
            h.update(data)
    return h.hexdigest()


def snapshot(source,target,budget,checkpoint):
    paths=pair(source);before=stamp(paths)
    total=sum(x['size'] for x in before if x)
    if total>budget:raise ValueError('scratch budget exceeded before snapshot')
    copied=[]
    try:
        for p in paths:
            checkpoint()
            if p.exists():
                dest=Path(target)/p.name
                with p.open('rb') as src, dest.open('xb') as out:
                    os.chmod(dest,0o600);copied.append(dest)
                    remaining=budget
                    while True:
                        data=src.read(min(1024*1024,remaining+1))
                        if not data:break
                        if len(data)>remaining:raise ValueError('snapshot exceeded budget')
                        out.write(data);remaining-=len(data)
                budget-=dest.stat().st_size
            checkpoint()
        if before!=stamp(paths):raise ValueError('source changed during snapshot')
        return Path(target)/source.name,before
    except BaseException:
        for p in copied:p.unlink(missing_ok=True)
        raise


@contextmanager
def read_db(path):
    con=sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro&immutable=1',uri=True)
    con.row_factory=sqlite3.Row
    try:yield con
    finally:con.close()


class VoiceLookup:
    """Indexed per-message lookup only; never scans or copies the derived store."""
    def __init__(self,path):self.path=Path(path);self.con=None
    def __enter__(self):
        no_symlinks(self.path)
        wal=Path(str(self.path)+'-wal')
        if wal.exists() and wal.stat().st_size:raise ValueError('derived store has nonempty WAL')
        self.con=sqlite3.connect(self.path.as_uri()+'?mode=ro&immutable=1',uri=True)
        return self
    def get(self,key):
        if not isinstance(key,tuple) or len(key)!=3:return None
        row=self.con.execute('SELECT text FROM voice_transcripts WHERE account_key=? AND conversation=? AND server_id=?',key).fetchone()
        return row[0] if row else None
    def __exit__(self,*_):
        if self.con:self.con.close()


def cached_metadata(account):
    names={};chats={};voices={}
    index=ARCHIVE/'index.db'
    if Path(str(index)+'-wal').exists() and Path(str(index)+'-wal').stat().st_size:
        raise ValueError('archive index has nonempty WAL; immutable read refused')
    with read_db(index) as c:
        for r in c.execute('SELECT id,username,name FROM conversations WHERE account=?',(account,)):
            chats[r['id']]=r['username'];names[r['username']]=r['name']
    if RECORDS.exists():
        no_symlinks(RECORDS)
        wal=Path(str(RECORDS)+'-wal')
        if wal.exists() and wal.stat().st_size:raise ValueError('derived names have nonempty WAL')
        with read_db(RECORDS) as c:
            for r in c.execute('SELECT username,display_name FROM wechat_db_names WHERE account_key=?',(account,)):
                names[r['username']]=r['display_name']
    return names,chats,voices


def read_messages(path,source,account,start,end,names,chats,voices,checkpoint,stats=None):
    _,decode,qid,rendered=codec()
    with read_db(path) as c:
        c.set_progress_handler(lambda:(checkpoint() or 0),10000)
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        idmap={r[0]:decode(r[1]) for r in c.execute('SELECT rowid,user_name FROM Name2Id')} if 'Name2Id' in tables else {}
        native={hashlib.md5(u.encode()).hexdigest():u for u in idmap.values()};native.update(chats)
        for table in sorted(tables):
            if not re.fullmatch(r'Msg_[a-fA-F0-9]{32}',table):continue
            checkpoint();cols={r[1] for r in c.execute('PRAGMA table_info('+qid(table)+')')}
            if not {'local_type','create_time','message_content'}.issubset(cols):raise ValueError('unsupported message schema')
            if stats is not None:
                stats['tablesScanned']+=1
                ext=c.execute('SELECT min(create_time),max(create_time),count(*) FROM '+qid(table)).fetchone()
                stats['totalSourceRows']+=ext[2]
                if ext[0] is not None:stats['sourceEarliest']=min(stats.get('sourceEarliest',ext[0]),ext[0])
                if ext[1] is not None:stats['sourceLatest']=max(stats.get('sourceLatest',ext[1]),ext[1])
            chat=table[4:];username=native.get(chat,chat)
            sql='SELECT rowid AS _rid,* FROM '+qid(table)+' WHERE create_time>=? AND create_time<? ORDER BY create_time,rowid'
            for r in c.execute(sql,(start,end)):
                checkpoint();raw=decode(r['message_content']);kind=int(r['local_type'] or 0)&0xffffffff
                text,meta=rendered(kind,raw)
                sender=idmap.get(r['real_sender_id'],'') if 'real_sender_id' in cols else ''
                match=re.match(r'^([A-Za-z0-9_@.\-]+):\n',raw)
                sender=sender or (match.group(1) if match else username)
                local=str(r['local_id'] if 'local_id' in cols else r['_rid'])
                server=next((str(r[x] or '') for x in ('server_id','msg_svr_id','svr_id') if x in cols),'')
                stable=f'{account}:{chat}:server:{server}' if server not in ('','0') else f'{account}:{chat}:{source}:{table}:local:{local}'
                record={'stableId':stable,'account':account,'chat':chat,'nativeChat':username,'conversationName':names.get(username,username),'sender':names.get(sender,sender),'senderId':sender,'time':utc(r['create_time']),'timeUnix':r['create_time'],'serverId':server,'localId':local,'source':source,'sourceTable':table,'kind':kind,'text':text,'metadata':meta,'needsASR':False,'needsContentRead':kind in (3,43,49),'readScope':'message-payload; media metadata only'}
                if kind==34:
                    transcript=voices.get((account,username,server)) or voices.get((account,chat,server)) or voices.get(stable)
                    record['voiceTranscript']=transcript or '';record['needsASR']=not bool(transcript)
                    if transcript:record['text']=transcript
                # Preserve full private payload for quotes, forwarding and unknown kinds.
                if kind!=1:record['raw']=raw
                yield record


def catalog(account):
    root=no_symlinks(NATIVE/account/'db_storage')
    entries=[]
    for p in sorted((root/'message').glob('*.db')):
        if not SOURCE_RE.fullmatch(p.name):continue
        paths=pair(p);st=stamp(paths)
        entries.append({'source':str(p.relative_to(root)),'components':[{'name':x.name,**s} if s else {'name':x.name,'absent':True} for x,s in zip(paths,st)]})
    if not entries:raise ValueError('no supported message sources')
    return root,entries


def reuse_plain(source,rel,account,checkpoint):
    base=ARCHIVE/'accounts'/account; snap=base/'snapshot'/rel;plain=base/'decrypted'/rel
    if not snap.exists() or not plain.exists():return None
    before=stamp(pair(source));snapshot_time=snap.stat().st_mtime_ns
    if any(s and s['mtimeNs']>=snapshot_time for s in before[:2]):return None
    proof=[]
    for original,old in zip(pair(source)[:2],pair(snap)[:2]):
        checkpoint();no_symlinks(old)
        if original.exists()!=old.exists():return None
        if not original.exists():continue
        if original.stat().st_size!=old.stat().st_size:return None
        current_hash=digest(original,checkpoint)
        if current_hash!=digest(old,checkpoint):return None
        proof.append({'component':original.name,'sha256':current_hash})
    if before!=stamp(pair(source)):raise ValueError('source changed during reuse verification')
    if plain.stat().st_mtime_ns<snapshot_time:return None
    with read_db(ARCHIVE/'index.db') as c:
        row=c.execute('SELECT status,updated FROM coverage WHERE account=? AND path=?',(account,rel)).fetchone()
        if row is None or row['status']!='ready' or row['updated']*1_000_000_000<plain.stat().st_mtime_ns:return None
    no_symlinks(plain)
    with read_db(plain) as c:
        c.set_progress_handler(lambda:(checkpoint() or 0),10000)
        if c.execute('PRAGMA integrity_check').fetchall()[0][0]!='ok':raise ValueError('cached plaintext integrity failed')
    return plain,{'method':'verified-unchanged-archive','originalStamp':before,'snapshotTime':utc(snapshot_time/1e9),'encryptedHashes':proof,'plaintextSha256':digest(plain,checkpoint)}


def export(account,start,end,output,timeout=540,budget=BUDGET):
    validate_account(account)
    if account!=ACCOUNT:raise ValueError('account not authorized by local configuration')
    a,b=window(start,end);output=no_symlinks(Path(output).absolute())
    if not output.parent.exists():raise ValueError('output parent must already exist')
    for forbidden in (NATIVE,ARCHIVE,FOUNDATION):
        if output.is_relative_to(forbidden):raise ValueError('output cannot be inside protected input roots')
    if output.exists() or Path(str(output)+'.receipt.json').exists():raise FileExistsError('output or receipt already exists')
    root,entries=catalog(account)
    keyfile=no_symlinks(ARCHIVE/'keys'/f'{account}.keys.json')
    if keyfile.stat().st_mode&0o077:raise ValueError('key file must have mode 0600')
    # This mapping never enters output, receipt, exceptions or logging.
    config=json.loads(keyfile.read_text())
    if Path(config.get('db_root','')).resolve()!=(root.parent).resolve():raise ValueError('key account mismatch')
    keys=config.get('keys',{})
    decrypt,_,_,_=codec();names,chats,voices=cached_metadata(account)
    begun=time.monotonic();deadline=begun+timeout
    def checkpoint():
        if time.monotonic()>deadline:raise TimeoutError('bounded read deadline reached')
    def alarm_handler(*_):raise TimeoutError('bounded read deadline reached')
    old_handler=signal.signal(signal.SIGALRM,alarm_handler);signal.alarm(timeout)
    receipt={'version':1,'account':account,'window':{'fromInclusive':start,'toExclusive':end},'startedAt':utc(),'sourceCatalog':entries,'sources':[],'scratchBudgetBytes':budget,'scratchPeakBytes':0,'outputCapBytes':OUTPUT_CAP,'messages':0,'duplicates':0,'needsASR':0,'needsContentRead':0,'semanticRead':False,'mediaCopied':False,'collectorStarted':False,'status':'partial','metadataSource':'archive conversations plus derived names; indexed derivative voice transcripts','failures':[]}
    seen=set();bytes_out=0
    try:
        with VoiceLookup(RECORDS) as voices, exclusive_output(output) as out:
            for entry in entries:
                rel=entry['source'];source=root/rel
                detail={'source':rel,'status':'failed','windowRows':0,'tablesScanned':0,'totalSourceRows':0};receipt['sources'].append(detail)
                try:
                    checkpoint();reuse=reuse_plain(source,rel,account,checkpoint)
                    with tempfile.TemporaryDirectory(prefix='codex-wechat-read-') as scratch:
                        if reuse:plain,proof=reuse;detail.update(proof)
                        else:
                            source_stamp=stamp(pair(source));source_size=source_stamp[0]['size'];estimated=source_size*2+sum(s['size'] for s in source_stamp[1:] if s)+OUTPUT_CAP
                            if estimated>budget:raise ValueError('source exceeds combined scratch/output budget')
                            receipt['scratchPeakBytes']=max(receipt['scratchPeakBytes'],estimated)
                            snap,snap_stamp=snapshot(source,Path(scratch),budget-source_size-OUTPUT_CAP,checkpoint)
                            with snap.open('rb') as f:salt=f.read(16).hex()
                            keyhex=keys.get(salt,'')
                            if not re.fullmatch(r'[a-fA-F0-9]{64}',keyhex):raise ValueError('missing or invalid key for source')
                            plain=Path(scratch)/'plain.db';decrypt(snap,plain,bytes.fromhex(keyhex),checkpoint=checkpoint)
                            detail.update({'method':'fresh-verified-snapshot','originalStamp':snap_stamp,'snapshotTime':utc(),'encryptedSha256':digest(snap,checkpoint),'plaintextSha256':digest(plain,checkpoint)})
                        detail['readStartedAt']=utc()
                        for record in read_messages(plain,rel,account,a,b,names,chats,voices,checkpoint,detail):
                            detail['windowRows']+=1
                            if record['stableId'] in seen:receipt['duplicates']+=1;continue
                            seen.add(record['stableId']);line=json.dumps(record,ensure_ascii=False)+'\n';bytes_out+=len(line.encode())
                            if bytes_out>OUTPUT_CAP:raise ValueError('output cap reached')
                            out.write(line);receipt['messages']+=1
                            receipt['needsASR']+=int(record['needsASR']);receipt['needsContentRead']+=int(record['needsContentRead'])
                        detail['readFinishedAt']=utc();detail['status']='ok'
                except Exception as exc:
                    # Exception texts from codecs might contain message material, never log them.
                    code=type(exc).__name__;detail['errorType']=code
                    receipt['failures'].append({'source':rel,'errorType':code})
                    if isinstance(exc,TimeoutError):break
            out.flush();os.fsync(out.fileno())
        receipt['status']='complete' if len(receipt['sources'])==len(entries) and not receipt['failures'] else 'partial'
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,old_handler)
        receipt['finishedAt']=utc();receipt['durationSeconds']=round(time.monotonic()-begun,3);receipt['scratchCleaned']=True
        if output.exists():receipt['outputSha256']=digest(output);receipt['outputBytes']=output.stat().st_size
        with exclusive_output(Path(str(output)+'.receipt.json')) as f:json.dump(receipt,f,ensure_ascii=False,indent=2)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command')
    inspect=sub.add_parser('inspect',help='read source file catalog only; no messages, keys or writes')
    exp=sub.add_parser('export',help='explicit bounded private JSONL export')
    for p in (inspect,exp):p.add_argument('--account',default=ACCOUNT)
    exp.add_argument('--from',dest='start',required=True);exp.add_argument('--to',dest='end',required=True);exp.add_argument('--output',required=True)
    args=parser.parse_args()
    if not args.command:parser.print_help();return 0
    try:
        validate_account(args.account)
        if args.account!=ACCOUNT:raise ValueError('unknown account')
        if args.command=='inspect':print(json.dumps(catalog(args.account)[1],indent=2));return 0
        receipt=export(args.account,args.start,args.end,args.output)
        print(json.dumps({'status':receipt['status'],'messages':receipt['messages'],'needsASR':receipt['needsASR'],'needsContentRead':receipt['needsContentRead'],'output':args.output,'receipt':args.output+'.receipt.json'}))
        return 0 if receipt['status']=='complete' else 2
    except Exception as exc:
        print(json.dumps({'status':'failed','errorType':type(exc).__name__}),file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
