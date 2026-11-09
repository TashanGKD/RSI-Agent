import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
import sys
from contextlib import contextmanager, closing

sys.path.insert(0, str(Path(__file__).parent / 'foundation'))
# Archive preparation is reserved and rejected before every legacy import.
if __name__ == '__main__' and any(arg.startswith('--archive-lock') for arg in sys.argv[1:]):
    from archive_lock_driver import main as _archive_lock_main
    raise SystemExit(_archive_lock_main())
# Reserved connection mode is dispatched before importing legacy worker modules.
if __name__ == '__main__' and any(arg == '--connect' or arg.startswith('--connect=') for arg in sys.argv[1:]):
    from connection_driver import main as _connect_main
    raise SystemExit(_connect_main())
from library import Library, DEFAULT_ROOT
from archive_read import read_archive_index
from media import Media, AttachmentUnavailable
from capture import Jobs
from playback import PlaybackCheckpoint as _playback_checkpoint_factory, PlaybackUnavailable, noop_checkpoint

class ReadOnlyArchive(Library):
    def __init__(self, state, source=None):
        self.state = Path(state).resolve()
        self.source = Path(source) if source is not None else DEFAULT_ROOT
        self.index = self.state / 'index.db'
        self._account_cache = None
        self._conversation_cache = {}
    @contextmanager
    def connect(self):
        with read_archive_index(self.index) as connection:
            yield connection

def local_identity(source, chat, local):
    digest = hashlib.sha256((source + '\nMsg_' + chat + '\n' + str(local)).encode()).digest()
    return -1 - (int.from_bytes(digest[:8], 'little') & 0x7fffffffffffffff)

def media_source_root(value):
    if 'sourceRoot' not in value:return None
    source=Path(value['sourceRoot'])
    if not source.is_absolute():raise ValueError('来源必须为绝对路径')
    for component in (source,*source.parents):
        if component.is_symlink() and not (str(component) in ('/var','/tmp','/etc') and component.resolve()==Path('/private'+str(component))):raise ValueError('来源不能是链接')
    account=value.get('account')
    if not isinstance(account,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',account):raise ValueError('账号标识无效')
    if (source/account).is_symlink() or (source/account/'db_storage').is_symlink() or not (source/account/'db_storage').is_dir():raise ValueError('来源账号目录无效')
    return source.resolve()

def diagnostic_image_path(root,relative):
    if not isinstance(relative,str) or not relative or '\0' in relative:raise ValueError('图片诊断路径无效')
    fragment=Path(relative)
    if fragment.is_absolute() or any(part in ('.','..') for part in fragment.parts):raise ValueError('图片诊断必须限定在所选账号内')
    path=root
    for part in fragment.parts:
        path=path/part
        if path.is_symlink():raise ValueError('图片诊断来源不能是链接')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=128*1024*1024:raise ValueError('图片诊断来源无效或过大')
    return path

def verified_source_database(library, account, relative, empty_non_message=False):
    """Bind a critical verified copy to its content and file identity."""
    try:
        allowed = r'message/[A-Za-z0-9_.-]{1,128}\.db' if empty_non_message else r'(?:contact/contact|message/(?:biz_)?message_[0-9]+)\.db'
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', account) or not re.fullmatch(allowed, relative): raise ValueError('invalid manifest path')
        path=Path(library.state).absolute()
        if path.is_symlink(): raise ValueError('linked archive')
        for part in ('accounts',account,'decrypted',*Path(relative).parts):
            path=path/part
            if path.is_symlink(): raise ValueError('linked source')
        if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')): raise ValueError('source has an unverified journal')
        def identity(info): return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
        with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as source:
            before=os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1: raise ValueError('source is not a private regular copy')
            checkpoint=getattr(library,'checkpoint',noop_checkpoint)
            checkpoint()
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]: raise ValueError('source integrity failed')
                if empty_non_message and db.execute('SELECT COUNT(*) FROM sqlite_schema').fetchone()[0]!=0: raise ValueError('unknown source is no longer empty')
            digest=hashlib.sha256()
            while True:
                checkpoint()
                chunk=source.read(1024*1024)
                if not chunk:break
                digest.update(chunk)
            digest=digest.hexdigest()
            after=os.fstat(source.fileno());current=path.lstat()
            if identity(before)!=identity(after) or identity(before)!=identity(current) or not stat.S_ISREG(current.st_mode) or current.st_nlink!=1: raise ValueError('source changed during verification')
        return {'path':relative,'bytes':before.st_size,'sha256':digest,'identity':':'.join(map(str,identity(before))),'emptyNonMessage':empty_non_message}
    except PlaybackUnavailable:
        raise
    except (OSError,AttributeError,TypeError,sqlite3.Error) as error:
        raise ValueError('关键消息或联系人副本不存在、损坏或发生变化；已保存记录和备份保留') from error

