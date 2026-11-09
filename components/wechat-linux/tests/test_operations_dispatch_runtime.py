import unittest,tempfile,json,threading,time
from pathlib import Path
from operations.public_api import PublicAPI
from operations.runtime import Executor
from operations import lease
from operations.assets import descriptor
import hashlib
CFG={'account':'self','clients':{'a':{'peers':['owner'],'actions':['send_text','send_file']}}}
def entry(rid,kind):return {'job':{'client':'a','request_id':rid,'peer':'owner','action':'send_text','payload':{'text':rid}},'dispatch':{'kind':kind}}
class Driver:
 def __init__(self):self.acquired=0;self.sent=0;self.cleaned=0
 def acquire(self):self.acquired+=1;return True
 def release(self):pass
 def prepare(self,j):return {'sha256':'a'*64,'summary':{'peer':'owner','text':j['payload']['text']}}
 def cleanup(self,j):self.cleaned+=1;return True
 def execute(self,j):self.sent+=1;return {'state':'accepted','serverId':'1'}
 def verify(self,j):return {'state':'unknown'}
class RuntimeDispatch(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name).resolve()/'s';self.a=PublicAPI(self.root,CFG);self.addCleanup(self.a.close);self.d=Driver();self.e=Executor(self.a.s,self.d)
 def admit(self,rid,kind='delivery'):
  return self.a.call({'op':'admit','client':'a','batch_id':rid,'items':[entry(rid,kind)]})['jobs'][0]
 def test_waiting_assets_never_acquire_window(self):
  aid=descriptor('a','x.txt',1,hashlib.sha256(b'x').hexdigest());x=entry('file','delivery');x['job'].update(action='send_file',payload={'asset':aid});x['dispatch']['expected_asset']={'name':'x.txt','bytes':1,'sha256':hashlib.sha256(b'x').hexdigest()}
  self.a.call({'op':'admit','client':'a','batch_id':'x','items':[x]});self.e.step();self.assertEqual(self.d.acquired,0)
 def test_owned_maintenance_yields_only_after_cleanup(self):
  self.admit('maintenance','maintenance');self.e.step();self.admit('reply','reply');self.e.step()
  j=self.a.s.get('a','maintenance');self.assertEqual(j['state'],'cancelled');self.assertTrue(j['result']['noSend']);self.assertEqual(self.d.cleaned,1);self.assertEqual(self.d.sent,0);self.e.step();self.assertEqual(self.a.s.get('a','reply')['state'],'awaiting_confirmation')
 def test_attempted_maintenance_and_unknown_never_yield(self):
  j=self.admit('maintenance','maintenance');self.e.step();(self.root/(j['id']+'-attempt.json')).write_text('{}');self.admit('reply','reply');self.e.step();self.assertEqual(self.a.s.get('a','maintenance')['state'],'awaiting_confirmation');self.assertEqual(self.d.cleaned,0)
  self.a.s.set_state(j['id'],'unknown',{'automaticReplay':False});self.e.step();self.assertEqual(self.a.s.get('a','maintenance')['state'],'unknown');self.assertEqual(self.d.sent,0)
 def test_failed_cleanup_retains_protection(self):
  self.admit('maintenance','maintenance');self.e.step();self.admit('reply','reply');self.d.cleanup=lambda j:False;self.e.step();self.assertNotEqual(self.a.s.get('a','maintenance')['state'],'cancelled');self.assertEqual(self.a.s.get('a','reply')['state'],'queued')
 def test_business_is_never_cancelled_by_new_reply(self):
  self.admit('delivery');self.e.step();self.admit('reply','reply');self.e.step();self.assertEqual(self.a.s.get('a','delivery')['state'],'awaiting_confirmation');self.assertEqual(self.d.cleaned,0)
 def test_maintenance_guard_denies_ready_and_unknown_without_lease(self):
  self.assertTrue(hasattr(lease,'maintenance_guard'))
  self.admit('reply','reply')
  with self.assertRaises(ValueError):
   with lease.maintenance_guard(self.root):self.fail('maintenance admitted ahead of reply')
 def test_admission_serialises_with_real_maintenance_reservation_transaction(self):
  self.assertTrue(hasattr(lease,'maintenance_guard'));done=threading.Event();errors=[]
  def admit():
   a=PublicAPI(self.root,CFG)
   try:a.call({'op':'admit','client':'a','batch_id':'new','items':[entry('new','reply')]});done.set()
   except Exception as e:errors.append(type(e).__name__)
   finally:a.close()
  with lease.maintenance_guard(self.root):
   t=threading.Thread(target=admit);t.start();self.assertFalse(done.wait(.05))
  t.join(3);self.assertTrue(done.is_set());self.assertEqual(errors,[])
if __name__=='__main__':unittest.main()

class Publication(unittest.TestCase):
 def test_future_asset_becoming_ready_serialises_with_maintenance_start(self):
  from operations.assets import Assets
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve()/'s';api=PublicAPI(root,CFG);data=b'x';sha=hashlib.sha256(data).hexdigest();aid=descriptor('a','x.txt',1,sha)
   x=entry('asset','delivery');x['job'].update(action='send_file',payload={'asset':aid});x['dispatch']['expected_asset']={'name':'x.txt','bytes':1,'sha256':sha}
   api.call({'op':'admit','client':'a','batch_id':'b','items':[x]});done=threading.Event();errors=[]
   def publish():
    try:Assets(root).put('a','x.txt',data,sha);done.set()
    except Exception as e:errors.append(type(e).__name__)
   try:
    with lease.maintenance_guard(root):
     t=threading.Thread(target=publish);t.start();self.assertFalse(done.wait(.1));self.assertFalse((root/'assets'/aid).exists())
    t.join(3);self.assertTrue(done.is_set());self.assertEqual(errors,[]);self.assertFalse(api.s.maintenance_eligibility()['eligible'])
   finally:api.close()
