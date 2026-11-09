#!/usr/bin/env python3
"""Explicit bounded detection of older messages newly ingested/changed since archive baseline."""
import argparse,json,os,re,signal,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import wechat_read as wr


def late_rows(current,baseline,start,end,checkpoint):
    _,_,qid,_=wr.codec()
    with wr.read_db(current) as c:
        c.set_progress_handler(lambda:(checkpoint() or 0),10000)
        c.execute('ATTACH DATABASE ? AS previous',(Path(baseline).absolute().as_uri()+'?mode=ro&immutable=1',))
        c.execute('PRAGMA query_only=ON')
        old={r[0] for r in c.execute("SELECT name FROM previous.sqlite_master WHERE type='table'")}
        tables=[r[0] for r in c.execute("SELECT name FROM main.sqlite_master WHERE type='table'")]
        for table in sorted(tables):
            if not re.fullmatch(r'Msg_[a-fA-F0-9]{32}',table):continue
            checkpoint();cols={r[1] for r in c.execute('PRAGMA main.table_info('+qid(table)+')')}
            if not {'local_id','create_time','local_type','message_content'}.issubset(cols):raise ValueError('unsupported native message schema')
            if table in old:
                oldcols={r[1] for r in c.execute('PRAGMA previous.table_info('+qid(table)+')')}
                fields=[x for x in ('server_id','local_type','create_time','message_content','real_sender_id','compress_content','packed_info_data') if x in cols and x in oldcols]
                different=' OR '.join('n.'+qid(x)+' IS NOT o.'+qid(x) for x in fields)
                sql='SELECT n.rowid AS _rid,n.*,CASE WHEN o.local_id IS NULL THEN \'new\' ELSE \'changed\' END AS _change FROM main.'+qid(table)+' n LEFT JOIN previous.'+qid(table)+' o ON o.local_id=n.local_id WHERE n.create_time>=? AND n.create_time<? AND (o.local_id IS NULL OR '+different+') ORDER BY n.local_id'
            else:sql='SELECT rowid AS _rid,*,\'new-table\' AS _change FROM main.'+qid(table)+' WHERE create_time>=? AND create_time<? ORDER BY local_id'
            for row in c.execute(sql,(start,end)):
                checkpoint();r=dict(row);r['_table']=table;yield r


