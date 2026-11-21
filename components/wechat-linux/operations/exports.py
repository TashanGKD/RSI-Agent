"""Exact native file cache binding. No caller path, no full-media copies."""
import hashlib,re
from .proof import xml

MAX_FILE_BYTES=25000000
class FileTooLarge(ValueError):pass

def file_identity(raw):
 r=xml(raw);name=r.findtext('.//appmsg/title');length=r.findtext('.//totallen') or '';md5=r.findtext('.//filemd5') or r.findtext('.//md5') or ''
 if r.findtext('.//appmsg/type')!='6' or not isinstance(name,str) or not 1<=len(name.encode())<=180 or any(x in name for x in ['/','\\','\0','\r','\n']) or name in ('.','..'):raise ValueError('bounded ordinary-file identity required')
 if not re.fullmatch('[0-9]{1,9}',length) or not 0<int(length) or not re.fullmatch('[a-fA-F0-9]{32}',md5):raise ValueError('native file size/MD5 not available')
 if int(length)>MAX_FILE_BYTES:raise FileTooLarge('native file exceeds the read budget')
 return {'name':name,'size':int(length),'md5':md5.lower()}
def validate_bytes(meta,data):
 if len(data)!=meta['size'] or hashlib.md5(data).hexdigest()!=meta['md5']:raise ValueError('cache content differs from exact native message')

def cached(peer,server,resource,raw):
 from linux_tool import native,signed,PROFILE
 from attachments import read_bound
 meta=file_identity(raw)
 with native('message/message_resource.db') as (c,r):
  if r.get('consistency')!='committed':raise ValueError('resource snapshot gap')
  sql='select d.resource_id,d.size,d.status,d.type,d.packed_info from MessageResourceDetail d join MessageResourceInfo i on i.message_id=d.message_id join ChatName2Id n on n.rowid=i.chat_id where n.user_name=? and i.message_svr_id=?'
  args=[peer,signed(server)]
  if resource is not None:sql+=' and d.resource_id=?';args.append(resource)
  rows=c.execute(sql+' limit 65',args).fetchall()
  rows=[x for x in rows if x['size']==meta['size'] and x['status']==1 and x['type'] in (3735555,3407875,3342339,3801091)]
  if len(rows)!=1:raise ValueError('no unique completed ordinary-file resource; use official client to download first')
  row=rows[0];packed=bytes(row['packed_info'] or b'');rid=row['resource_id']
  if len(packed)>16384:raise ValueError('resource metadata over budget')
 paths=[]
 with native('hardlink/hardlink.db') as (c,r):
  if r.get('consistency')!='committed':raise ValueError('file index snapshot gap')
  rows=c.execute('select md5,file_name,file_size,dir1,dir2 from file_hardlink_info_v4 where md5=? or md5=? limit 5',(meta['md5'],bytes.fromhex(meta['md5']))).fetchall()
  if len(rows)>4:raise ValueError('file index ambiguous')
  for x in rows:
   name=x['file_name']
   if not isinstance(name,str) or any(k in name for k in ['/','\\','\0','\r','\n']) or name in ('.','..'):raise ValueError('unsafe cached filename')
   if x['dir2']!=0 or x['file_size']!=meta['size'] or name.encode() not in packed:continue
   month=c.execute('select username from dir2id where rowid=?',(x['dir1'],)).fetchone()
   if month and re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])',month[0]):
    p=PROFILE/'msg/file'/month[0]/name
    if p.is_file():paths.append(p)
 paths=list(dict.fromkeys(paths))
 if len(paths)!=1:raise ValueError('resource/cache identity absent or ambiguous')
 data=read_bound(PROFILE,paths[0],cap=MAX_FILE_BYTES);validate_bytes(meta,data)
 return data,dict(meta,resourceId=rid,sourceId=server,nativeMessageMD5Matched=True,resourceCacheBindingVerified=True)
