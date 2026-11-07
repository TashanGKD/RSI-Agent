"""Respect a finite local ownership notice before opening the shared AUP display."""
import json,os,time,fcntl,argparse,re
from pathlib import Path
NOTICE=Path(os.environ.get('SECRETARY_WORKSPACE','var/workspace'))/'.runtime/aup-ui-ownership.json'
def check(notice,thread_id,now):
 if notice.get('expiresAt',0)>now and notice.get('ownerThreadId')!=thread_id:raise PermissionError('AUP window is owned by another active task; finish coordination first')
def check_from_env():
 if not NOTICE.exists():return
 if NOTICE.is_symlink() or NOTICE.stat().st_mode&0o077 or NOTICE.stat().st_uid!=os.getuid():raise ValueError('private UI ownership notice required')
 check(json.loads(NOTICE.read_text()),os.environ.get('CODEX_THREAD_ID'),time.time())
def acquire(ttl,purpose):
 actor=os.environ.get('CODEX_THREAD_ID')
 if not re.fullmatch('[a-f0-9-]{36}',actor or '') or type(ttl) is not int or not 60<=ttl<=1800:raise ValueError('real native conversation and bounded lease required')
 fd=os.open(NOTICE.with_suffix('.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  old=json.loads(NOTICE.read_text()) if NOTICE.exists() else {};check(old,actor,time.time())
  out={'ownerThreadId':actor,'purpose':str(purpose)[:200],'claimedAt':time.time(),'expiresAt':time.time()+ttl,'state':'active'}
  temp=NOTICE.with_suffix('.tmp');temp.write_text(json.dumps(out,indent=2));temp.chmod(0o600);os.replace(temp,NOTICE);return out
 finally:os.close(fd)
def release():
 actor=os.environ.get('CODEX_THREAD_ID');old=json.loads(NOTICE.read_text())
 if old.get('ownerThreadId')!=actor:raise PermissionError('cannot release another operator notice')
 old.update(expiresAt=time.time(),state='released');NOTICE.write_text(json.dumps(old,indent=2));return {'state':'released','ownerThreadId':actor}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',nargs='?',choices=['acquire','release']);p.add_argument('--execute',action='store_true');p.add_argument('--ttl',type=int,default=600);p.add_argument('--purpose',default='Four-group secretary');a=p.parse_args()
 if not a.execute or not a.action:p.print_help()
 else:print(json.dumps(acquire(a.ttl,a.purpose) if a.action=='acquire' else release()))
