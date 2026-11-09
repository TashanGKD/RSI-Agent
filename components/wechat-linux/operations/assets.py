"""Owner content-addressed assets; streaming, atomic publication and provenance."""
import os,json,hashlib,re,stat,tempfile,io,fcntl,shutil,time
from pathlib import Path
from contextlib import contextmanager
from .store import private_root
from .contract import ident,digest
CHUNK=1048576
# No configured business-size/cache-total ceiling. Admission depends on actual
# disk headroom; explicit finite overrides remain usable by isolated tests.
SINGLE_BYTES=None
TOTAL_BYTES=None
RESERVE_BYTES=0
INLINE_BYTES=10000000

class AssetBudgetError(ValueError):
 def __init__(self,code,required,available,limit):
  super().__init__('Asset budget rejected before publication; no automatic deletion or sending.')
  self.code=code;self.details={'requiredBytes':required,'availableBytes':max(0,available),'limitBytes':limit}
 def response(self):return {'state':'error','error':{'code':self.code,'message':str(self),'details':self.details}}

def filename(name):
 if not isinstance(name,str) or not name or name in ('.','..') or '/' in name or '\0' in name:raise ValueError('actual filesystem filename required')
 return name

def descriptor(client,name,size,sha):
 ident(client);filename(name)
 if type(size) is not int or not 0<size<(1<<63) or (SINGLE_BYTES is not None and size>SINGLE_BYTES) or not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('regular-file size/checksum required')
 return digest({'client':client,'name':name,'sha256':sha})

