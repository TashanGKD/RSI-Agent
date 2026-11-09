import unittest,tempfile,json,copy
from pathlib import Path
from employee_profiles import validate_profile,profile_refs,normalize_profile,collect_source,refresh_profiles

class ProfileTests(unittest.TestCase):
 def fixture(self):
  src={'s':{'id':'s','text':'用户是服务对象；科研三人群只读。负责科研分析。'}}
  p={'roleName':'科研协作者','purpose':'科研分析','identityEvidence':[{'id':'s','quote':'负责科研分析。'}],
   'responsibilities':[{'text':'科研分析','evidence':[{'id':'s','quote':'负责科研分析。'}]}],
   'relations':[{'label':'科研三人群','kind':'channel','types':['reads'],'scope':'只读','evidence':[{'id':'s','quote':'科研三人群只读。'}]}],
   'boundaries':[],'routines':[],'resources':[],'capabilities':[],'lifecycle':{'state':'unknown','note':'未核实','evidence':[]},'history':[]}
  return p,src
 def test_reading_does_not_become_service(self):
  p,s=self.fixture();r=normalize_profile('science',p);validate_profile(r,s);self.assertEqual(r['relations'][0]['types'],['reads'])
 def test_entity_kind_and_service_relation_cannot_be_confused(self):
  p,s=self.fixture();p['relations'][0]['types']=['serves']
  with self.assertRaises(ValueError):validate_profile(normalize_profile('science',p),s)
 def test_false_quote_source_and_relation_rejected(self):
  for key in ['quote','source','enum']:
   p,s=self.fixture()
   if key=='quote':p['relations'][0]['evidence'][0]['quote']='不存在的授权'
   if key=='source':p['relations'][0]['evidence'][0]['id']='fake'
   if key=='enum':p['relations'][0]['types']=['can_pay_everyone']
   with self.assertRaises(ValueError):validate_profile(normalize_profile('science',p),s)
 def test_lifecycle_unknown_does_not_infer_away_from_task_pause(self):
  p,s=self.fixture();p['responsibilities'][0]['text']='任务暂缓';r=normalize_profile('science',p);validate_profile(r,s);self.assertEqual(r['lifecycle']['state'],'unknown')
 def test_all_refs_can_be_projected(self):
  p,s=self.fixture();r=normalize_profile('science',p);self.assertEqual({x['id'] for x in profile_refs(r)},{'s'})
 def test_restricted_and_symlink_paths_refused(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();(root/'x').symlink_to('/etc/passwd')
   for p in [root/'x',root/'.restricted-archive/a.md',Path('/etc/passwd')]:
    with self.assertRaises(ValueError):collect_source('science',p,[root])
 def test_one_profile_failure_preserves_previous(self):
  from unittest.mock import patch
  p,s=self.fixture();old={'science':normalize_profile('science',p),'organoid':normalize_profile('organoid',p)}
  with patch('employee_profiles.read_employee_profile',side_effect=ValueError('模拟失效')):
   result,_,state=refresh_profiles({'profiles':old},{}, {},'2026-10-31T00:00:00+00:00',names=['science'])
   self.assertEqual(result['science']['relations'],old['science']['relations']);self.assertTrue(result['science']['health']['error']);self.assertNotEqual(result['organoid'].get('health',{}),result['science']['health'])
 def test_one_failure_does_not_block_another_profile(self):
  from unittest.mock import patch
  p,s=self.fixture();good=normalize_profile('organoid',p)
  def read(name,when):
   if name=='science':raise ValueError('单源失效')
   return good,s
  with patch('employee_profiles.read_employee_profile',side_effect=read):
   result,sources,_=refresh_profiles({}, {}, {},'2026-10-31T00:00:00+00:00',names=['science','organoid'])
  self.assertTrue(result['science']['health']['error']);self.assertEqual(result['organoid']['roleName'],good['roleName']);self.assertIn('s',sources)
 def test_unchanged_role_text_uses_validated_cache(self):
  from unittest.mock import patch
  import employee_profiles as ep
  p,s=self.fixture();records=[{'id':'s','label':'ROLE.md','text':s['s']['text']}]
  packet={'employee':'science','threadId':ep.IDS['science'],'sources':records}
  with tempfile.TemporaryDirectory() as d,patch.object(ep,'PRIVATE',Path(d)):
   key=ep.digest(ep.SYSTEM+'\0'+json.dumps(packet,ensure_ascii=False,sort_keys=True))
   target=Path(d)/'profile-analysis'/key;target.mkdir(parents=True);(target/'result.json').write_text(json.dumps(p))
   with patch.object(ep.subprocess,'run',side_effect=AssertionError('不应重复整理不变资料')):
    result=ep.extract('science',records)
   self.assertEqual(result['roleName'],p['roleName'])

class ProfileProjectionTests(unittest.TestCase):
 def test_profile_evidence_is_kept_in_online_projection(self):
  from online_sync import make_projection
  s={'tasks':[],'warnings':[],'profiles':{'science':{'identityEvidence':[{'id':'r','quote':'岗位'}],'relations':[]}}}
  _,sources=make_projection(s,{'r':{'id':'r','text':'岗位','path':'/home/operator/softmatter/ROLE.md'},'unused':{'text':'不应发布'}})
  self.assertEqual(set(sources),{'r'})
 def test_missing_profile_evidence_rejects_atomic_publication(self):
  from live_core import publish,atomic_json
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);atomic_json(root/'live.json',{'revision':'old'})
   with self.assertRaises(ValueError):publish(root,{'tasks':[],'profiles':{'science':{'identityEvidence':[{'id':'missing','quote':'原文'}]}}},{},'new')
   self.assertEqual(json.loads((root/'live.json').read_text())['revision'],'old')
 def test_state_channel_credentials_not_projected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();p=root/'STATE.json';p.write_text(json.dumps({'channels':{'wechat':{'peer':'123@chatroom','access_token':'DO-NOT-PUBLISH'}},'role':'ROLE.md'}))
   source=collect_source('science',p,[root]);self.assertNotIn('DO-NOT-PUBLISH',source['text']);self.assertIn('123@chatroom',source['text'])

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
