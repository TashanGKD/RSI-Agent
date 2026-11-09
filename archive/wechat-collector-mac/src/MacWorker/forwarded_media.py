"""Forwarded attachments: parent row -> bounded original record path -> exact hash map.

The caller must resolve `parent` uniquely by account/chat/serverId using the normal
worker query. UI-supplied hashes, names and paths are never accepted here.
"""
import hashlib
import re
from pathlib import Path
from library import read_db
from security import xml_root


def _record(container):
    if container is None: return None
    if container.tag == 'recordinfo': return container
    record=container.find('recordinfo')
    if record is None and container.text and container.text.strip(): record=xml_root(container.text)
    return record if record is not None and record.tag == 'recordinfo' else None


def resolve_item(parent,item_path):
    if not isinstance(item_path,list) or not 1<=len(item_path)<=5 or any(type(i) is not int or not 0<=i<500 for i in item_path):raise ValueError('转发条目标识无效')
    if parent.get('kind')!=49:raise ValueError('父消息不是聊天记录')
    raw=parent.get('raw')
    if not isinstance(raw,str):raise ValueError('转发正文未保存')
    # Group messages may prefix their XML with a sender line, just like the core parser.
    if not raw.startswith('<') and ':\n' in raw:raw=raw.split(':\n',1)[1]
    if raw.startswith('<msg><?xml '):
        end=raw.find('?>',5,256)
        if end>5:raw='<msg>'+raw[end+2:]
    root=xml_root(raw)
    app=root.find('appmsg') if root is not None and root.tag=='msg' else root if root is not None and root.tag=='appmsg' else None
    record=_record(app.find('recorditem') if app is not None else None)
    remaining=[500]
    def walk(record,depth):
        if record is None or depth>=5:return []
        data=record.find('datalist');items=[]
        if data is None:return items
        for node in data:
            if node.tag!='dataitem':continue
            if remaining[0]<=0:break
            remaining[0]-=1
            nested=walk(_record(node.find('recordxml')),depth+1) if node.get('datatype')=='17' else None
            items.append((node,nested))
        return items
    tree=walk(record,0);selected=None
    for depth,index in enumerate(item_path):
        if index>=len(tree):raise ValueError('转发条目已更新或超出展开上限')
        selected,nested=tree[index]
        if depth+1<len(item_path):
            if nested is None:raise ValueError('此条目没有子聊天记录')
            tree=nested
    kind=selected.get('datatype')
    if kind not in ('2','8'):raise ValueError('此转发条目没有本地图片或文件')
    hash=(selected.findtext('fullmd5') or '').strip()
    if not re.fullmatch('[a-fA-F0-9]{32}',hash):raise ValueError('此条目未保存可验证的附件标识')
    name=(selected.findtext('datatitle') or '').strip() if kind=='8' else None
    if kind=='8' and (not name or len(name)>255 or name in ('.','..') or any(x in name for x in ('/','\\','\0'))):raise ValueError('转发文件名称无效')
    size=selected.findtext('datasize')
    if size is not None and (not re.fullmatch('[0-9]{1,19}',size) or int(size)>128*1024*1024):raise ValueError('转发附件大小无效或超出限制')
    return {'kind':int(kind),'hash':hash.lower(),'name':name,'size':int(size) if size is not None else None}


def _inside_without_links(root,path):
    root=Path(root).absolute();path=Path(path).absolute()
    try:relative=path.relative_to(root)
    except ValueError:raise ValueError('附件位置不属于当前账号')
    current=root
    if current.is_symlink():raise ValueError('附件目录不能是链接')
    for part in relative.parts:
        if part in ('.','..'):raise ValueError('附件路径无效')
        current=current/part
        if current.is_symlink():raise ValueError('附件位置不能是链接')
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('附件位置不属于当前账号')
    return path


def forwarded_attachment(media,parent,item_path):
    item=resolve_item(parent,item_path)
    account=parent.get('account');chat=parent.get('chat')
    if not isinstance(account,str) or not re.fullmatch('[A-Za-z0-9_-]{1,256}',account) or not isinstance(chat,str) or not re.fullmatch('[a-fA-F0-9]{32}',chat):raise ValueError('父消息账号或会话无效')
    source=Path(media.lib.account_path(account))
    if hasattr(media.lib,'source'):
        _inside_without_links(media.lib.source,Path(media.lib.source)/account)
    hard=_inside_without_links(media.lib.state,Path(media.lib.state)/'accounts'/account/'decrypted/hardlink/hardlink.db')
    if not hard.is_file():raise ValueError('当前账号未保存附件资源索引')
    table='image_hardlink_info_v4' if item['kind']==2 else 'file_hardlink_info_v4'
    candidates=[]
    with read_db(hard) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if table not in tables or 'dir2id' not in tables:raise ValueError('本地未找到该转发附件的资源映射')
        rows=db.execute('SELECT file_name,dir1,dir2 FROM '+table+' WHERE md5=? COLLATE NOCASE OR md5=? LIMIT 21',(item['hash'],bytes.fromhex(item['hash']))).fetchall()
        if len(rows)>20:raise ValueError('转发附件资源映射过多，未打开文件')
        for row in rows:
            parts=[]
            for key in ('dir1','dir2'):
                entry=db.execute('SELECT username FROM dir2id WHERE rowid=?',(row[key],)).fetchone()
                if entry is not None:parts.append(str(entry[0]))
                elif row[key] in (0,None):parts.append('')
                else:raise ValueError('附件目录映射缺失')
            name=row['file_name']
            if not isinstance(name,str) or not name or len(name)>255 or name in ('.','..') or any(x in name for x in ('/','\\','\0')):raise ValueError('附件映射名称无效')
            if item['kind']==2:
                if not re.fullmatch('[a-fA-F0-9]{32}',parts[0]) or not re.fullmatch('[0-9]{4}-(?:0[1-9]|1[0-2])',parts[1]):raise ValueError('图片目录映射无效')
            elif any(part in ('.','..') or len(part)>255 or any(x in part for x in ('/','\\','\0')) for part in parts):raise ValueError('文件目录映射无效')
            relative=Path('msg/attach')/parts[0]/parts[1]/'Img'/name if item['kind']==2 else Path('msg/file')/parts[0]/parts[1]/name
            path=_inside_without_links(source,source/relative)
            if path.is_file():
                if path.stat().st_size>128*1024*1024:raise ValueError('转发附件过大，请从微信中查看')
                if item['kind']==8:
                    if item['size'] is not None and path.stat().st_size!=item['size']:continue
                    digest=hashlib.md5()
                    with path.open('rb') as stream:
                        for chunk in iter(lambda:stream.read(128*1024),b''):digest.update(chunk)
                    if digest.hexdigest()!=item['hash']:continue
                if path not in candidates:candidates.append(path)
    if not candidates:raise ValueError('本地未找到可验证的转发附件，可能尚未下载')
    if item['kind']==8:
        if len(candidates)!=1:raise ValueError('多个文件匹配该转发条目，未自动打开')
        return candidates[0],'application/octet-stream'
    _inside_without_links(media.lib.state,Path(media.lib.state)/'media')
    _inside_without_links(media.lib.state,Path(media.lib.state)/'keys'/(account+'.keys.json'))
    candidates.sort(key=lambda p:('_t' in p.stem,'_h' not in p.stem))
    for candidate in candidates[:8]:
        try:return media.image_file(parent,source,candidate)
        except (ValueError,OSError):continue
    raise ValueError('本地转发图片暂时无法解码')
