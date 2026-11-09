import json, pathlib, subprocess, sys, unittest
P=pathlib.Path(__file__).resolve().parents[2];W=P/'src/MacWorker/mac_worker.py'
class DriverTests(unittest.TestCase):
 def test_mixed_reserved_rejected_before_legacy_imports(self):
  for args in (['--archive-lock','--connect'],['--archive-lock=bad'],['--connect','--archive-lock','--serve']):
   r=subprocess.run([sys.executable,'-I',str(W),*args],input=b'{}\n',capture_output=True)
   self.assertNotEqual(r.returncode,0)
   self.assertEqual(r.stderr,b'')
   self.assertEqual(json.loads(r.stdout),{'v':1,'status':'error','code':'invalid_mode'})

import io, tempfile
sys.path.insert(0,str(P/'src/MacWorker/foundation'))
from archive_lock import _Store, ArchiveLockError
from archive_lock_driver import _run, parse_request
class StrictProtocolTests(unittest.TestCase):
 def test_strict_fields_duplicate_types_nul_size_depth(self):
  valid={'v':1,'request':'a'*32,'targets':[{'path':'/private/fixture/archive','mode':'exclusive'}]}
  bad=[b'{"v":1,"v":1}',b'{"v":true}',b'['*100+b']'*100,b'x'*8193]
  for key,value in [('v',True),('v',2),('request','A'*32),('targets',[]),('targets',[{}]),('root','/tmp')]:
   obj=dict(valid);obj[key]=value;bad.append(json.dumps(obj).encode())
  for change in ({'path':'/a\0x','mode':'shared'},{'path':'/a','mode':'held'},{'path':1,'mode':'shared'},{'path':'/a','mode':'shared','fd':3}):
   obj=dict(valid);obj['targets']=[change];bad.append(json.dumps(obj).encode())
  for raw in bad:
   with self.subTest(raw=raw[:80]),self.assertRaises(ArchiveLockError):parse_request(raw)
 def test_prepared_exact_binding_order_and_fixed_error_no_path(self):
  with tempfile.TemporaryDirectory(prefix='c10a-driver-') as tmp:
   base=pathlib.Path(tmp).resolve();a=base/'a';a.mkdir();root=base/'coord';req={'v':1,'request':'a'*32,'targets':[{'path':str(a),'mode':'shared'},{'path':str(base/'b'),'mode':'exclusive'}]};out=io.StringIO()
   self.assertEqual(_run(['--archive-lock'],io.BytesIO(json.dumps(req).encode()+b'\n'),out,lambda:_Store._for_tests(root)),0)
   reply=json.loads(out.getvalue());self.assertEqual(set(reply),{'v','status','request','bindings'});self.assertEqual(reply['request'],req['request']);self.assertEqual([b['mode'] for b in reply['bindings']],['shared','exclusive']);self.assertEqual(len(reply['bindings']),2)
   for b in reply['bindings']:self.assertEqual(set(b),{'id','mode','parentDev','parentIno'})
   self.assertNotIn(str(base),out.getvalue());out=io.StringIO();req['targets'][1]['path']=str(base/'missing'/'b')
   self.assertNotEqual(_run(['--archive-lock'],io.BytesIO(json.dumps(req).encode()+b'\n'),out,lambda:_Store._for_tests(root)),0);self.assertNotIn(str(base),out.getvalue())
 def test_invalid_never_constructs_production_store(self):
  called=[]
  def deny():called.append(True);raise AssertionError()
  for raw in (b'{}\n',b'x'*8194,b'{}',b'{"v":1,"v":2}\n'):
   out=io.StringIO();self.assertNotEqual(_run(['--archive-lock'],io.BytesIO(raw),out,deny),0);self.assertEqual(json.loads(out.getvalue())['code'],'invalid_request')
  self.assertEqual(called,[])
 def test_extra_line_cannot_prepare(self):
  called=[];req={'v':1,'request':'a'*32,'targets':[{'path':'/private/fixture','mode':'exclusive'}]};out=io.StringIO()
  result=_run(['--archive-lock'],io.BytesIO(json.dumps(req).encode()+b'\n{}\n'),out,lambda:called.append(True))
  self.assertEqual(called,[]);self.assertNotEqual(result,0)
 def test_legacy_dispatch_remains_exact(self):
  connect=subprocess.run([sys.executable,'-I',str(W),'--connect'],input=b'{}\n',capture_output=True)
  self.assertEqual(connect.stderr,b'');reply=json.loads(connect.stdout);self.assertEqual(reply['event'],'terminal');self.assertEqual(reply['code'],'invalid_request');self.assertNotIn('status',reply)
  ordinary=subprocess.run([sys.executable,'-I',str(W)],input=b'[]\n',capture_output=True)
  self.assertEqual(ordinary.returncode,0);self.assertEqual(ordinary.stderr,b'');self.assertEqual(json.loads(ordinary.stdout)['status'],'missing')

if __name__=='__main__':unittest.main()
