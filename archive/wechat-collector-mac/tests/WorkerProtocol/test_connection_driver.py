"""C8 protocol: reject caller authority, secret frames and replay before dispatch."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/MacWorker/foundation'))
try:
    import connection_driver as driver
except ImportError:
    driver = None

class Protocol(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(driver, 'owned driver implementation required')
    def test_reserved_mode_rejects_malformed_before_legacy(self):
        self.assertTrue(driver.reserved(['--connect']))
        self.assertFalse(driver.reserved(['--serve']))
        for args in (['--connect=1'], ['--serve','--connect'], ['--connect','--connect'], ['--connect','--home','/tmp']):
            self.assertTrue(driver.reserved(args))
            with self.assertRaises(driver.DriverError): driver.validate_mode(args)
    def test_request_rejects_duplicate_oversize_deep_authority_and_relative(self):
        valid={'v':1,'account':'fixture_account','archive':'/private/tmp/generated'}
        cases=[b'{"v":1,"v":1}', b'x'*4097, b'{"v":'+b'['*10+b'0'+b']'*10+b'}']
        cases += [json.dumps(dict(valid,**change)).encode() for change in ({'v':True},{'home':'/tmp'},{'pid':1},{'helper':'/tmp/evil'},{'archive':'relative'},{'account':'../escape'})]
        for raw in cases:
            with self.subTest(raw=raw[:80]),self.assertRaises(driver.DriverError): driver.parse_request(raw)
    def test_control_rejects_wrong_nonce_account_secret_and_replay(self):
        nonce='a'*32
        valid={'v':1,'operation':nonce,'command':'start','account':'fixture_account'}
        for change in ({'operation':'b'*32},{'account':'other'},{'key':'secret'},{'command':'release'},{'v':True}):
            with self.assertRaises(driver.DriverError): driver.parse_control(json.dumps(dict(valid,**change)).encode(),nonce,'fixture_account',False)
        self.assertEqual('start',driver.parse_control(json.dumps(valid).encode(),nonce,'fixture_account',False))
        with self.assertRaises(driver.DriverError): driver.parse_control(json.dumps(valid).encode(),nonce,'fixture_account',True)
    def test_relay_strict_schema_states_codes_and_transitions(self):
        nonce='a'*32
        valid={'v':1,'operation':nonce,'state':'authorizing','cleanup':'pending','code':''}
        self.assertEqual(valid,driver.parse_receipt(json.dumps(valid).encode(),None,'',False))
        for change in ({'v':True},{'key':'secret'},{'code':'secret'},{'state':'done'},{'operation':'bad'},{'cleanup':'complete'}):
            with self.assertRaises(driver.DriverError): driver.parse_receipt(json.dumps(dict(valid,**change)).encode(),None,'',False)
        valid.update(state='running')
        with self.assertRaises(driver.DriverError): driver.parse_receipt(json.dumps(valid).encode(),nonce,'authorizing',True)


import base64
import hashlib
import hmac
import os
import select
import stat
import struct
import subprocess
import tempfile
import threading
import time
from unittest import mock
import connection
import helper_payload

@unittest.skipUnless(sys.platform=='darwin','Darwin owned relay/C3 lifecycle')
class OwnedDriver(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir='/private/tmp',prefix='wechat-c8-driver-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.home=self.root/'home'
        (self.home/'Library/Application Support').mkdir(parents=True)
        self.source=self.home/connection._SOURCE;self.account='fixture_account'
        self.message=self.source/self.account/'db_storage/message';self.message.mkdir(parents=True)
        self.archive=self.root/'archive';self.archive.mkdir(mode=0o700)
        self.pages={};self.keys={};self.page('message_0.db',3)
        self.nonce='a'*32;self.relay_log=self.root/'relay-log.json'
        self.input_r,self.input_w=os.pipe();self.output=self.root/'output.jsonl'
        self.output_fd=os.open(self.output,os.O_CREAT|os.O_RDWR,0o600)
        self.addCleanup(os.close,self.input_r);self.addCleanup(os.close,self.output_fd)
        self.thread=None;self.code=None;self.children=[]
        self.addCleanup(self.finish)
    def finish(self):
        if self.input_w is not None:os.close(self.input_w);self.input_w=None
        if self.thread:self.thread.join(8);self.assertFalse(self.thread.is_alive(),'driver stranded')
        for owner in self.children:self.assertIsNotNone(owner._process.returncode,'owned relay not reaped')
        for name,page in self.pages.items():self.assertEqual(page,(self.message/name).read_bytes())
        self.assertFalse((self.archive/'index.db').exists(),'connection initialized Library/index')
    def page(self,name,seed):
        salt=bytes([seed])*16;key=bytes([seed+20])*32
        page=bytearray(bytes([seed+1])*4096);page[:16]=salt
        mac=hashlib.pbkdf2_hmac('sha512',key,bytes(x^0x3a for x in salt),2,32)
        page[4032:]=hmac.new(mac,page[16:4032]+struct.pack('<I',1),hashlib.sha512).digest()
        self.pages[name]=bytes(page);self.keys[salt.hex()]=key.hex();(self.message/name).write_bytes(page)
    def config(self,keys=None):
        return dict(schema_version=2,wxid=self.account,db_root=str(self.source/self.account),keys=self.keys if keys is None else keys,key_epoch=1)
    def cached(self,value):
        keys=self.archive/'keys';keys.mkdir(mode=0o700,exist_ok=True)
        path=keys/(self.account+'.keys.json');path.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode());path.chmod(0o600)
        return path
    def script(self,mode):
        script=self.root/'generated-relay.py'
        script.write_text('''import json,sys,os
from pathlib import Path
nonce='''+repr(self.nonce)+'''
account='''+repr(self.account)+'''
home=Path('''+repr(str(self.home))+''')
mode='''+repr(mode)+'''
log=[]
def emit(state,cleanup='pending',code=''):
 print(json.dumps(dict(v=1,operation=nonce,state=state,cleanup=cleanup,code=code)),flush=True)
if mode=='flood':
 print('secret-key-body'*400,flush=True)
else:emit('authorizing')
for line in sys.stdin:
 v=json.loads(line);command=v['command'];log.append(command)
 if command=='start':
  emit('bound');emit('running')
  if mode=='publish':
   keys=home/'Library/Application Support/LocalWeChatReader/keys'
   path=keys/('connect-'+nonce+'.keys.json')
   fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
   os.write(fd,'''+repr(json.dumps(self.config()).encode())+''');os.close(fd)
   emit('cleaning');emit('done','complete')
 elif command=='cancel':
  if mode=='no_terminal':break
  if 'start' in log:emit('cancel_requested',code='cancelled');emit('cleaning',code='cancelled')
  emit('cancelled','complete','cancelled')
  if 'start' not in log:break
 elif command=='release':break
Path('''+repr(str(self.relay_log))+''').write_text(json.dumps(log))
raise SystemExit(0 if mode=='publish' and 'release' in log else 130 if 'cancel' in log else 70)
''')
        return script
    def start(self,mode='publish',budget=3,observe=None,launch_real=None):
        script=self.script(mode)
        def launch(argv,**kw):
            owner=connection._launch_owned_relay([sys.executable,str(script)],**kw)
            self.children.append(owner);return owner
        def action():
            self.code=driver.run(self.input_r,self.output_fd,_home_lookup=lambda uid:str(self.home),
                _materialize=lambda:'/generated-only-helper',_launch=launch_real or launch,
                _observe=observe,_budget=budget,_cleanup_budget=.6)
        self.thread=threading.Thread(target=action);self.thread.start()
        self.send(dict(v=1,account=self.account,archive=str(self.archive)))
    def send(self,value):os.write(self.input_w,(json.dumps(value)+'\n').encode())
    def frames(self):
        raw=self.output.read_bytes()
        return [json.loads(line) for line in raw.splitlines() if line]
    def wait_frame(self,event):
        end=time.monotonic()+5
        while time.monotonic()<end:
            values=self.frames()
            found=[v for v in values if v['event']==event]
            if found:return found[-1]
            if self.thread and not self.thread.is_alive():break
            time.sleep(.01)
        self.fail('missing '+event+': '+repr(self.output.read_bytes()))
    def command(self,command,**changes):
        value=dict(v=1,operation=self.nonce,command=command)
        if command=='start':value['account']=self.account
        value.update(changes);self.send(value)
    def terminal(self):
        value=self.wait_frame('terminal');self.thread.join(3)
        self.assertFalse(self.thread.is_alive());self.assertEqual(1,len([v for v in self.frames() if v['event']=='terminal']))
        self.assertNotIn(next(iter(self.keys.values())),self.output.read_text())
        return value
    def test_real_c3_candidate_finalize_cleanup_before_release_then_one_reap(self):
        order=[];original_finalize=connection.finalize_connection;original_cleanup=connection.cleanup_connection
        def finalize(ticket,raw):
            ticket._owner._check();order.append('finalize');result=original_finalize(ticket,raw);self.assertEqual('published',result['state']);return result
        def cleanup(ticket):
            ticket._owner._check();order.append('cleanup');self.assertFalse(self.relay_log.exists());return original_cleanup(ticket)
        with mock.patch.object(connection,'finalize_connection',finalize),mock.patch.object(connection,'cleanup_connection',cleanup):
            self.start();self.wait_frame('authorize');self.command('start');terminal=self.terminal()
        self.assertEqual(['finalize','cleanup'],order)
        self.assertEqual(('published','complete',1,0),(terminal['state'],terminal['cleanup'],terminal['verified'],terminal['missing']))
        self.assertEqual(['start','release'],json.loads(self.relay_log.read_text()))
        self.assertFalse((self.home/connection._HANDOFF/('connect-'+self.nonce+'.keys.json')).exists())
    def test_cache_valid_bypasses_authorize_and_preserves_inode(self):
        path=self.cached(self.config());before=(path.stat().st_ino,path.read_bytes())
        self.start();terminal=self.terminal()
        self.assertEqual(('cache_reused','complete',1),(terminal['state'],terminal['cleanup'],terminal['verified']))
        self.assertFalse(any(v['event']=='authorize' for v in self.frames()))
        self.assertEqual(before,(path.stat().st_ino,path.read_bytes()))
        self.assertEqual(['cancel'],json.loads(self.relay_log.read_text()))
    def test_partial_and_invalid_existing_preserved_without_authorize(self):
        self.page('message_1.db',4)
        keys=dict(self.keys);keys.pop(bytes([4]).hex()*16)
        path=self.cached(self.config(keys));before=(path.stat().st_ino,path.read_bytes())
        self.start();terminal=self.terminal();self.assertEqual('repair_required',terminal['state'])
        self.assertEqual((1,1),(terminal['verified'],terminal['missing']))
        self.assertEqual(before,(path.stat().st_ino,path.read_bytes()))
        self.assertFalse(any(v['event']=='authorize' for v in self.frames()))
    def test_invalid_existing_preserved(self):
        path=self.cached(b'not valid secret content');before=(path.stat().st_ino,path.read_bytes())
        self.start();terminal=self.terminal();self.assertEqual('repair_required',terminal['state'])
        self.assertEqual(before,(path.stat().st_ino,path.read_bytes()))
        self.assertNotIn('secret content',self.output.read_text())
    def test_before_start_cancel(self):
        self.start();self.wait_frame('authorize');self.command('cancel')
        self.assertEqual(('cancelled','complete'),tuple(self.terminal()[x] for x in ('state','cleanup')))
        self.assertFalse((self.archive/'keys'/(self.account+'.keys.json')).exists())
    def test_after_start_cancel_and_cleanup(self):
        self.start('hang');self.wait_frame('authorize');self.command('start')
        end=time.monotonic()+3
        while time.monotonic()<end and not any(v['state']=='running' for v in self.frames()):time.sleep(.01)
        self.command('cancel');self.assertEqual('cancelled',self.terminal()['state'])
        self.assertEqual(['start','cancel','release'],json.loads(self.relay_log.read_text()))
    def test_after_start_without_authentic_terminal_is_unconfirmed(self):
        self.start('no_terminal');self.wait_frame('authorize');self.command('start');self.command('cancel')
        self.assertEqual(('cleanup_unconfirmed','unconfirmed'),tuple(self.terminal()[x] for x in ('state','cleanup')))
    def test_wrong_nonce_is_sanitized_and_revokes(self):
        self.start();self.wait_frame('authorize');self.command('start',operation='b'*32,key='secret-key-body')
        self.assertEqual('cancelled',self.terminal()['state'])
        self.assertNotIn('secret-key-body',self.output.read_text())
    def test_host_eof_before_start(self):
        self.start();self.wait_frame('authorize');os.close(self.input_w);self.input_w=None
        self.assertEqual('cancelled',self.terminal()['state'])
    def test_native_parent_identity_loss_while_stdin_remains_open(self):
        lost=threading.Event()
        def observe(pid):
            value=connection._observe(pid)
            return (*value[:-1],value[-1]+1) if lost.is_set() else value
        self.start(observe=observe);self.wait_frame('authorize');lost.set()
        self.assertEqual('cancelled',self.terminal()['state']);self.assertIsNotNone(self.input_w)
    def test_deadline_revokes_before_start(self):
        self.start(budget=.4);self.assertEqual('cancelled',self.terminal()['state'])
    def test_flood_relay_is_bounded_sanitized_and_reaped(self):
        self.start('flood',budget=.3);terminal=self.terminal()
        self.assertNotIn('secret-key-body',self.output.read_text());self.assertLess(len(self.output.read_bytes()),4096)
    def test_actual_accepted_binary_startup_cancel_generated_home_only(self):
        accepted=Path('/private/tmp/wxkey-c7d-final-receipts-g3ob8mgx/wxkey-built')
        self.assertEqual('a0e1bfceff87c7ab61f658829f2f2e22e2b42924b7c86a834c2734cd26cb1112',hashlib.sha256(accepted.read_bytes()).hexdigest())
        raw=accepted.read_bytes();sealed=json.dumps(dict(v=1,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),image=base64.b64encode(raw).decode())).encode()
        helper=helper_payload.materialize(_sealed=sealed,_home=str(self.home))
        def launch(argv,**kw):
            owner=connection._launch_owned_relay([helper,*argv[1:]],**kw);self.children.append(owner);return owner
        self.start(launch_real=launch);self.wait_frame('authorize')
        values=self.frames();nonce=values[0]['operation'];self.send(dict(v=1,operation=nonce,command='cancel'))
        terminal=self.terminal();self.assertEqual(('cancelled','complete'),(terminal['state'],terminal['cleanup']))
        self.assertFalse((Path('/private/tmp')/('wxkey-connect-'+nonce)).exists())
        self.assertTrue(Path(helper).exists(),'persistent version deleted during operation cleanup')

    def test_cancel_during_real_c3_commit_gate_prevents_publication(self):
        held=threading.Event();release=threading.Event();original=connection.finalize_connection
        def finalize(ticket,raw):
            checkpoint=ticket._owner._gate
            def gate(point):
                if point=='before_commit':held.set();release.wait(2)
                checkpoint(point)
            ticket._owner._gate=gate
            return original(ticket,raw)
        with mock.patch.object(connection,'finalize_connection',finalize):
            self.start();self.wait_frame('authorize');self.command('start')
            self.assertTrue(held.wait(2));self.command('cancel');time.sleep(.12);release.set()
            self.assertEqual('cancelled',self.terminal()['state'])
        self.assertFalse((self.archive/'keys'/(self.account+'.keys.json')).exists())
    def test_unsafe_selected_parent_refused_without_creation(self):
        self.root.chmod(0o777)
        try:
            with self.assertRaises(driver.DriverError):driver._archive(str(self.home),str(self.archive/'new'))
        finally:self.root.chmod(0o700)
    def test_host_eof_after_start_authentic_cleanup(self):
        self.start('hang');self.wait_frame('authorize');self.command('start')
        end=time.monotonic()+2
        while time.monotonic()<end and not any(v['state']=='running' for v in self.frames()):time.sleep(.01)
        os.close(self.input_w);self.input_w=None
        self.assertEqual(('cancelled','complete'),tuple(self.terminal()[x] for x in ('state','cleanup')))
    def test_deadline_after_start_authentic_cleanup(self):
        self.start('hang',budget=1.2);self.wait_frame('authorize');self.command('start')
        self.assertEqual(('cancelled','complete'),tuple(self.terminal()[x] for x in ('state','cleanup')))
    def test_native_parent_identity_loss_after_start_stdin_held_open(self):
        lost=threading.Event()
        def observe(pid):
            value=connection._observe(pid)
            return (*value[:-1],value[-1]+1) if lost.is_set() else value
        self.start('hang',observe=observe);self.wait_frame('authorize');self.command('start')
        end=time.monotonic()+2
        while time.monotonic()<end and not any(v['state']=='running' for v in self.frames()):time.sleep(.01)
        lost.set();self.assertEqual('cancelled',self.terminal()['state']);self.assertIsNotNone(self.input_w)
    def test_duplicate_start_revokes_one_dispatch(self):
        self.start('hang');self.wait_frame('authorize');self.command('start');time.sleep(.05);self.command('start')
        self.assertEqual('cancelled',self.terminal()['state'])
        self.assertEqual(1,json.loads(self.relay_log.read_text()).count('start'))
    def test_private_archive_created_without_index_initialization(self):
        self.archive.rmdir();self.start();self.wait_frame('authorize');self.command('cancel');self.terminal()
        self.assertEqual(0o700,stat.S_IMODE(self.archive.stat().st_mode));self.assertFalse((self.archive/'index.db').exists())
    def test_existing_keys_0755_reconciled_only_exact_leaf(self):
        keys=self.archive/'keys';keys.mkdir(mode=0o755);sentinel=keys/'unrelated';sentinel.write_bytes(b'keep')
        before=(keys.stat().st_ino,sentinel.stat().st_ino,sentinel.read_bytes(),self.archive.stat().st_mode)
        self.start();self.wait_frame('authorize');self.command('cancel');self.terminal()
        self.assertEqual(0o700,stat.S_IMODE(keys.stat().st_mode))
        self.assertEqual(before,(keys.stat().st_ino,sentinel.stat().st_ino,sentinel.read_bytes(),self.archive.stat().st_mode))
    def test_fd_count_and_joined_monitor_threads_after_run(self):
        before=len(os.listdir('/dev/fd'));self.start();self.wait_frame('authorize');self.command('cancel');self.terminal()
        self.assertEqual(before,len(os.listdir('/dev/fd')))
        self.assertFalse(any(t.name=='connection-owner-monitor' and t.is_alive() for t in threading.enumerate()))

    def test_actual_parent_process_death_with_stdin_writer_still_open(self):
        relay=self.script('hang');done=self.root/'driver-process-done.json'
        entry=self.root/'driver-process.py'
        foundation=Path(__file__).resolve().parents[2]/'src/MacWorker/foundation'
        entry.write_text("import sys,json\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(foundation))+")\nimport connection as c, connection_driver as d\nowners=[]\ndef launch(argv,**kw):\n owner=c._launch_owned_relay([sys.executable,"+repr(str(relay))+"],**kw);owners.append(owner);return owner\ncode=d.run(_home_lookup=lambda uid:"+repr(str(self.home))+",_materialize=lambda:'/generated-only',_launch=launch,_budget=4,_cleanup_budget=.6)\nPath("+repr(str(done))+").write_text(json.dumps(dict(code=code,reaped=[o._process.returncode for o in owners])))\nraise SystemExit(code)\n")
        host_entry=self.root/'generated-native-host.py'
        host_entry.write_text("import sys,subprocess,time\np=subprocess.Popen([sys.executable,"+repr(str(entry))+"],stdin=sys.stdin,stdout=sys.stdout,stderr=subprocess.DEVNULL)\ntime.sleep(8)\n")
        with self.output.open('wb') as out:
            host=subprocess.Popen([sys.executable,str(host_entry)],stdin=subprocess.PIPE,stdout=out,stderr=subprocess.DEVNULL)
        try:
            host.stdin.write((json.dumps(dict(v=1,account=self.account,archive=str(self.archive)))+'\n').encode());host.stdin.flush()
            self.wait_frame('authorize');started=time.monotonic()
            host.kill();host.wait(timeout=2)
            terminal=self.wait_frame('terminal')
            self.assertLess(time.monotonic()-started,1.5,'deadline substituted for real parent loss')
            self.assertFalse(host.stdin.closed,'stdin writer must remain open through parent-loss acceptance')
            end=time.monotonic()+2
            while time.monotonic()<end and not done.exists():time.sleep(.01)
            self.assertTrue(done.exists())
            self.assertEqual(dict(code=130,reaped=[130]),json.loads(done.read_text()))
            self.assertEqual(('cancelled','complete'),(terminal['state'],terminal['cleanup']))
        finally:
            if host.poll() is None:host.kill();host.wait(timeout=2)
            host.stdin.close()

    def test_actual_default_archive_shape_and_os_home_anchor_acl_allowed(self):
        app=self.home/'Library/Application Support/WechatCollectorMac';app.mkdir(mode=0o700)
        selected=app/'archive'
        subprocess.run(['/bin/chmod','+a','everyone deny delete',str(self.home)],check=True,capture_output=True)
        try:
            library=driver._archive(str(self.home),str(selected))
            self.assertEqual(selected,library.state)
            self.assertTrue(selected.is_dir());self.assertFalse((selected/'index.db').exists())
            self.assertEqual(self.source,library.source)
            with self.assertRaises(driver.DriverError):driver._archive(str(self.home),str(app/'helpers'/'anything'))
            with self.assertRaises(driver.DriverError):driver._archive(str(self.home),str(app))
        finally:subprocess.run(['/bin/chmod','-N',str(self.home)],check=True)

    def test_owned_child_wait_failure_still_emits_one_terminal_and_restores_output(self):
        script=self.script('hang');reapers=[]
        def launch(argv,**kw):
            owner=connection._launch_owned_relay([sys.executable,str(script)],**kw)
            self.children.append(owner);actual_wait=owner._process.wait;reapers.append(actual_wait)
            def wait_failure(timeout=None):raise subprocess.TimeoutExpired('generated-owned-child',timeout)
            owner._process.wait=wait_failure
            return owner
        try:
            self.start(launch_real=launch);self.wait_frame('authorize');self.command('cancel')
            terminal=self.terminal()
            self.assertEqual(('cleanup_unconfirmed','unconfirmed'),(terminal['state'],terminal['cleanup']))
            self.assertTrue(os.get_blocking(self.output_fd))
        finally:
            for reap in reapers:reap(timeout=2)
    def test_monitor_join_failure_retains_live_reader_descriptors(self):
        entered=threading.Event();release=threading.Event();count=[0]
        def observe(pid):
            count[0]+=1
            if count[0]>1:entered.set();release.wait(2)
            return connection._observe(pid)
        monitor=driver._Monitor(self.input_r,observe,time.monotonic()+4)
        owner=connection._launch_owned_relay([sys.executable,'-c','import sys;sys.stdin.buffer.read()'],
            _capture_stdout=True,_empty_env=True)
        self.children.append(owner);monitor.attach(owner,self.account)
        try:
            self.assertTrue(entered.wait(1));self.assertFalse(monitor.close())
            # A failed join must not recycle any live reader descriptor.
            os.fstat(monitor.wake_r);os.fstat(monitor.wake_w)
            self.assertFalse(owner._process.stdout.closed)
            os.fstat(owner._process.stdout.fileno())
        finally:
            release.set();monitor.thread.join(2)
            self.assertTrue(monitor.close())
            self.assertTrue(owner._process.stdout.closed)
            owner._process.stdin.close();owner._process.wait(timeout=2)

class EarlyRoute(unittest.TestCase):
    def test_buffered_malformed_first_request_rejected_even_when_followed_by_eof(self):
        worker=Path(__file__).resolve().parents[2]/'src/MacWorker/mac_worker.py'
        result=subprocess.run([sys.executable,str(worker),'--connect'],input=b'{"v":1,"home":"secret"}\n',capture_output=True,timeout=4)
        self.assertEqual(70,result.returncode,result.stdout)
        value=json.loads(result.stdout);self.assertEqual(('failed','invalid_request'),(value['state'],value['code']))
        self.assertFalse(result.stderr);self.assertNotIn(b'secret',result.stdout)
    def test_malformed_reserved_mode_before_library_import_or_operation(self):
        worker=Path(__file__).resolve().parents[2]/'src/MacWorker/mac_worker.py'
        code='''import sys,runpy
class NoLibrary:
 def find_spec(self,fullname,path=None,target=None):
  if fullname in ('library','media','capture'):raise RuntimeError('legacy module imported')
sys.meta_path.insert(0,NoLibrary())
sys.argv=['mac-worker',*sys.argv[1:]]
runpy.run_path('''+repr(str(worker))+''',run_name='__main__')
'''
        for args in (['--connect=secret'],['--serve','--connect'],['--connect','--home','/private/tmp']):
            result=subprocess.run([sys.executable,'-c',code,*args],capture_output=True,timeout=3)
            self.assertEqual(64,result.returncode,result.stderr)
            value=json.loads(result.stdout);self.assertEqual('invalid_request',value['code'])
            self.assertFalse(result.stderr);self.assertNotIn('secret',result.stdout.decode())

if __name__=='__main__':unittest.main()
