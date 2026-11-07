import contextlib, importlib, os, pathlib, stat, sys, tempfile, unittest
P=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(P/'src/MacWorker/foundation'))
class ArchiveLockTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='c10a-fixture-');self.base=pathlib.Path(self.tmp.name).resolve();self.archive=self.base/'archive';self.archive.mkdir();self.root=self.base/'coord';self.m=importlib.import_module('archive_lock');self.store=self.m._Store._for_tests(self.root)
 def tearDown(self):self.tmp.cleanup()
 def test_coord_symlink_rejected(self):
  elsewhere=self.base/'elsewhere';elsewhere.mkdir();self.root.symlink_to(elsewhere,target_is_directory=True)
  with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(self.archive),'exclusive')])
  self.assertEqual(list(elsewhere.iterdir()),[])
 def test_hardlinked_file_rejected(self):
  b=self.store.prepare([(str(self.archive),'exclusive')])[0];lock=self.root/b['id'];os.link(lock,self.base/'hardlink')
  with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(self.archive),'exclusive')])
 def test_invalid_second_no_first_persistent_preparation(self):
  with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(self.archive),'exclusive'),(str(self.base/'missing'/'bad'),'exclusive')])
  self.assertFalse(self.root.exists())

import errno, fcntl, json, subprocess, threading, time
class FullLeaseTests(ArchiveLockTests):
 def child(self,targets):
  script="import sys,json;sys.path.insert(0,"+repr(str(P/'src/MacWorker/foundation'))+");from archive_lock import _Store;s=_Store._for_tests("+repr(str(self.root))+");a=s.acquire_many(json.loads("+repr(json.dumps(targets))+"));print('ACQUIRED',flush=True);sys.stdin.readline();a.check();a.close();print('CLOSED',flush=True)"
  return subprocess.Popen([sys.executable,'-I','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 def stop(self,child):
  out,err=child.communicate('\n',timeout=5);self.assertEqual(child.returncode,0,err);self.assertEqual(err,'');return out
 def test_identity_mkdir_alias_case_unicode_and_inode_retention(self):
  leaf=self.base/'New';a=self.store.prepare([(str(leaf),'exclusive')])[0];inode=(self.root/a['id']).stat().st_ino;leaf.mkdir()
  b=self.store.prepare([(str(leaf),'shared')])[0];self.assertEqual(a['id'],b['id']);self.assertEqual(inode,(self.root/a['id']).stat().st_ino)
  case=self.store.prepare([(str(self.base/'new'),'exclusive')])[0];self.assertEqual(a['id'],case['id'])
  u=self.store.prepare([(str(self.base/'é'),'exclusive')])[0];v=self.store.prepare([(str(self.base/'e\u0301'),'exclusive')])[0];self.assertEqual(u['id'],v['id'])
  alias='/var'+str(self.archive)[len('/private/var'):] if str(self.archive).startswith('/private/var/') else str(self.archive)
  self.assertEqual(self.store.prepare([(alias,'shared')])[0]['id'],self.store.prepare([(str(self.archive),'shared')])[0]['id'])
  with self.store.acquire_many([(str(leaf),'exclusive')]) as held:held.check()
  self.assertEqual(inode,(self.root/a['id']).stat().st_ino)
 def test_ex_ex_and_shared_ex_block_until_release(self):
  for mode in ('exclusive','shared'):
   with self.store.acquire_many([(str(self.archive),mode)]):
    child=self.child([(str(self.archive),'exclusive')]);time.sleep(.15);self.assertIsNone(child.poll())
    import select
    self.assertEqual(select.select([child.stdout],[],[],0)[0],[])
   self.assertEqual(child.stdout.readline().strip(),'ACQUIRED');self.stop(child)
 def test_shared_shared_parallel_and_release_reacquire(self):
  with self.store.acquire_many([(str(self.archive),'shared')]):
   child=self.child([(str(self.archive),'shared')]);self.assertEqual(child.stdout.readline().strip(),'ACQUIRED');self.stop(child)
  with self.store.acquire_many([(str(self.archive),'exclusive')]):pass
 def test_two_targets_reverse_order_and_duplicate_ex_coalescing(self):
  other=self.base/'other';other.mkdir();a=str(self.archive);b=str(other)
  with self.store.acquire_many([(a,'shared'),(b,'exclusive')]) as held:
   child=self.child([(b,'exclusive'),(a,'shared')]);time.sleep(.1);self.assertIsNone(child.poll());self.assertEqual(len(held.locks),2)
  self.assertEqual(child.stdout.readline().strip(),'ACQUIRED');self.stop(child)
  with self.store.acquire_many([(a,'shared'),(a,'exclusive')]) as held:self.assertEqual(len(held.locks),1);self.assertEqual(list(held.modes.values()),['exclusive'])
 def test_reentrant_subset_upgrade_additions_rejected(self):
  a=str(self.archive);other=self.base/'other';other.mkdir()
  with self.store.acquire_many([(a,'exclusive')]) as outer:
   with self.store.acquire_many([(a,'shared')]) as inner:inner.check();outer.check()
   with self.assertRaises(self.m.ArchiveLockError):self.store.acquire_many([(str(other),'shared')])
  with self.store.acquire_many([(a,'shared')]):
   with self.assertRaises(self.m.ArchiveLockError):self.store.acquire_many([(a,'exclusive')])
 def test_other_threads_serialize(self):
  entered=threading.Event();done=threading.Event();errors=[]
  def run():
   try:
    with self.store.acquire_many([(str(self.archive),'shared')]):entered.set()
   except BaseException as e:errors.append(e)
   finally:done.set()
  with self.store.acquire_many([(str(self.archive),'shared')]):
   thread=threading.Thread(target=run);thread.start();self.assertFalse(entered.wait(.12))
  self.assertTrue(done.wait(3));thread.join();self.assertFalse(errors);self.assertTrue(entered.is_set())
 def test_coord_mode_acl_and_replacement_rejected(self):
  b=self.store.prepare([(str(self.archive),'exclusive')])[0];lock=self.root/b['id'];os.chmod(lock,0o640)
  with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(self.archive),'exclusive')])
  os.chmod(lock,0o600)
  subprocess.run(['/bin/chmod','+a','everyone allow read',str(lock)],check=True)
  try:
   with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(self.archive),'exclusive')])
  finally:subprocess.run(['/bin/chmod','-N',str(lock)],check=True)
  with self.store.acquire_many([(str(self.archive),'exclusive')]) as held:
   lock.rename(self.base/'original-lock');lock.touch(mode=0o600)
   with self.assertRaises(self.m.ArchiveLockError):held.check()
 def test_parent_and_coord_directory_substitution_loses_authority(self):
  for which in ('parent','coord'):
   with tempfile.TemporaryDirectory(dir=self.base) as td:
    parent=pathlib.Path(td);archive=parent/'a';archive.mkdir();store=self.m._Store._for_tests(parent/'c')
    lease=store.acquire_many([(str(archive),'exclusive')])
    try:
     if which=='coord':(parent/'c').rename(parent/'old');(parent/'c').mkdir(mode=0o700)
     else:archive.rename(parent/'old');archive.mkdir()
     with self.assertRaises(self.m.ArchiveLockError):lease.check()
    finally:lease.close()
 def test_shared_source_unchanged_and_no_inside_lock(self):
  f=self.archive/'original';f.write_bytes(b'fixture');before=(self.archive.stat().st_mtime_ns,f.stat().st_mtime_ns,f.read_bytes(),set(self.archive.iterdir()))
  with self.store.acquire_many([(str(self.archive),'shared')]):pass
  self.assertEqual(before,(self.archive.stat().st_mtime_ns,f.stat().st_mtime_ns,f.read_bytes(),set(self.archive.iterdir())))
 def test_cancel_partial_acquisition_closes_all_fds(self):
  other=self.base/'second';other.mkdir();bindings=self.store.prepare([(str(self.archive),'exclusive'),(str(other),'exclusive')]);bindings.sort(key=lambda x:x['id']);last=bindings[-1]['id'];fd=os.open(self.root/last,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  before=len(os.listdir('/dev/fd'));calls=0
  def cancel():
   nonlocal calls
   calls+=1
   if calls>=4:raise InterruptedError('cancelled')
  try:
   with self.assertRaises(InterruptedError):self.store.acquire_many([(str(self.archive),'exclusive'),(str(other),'exclusive')],cancel)
   self.assertEqual(before,len(os.listdir('/dev/fd')))
   first=os.open(self.root/bindings[0]['id'],os.O_RDWR)
   try:fcntl.flock(first,fcntl.LOCK_EX|fcntl.LOCK_NB)
   finally:os.close(first)
  finally:os.close(fd)
 def test_fork_rejects_authority_and_parent_stays_locked(self):
  with self.store.acquire_many([(str(self.archive),'exclusive')]) as lease:
   r,w=os.pipe();pid=os.fork()
   if pid==0:
    os.close(r)
    try:
     try:lease.check();os.write(w,b'bad')
     except self.m.ArchiveLockError:os.write(w,b'ok')
    finally:os._exit(0)
   os.close(w);self.assertEqual(os.read(r,8),b'ok');os.close(r);os.waitpid(pid,0);lease.check()
   fd=os.open(self.root/next(iter(lease.modes)),os.O_RDWR)
   try:
    with self.assertRaises(BlockingIOError):fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   finally:os.close(fd)
 def test_cloexec_descriptors_not_retained(self):
  with self.store.acquire_many([(str(self.archive),'exclusive')]) as lease:
   fd=lease.locks[0][0];p=os.fstat(fd)
   code='import os,sys\ntry:\n s=os.fstat('+str(fd)+')\n sys.exit(1 if (s.st_dev,s.st_ino)=='+repr((p.st_dev,p.st_ino))+' else 0)\nexcept OSError:sys.exit(0)'
   r=subprocess.run([sys.executable,'-I','-c',code],close_fds=False,capture_output=True);self.assertEqual(r.returncode,0)
 def test_roles_symlink_reserved_nonempty_and_owner(self):
  for path,mode in ((self.base/'absent','shared'),(self.root,'exclusive'),(pathlib.Path(self.store.home),'exclusive')):
   with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(path),mode)])
  link=self.base/'linked';link.symlink_to(self.archive,target_is_directory=True)
  with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(link),'shared')])
  b=self.store.prepare([(str(self.archive),'exclusive')])[0];(self.root/b['id']).write_bytes(b'x')
  with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(self.archive),'exclusive')])
 def test_nested_close_after_authority_loss_releases_every_resource(self):
  outer=self.store.acquire_many([(str(self.archive),'exclusive')]);nested=self.store.acquire_many([(str(self.archive),'shared')])
  self.archive.rename(self.base/'old-archive');self.archive.mkdir()
  try:
   with self.assertRaises(self.m.ArchiveLockError):nested.check()
   nested.close();outer.close()
  finally:
   # A failing implementation remains inspectable; do not mask its failure.
   if not nested.closed:
    for t in nested.targets:t.close()
    outer.nested-=1;nested.closed=True;self.m._active.remove(nested);self.m._gate.release()
   if not outer.closed:outer.close()
 def test_new_ex_leaf_becomes_pinned(self):
  leaf=self.base/'first-create'
  with self.store.acquire_many([(str(leaf),'exclusive')]) as held:
   leaf.mkdir();held.check();leaf.rename(self.base/'old-create');leaf.mkdir()
   with self.assertRaises(self.m.ArchiveLockError):held.check()
 def test_nonprivate_target_and_parent_roles_reject(self):
  self.archive.chmod(0o777)
  try:
   with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(self.archive),'shared')])
  finally:self.archive.chmod(0o755)
  with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([('/private/tmp','shared')])
 def test_real_parent_chain_rename_loses_authority(self):
  parent=self.base/'parent';parent.mkdir();archive=parent/'archive';archive.mkdir()
  with self.store.acquire_many([(str(archive),'shared')]) as held:
   parent.rename(self.base/'old-parent');parent.mkdir()
   with self.assertRaises(self.m.ArchiveLockError):held.check()
 def test_coord_directory_acl_and_nondirectory_nodes(self):
  self.store.prepare([(str(self.archive),'shared')]);subprocess.run(['/bin/chmod','+a','everyone allow read',str(self.root)],check=True)
  try:
   with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(self.archive),'shared')])
  finally:subprocess.run(['/bin/chmod','-N',str(self.root)],check=True)
 def test_fork_nested_closes_only_child_copies(self):
  outer=self.store.acquire_many([(str(self.archive),'exclusive')]);inner=self.store.acquire_many([(str(self.archive),'shared')]);r,w=os.pipe();pid=os.fork()
  if pid==0:
   os.close(r)
   try:
    try:inner.check();os.write(w,b'bad')
    except self.m.ArchiveLockError:os.write(w,b'ok')
   finally:os._exit(0)
  os.close(w)
  try:self.assertEqual(os.read(r,8),b'ok');os.waitpid(pid,0);inner.check();outer.check()
  finally:os.close(r);inner.close();outer.close()
 def test_missing_case_alias_of_reserved_root_rejected_before_creation(self):
  alias=self.base/'COORD'
  with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(alias),'exclusive')])
  self.assertFalse(self.root.exists());self.assertFalse(alias.exists())
 def test_firmlink_identity_and_missing_reserved_alias(self):
  alias=pathlib.Path('/System/Volumes/Data'+str(self.base))
  if not alias.is_dir() or (alias.stat().st_dev,alias.stat().st_ino)!=(self.base.stat().st_dev,self.base.stat().st_ino):self.skipTest('fixture firmlink alias unavailable')
  direct=self.store.prepare([(str(self.archive),'shared')])[0]
  same=self.store.prepare([(str(alias/'archive'),'shared')])[0];self.assertEqual(direct['id'],same['id'])
  missing_store=self.m._Store._for_tests(self.base/'future-coord')
  with self.assertRaises(self.m.ArchiveLockError):missing_store.prepare([(str(alias/'FUTURE-COORD'),'exclusive')])
  self.assertFalse((self.base/'future-coord').exists())
 def test_prepare_entry_substitution_never_writes_held_selected_inode(self):
  from unittest.mock import patch
  self.archive.chmod(0o700);(self.archive/'original').write_bytes(b'untouched fixture');before=self.archive.stat();original_prepare=self.store._prepare
  def substitute(targets):
   self.archive.rename(self.root)
   return original_prepare(targets)
  with patch.object(self.store,'_prepare',side_effect=substitute):
   with self.assertRaises(self.m.ArchiveLockError):self.store.prepare([(str(self.archive),'shared')])
  self.assertEqual((before.st_dev,before.st_ino),(self.root.stat().st_dev,self.root.stat().st_ino))
  self.assertEqual({p.name for p in self.root.iterdir()},{'original'},'preparation wrote inside the held selected inode after validation')
  self.assertEqual((self.root/'original').read_bytes(),b'untouched fixture')
 def _coord_open_substitution(self,level):
  from unittest.mock import patch
  self.archive.chmod(0o700);(self.archive/'original').write_bytes(b'untouched fixture');before=self.archive.stat()
  anchor=self.base/'anchor';anchor.mkdir(mode=0o700)
  if level=='anchor':
   store=self.m._Store._for_tests(anchor/'coord');part='anchor';destination=anchor
  elif level=='managed_ancestor':
   store=self.m._Store._for_tests(anchor/'first'/'last');store.anchor=str(anchor);store.components=('first','last');part='first';destination=anchor/'first'
  else:
   store=self.store;part='coord';destination=self.root
  original_coord=store._coord;original_append=self.m._Chain.append;state={'opening':False,'moved':False}
  def coord(*args,**kwargs):
   state['opening']=bool(args[0])
   try:return original_coord(*args,**kwargs)
   finally:state['opening']=False
  def append(chain,name):
   if state['opening'] and name==part and not state['moved']:
    # Execute after preparation's target precheck, exactly before this
    # existing/new coordination component is opened. Only fixture dirs move.
    destination.rmdir();self.archive.rename(destination);state['moved']=True
   return original_append(chain,name)
  fds_before=len(os.listdir('/dev/fd'))
  with patch.object(store,'_coord',side_effect=coord),patch.object(self.m._Chain,'append',new=append):
   with self.assertRaises(self.m.ArchiveLockError):store.prepare([(str(self.archive),'shared')])
  self.assertTrue(state['moved'],'deterministic post-precheck seam was not exercised')
  self.assertEqual(fds_before,len(os.listdir('/dev/fd')),'substitution rejection leaked owned fds')
  self.assertEqual((before.st_dev,before.st_ino),(destination.stat().st_dev,destination.stat().st_ino))
  self.assertEqual({p.name for p in destination.iterdir()},{'original'},'opened coordination ancestor was the selected inode and received writes')
  self.assertEqual((destination/'original').read_bytes(),b'untouched fixture')
 def test_post_precheck_opened_coord_root_never_writes_selected_inode(self):self._coord_open_substitution('root')
 def test_post_precheck_opened_coord_ancestor_never_mkdirs_in_selected_inode(self):self._coord_open_substitution('managed_ancestor')
 def test_post_precheck_opened_coord_anchor_never_mkdirs_in_selected_inode(self):self._coord_open_substitution('anchor')

if __name__=='__main__':unittest.main()
