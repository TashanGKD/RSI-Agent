import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from attachment_names import packed_name
from Crypto.Cipher import AES
from library import read_db,columns
from security import qid,safe_path


class AttachmentUnavailable(ValueError):
    """A completed attachment lookup with a bounded, non-system failure reason."""
    def __init__(self,code,message):
        super().__init__(message)
        self.code=code


def _video_path(root,fragment):
    # Check the lexical components before safe_path resolves them, including
    # links which stay inside the account. System aliases in root are allowed.
    current=Path(root).resolve()
    for part in Path(fragment).parts:
        current=current/part
        if current.is_symlink():raise ValueError('视频资源位置不能是链接')
    return safe_path(root,fragment)


def _video_db_exists(path):
    try:info=path.stat()
    except FileNotFoundError:return False
    if not stat.S_ISREG(info.st_mode):raise ValueError('视频缓存数据库必须是普通文件')
    return True


def voice_from_db(path,message,candidates,allow_time=False):
    with read_db(path) as c:
        matches=[]
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        names=next((x for x in tables if x.startswith('Name2Id')),None)
        if names is None: return None
        ids=[r[0] for r in c.execute('SELECT rowid FROM '+qid(names)+' WHERE user_name IN ('+','.join('?' for _ in candidates)+')',candidates)]
        if not ids: return None
        for table in (x for x in tables if x.startswith('VoiceInfo')):
            cols=columns(c,table);bylower={x.lower():x for x in cols}
            def pick(*options):return next((bylower[x] for x in options if x in bylower),None)
            data=pick('voice_data','buf','voicebuf','data');chat=pick('chat_name_id','chatnameid','chat_nameid');svr=pick('msg_svr_id','msgsvrid','svr_id','svrid','server_id','serverid');ts=pick('create_time','createtime','time')
            if not data or not chat:continue
            base='SELECT '+qid(data)+' FROM '+qid(table)+' WHERE '+qid(chat)+' IN ('+','.join('?' for _ in ids)+')'
            rows=[]
            if svr and message.get('server_id') not in ('','0',None):
                rows=c.execute(base+' AND '+qid(svr)+'=?',ids+[message['server_id']]).fetchall()
            if not rows and ts and allow_time and message.get('server_id') in ('','0',None):
                rows=c.execute(base+' AND '+qid(ts)+'=?',ids+[message['time']]).fetchall()
            if len(rows)>1:raise ValueError('同一时间有多条语音，无法唯一关联；请使用含服务器消息编号的数据库')
            if rows and rows[0][0]:
                raw=rows[0][0]
                if isinstance(raw,str):
                    try:raw=bytes.fromhex(raw)
                    except ValueError:raise ValueError('unsupported voice data encoding')
                matches.append(bytes(raw))
        if len(matches)>1:raise ValueError('多个语音表存在不同匹配，无法唯一关联')
        return matches[0] if matches else None


def _image_type(data):
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if data.startswith((b'GIF87a',b'GIF89a')):return 'image/gif'
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP':return 'image/webp'
    return None


def unwrap_wxgf(data):
    if len(data)>128*1024*1024:raise ValueError('图片过大')
    matches=[]
    for match in re.finditer(b'\x00\x00(?:\x00)?\x01',data[4:]):
        matches.append(match)
        if len(matches)>4096:raise ValueError('图片内容复杂度超出限制')
    units=[]
    for i,match in enumerate(matches):
        end=4+matches[i+1].start() if i+1<len(matches) else len(data)
        unit=data[4+match.end():end]
        if len(unit)>=2 and not unit[0]&0x80:units.append(unit)
    starts=[i for i,unit in enumerate(units) if (unit[0]>>1)&63==32]
    candidates=[]
    for i,start in enumerate(starts):
        group=units[start:starts[i+1] if i+1<len(starts) else len(units)]
        if any((unit[0]>>1)&63 in (1,19,20) for unit in group):candidates.append(b''.join(b'\0\0\0\1'+unit for unit in group))
    candidates.sort(key=len,reverse=True)
    if units:candidates.append(b''.join(b'\0\0\0\1'+unit for unit in units))
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise ValueError('此微信图片需要本机图片解码工具')
    for candidate in candidates[:4]:
        try:
            result=subprocess.run([ffmpeg,'-v','error','-threads','1','-max_pixels','16777216','-f','hevc','-i','pipe:0','-frames:v','1','-f','image2pipe','-vcodec','png','pipe:1'],input=candidate,capture_output=True,timeout=15)
            if result.returncode==0 and result.stdout.startswith(b'\x89PNG\r\n\x1a\n') and len(result.stdout)<=64*1024*1024:return result.stdout
        except subprocess.TimeoutExpired:continue
    raise ValueError('微信图片格式解码失败')


