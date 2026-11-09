"""Exact message/resource attachment lookup, no caller-provided source paths."""
import base64,hashlib,os,re,stat
from pathlib import Path

def read_bound(root,path,cap=None):
    root=Path(root).absolute();path=Path(path).absolute()
    if '..' in path.parts or not path.is_relative_to(root):raise ValueError('attachment path outside profile')
    for p in [path,*path.parents]:
        if p.is_symlink():raise ValueError('attachment symlink refused')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size<=0 or (cap is not None and info.st_size>cap):raise ValueError('actual nonempty attachment required')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as f:
        data=f.read(info.st_size+1)
        if len(data)!=info.st_size:raise ValueError('attachment changed while reading')
        after=os.fstat(f.fileno())
    if (info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('attachment changed while reading')
    return data

def fetch(tool,r):
    from linux_tool import signed,PROFILE
    peer=tool.resolve(r['peer'])['username'];server=r['server_id'];resource=r.get('resource_id')
    if type(resource) is not int or resource<1:raise ValueError('positive exact resource_id required')
    with tool.open('message/message_resource.db') as (c,receipt):
        rows=c.execute('select d.resource_id,d.size,d.type,i.packed_info from MessageResourceDetail d join MessageResourceInfo i on i.message_id=d.message_id join ChatName2Id n on n.rowid=i.chat_id where n.user_name=? and i.message_svr_id=? and d.resource_id=?',(peer,signed(server),resource)).fetchall()
        if len(rows)!=1:raise ValueError('resource not bound to this peer/server ID')
        packed=bytes(rows[0]['packed_info'] or b'');kind=rows[0]['type'];expected=rows[0]['size']
    hashes={x.decode() for x in re.findall(rb'[0-9a-f]{32}',packed)}
    if not hashes:return {'state':'attachment_unavailable','peer':peer,'serverId':str(server),'resourceId':resource,'gap':'no verifiable local attachment identifier'}
    candidates=[]
    with tool.open('hardlink/hardlink.db') as (c,hr):
        dirs={x[0]:x[1] for x in c.execute('select rowid,username from dir2id')}
        for table,sub in [('image_hardlink_info_v4','Img'),('file_hardlink_info_v4','File'),('video_hardlink_info_v4','Video')]:
            for h in hashes:
                for x in c.execute('select file_name,md5,dir1,dir2 from '+table+' where md5=? or file_name like ? limit 65',(h,h+'%')):
                    d1,d2=dirs.get(x['dir1']),dirs.get(x['dir2']);name=x['file_name']
                    if d1!=hashlib.md5(peer.encode()).hexdigest() or not d2 or not re.fullmatch(r'20\d\d-\d\d',d2):continue
                    if not isinstance(name,str) or '/' in name or '\\' in name or '..' in name:raise ValueError('unsafe native attachment filename')
                    names=[name]
                    if kind==262145 and name.endswith('.dat'):names=[name.removesuffix('_h.dat').removesuffix('.dat')+'_t.dat']
                    for n in names:
                        p=PROFILE/'msg/attach'/d1/d2/sub/n
                        if p.exists() and (not expected or p.stat().st_size in (expected,expected+31)):candidates.append(p)
    candidates=list(dict.fromkeys(candidates))
    if len(candidates)!=1:return {'state':'attachment_unavailable','peer':peer,'serverId':str(server),'resourceId':resource,'gap':'missing or ambiguous local file','candidateCount':len(candidates)}
    data=read_bound(PROFILE,candidates[0]);encrypted=data.startswith((b'\x07\x08V1',b'\x07\x08V2'))
    ready=not encrypted and (candidates[0].suffix!='.dat' or data.startswith((b'\xff\xd8\xff',b'\x89PNG\r\n\x1a\n',b'GIF8',b'RIFF')))
    return {'state':'attachment_ready','peer':peer,'serverId':str(server),'resourceId':resource,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'content_base64':base64.b64encode(data).decode(),'encoding':'wechat-v2-encrypted' if encrypted else 'native-file','contentReady':ready,'gap':'native image encoding not decoded; no process/key extraction performed' if not ready else None,'receipt':receipt}
