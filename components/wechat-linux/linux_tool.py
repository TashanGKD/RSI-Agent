"""On-demand Linux WeChat tool. No model, worker, timer, or automatic replies."""
import argparse,base64,hashlib,json,os,re,sys,time,sqlite3
from datetime import datetime,timezone,timedelta
from contextlib import contextmanager
from collections import Counter
from pathlib import Path
from receive_source import sid

ROOT=Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))
ACCOUNT=os.environ.get('WECHAT_ACCOUNT_ID','wxid_fixture_operator')
PROFILE=Path(os.environ.get('WECHAT_PROFILE',str(ROOT/'xwechat_files/fixture-profile')))
READABLE={'message/message_0.db','message/media_0.db','contact/contact.db','session/session.db','message/message_resource.db','hardlink/hardlink.db','emoticon/emoticon.db'}

def parse_request(raw):
    if not isinstance(raw,str) or len(raw.encode())>1500000:raise ValueError('request size cap')
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate JSON key')
            d[k]=v
        return d
    try:r=json.loads(raw,object_pairs_hook=unique)
    except (ValueError,RecursionError):raise ValueError('invalid JSON request') from None
    if not isinstance(r,dict) or len(r)>12:raise ValueError('bounded JSON object required')
    return r

def secret(path):
    import snapshot
    path=snapshot.private_regular(path)
    if path.stat().st_mode&0o077 or path.stat().st_size>32768 or path.stat().st_uid!=os.getuid():raise ValueError('private bounded material required')
    return path.read_text()

@contextmanager
def native(rel):
    if rel not in READABLE:raise ValueError('source is not authorized')
    if rel=='message/message_0.db':
        from remote import require_supported_sources
        require_supported_sources([p.name for p in (PROFILE/'db_storage/message').glob('message_*.db')])
    if str(ROOT/'deps') not in sys.path:sys.path.insert(0,str(ROOT/'deps'))
    import snapshot
    source=snapshot.private_regular(PROFILE/'db_storage'/rel);keys=json.loads(secret(ROOT/'db-keys.json'))
    if rel in keys:key=bytes.fromhex(keys[rel])
    else:
        # Existing authorization material only; no process access, login, or extraction.
        master=bytes.fromhex(secret(ROOT/'capture-secret.hex').strip())
        with source.open('rb') as f:salt=f.read(16)
        key=hashlib.pbkdf2_hmac('sha512',master,salt,256000,32)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="wechat-native-") as scratch:
        with snapshot.database(source,key,Path(scratch),allow_baseline=True) as pair:yield pair

def signed(value):
    n=int(sid(value));return n if n<2**63 else n-2**64

def beijing(value):return datetime.fromtimestamp(value,timezone(timedelta(hours=8))).isoformat()

def decode(v):
    # Reuse only bounded text decoding, never the legacy live SQLCipher connection.
    from remote import decode_text
    return decode_text(v)

def require_peer(value):
    if not isinstance(value,str) or not 1<=len(value)<=120 or any(c in value for c in '/\\\0\n\r'):raise ValueError('explicit peer identity required')
    return value

def selector(r):
    limit=r.get('limit',100)
    if type(limit) is not int or not 1<=limit<=500:raise ValueError('limit must be 1..500')
    ids=r.get('server_ids')
    if ids is not None:
        if not isinstance(ids,list) or not 1<=len(ids)<=100:raise ValueError('1..100 server IDs required')
        return [signed(v) for v in ids],None,None,limit
    a,b=r.get('start'),r.get('end')
    if type(a) is not int or type(b) is not int or not 0<=a<b or b-a>31*86400:raise ValueError('explicit epoch window required, at most 31 days')
    return None,a,b,limit

def where(ids,a,b,idcol,timecol):
    if ids is not None:return idcol+' in ('+','.join('?' for _ in ids)+')',ids
    return timecol+'>=? and '+timecol+'<?',[a,b]

