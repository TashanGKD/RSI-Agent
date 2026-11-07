"""Small inter-tool display ownership notice, coupled to a live process identity."""
import json,time,os,fcntl,stat
from pathlib import Path
def birth(pid):
 try:return Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[19]
 except (OSError,IndexError):return 'local-test' if pid==os.getpid() and not Path('/proc').exists() else None
def guard_busy(root):
 p=Path(root)/'display-guard.lock'
 if p.is_symlink():raise ValueError('display guard symlink refused')
 if not p.exists():return False
 fd=os.open(p,os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  mode=os.fstat(fd)
  if not stat.S_ISREG(mode.st_mode) or mode.st_uid!=os.getuid() or mode.st_mode&0o077:raise ValueError('private regular display guard required')
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return True
  return False
 finally:os.close(fd)
def active(root):
 if guard_busy(root):return True
 # Protected originals remain reserved while the executor yields its physical
 # guards to the existing same-original recovery path. No UI caller may treat
 # that handoff as ordinary idle, including the older desktop/native adapters.
 db=Path(root)/'queue.sqlite'
 if db.is_symlink():raise ValueError('state database symlink refused')
 if db.exists():
  before=db.stat()
  if not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_mode&0o077:raise ValueError('private regular state database required')
  import sqlite3
  from .store import ACTIVE
  try:
   c=sqlite3.connect(db.absolute().as_uri()+'?mode=ro',uri=True,timeout=.1)
   try:protected=c.execute('SELECT 1 FROM jobs WHERE state IN ('+','.join('?' for _ in ACTIVE)+') LIMIT 1',ACTIVE).fetchone()
   finally:c.close()
  except sqlite3.Error:return True # Unreadable/unknown state is never idle.
  after=db.stat()
  if db.is_symlink() or (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):raise ValueError('state database identity changed')
  if protected:return True
 p=Path(root)/'display-lease.json'
 if p.is_symlink():raise ValueError('display lease symlink refused')
 if not p.exists():return False
 if p.stat().st_mode&0o077 or p.stat().st_uid!=os.getuid() or p.stat().st_size>4096:raise ValueError('private display lease required')
 x=json.loads(p.read_text());return bool(x.get('expiresAt',0)>time.time() and birth(x.get('pid')) is not None and birth(x.get('pid'))==x.get('birth'))
def publish(root):
 p=Path(root)/'display-lease.json'
 if p.is_symlink():raise ValueError('display lease symlink refused')
 x={'pid':os.getpid(),'birth':birth(os.getpid()),'expiresAt':time.time()+5,'purpose':'serial explicit operations'};tmp=p.with_suffix('.tmp')
 if tmp.is_symlink():raise ValueError('display lease temporary symlink refused')
 fd=os.open(tmp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(x,f);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
def release(root):
 p=Path(root)/'display-lease.json'
 if p.is_symlink():raise ValueError('display lease symlink refused')
 if p.exists() and json.loads(p.read_text()).get('pid')==os.getpid():p.unlink()

def desktop_busy(session,now,process_birth=birth):
 if session.get('expiresAt',0)+5<=now or session.get('mode') not in ('navigate','compose'):return False
 processes=session.get('processes')
 if not isinstance(processes,list) or not processes:return True
 return any(p.get('birth') is None or process_birth(p.get('pid'))==p['birth'] for p in processes)

from contextlib import contextmanager
class MaintenanceDeferred(ValueError):pass
@contextmanager
def maintenance_guard(root):
 """Caller retains original session/kernel guards; admission shares this DB txn.
 A readonly eligibility response is never a substitute for this reservation.
 """
 from .store import Store
 s=Store(root)
 try:
  with s.tx():
   check=s.maintenance_eligibility()
   if not check['eligible']:raise MaintenanceDeferred('maintenance deferred: '+check['reason'])
   yield check
 finally:s.close()