def empty_non_message_database(library, account, relative):
    """Inspect a verified copy anew; no file-name allowlist for unknown DBs."""
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', account): return False
        fragment=Path(relative)
        if fragment.is_absolute() or any(part in ('.','..') for part in fragment.parts): return False
        path=Path(library.state)
        if path.is_symlink(): return False
        for part in ('accounts',account,'decrypted',*fragment.parts):
            path=path/part
            if path.is_symlink(): return False
        if not path.is_file() or any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')): return False
        getattr(library,'checkpoint',noop_checkpoint)()
        with closing(sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True)) as db:
            return db.execute('PRAGMA quick_check').fetchall()==[('ok',)] and db.execute('SELECT COUNT(*) FROM sqlite_schema').fetchone()[0]==0
    except PlaybackUnavailable:
        raise
    except (OSError,ValueError,AttributeError,sqlite3.Error): return False

def main(value=None):
    if value is None: value = json.loads(sys.stdin.buffer.readline(32769))
    if not isinstance(value,dict): raise ValueError("请求必须是对象")
    if value.get('action') in ('capture','import'):
        full = value.get('full', False)
        if not isinstance(full, bool): raise ValueError('全面重新解析标志必须为布尔值')
        scope=value.get('scope','messages')
        if scope not in ('messages','contacts'): raise ValueError('未知导入范围')
        if 'sourceRoot' in value:
            source=Path(value['sourceRoot'])
            if not source.is_absolute(): raise ValueError('来源必须为绝对路径')
            for component in (source,*source.parents):
                if component.is_symlink() and not (str(component) in ('/var','/tmp','/etc') and component.resolve()==Path('/private'+str(component))): raise ValueError('来源不能是链接')
            account=value['account']
            if not isinstance(account,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}',account): raise ValueError('账号无效')
            if (source/account).is_symlink() or (source/account/'db_storage').is_symlink() or not (source/account/'db_storage').is_dir(): raise ValueError('来源账号目录无效')
            library=Library(value['archive'],source=source.resolve())
        else: library = Library(value['archive'])
        library.checkpoint = _playback_checkpoint_factory()
        library.checkpoint()
        jobs = Jobs(library)
        if value['action']=='capture' and not jobs.consent(): raise ValueError('尚未授权本机读取，请在应用中确认读取范围')
        def progress(message):
            jobs.update(message); print(json.dumps({'phase':message},ensure_ascii=False),file=sys.stderr,flush=True)
        jobs.update = lambda message: print(json.dumps({'phase':message},ensure_ascii=False),file=sys.stderr,flush=True)
        # The original reader always refreshes/decrypts each source with the
        # saved keys before rebuilding its index; full does not mean key capture
        # or an index-only rescan. Require complete message coverage for full.
        if scope=='contacts':jobs.run(value['account'],value['action'],contacts_only=True)
        else:jobs.run(value['account'],value['action'])
        result = jobs.status()
        result.update(full=full, fullSourceVerified=False)
        if scope=='contacts' and result.get('state')=='done':
            critical=[row for row in library.coverage(value['account']) if row['path']=='contact/contact.db']
            if len(critical)!=1 or critical[0]['status'] not in ('ready','archived'): raise ValueError('联系人来源未完成校验')
            result.update(sourceScope='contacts',sourceVerified=True,sourceManifest=[verified_source_database(library,value['account'],'contact/contact.db')])
            print(json.dumps(result,ensure_ascii=False));return
        if scope=='messages' and result.get('state')=='done':
            messages=[row for row in library.coverage(value['account']) if re.fullmatch(r'message/(?:biz_)?message_[0-9]+\.db',row['path'])]
            if len(messages)>511 or len({row['path'] for row in messages})!=len(messages):raise ValueError('消息来源覆盖清单不唯一或过多')
            # Indexing may finish after an individual source failed. Preserve
            # available commits, but let every caller report partial failure.
            result.update(messageCoverageChecked=True,messageSourceScope='supported_message_databases',messageSourceCount=len(messages),failedMessageDatabaseCount=sum(row['status'] not in ('ready','archived') for row in messages))
        if full and result.get('state') == 'done':
            coverage = library.coverage(value['account'])
            required = [row for row in coverage if re.fullmatch(r'(?:contact/contact|message/(?:biz_)?message_[0-9]+)\.db', row['path'])]
            # Source names below are the same raw-message providers consumed by
            # Library.import_plain and MacArchiveImport. Media/resource databases
            # are known separate providers; an unknown message DB is not proof
            # that the original-message range was covered.
            # Exact FTS paths were separately classified as derived search
            # providers. This does not permit guessing about e.g. weclaw.db or
            # any other new message provider with an unknown source schema.
            derived_fts = {'contact/contact_fts.db', 'favorite/favorite_fts.db', 'message/message_fts.db'}
            unknown = [row for row in coverage if row['path'].startswith('message/') and row['path'] not in derived_fts and not re.fullmatch(r'message/(?:(?:biz_)?message_[0-9]+|media_[0-9]+|message_resource)\.db', row['path'])]
            empty_unknown = [row for row in unknown if row['status'] in ('ready','decrypted','archived') and empty_non_message_database(library,value['account'],row['path'])]
            if len(empty_unknown)!=len(unknown) or not any(row['path'] == 'contact/contact.db' for row in required) or not any(row['path'].startswith('message/') for row in required) or any(row['status'] not in ('ready', 'archived') for row in required):
                raise ValueError('消息来源未全部解密和校验，未开始全面重新解析；已保存记录和备份保留')
            result['fullSourceVerified'] = True
            if len(required)+len(empty_unknown)>512 or len({row['path'] for row in required+empty_unknown})!=len(required)+len(empty_unknown): raise ValueError('关键来源清单不唯一或过多')
            result['fullSourceManifest'] = [verified_source_database(library,value['account'],row['path']) for row in required]+[verified_source_database(library,value['account'],row['path'],True) for row in empty_unknown]
            result['fullSourceScope'] = 'supported_message_databases'
            result['fullMessageDatabaseCount'] = sum(row['path'].startswith('message/') for row in required)
            result['excludedNonMessageDatabaseCount'] = len(coverage) - len(required)
            result['emptyNonMessageDatabaseCount'] = len(empty_unknown)
        print(json.dumps(result,ensure_ascii=False)); return
    if value.get('action') not in ('attachment','voice','avatar','forwardedAttachment','debugImageDecode'):raise ValueError('未知媒体操作')
    source=media_source_root(value)
    archive = ReadOnlyArchive(value['archive'],source)
    if value.get('action')=='debugImageDecode':
        if source is None:raise ValueError('图片诊断必须明确账号来源')
        account=value['account'];root=archive.account_path(account)
        path=diagnostic_image_path(root,value.get('relativeFile'))
        config_path=archive.state/'keys'/f'{account}.keys.json'
        if config_path.exists() or config_path.is_symlink():
            if (archive.state/'keys').is_symlink() or config_path.is_symlink():raise ValueError('图片缓存密钥不能是链接')
            info=config_path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_size>1024*1024:raise ValueError('图片缓存密钥未通过校验')
            config=json.loads(config_path.read_text())
            if Path(config.get('db_root','')).resolve()!=root.resolve():raise ValueError('图片缓存密钥与账号来源不一致')
        media=Media(archive)
        template=value.get('relativeTemplate')
        if template is not None:
            reference=diagnostic_image_path(root,template)
            if reference!=path:media.image_file({'account':account},root,reference)
        output,mime=media.image_file({'account':account},root,path)
        with path.open('rb') as image_source:key_cached=image_source.read(6)==b'\x07\x08V2\x08\x07'
        print(json.dumps({'status':'ready','path':str(output),'mime':mime,'keyCacheUsed':key_cached,'diagnosticIdentity':{'account':account,'relativeFile':value['relativeFile']}},ensure_ascii=False));return
    account, chat = value['account'], value['chat']
    if not isinstance(account, str) or not isinstance(chat, str) or len(account) > 256 or len(chat) > 256: raise ValueError('消息标识无效')
    media = Media(archive)
    if value['action'] == 'avatar':
        data, mime = media.avatar(account, chat)
        cache = archive.state / 'media'; cache.mkdir(mode=0o700, exist_ok=True)
        path = cache / (hashlib.sha256(data).hexdigest() + '.avatar')
        if not path.is_file(): path.write_bytes(data); os.chmod(path, 0o600)
    else:
        server = int(value['serverId'])
        with archive.connect() as connection:
            chats = connection.execute('SELECT id FROM conversations WHERE account=? AND username=?', (account,chat)).fetchall()
            if len(chats) != 1: raise ValueError('无法确定本地附件所属会话')
            chat_hash = chats[0][0]
            query = 'SELECT m.rowid AS id,m.* FROM messages m INDEXED BY message_time WHERE m.account=? AND m.chat=?'
            rows = connection.execute(query + ' AND m.server_id=? LIMIT 2', (account, chat_hash, str(server))).fetchall()
            if not rows and server < 0: rows = [r for r in connection.execute(query + " AND (m.server_id='0' OR m.server_id='')", (account, chat_hash)) if local_identity(r['source'],r['chat'],r['local_id']) == server]
            if len(rows) != 1: raise ValueError('无法唯一关联本地附件，未打开文件')
            row = rows[0]
            binding=('localId','createTime')
            if any(key in value for key in binding):
                if not all(key in value for key in binding) or type(value['localId']) is not int or type(value['createTime']) is not int:raise ValueError('消息来源身份不完整')
                if ('source' in value and value['source']!=row['source']) or str(value['localId'])!=str(row['local_id']) or value['createTime']!=row['time']:raise ValueError('消息来源已变化，未读取其他资源')
        if value['action'] == 'forwardedAttachment':
            from forwarded_media import forwarded_attachment
            path,mime=forwarded_attachment(media,dict(row),value.get('itemPath'))
        else:
            path, mime = media.voice(row['id']) if value['action'] == 'voice' else media.attachment(row['id'])
    response={'status':'ready','path':str(path),'mime':mime}
    if value['action']!='avatar':response['messageIdentity']={'account':account,'chat':chat,'serverId':str(server),'source':row['source'],'localId':int(row['local_id']),'createTime':row['time']}
    print(json.dumps(response,ensure_ascii=False))

def respond(value=None):
    try:
        if value is None:value=json.loads(sys.stdin.buffer.readline(32769))
        main(value)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        message='图片诊断未完成；账号来源、图片或缓存密钥未通过校验' if isinstance(value,dict) and value.get('action')=='debugImageDecode' else str(error)
        response={'status':'missing','error':message}
        if isinstance(value,dict) and value.get('action')=='attachment' and isinstance(error,AttachmentUnavailable):
            response['errorCode']=error.code
        print(json.dumps(response,ensure_ascii=False))
    finally: sys.stdout.flush()

if __name__ == '__main__':
    if '--serve' in sys.argv:
        while True:
            line=sys.stdin.buffer.readline(32769)
            if not line: break
            if len(line)>32768:
                while line and not line.endswith(b'\n'): line=sys.stdin.buffer.readline(32769)
                print(json.dumps({'status':'missing','error':'请求过长'}),flush=True);continue
            try: value=json.loads(line)
            except (ValueError,RecursionError):
                print(json.dumps({'status':'missing','error':'请求格式无效'}),flush=True);continue
            respond(value)
    else: respond()