def decode_image(data,config):
    if _image_type(data):return data
    if data.startswith(b'wxgf'):return unwrap_wxgf(data)
    if data.startswith(b'\x07\x08V2\x08\x07'):
        aeskey=str(config.get('image_key','')).encode('ascii')
        xor=config.get('image_xor_key')
        if len(aeskey)!=16 or not isinstance(xor,int) or not 0<=xor<=255:raise ValueError('此图片需要单独的图片密钥')
        if len(data)<15:raise ValueError('truncated image')
        aeslen,xorlen=struct.unpack('<II',data[6:14]);aligned=(aeslen//16+1)*16;payload=data[15:]
        if aligned>len(payload) or xorlen>len(payload)-aligned:raise ValueError('invalid image size')
        decoded=AES.new(aeskey,AES.MODE_ECB).decrypt(payload[:aligned]);pad=decoded[-1]
        if not 1<=pad<=16 or decoded[-pad:]!=bytes([pad])*pad:raise ValueError('图片密钥不匹配')
        remaining=payload[aligned:];rawlen=len(remaining)-xorlen
        out=decoded[:-pad]+remaining[:rawlen]+bytes(x^xor for x in remaining[rawlen:])
        if out.startswith(b'wxgf'):return unwrap_wxgf(out)
        if not _image_type(out):raise ValueError('不支持此图片编码')
        return out
    for prefix in (b'\xff\xd8\xff',b'\x89PNG\r\n\x1a\n',b'GIF89a',b'RIFF'):
        if not data:break
        key=data[0]^prefix[0]
        if bytes(x^key for x in data[:len(prefix)])==prefix:
            out=bytes(x^key for x in data)
            if _image_type(out):return out
    raise ValueError('图片尚未成功解码')


class Media:
    def __init__(self,library):self.lib=library

    def avatar(self,account,username):
        self.lib.account_path(account)
        if not isinstance(username,str) or len(username)>256:raise ValueError('头像账号无效')
        path=safe_path(self.lib.state,'accounts/'+account+'/decrypted/head_image/head_image.db')
        if not path.is_file():raise ValueError('头像尚未保存')
        with read_db(path) as c:
            row=c.execute('SELECT image_buffer FROM head_image WHERE username=?',(username,)).fetchone()
            if not row or not row[0] or len(row[0])>2*1024*1024:raise ValueError('没有可显示的本地头像')
            data=bytes(row[0]);mime=_image_type(data)
            if not mime:raise ValueError('本地头像格式不支持')
            return data,mime

    def original_file_name(self,message):
        plain=self.lib.state/'accounts'/message['account']/'decrypted'
        if not re.fullmatch(r'message/(?:message|biz_message)_[0-9]+\.db',message['source']):return None
        path=safe_path(plain,message['source'])
        if not path.is_file():return None
        table='Msg_'+message['chat']
        with read_db(path) as c:
            cols=columns(c,table)
            if not {'packed_info_data','local_id','create_time','local_type'}.issubset(cols):return None
            server=next((x for x in ('server_id','msg_svr_id','svr_id') if x in cols),None)
            clauses=['local_id=?','create_time=?','(local_type & 4294967295)=?'];args=[message['local_id'],message['time'],message['kind']]
            if message['server_id'] not in ('','0',None):
                if not server:return None
                clauses.append(qid(server)+'=?');args.append(message['server_id'])
            rows=c.execute('SELECT packed_info_data FROM '+qid(table)+' WHERE '+' AND '.join(clauses),args).fetchall()
            if len(rows)!=1:return None
            return packed_name(rows[0][0])

    def video_resource_name(self,message):
        server=message.get('server_id');username=message.get('username')
        if isinstance(server,bool) or not re.fullmatch(r'[0-9]{1,19}',str(server or '')):return None
        server=int(server)
        if not 0<server<=9223372036854775807 or not isinstance(username,str) or not username:return None
        path=_video_path(self.lib.state,'accounts/'+message['account']+'/decrypted/message/message_resource.db')
        if not _video_db_exists(path):return None
        with read_db(path) as c:
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'MessageResourceInfo','ChatName2Id'}.issubset(tables):raise ValueError('视频资源数据库缺少必需表')
            cols=columns(c,'MessageResourceInfo')
            clauses=['n.user_name=?','i.message_svr_id=?','(i.message_local_type & 4294967295)=43']
            args=[username,server]
            for column,key in (('message_local_id','local_id'),('message_create_time','time')):
                if column in cols:
                    clauses.append('i.'+qid(column)+'=?');args.append(message[key])
            rows=c.execute('SELECT i.packed_info FROM MessageResourceInfo i JOIN ChatName2Id n ON n.rowid=i.chat_id WHERE '+' AND '.join(clauses)+' LIMIT 2',args).fetchall()
            if len(rows)!=1:return None
            packed=rows[0][0]
            # This strict resource record carries a filename token, not an MD5.
            if not isinstance(packed,bytes) or len(packed)!=36 or packed[:4]!=b'\x12\x22\x0a\x20':return None
            if not re.fullmatch(b'[a-fA-F0-9]{32}',packed[4:]):return None
            return packed[4:].decode('ascii').lower()

    def video_from_resource(self,message,root):
        token=self.video_resource_name(message)
        if not token:raise AttachmentUnavailable('attachment_identity_unavailable','这条消息没有保存可识别的本地文件信息')
        hard=_video_path(self.lib.state,'accounts/'+message['account']+'/decrypted/hardlink/hardlink.db')
        candidate=None
        if _video_db_exists(hard):
            with read_db(hard) as c:
                tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'video_hardlink_info_v4','dir2id'}.issubset(tables):raise ValueError('视频文件数据库缺少必需表')
                rows=c.execute('SELECT file_name,dir1,dir2 FROM video_hardlink_info_v4 WHERE file_name=? COLLATE NOCASE LIMIT 2',(token+'.mp4',)).fetchall()
                if len(rows)>1:raise ValueError('视频资源有多个文件名匹配')
                if rows:
                    row=rows[0]
                    if row['dir2']!=0:raise ValueError('视频资源目录无效')
                    mapping=c.execute('SELECT username FROM dir2id WHERE rowid=?',(row['dir1'],)).fetchone()
                    month=mapping[0] if mapping else None
                    if not isinstance(month,str) or not re.fullmatch(r'[0-9]{4}-(?:0[1-9]|1[0-2])',month) or month.startswith('0000-'):raise ValueError('视频资源月份无效')
                    name=row['file_name']
                    if not isinstance(name,str) or not re.fullmatch(r'[a-fA-F0-9]{32}\.mp4',name,re.IGNORECASE):raise ValueError('视频资源文件名无效')
                    candidate=_video_path(root,str(Path('msg/video')/month/name))
        if candidate is None or not candidate.is_file():raise AttachmentUnavailable('attachment_not_local','当前账号的所选本地来源中未找到对应附件')
        if candidate.stat().st_size>128*1024*1024:raise ValueError('此附件过大，请从微信中查看')
        return candidate,'video/mp4'

    def voice(self,mid):
        message=self.lib.message(mid)
        if message['kind']!=34:raise ValueError('不是语音消息')
        allow_time=False
        if message['server_id'] in ('','0',None):
            with self.lib.connect() as c:
                same_second=c.execute('SELECT count(*) FROM messages WHERE account=? AND chat=? AND time=? AND kind=34',(message['account'],message['chat'],message['time'])).fetchone()[0]
            coverage=[r for r in self.lib.coverage(message['account']) if re.fullmatch(r'message/message_[0-9]+\.db',r['path'])]
            allow_time=same_second==1 and bool(coverage) and all(r['status']=='ready' for r in coverage)
            if not allow_time:raise ValueError('语音缺少消息编号，且同秒消息或聊天分片不完整，无法唯一关联')
        cache=self.lib.state/'media';cache.mkdir(exist_ok=True,mode=0o700)
        identity=[message[k] for k in ('account','chat','source','local_id','server_id','time','raw')]
        cache_id=hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
        dest=cache/f'{cache_id}.wav'
        if dest.exists():return dest,'audio/wav'
        root=self.lib.state/'accounts'/message['account']/'decrypted/message'
        candidates=[message['username']]
        candidates=[x for x in candidates if x]
        if not candidates:raise ValueError('无法确定语音所属会话')
        matches=[]
        for db in sorted(root.glob('media_*.db')):
            blob=voice_from_db(db,message,candidates,allow_time=allow_time)
            if blob:matches.append(blob)
        if len(matches)>1:raise ValueError('多个数据库匹配到语音，未播放以免关联错误')
        if not matches:raise ValueError('未找到本地语音；请检查语音数据库的解密覆盖')
        blob=matches[0]
        if len(blob)>16*1024*1024:raise ValueError('语音数据过大')
        fd,tmp=tempfile.mkstemp(dir=cache,prefix='.voice-',suffix='.silk')
        try:
            with os.fdopen(fd,'wb') as f:f.write(blob)
            node=shutil.which('node')
            if not node:raise ValueError('未找到本地语音解码运行时')
            result=subprocess.run([node,str(Path(__file__).parent/'decode-voice.cjs'),tmp,str(dest)],capture_output=True,timeout=30)
            if result.returncode:dest.unlink(missing_ok=True);raise ValueError('本地语音解码失败')
            os.chmod(dest,0o600);return dest,'audio/wav'
        finally:Path(tmp).unlink(missing_ok=True)

    def local_sticker(self,root,md5):
        # Same five source directories as the original EmojiCache; never borrow
        # another account or trust a matching filename without the content MD5.
        root=root.resolve() # Canonicalize the already validated system /var alias.
        for fragment in ('business/emoticon','emoticon','emoji','msg/emotion','msg/emoji'):
            directory=root
            linked=False
            for part in Path(fragment).parts:
                directory=directory/part
                if directory.is_symlink():linked=True;break
            if linked or not directory.is_dir():continue
            checked=0;visited=0
            for current,dirs,files in os.walk(directory,followlinks=False):
                visited+=1
                if visited>10000:break
                dirs[:]=[name for name in dirs if not (Path(current)/name).is_symlink()]
                for name in files:
                    checked+=1
                    if checked>10000:break
                    if md5.lower() not in name.lower():continue
                    path=Path(current)/name
                    try:
                        if path.is_symlink():continue
                        nofollow=0x20000000 if sys.platform=='darwin' else getattr(os,'O_NOFOLLOW',0)
                        descriptor=os.open(path,os.O_RDONLY|os.O_NONBLOCK|nofollow)
                        with os.fdopen(descriptor,'rb') as source:
                            before=os.fstat(source.fileno())
                            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<before.st_size<=8*1024*1024:continue
                            data=source.read(8*1024*1024+1);after=os.fstat(source.fileno())
                        identity=lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
                        if identity(before)!=identity(after) or identity(before)!=identity(path.lstat()) or len(data)!=before.st_size:continue
                        mime=_image_type(data)
                        if mime and hashlib.md5(data).hexdigest()==md5.lower():return path,mime
                    except OSError:continue
                if checked>=10000:break
        return None

    def attachment(self,mid):
        message=self.lib.message(mid);root=self.lib.account_path(message['account'])
        metadata=json.loads(message['metadata']);md5=metadata.get('md5') or metadata.get('rawmd5','')
        if not re.fullmatch('[a-fA-F0-9]{32}',md5 or ''):md5=''
        if message['kind']==43 and not md5:return self.video_from_resource(message,root)
        if message['kind']==47 and md5:
            local=self.local_sticker(root,md5)
            if local:return local
        filename=None
        if not md5 or message['kind'] in (3,47):
            try:filename=self.original_file_name(message)
            except ValueError:
                if not md5:raise
        if not md5 and not filename:raise AttachmentUnavailable('attachment_identity_unavailable','这条消息没有保存可识别的本地文件信息')
        directory=safe_path(root,'msg/attach/'+message['chat'])
        matches=[]
        if filename and message['kind'] in (3,47):
            months={datetime.utcfromtimestamp(message['time']+delta).strftime('%Y-%m') for delta in (-86400,0,86400)}
            for month in sorted(months):
                for suffix in ('_h.dat','.dat','_t.dat','.t.dat'):
                    candidate=safe_path(root,str(Path('msg/attach')/message['chat']/month/'Img'/(filename+suffix)))
                    if candidate.is_file():matches.append(candidate)
        hard=self.lib.state/'accounts'/message['account']/'decrypted/hardlink/hardlink.db'
        kind=message['kind'];table={3:'image_hardlink_info_v4',47:'image_hardlink_info_v4',43:'video_hardlink_info_v4',49:'file_hardlink_info_v4'}.get(kind)
        if not matches and hard.exists() and table:
            with read_db(hard) as c:
                tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if table in tables and 'dir2id' in tables:
                    if md5:rows=c.execute('SELECT file_name,dir1,dir2 FROM '+qid(table)+' WHERE md5=? OR md5=?',(md5,bytes.fromhex(md5))).fetchall()
                    else:rows=c.execute('SELECT file_name,dir1,dir2 FROM '+qid(table)+' WHERE file_name IN (?,?,?,?)',tuple(filename+x for x in ('_h.dat','.dat','_t.dat','.t.dat'))).fetchall()
                    for row in rows:
                        parts=[]
                        for col in ('dir1','dir2'):
                            value=c.execute('SELECT username FROM dir2id WHERE rowid=?',(row[col],)).fetchone()
                            if value:parts.append(str(value[0]))
                            elif row[col] in (0,None):parts.append('')
                            else:raise ValueError('附件目录映射缺失')
                        if kind in (3,47):fragment=Path('msg/attach')/parts[0]/parts[1]/'Img'/row['file_name']
                        else:fragment=Path('msg')/('video' if kind==43 else 'file')/parts[0]/parts[1]/row['file_name']
                        candidate=safe_path(root,str(fragment))
                        if candidate.is_file() and not candidate.is_symlink():matches.append(candidate)
        if not matches and md5 and directory.exists():
            for p in directory.rglob('*'):
                if p.is_file() and not p.is_symlink() and (p.stem==md5 or p.stem in (md5+'_t',md5+'_h')):
                    matches.append(p)
        if not matches:raise AttachmentUnavailable('attachment_not_local','当前账号的所选本地来源中未找到对应附件')
        matches.sort(key=lambda p:('_t' in p.stem,'_h' not in p.stem))
        if message['kind'] in (3,47):
            error=None
            for candidate in matches[:8]:
                try:return self.image_file(message,root,safe_path(root,str(candidate.relative_to(root))))
                except (ValueError,OSError) as e:error=e
            raise ValueError('本机图片暂时无法解码：'+str(error))
        p=safe_path(root,str(matches[0].relative_to(root)))
        if p.stat().st_size>128*1024*1024:raise ValueError('此附件过大，请从微信中查看')
        if message['kind']==43 and p.suffix.lower()=='.mp4':return p,'video/mp4'
        return p,'application/octet-stream'

    def image_file(self,message,root,p):
        if p.stat().st_size>128*1024*1024:raise ValueError('图片过大')
        cache=self.lib.state/'media'
        if cache.is_symlink():raise ValueError('图片缓存目录不能是链接')
        cache.mkdir(exist_ok=True,mode=0o700)
        if cache.is_symlink() or not cache.resolve().is_relative_to(self.lib.state.resolve()):raise ValueError('图片缓存目录不属于当前归档')
        identity=['image-v2',message['account'],str(p.relative_to(root)),p.stat().st_size,p.stat().st_mtime_ns]
        dest=cache/(hashlib.sha256(json.dumps(identity).encode()).hexdigest()+'.image')
        if dest.is_symlink() or not dest.resolve().is_relative_to(cache.resolve()):raise ValueError('图片缓存位置不能是链接')
        if dest.is_file():
            fd=os.open(dest,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
            with os.fdopen(fd,'rb') as f:mime=_image_type(f.read(16))
            if mime:return dest,mime
        cfgpath=self.lib.state/'keys'/f"{message['account']}.keys.json"
        config=json.loads(cfgpath.read_text()) if cfgpath.exists() else {}
        data=decode_image(p.read_bytes(),config)
        fd,tmp=tempfile.mkstemp(dir=cache,prefix='.image-')
        try:
            with os.fdopen(fd,'wb') as f:f.write(data)
            os.replace(tmp,dest);os.chmod(dest,0o600)
        finally:Path(tmp).unlink(missing_ok=True)
        return dest,_image_type(data)
