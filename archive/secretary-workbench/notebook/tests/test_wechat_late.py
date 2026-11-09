import importlib.util
from pathlib import Path
import sqlite3,tempfile,unittest
TOOL=Path(__file__).resolve().parents[1]/'tools/wechat_late.py'
class LateTests(unittest.TestCase):
 def setUp(self):
  self.assertTrue(TOOL.exists(),'late-ingestion checker missing')
  s=importlib.util.spec_from_file_location('wechat_late',TOOL);self.m=importlib.util.module_from_spec(s);s.loader.exec_module(self.m)
 def fixture(self,p,rows):
  c=sqlite3.connect(p);c.execute('CREATE TABLE Msg_'+'a'*32+'(local_id INTEGER PRIMARY KEY,server_id INTEGER,local_type INTEGER,create_time INTEGER,message_content BLOB)')
  c.executemany('INSERT INTO Msg_'+'a'*32+' VALUES(?,?,?,?,?)',rows);c.commit();c.close()
 def test_detects_old_timestamp_new_and_changed_payload(self):
  with tempfile.TemporaryDirectory() as d:
   b=Path(d).resolve()/'old.db';n=b.with_name('new.db');self.fixture(b,[(1,11,1,100,b'original')]);self.fixture(n,[(1,11,1,100,b'changed'),(2,12,1,101,b'late arrival'),(3,13,1,200,b'outside')])
   rows=list(self.m.late_rows(n,b,90,150,lambda:None))
   self.assertEqual([(r['local_id'],r['_change']) for r in rows],[(1,'changed'),(2,'new')])
 def test_identical_source_has_no_late_changes(self):
  with tempfile.TemporaryDirectory() as d:
   b=Path(d).resolve()/'old.db';n=b.with_name('new.db');rows=[(1,11,1,100,b'original')];self.fixture(b,rows);self.fixture(n,rows)
   self.assertEqual(list(self.m.late_rows(n,b,90,150,lambda:None)),[])
if __name__=='__main__':unittest.main()
