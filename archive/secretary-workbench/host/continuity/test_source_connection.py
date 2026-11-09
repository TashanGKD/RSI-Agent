import contextlib,io,json,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import runtime as r

class SourceConnectionTests(unittest.TestCase):
 def make(self,path,status,clock):
  self.assertTrue(hasattr(r,'SourceConnection'),'EOF currently kills the whole original runtime; missing bounded connection recovery')
  return r.SourceConnection(path,status,clock=lambda:clock[0])
 def child(self,code):
  p=subprocess.Popen([sys.executable,'-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
  import os
  os.set_blocking(p.stderr.fileno(),False)
  return p
 def test_disconnect_preserves_pending_and_unknown_batch(self):
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d);status={'sourceReady':True,'bindings':{'test':{'sourceReady':True}}};clock=[0]
   ledger=r.Ledger(folder/'events.sqlite')
   ledger.c.execute("insert into events values('test','123','{}','pending',NULL)")
   ledger.c.execute("insert into batches values('batch','test','immutable','[]','unknown','q',NULL,NULL,'old',1)");ledger.c.commit()
   before=[tuple(x) for x in ledger.c.execute('select * from events')],[tuple(x) for x in ledger.c.execute('select * from batches')]
   p=self.child('import sys;sys.stderr.write("connection reset by peer\\n");sys.exit(255)');p.wait(timeout=3)
   with patch.object(r,'start_source',return_value=p):
    conn=self.make(folder,status,clock)
    self.assertIsNone(conn.read([]));self.assertFalse(status['sourceReady']);self.assertFalse(status['bindings']['test']['sourceReady'])
    self.assertEqual(status['sourceLastExitCode'],255);self.assertIsNone(conn.source)
   after=[tuple(x) for x in ledger.c.execute('select * from events')],[tuple(x) for x in ledger.c.execute('select * from batches')]
   self.assertEqual(after,before);ledger.close()
 def test_retry_waits_then_fresh_frame_restores_ready(self):
  with tempfile.TemporaryDirectory() as d:
   clock=[0];status={'sourceReady':True};dead=self.child('pass');dead.wait(timeout=3)
   live=self.child('import json,time;print(json.dumps({"kind":"source","binding":"test","events":[],"coverage":{"complete":True}}),flush=True);time.sleep(10)')
   with patch.object(r,'start_source',side_effect=[dead,live]) as start:
    conn=self.make(Path(d),status,clock);self.assertIsNone(conn.read([]));self.assertFalse(status['sourceReady'])
    self.assertIsNone(conn.read([]));self.assertEqual(start.call_count,1)
    clock[0]=31;frame=conn.read([]);self.assertEqual(frame['kind'],'source');self.assertEqual(start.call_count,2)
    # Only the runtime's validated frame handler may mark this source ready.
    self.assertFalse(status['sourceReady']);conn.close();self.assertIsNotNone(live.poll())
 def test_stderr_bounded_and_only_hash_exposed_in_status(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.child('import sys;sys.stderr.write("x"*6000+"THE_END");sys.exit(1)');p.wait(timeout=3)
   status={};clock=[0]
   with patch.object(r,'start_source',return_value=p):
    conn=self.make(Path(d),status,clock);conn.read([])
   v=json.loads((Path(d)/'source-last-failure.json').read_text());self.assertLessEqual(len(v['stderrTail'].encode()),4096);self.assertTrue(v['stderrTail'].endswith('THE_END'))
   self.assertNotIn('THE_END',json.dumps(status));self.assertEqual(len(status['sourceDiagnosticSHA256']),64)
 def test_malformed_or_oversize_frame_not_silently_retried(self):
  for text in ['not-json','x'*262145]:
   with tempfile.TemporaryDirectory() as d:
    p=self.child('import sys,time;sys.stdout.write('+repr(text+'\n')+');sys.stdout.flush();time.sleep(10)')
    with patch.object(r,'start_source',return_value=p):
     conn=self.make(Path(d),{},[0])
     try:
      with self.assertRaises(ValueError):conn.read([])
     finally:conn.close()
 def test_repeated_failures_back_off_and_dont_keep_old_child(self):
  with tempfile.TemporaryDirectory() as d:
   status={};clock=[0];children=[]
   def start(_):
    p=self.child('pass');p.wait(timeout=3);children.append(p);return p
   with patch.object(r,'start_source',side_effect=start) as fn:
    conn=self.make(Path(d),status,clock);waits=[]
    for _ in range(7):
     conn.read([]);waits.append(conn.retry_at-clock[0]);self.assertIsNone(conn.source)
     conn.read([]);self.assertEqual(fn.call_count,len(waits));clock[0]=conn.retry_at+.01
    self.assertTrue(all(0<x<=30+1e-8 for x in waits));self.assertGreater(waits[-1],waits[0]);conn.close()
   self.assertTrue(all(p.poll() is not None and p.stdout.closed and p.stderr.closed for p in children))

if __name__=='__main__':unittest.main()

def setUpModule():
 global _source_config
 from unittest.mock import patch
 _source_config=patch.multiple(__import__('runtime'),SSH_ALIAS='fixture-host',REMOTE='python3 fixture_source.py --stream');_source_config.start()
def tearDownModule():_source_config.stop()
