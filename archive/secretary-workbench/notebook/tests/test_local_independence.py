"""Portable module probes: no app server, legacy root files or other modules present."""
import os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
APP=Path(__file__).resolve().parents[1]
class IndependenceTests(unittest.TestCase):
 def isolated(self,names,code):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'modules').mkdir()
   for name in names:shutil.copytree(APP/'modules'/name,root/'modules'/name,ignore=shutil.ignore_patterns('__pycache__'))
   shutil.copytree(APP/'contracts',root/'contracts',ignore=shutil.ignore_patterns('__pycache__'))
   env=dict(os.environ);env.pop('PYTHONPATH',None)
   p=subprocess.run([sys.executable,'-S','-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=20)
   self.assertEqual(p.returncode,0,p.stderr)
 def test_source_alone(self):
  self.isolated(['sources'],"from modules.sources import SourceRegistry;r=SourceRegistry('workspace');assert r.list_sources()==[];r.import_records('wechat','test',[{'nativeId':'msg1','text':'fixture','at':'2026-10-22T08:00:00+08:00'}]);assert len(r.query('wechat:test')['records'])==1")
 def test_secretary_alone_with_shared_failure_contract(self):
  self.isolated(['secretary'],"from modules.secretary import SecretaryService;from contracts.errors import ConflictError;from pathlib import Path;s=SecretaryService(None,Path('workspace'));assert s.list_jobs()==[];assert s._is_revision_conflict(ConflictError('version'))")
 def test_scheduler_alone(self):
  self.isolated(['scheduler'],"from modules.scheduler import Scheduler;s=Scheduler('workspace',None,None);assert s.status()==[]")
 def test_executor_alone(self):
  self.isolated(['executors'],"from modules.executors import ExecutorRegistry;e=ExecutorRegistry('workspace',None);assert e.list_requests()==[]")
if __name__=='__main__':unittest.main()