class Assets:
 def __init__(self,root):self.root=private_root(Path(root)/'assets')
 @contextmanager
 def _lock(self,deadline):
  fd=os.open(self.root.parent/'assets-upload.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
  try:
   s=os.fstat(fd)
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('unsafe asset lock')
   while True:
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
    except BlockingIOError:
     if time.monotonic()>=deadline:raise ValueError('asset upload lock deadline')
     time.sleep(.025)
   yield
  finally:os.close(fd)
 def _usage(self):
  total=0
  for folder in self.root.iterdir():
   if folder.is_symlink() or not folder.is_dir():raise ValueError('asset store layout invalid')
   for p in folder.iterdir():
    s=p.lstat()
    if s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('unsafe stored asset component')
    if stat.S_ISREG(s.st_mode):total+=s.st_size
    elif p.name=='file' and stat.S_ISDIR(s.st_mode):
     for q in p.iterdir():
      info=q.lstat()
      if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('unsafe stored payload component')
      total+=info.st_size
    else:raise ValueError('unsafe stored asset component')
  return total
 def put(self,client,name,data,sha):
  if not isinstance(data,bytes) or not data:raise ValueError('actual asset bytes required')
  return self.put_stream(client,name,io.BytesIO(data),len(data),sha)
 def put_stream(self,client,name,source,size,sha,*,deadline=None):
  aid=descriptor(client,name,size,sha);folder=self.root/aid
  with self._lock(deadline if deadline is not None else time.monotonic()+20):
   exists=folder.exists() or folder.is_symlink()
   if exists:self.get(client,aid)
   free=shutil.disk_usage(self.root).free
   if TOTAL_BYTES is not None:
    usage=self._usage()
    if usage+size+4096>TOTAL_BYTES:raise AssetBudgetError('ASSET_QUOTA',size+4096,TOTAL_BYTES-usage,TOTAL_BYTES)
   if free<size+RESERVE_BYTES:raise AssetBudgetError('ASSET_DISK_RESERVE',size,free-RESERVE_BYTES,RESERVE_BYTES)
   with tempfile.TemporaryDirectory(prefix='.asset-',dir=self.root) as td:
    temp=Path(td);data_dir=temp
    if name=='metadata.json':data_dir=temp/'file';data_dir.mkdir(mode=0o700)
    p=data_dir/name;fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600);h=hashlib.sha256();m=hashlib.md5();n=0
    with os.fdopen(fd,'wb') as out:
     while n<size:
      if deadline is not None and time.monotonic()>=deadline:raise ValueError('explicit asset upload deadline')
      chunk=source.read(min(CHUNK,size-n))
      if not isinstance(chunk,bytes) or not chunk:raise ValueError('truncated asset stream')
      if len(chunk)>min(CHUNK,size-n):raise ValueError('asset stream exceeded declared size')
      out.write(chunk);h.update(chunk);m.update(chunk);n+=len(chunk)
      if shutil.disk_usage(self.root).free<RESERVE_BYTES:raise ValueError('asset disk reserve exhausted')
     if source.read(1):raise ValueError('extra asset stream bytes')
     if (deadline is not None and time.monotonic()>=deadline) or h.hexdigest()!=sha:raise ValueError('asset bytes/checksum/deadline mismatch')
     out.flush();os.fsync(out.fileno())
    meta={'id':aid,'client':client,'name':name,'bytes':size,'sha256':sha,'md5':m.hexdigest()}
    q=temp/'metadata.json';fd=os.open(q,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(meta,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    if not exists:
     # A waiting job becomes ready at this rename. Serialize that transition
     # with maintenance's original Store transaction, not just batch insertion.
     from .store import Store
     state=Store(self.root.parent)
     try:
      with state.tx():os.rename(temp,folder)
     finally:state.close()
   return self.get(client,aid)
 def get(self,client,aid):
  ident(client)
  if not isinstance(aid,str) or not re.fullmatch('[a-f0-9]{64}',aid):raise ValueError('asset ID required')
  folder=self.root/aid
  if folder.is_symlink() or not folder.is_dir():raise ValueError('asset folder invalid')
  ms=folder.stat()
  if ms.st_uid!=os.getuid() or ms.st_mode&0o077:raise ValueError('unsafe asset folder')
  meta=folder/'metadata.json'
  fd=os.open(meta,os.O_RDONLY|os.O_NOFOLLOW)
  try:
   s=os.fstat(fd)
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>4096:raise ValueError('asset metadata invalid')
   with os.fdopen(fd,'r') as f:fd=None;x=json.load(f)
  finally:
   if fd is not None:os.close(fd)
  if descriptor(x.get('client'),x.get('name'),x.get('bytes'),x.get('sha256'))!=aid or x.get('id')!=aid:raise ValueError('asset metadata identity mismatch')
  parent=folder/'file' if x['name']=='metadata.json' else folder
  if parent.is_symlink() or not parent.is_dir() or parent.stat().st_uid!=os.getuid() or parent.stat().st_mode&0o077:raise ValueError('unsafe stored payload parent')
  p=parent/x['name']
  try:fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  except OSError:raise ValueError('unsafe asset path') from None
  try:
   s=os.fstat(fd)
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_nlink!=1 or s.st_size!=x['bytes']:raise ValueError('asset changed')
   h=hashlib.sha256();m=hashlib.md5();n=0
   while True:
    data=os.read(fd,CHUNK)
    if not data:break
    n+=len(data)
    if n>x['bytes']:raise ValueError('asset grew during validation')
    h.update(data);m.update(data)
   after=os.fstat(fd)
   if (s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or n!=x['bytes'] or h.hexdigest()!=x['sha256'] or m.hexdigest()!=x.get('md5'):raise ValueError('asset checksum/identity changed')
  except OSError:raise ValueError('unsafe asset path') from None
  finally:os.close(fd)
  return dict(x,path=str(p))

def validate_image(data,*,encoded_byte_limit=None):
 """Validate the image and report whether it contains multiple frames."""
 if not isinstance(data,bytes) or not data:raise ValueError('actual image bytes required')
 from PIL import Image
 Image.MAX_IMAGE_PIXELS=None
 try:
  with Image.open(io.BytesIO(data)) as image:
   image.verify()
  with Image.open(io.BytesIO(data)) as image:
   image.load()
   return bool(getattr(image,'is_animated',False))
 except Exception:raise ValueError('image is not readable by the installed decoder') from None