class Tool:
    def __init__(self,opened=native,account=ACCOUNT,sender=None,metadata=None):self.open=opened;self.account=account;self.sender=sender;self.metadata=metadata
    def resolve(self,value):
        require_peer(value)
        with self.open('contact/contact.db') as (c,receipt):
            rows=c.execute('select username,remark,nick_name,alias from contact where username=?',(value,)).fetchall()
            if not rows:rows=c.execute('select username,remark,nick_name,alias from contact where remark=? or nick_name=? or alias=?',(value,value,value)).fetchall()
            distinct={r['username']:dict(r) for r in rows}
            if len(distinct)!=1:raise ValueError('peer missing or ambiguous; use exact username')
            r=next(iter(distinct.values()));require_peer(r['username'])
            r['displayName']=r['remark'] or r['nick_name'] or r['username']
            r['contactEvidence']=receipt
            return r
    def sessions(self,r):
        limit=r.get('limit')
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('explicit sessions limit 1..100 required')
        query=r.get('query','')
        if not isinstance(query,str) or len(query)>120:raise ValueError('invalid session query')
        with self.open('session/session.db') as (c,receipt):
            rows=c.execute('select username,unread_count,last_timestamp,last_msg_type,last_msg_sender from SessionTable where is_hidden=0 order by sort_timestamp desc limit ?',(limit*4,)).fetchall()
        out=[]
        for row in rows:
            try:target=self.resolve(row['username'])
            except ValueError:target={'username':row['username'],'displayName':row['username']}
            if query and query not in target['displayName'] and query not in target['username']:continue
            out.append({**dict(row),'displayName':target['displayName']})
            if len(out)>=limit:break
        return {'state':'ok','sessions':out,'receipt':receipt,'truncated':len(rows)>=limit*4}
    def unread(self,peer,ids,a,b):
        condition,args=where(ids,a,b,'u.server_id','u.create_time')
        with self.open('session/session.db') as (c,receipt):
            rows=c.execute('select u.server_id,u.local_id,u.create_time from SessionUnreadListTable_1 u join Name2Id n on n.rowid=u.username_id where n.user_name=? and '+condition+' order by u.create_time,u.server_id limit 501',[peer,*args]).fetchall()
            return {sid(r['server_id']):dict(r) for r in rows},receipt
    def messages(self,r):
        peer=self.resolve(r['peer'])['username'];ids,a,b,limit=selector(r);out={};receipts=[];gaps=[]
        table='Msg_'+hashlib.md5(peer.encode()).hexdigest();condition,args=where(ids,a,b,'server_id','create_time')
        with self.open('message/message_0.db') as (c,receipt):
            receipts.append(receipt)
            if receipt.get('gap'):gaps.append({'source':'message','reason':receipt['gap']})
            exists=c.execute('select 1 from sqlite_master where type="table" and name=?',(table,)).fetchone()
            main_latest=c.execute('select max(create_time) from '+table).fetchone()[0] if exists else None
            if exists:
                rows=c.execute('select * from '+table+' where '+condition+' order by create_time,sort_seq,local_id limit ?',[*args,limit+1]).fetchall()
                names={row[0]:row[1] for row in c.execute('select rowid,user_name from Name2Id')}
                sticker_ids = Counter(row['server_id'] for row in rows) if (
                    len(rows) <= limit and receipt.get('consistency') == 'committed' and not receipt.get('gap')) else {}
                for x in rows:
                    if not x['server_id']:continue
                    s=sid(x['server_id']);kind=int(x['local_type'])&0xffffffff
                    out[s]={'serverId':s,'localId':x['local_id'],'time':x['create_time'],'kind':kind,'senderId':names.get(x['real_sender_id']),'text':decode(x['message_content']) if kind==1 else '', 'sourceKind':'message','peer':peer}
                    if kind==49:
                        from app_message import parse_app_message
                        out[s].update(parse_app_message(x['message_content'],local_type=x['local_type'],peer=peer,sender=out[s]['senderId'],decode=decode))
                    if kind==47 and out[s]['senderId'] and sticker_ids.get(x['server_id'])==1:
                        from operations.proof import sticker_md5
                        md5=sticker_md5(x['message_content'],decode,out[s]['senderId'] if peer.endswith('@chatroom') else None)
                        if md5:
                            out[s]['sticker']={'md5':md5}
                            out[s]['nativeStatus']=x['status']
                    if self.metadata and out[s]['senderId']:self.metadata.remember(peer,s,out[s]['senderId'],'message/message_0.db:Name2Id')
        try:
            unread,ur=self.unread(peer,ids,a,b);receipts.append(ur)
            with self.open('session/session.db') as (c,sr):
                tables={x[0] for x in c.execute('select name from sqlite_master where type="table"')}
                latest=c.execute('select last_timestamp from SessionTable where username=?',(peer,)).fetchone() if 'SessionTable' in tables else None
                if latest and (main_latest is None or latest[0]>main_latest):gaps.append({'source':'message','reason':'session_newer_than_message_rows','messageLatest':main_latest,'sessionLatest':latest[0]})
        except (KeyError,sqlite3.Error):unread={};gaps.append({'source':'unread','reason':'unavailable'})
        if self.metadata and not peer.endswith('@chatroom'):
            for s in unread:self.metadata.remember(peer,s,peer,'session/session.db:SessionUnreadListTable_1:private-incoming')
        condition,args=where(ids,a,b,'v.svr_id','v.create_time')
        with self.open('message/media_0.db') as (c,receipt):
            receipts.append(receipt)
            if receipt.get('gap'):gaps.append({'source':'voice','reason':receipt['gap']})
            rows=c.execute('select v.svr_id,v.local_id,v.create_time,length(v.voice_data) size from VoiceInfo v join Name2Id n on n.rowid=v.chat_name_id where n.user_name=? and '+condition+' order by v.create_time,v.svr_id limit ?',[peer,*args,limit+1]).fetchall()
            for x in rows:
                s=sid(x['svr_id'])
                if s not in out:
                    # Private unread metadata is incoming; group sender is still unknown.
                    incoming=s in unread and not peer.endswith('@chatroom')
                    out[s]={'serverId':s,'localId':x['local_id'],'time':x['create_time'],'kind':34,'senderId':peer if incoming else None,'text':'','sourceKind':'voice_media+unread' if incoming else 'voice_media','peer':peer,'messageRowMissing':True}
                    if not incoming and self.metadata:
                        prior=self.metadata.get(peer,s)
                        if prior:out[s].update(prior)
                out[s]['audioBytes']=x['size'];out[s]['audioAvailable']=bool(x['size'])
        for s,x in unread.items():
            if s not in out:
                out[s]={'serverId':s,'localId':x['local_id'],'time':x['create_time'],'kind':None,'senderId':peer if not peer.endswith('@chatroom') else None,'text':None,'sourceKind':'unread_only','peer':peer,'contentMissing':True}
        allrows=sorted(out.values(),key=lambda x:(x['time'],int(x['serverId'])))
        for row in allrows:row['timeBeijing']=beijing(row['time'])
        recovered=sum(bool(x.get('messageRowMissing')) for x in allrows)
        if recovered:gaps.append({'source':'message','reason':'main_message_rows_missing_recovered_from_voice_media','count':recovered})
        missing=[sid(v) for v in (ids or []) if sid(v) not in out]
        return {'state':'ok','account':self.account,'peer':peer,'messages':allrows[:limit],
            'coverage':{'messageMetadataComplete':not gaps and not recovered,'gaps':gaps,'recoveredVoiceCount':recovered,'senderUnresolvedCount':sum(x.get('senderId') is None for x in allrows),'missingIds':missing,'truncated':len(allrows)>limit,'requestedIds':len(ids) if ids else None},'receipts':receipts}
    def voice(self,r):
        peer=self.resolve(r['peer'])['username'];server=sid(r['server_id'])
        with self.open('message/media_0.db') as (c,receipt):
            rows=c.execute('select v.voice_data,v.create_time,v.local_id from VoiceInfo v join Name2Id n on n.rowid=v.chat_name_id where n.user_name=? and v.svr_id=?',(peer,signed(server))).fetchall()
            if not rows:raise ValueError('no voice with that peer and server identity')
            blobs={bytes(x['voice_data']) for x in rows if x['voice_data']}
            if len(blobs)!=1:raise ValueError('missing or conflicting native voice')
            data=blobs.pop()
            if not 0<len(data)<=2000000:raise ValueError('voice byte cap')
            return {'state':'audio_ready','peer':peer,'serverId':server,'time':rows[0]['create_time'],'timeBeijing':beijing(rows[0]['create_time']),'localId':rows[0]['local_id'],'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'codec':'silk' if b'#!SILK_V3' in data[:16] else 'unknown','audio_base64':base64.b64encode(data).decode(),'receipt':receipt}
    def attachments(self,r):
        peer=self.resolve(r['peer'])['username'];server=sid(r['server_id'])
        with self.open('message/message_resource.db') as (c,receipt):
            rows=c.execute('select d.resource_id,d.type,d.size,d.status,d.data_index,d.packed_info,i.message_local_type,i.message_create_time from MessageResourceDetail d join MessageResourceInfo i on i.message_id=d.message_id join ChatName2Id n on n.rowid=i.chat_id where n.user_name=? and i.message_svr_id=? order by d.resource_id limit 65',(peer,signed(server))).fetchall()
            resources=[]
            for x in rows:
                d={k:x[k] for k in x.keys() if k not in ('packed_info','data_index')};d['packedMetadataBytes']=len(x['packed_info'] or b'');resources.append(d)
            return {'state':'metadata_ready' if resources else 'attachment_missing','peer':peer,'serverId':server,'resources':resources,'contentReady':False,'gap':'resource metadata is not a decoded attachment; use attachment with resource_id','receipt':receipt}
    def handle(self,r):
        if not isinstance(r,dict):raise ValueError('object required')
        action=r.get('action')
        if action=='sessions':return self.sessions(r)
        if action=='resolve':return self.resolve(r['peer'])
        if action=='messages':return self.messages(r)
        if action=='voice':return self.voice(r)
        if action=='attachments':return self.attachments(r)
        if action=='attachment':
            from attachments import fetch
            return fetch(self,r)
        if action in ('image_prepare','image'):
            from image_client import dispatch
            return dispatch(self,r)
        if action in ('target_prepare','open_target'):
            from target_picker import dispatch
            return dispatch(self,r)
        if action in ('inspect_target','bind_target','select_target'):
            if self.sender is None:raise ValueError('no sender configured')
            return self.sender(r,self.resolve(r['peer']))
        if action in ('send_text','send_image'):
            if r.get('execute') is not True:raise ValueError('sending requires explicit execute=true')
            target=self.resolve(r['peer'])
            if target.get('contactEvidence',{}).get('consistency')!='committed':raise ValueError('send blocked by contact-source consistency gap')
            if not re.fullmatch('[a-f0-9]{64}',r.get('request_id','')):raise ValueError('SHA256 request ID required')
            if self.sender is None:raise ValueError('no sender configured')
            return self.sender(r,target)
        if action=='delivery':
            if self.sender is None:raise ValueError('no sender configured')
            return self.sender(r,None)
        raise ValueError('unsupported tool action')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');a=p.parse_args()
    if not a.execute:p.print_help();return
    os.umask(0o077);sys.path.insert(0,str(ROOT/'deps'))
    try:
        from sender import dispatch
        from read_metadata import Metadata
        m=Metadata(ROOT/'tool-read-metadata.sqlite')
        try:r=parse_request(sys.stdin.read(1500001));result=Tool(sender=dispatch,metadata=m).handle(r)
        finally:m.close()
        output=json.dumps(result,ensure_ascii=False)
        if len(output.encode())>4000000:raise ValueError('output cap')
        print(output)
    except Exception as e:
        print(json.dumps({'state':'error','errorType':type(e).__name__,'reason':str(e)[:200]}));sys.exit(2)

if __name__=='__main__':main()
