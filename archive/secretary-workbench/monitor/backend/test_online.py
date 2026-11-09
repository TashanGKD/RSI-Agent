import copy,io,json,tarfile,tempfile,unittest
from pathlib import Path
from online_sync import make_projection,build_payload
from cloud_receive import receive

class OnlineBoundaries(unittest.TestCase):
 def test_unused_source_and_private_paths_not_uploaded(self):
  snap={'tasks':[{'id':'a','evidence':[{'id':'needed','quote':'证据'}],'trajectory':[]}],'employees':[],'warnings':[]}
  sources={'needed':{'id':'needed','text':'证据','path':'/home/operator/Secretary/notebook/a.md'},'unused':{'id':'unused','text':'无关口令备忘','path':'/home/operator/.codex/auth.json'}}
  s,src=make_projection(snap,sources);self.assertEqual(set(src),{'needed'});self.assertNotIn('/home/operator',src['needed']['path'])
 def archive(self,names):
  f=io.BytesIO()
  with tarfile.open(fileobj=f,mode='w:gz') as tar:
   for name,data in names:
    t=tarfile.TarInfo(name);t.size=len(data);tar.addfile(t,io.BytesIO(data))
  return f.getvalue()
 def test_traversal_unknown_file_and_symlink_rejected_before_publish(self):
  for name in ['../private/key','private/state.json','/etc/passwd']:
   with tempfile.TemporaryDirectory() as d:
    p=Path(d);(p/'live.json').write_text('{"revision":"old"}')
    with self.assertRaises(ValueError):receive(p,'20261030T220000-abcdef',self.archive([(name,b'bad')]))
    self.assertEqual(json.loads((p/'live.json').read_text())['revision'],'old')
  f=io.BytesIO()
  with tarfile.open(fileobj=f,mode='w:gz') as tar:
   t=tarfile.TarInfo('snapshot.json');t.type=tarfile.SYMTYPE;t.linkname='/etc/passwd';tar.addfile(t)
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):receive(Path(d),'20261030T220000-abcdef',f.getvalue())
 def test_missing_evidence_preserves_previous_version(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'live.json').write_text('{"revision":"old"}')
   s={'tasks':[{'evidence':[{'id':'missing'}],'trajectory':[]} ]}
   with self.assertRaises(ValueError):receive(p,'20261030T220000-abcdef',self.archive([('snapshot.json',json.dumps(s).encode()),('sources.json',b'{}'),('status.json',b'{}')]))
   self.assertEqual(json.loads((p/'live.json').read_text())['revision'],'old')
 def test_repeated_publish_is_idempotent(self):
  with tempfile.TemporaryDirectory() as d:
   s={'tasks':[{'id':'a','evidence':[{'id':'s'}],'trajectory':[]}],'live':{'revision':'20261030T220000-abcdef'}}
   payload=build_payload(s,{'s':{'id':'s','text':'原文'}},{})
   a=receive(Path(d),'20261030T220000-abcdef',payload);b=receive(Path(d),'20261030T220000-abcdef',payload)
   self.assertEqual(a,b);self.assertEqual(len(list((Path(d)/'versions').iterdir())),1)

def setUpModule():
 from unittest.mock import patch
 import contextlib,collect,send_tool_observer,delivery_obligations,employee_profiles,account_contract,model_accounts
 global _portable_patches
 _portable_patches=contextlib.ExitStack()
 clients={'secretary':'secretary','science':'science','organoid_bp':'organoid','forum_employee':'forum','employee_pilot':'employee-pilot','employee_method':'system','aup_support':'aup-support','research_secretary':'research-secretary'}
 ids={'secretary':'00000000-0000-4000-8000-4344f0fd9daa','science':'00000000-0000-4000-8000-37b7cd446cba','organoid':'00000000-0000-4000-8000-f709f264f942'}
 emails=tuple('fixture'+str(i)+'@example.invalid' for i in range(3))
 for mod,key,value in [(send_tool_observer,'CLIENTS',clients),(collect,'IDS',ids),(delivery_obligations,'CLIENTS',clients),(delivery_obligations,'OWNERS',ids),(employee_profiles,'IDS',ids),(account_contract,'EMAILS',emails),(model_accounts,'EMAILS',emails)]:
  _portable_patches.enter_context(patch.object(mod,key,value))
def tearDownModule():
 _portable_patches.close()