def execute(start,end,output):
    def parse(value):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',value):raise ValueError('UTC timestamp required')
        return int(wr.datetime.strptime(value,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=wr.timezone.utc).timestamp())
    a,b=parse(start),parse(end)
    # Late-import auditing deliberately spans more than the regular 31-day export window.
    if not 0<b-a<=92*86400:raise ValueError('late comparison limited to 92 days')
    output=wr.no_symlinks(Path(output).absolute())
    for root in (wr.NATIVE,wr.ARCHIVE,wr.FOUNDATION):
        if output.is_relative_to(root):raise ValueError('output inside protected root')
    if output.exists() or Path(str(output)+'.receipt.json').exists():raise FileExistsError('output exists')
    root,catalog=wr.catalog(wr.ACCOUNT);keyfile=wr.no_symlinks(wr.ARCHIVE/'keys'/f'{wr.ACCOUNT}.keys.json')
    if keyfile.stat().st_mode&0o077:raise ValueError('key permissions')
    cfg=json.loads(keyfile.read_text())
    if Path(cfg.get('db_root','')).resolve()!=root.parent.resolve():raise ValueError('account mismatch')
    decrypt,decode,qid,rendered=wr.codec();names,chats,_=wr.cached_metadata(wr.ACCOUNT)
    receipt={'startedAt':wr.utc(),'window':{'fromInclusive':start,'toExclusive':end},'purpose':'older new/changed rows since verified archive baseline; not semantic rereview','sourceCatalog':catalog,'sources':[],'rows':0,'rowCap':50000,'bytesCap':wr.OUTPUT_CAP,'failures':[],'status':'partial','sourceWrites':False}
    begun=time.monotonic();deadline=begun+165
    def checkpoint():
        if time.monotonic()>deadline:raise TimeoutError('late import comparison deadline')
    def alarm(*_):raise TimeoutError('late import comparison deadline')
    old=signal.signal(signal.SIGALRM,alarm);signal.alarm(165);totalbytes=0
    try:
        with wr.exclusive_output(output) as out:
            for ent in catalog:
                checkpoint();rel=ent['source'];source=root/rel;baseline=wr.ARCHIVE/'accounts'/wr.ACCOUNT/'decrypted'/rel
                info={'source':rel,'status':'failed','lateRows':0};receipt['sources'].append(info)
                try:
                    reused=wr.reuse_plain(source,rel,wr.ACCOUNT,checkpoint)
                    if reused:
                        info.update(reused[1]);info['status']='unchanged-encrypted-source-proven';continue
                    st=wr.stamp(wr.pair(source));estimate=st[0]['size']*2+sum(x['size'] for x in st[1:] if x)+wr.OUTPUT_CAP
                    if estimate>wr.BUDGET:raise ValueError('scratch budget')
                    with tempfile.TemporaryDirectory(prefix='codex-wechat-late-') as d:
                        snap,st=wr.snapshot(source,Path(d),wr.BUDGET-st[0]['size']-wr.OUTPUT_CAP,checkpoint)
                        with snap.open('rb') as f:salt=f.read(16).hex()
                        key=cfg['keys'].get(salt,'')
                        if not re.fullmatch(r'[A-Fa-f0-9]{64}',key):raise ValueError('missing native key')
                        plain=Path(d)/'plain.db';decrypt(snap,plain,bytes.fromhex(key),checkpoint=checkpoint)
                        info.update({'method':'fresh-native-vs-archive-raw-comparison','sourceStamp':st,'plannedPeakBytes':estimate,'baselineSha256':wr.digest(baseline,checkpoint),'currentSha256':wr.digest(plain,checkpoint),'snapshotAt':wr.utc()})
                        with wr.read_db(plain) as c:
                            idmap={r[0]:decode(r[1]) for r in c.execute('SELECT rowid,user_name FROM Name2Id')};native={wr.hashlib.md5(u.encode()).hexdigest():u for u in idmap.values()};native.update(chats)
                        for r in late_rows(plain,baseline,a,b,checkpoint):
                            chat=r['_table'][4:];username=native.get(chat,chat);server=str(r.get('server_id') or '');local=str(r['local_id']);raw=decode(r['message_content']);kind=int(r['local_type'] or 0)&0xffffffff;text,meta=rendered(kind,raw);sender=idmap.get(r.get('real_sender_id'),'')
                            if not sender:
                                m=re.match(r'^([A-Za-z0-9_@.\-]+):\n',raw);sender=m.group(1) if m else username
                            stable=f'{wr.ACCOUNT}:{chat}:server:{server}' if server not in ('','0') else f'{wr.ACCOUNT}:{chat}:{rel}:{r["_table"]}:local:{local}'
                            row={'stableId':stable,'account':wr.ACCOUNT,'chat':chat,'nativeChat':username,'conversationName':names.get(username,username),'sender':names.get(sender,sender),'senderId':sender,'time':wr.utc(r['create_time']),'timeUnix':r['create_time'],'source':rel,'sourceTable':r['_table'],'serverId':server,'localId':local,'kind':kind,'text':text,'metadata':meta,'raw':raw,'lateChange':r['_change'],'semanticRead':False,'needsASR':kind==34,'needsContentRead':kind in (3,43,49)}
                            line=json.dumps(row,ensure_ascii=False)+'\n';totalbytes+=len(line.encode());receipt['rows']+=1;info['lateRows']+=1
                            if receipt['rows']>50000 or totalbytes>wr.OUTPUT_CAP:raise ValueError('late output cap')
                            out.write(line)
                    info['status']='ok'
                except Exception as exc:
                    info['errorType']=type(exc).__name__;receipt['failures'].append({'source':rel,'errorType':type(exc).__name__})
                    if isinstance(exc,TimeoutError):break
            out.flush();os.fsync(out.fileno())
        receipt['status']='complete' if len(receipt['sources'])==len(catalog) and not receipt['failures'] else 'partial'
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,old);receipt['finishedAt']=wr.utc();receipt['elapsedSeconds']=time.monotonic()-begun;receipt['scratchCleaned']=True
        if output.exists():receipt['outputSha256']=wr.digest(output);receipt['outputBytes']=output.stat().st_size
        with wr.exclusive_output(Path(str(output)+'.receipt.json')) as f:json.dump(receipt,f,ensure_ascii=False,indent=2)
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');p.add_argument('--from',dest='start');p.add_argument('--to',dest='end');p.add_argument('--output');a=p.parse_args()
    if not a.execute:p.print_help();return 0
    if not all([a.start,a.end,a.output]):p.error('explicit UTC from/to/output required')
    r=execute(a.start,a.end,a.output);print(json.dumps({'status':r['status'],'rows':r['rows'],'sources':len(r['sources'])}));return 0 if r['status']=='complete' else 2
if __name__=='__main__':raise SystemExit(main())
