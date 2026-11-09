import json, tempfile, unittest
from pathlib import Path
from live_core import read_append, merge_changes, checked_path, redact_record, stable_note, atomic_json, publish

class LiveTests(unittest.TestCase):
 def test_partial_append_and_retry(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'rows';p.write_bytes(b'{"a":1}\n{"a":')
   rows,c=read_append(p,{},10000);self.assertEqual(rows,[(1,{'a':1})]);self.assertEqual(c['offset'],8)
   with p.open('ab') as f:f.write(b'2}\n')
   rows,c2=read_append(p,c,10000);self.assertEqual(rows,[(2,{'a':2})]);self.assertEqual(read_append(p,c2,10000)[0],[])
 def test_rotation_reset(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'rows';p.write_text('{"long":12345}\n');_,c=read_append(p,{},10000);p.write_text('{"a":2}\n')
   self.assertEqual(read_append(p,c,10000)[0],[(1,{'a':2})])
 def test_bad_source_and_cross_employee_rejected(self):
  old=[{'id':'a','employee':'science','state':'进行中','evidence':[],'trajectory':[]}]
  for patch in [{'id':'a','employee':'secretary','evidence':[{'id':'src','quote':'证据'}]}, {'id':'a','evidence':[{'id':'fake','quote':'证据'}]}, {'id':'a','evidence':[{'id':'src','quote':'凭空发生'}]}]:
   with self.assertRaises(ValueError):merge_changes(old,[patch],{'src':{'text':'证据'}},'science',{'src'})
 def test_merge_keeps_history_and_idempotent(self):
  old=[{'id':'a','employee':'science','state':'进行中','evidence':[{'id':'old','quote':'过去'}],'trajectory':[{'time':'1','event':'收到','source_id':'old'}]}]
  p={'id':'a','state':'已完成','evidence':[{'id':'new','quote':'已完成'}],'trajectory':[{'time':'2','event':'交付','source_id':'new'}]}
  ss={'old':{'text':'过去'},'new':{'text':'已完成'}};a=merge_changes(old,[p],ss,'science',{'new'});b=merge_changes(a,[p],ss,'science',{'new'})
  self.assertEqual(a,b);self.assertEqual(len(a[0]['trajectory']),2);self.assertEqual(len(a[0]['evidence']),2)
 def test_paths_restricted_symlink(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'x').symlink_to('/etc/passwd')
   for p in [root/'x',root/'.restricted-archive/a.md',Path('/etc/passwd')]:
    with self.assertRaises(ValueError):checked_path(p,[root])
 def test_redaction_exclusion(self):
  self.assertIsNone(redact_record('请读credential方案'))
  self.assertNotIn('abc123',redact_record('password=abc123'))
 def test_partial_json_not_accepted(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'CURRENT.json';p.write_text('{"a":')
   with self.assertRaises(ValueError):stable_note(p,json_required=True)
 def test_publish_failure_preserves_pointer(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);atomic_json(root/'live.json',{'revision':'old'})
   with self.assertRaises(ValueError):publish(root,{'tasks':[{'evidence':[{'id':'missing'}],'trajectory':[]}]},{},'new')
   self.assertEqual(json.loads((root/'live.json').read_text())['revision'],'old')

class IncrementalIntegrationTests(unittest.TestCase):
 def setUp(self):
  from unittest.mock import patch
  self.observer=patch('work_observer.refresh_work',side_effect=lambda s,rs,t,**kw:(s,rs));self.observer.start();self.addCleanup(self.observer.stop)
 def test_readonly_observer_single_source_failure_and_retry(self):
  import copy
  from unittest.mock import patch
  import live_update as m
  from live_core import publish,atomic_json
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);private=root/'private';live=root/'live';private.mkdir()
   tasks=[{'id':'a-'+n,'employee':n,'title':n,'kind':'workstream','state':'进行中','pending':'未完','evidence':[{'id':'s','quote':'旧'}],'trajectory':[]} for n in m.IDS]
   snap={'tasks':tasks,'employees':[{'id':n,'coverage':{'messages':1,'notes':1,'files':1},'current':'旧','runtime':'未知'} for n in m.IDS],'warnings':[]}
   state={'cycles':0,'employees':{n:{'files':{},'notes':{},'seen':[],'lastSuccess':'old','cursor':1} for n in m.IDS}}
   atomic_json(private/'live-checkpoints'/'base'/'state.json',state);publish(live,snap,{'s':{'text':'旧'}},'base')
   def msgs(n,s,cutoff):
    if n=='science':raise ValueError('模拟单源失联')
    x=copy.deepcopy(s);x['cursor']=2;return [],x,{'newMessages':0}
   native={n:{'status':'idle','queueCount':0} for n in m.IDS}
   with patch.multiple(m,PRIVATE=private,LIVE=live,STATE=private/'state.json'),patch('model_accounts.read_accounts',return_value=None),patch('employee_profiles.refresh_profiles',side_effect=lambda snap,src,st,t:(snap.get('profiles',{}),src,st)),patch.object(m,'read_messages',msgs),patch.object(m,'read_notes',lambda n,s,t:([],s,[],{})),patch.object(m.subprocess,'run',return_value=type('R',(),{'returncode':0,'stdout':json.dumps(native)})()):
    receipt=m.run_cycle();result=json.loads((private/'state.json').read_text())
    self.assertEqual(result['employees']['science']['cursor'],1);self.assertEqual(result['employees']['secretary']['cursor'],2)
    self.assertEqual(result['employees']['science']['lastSuccess'],'old')
    manifest=json.loads((live/'live.json').read_text());current=json.loads((live/manifest['snapshotUrl'].lstrip('/')).read_text());self.assertEqual(current['tasks'],tasks)
 def test_source_append_literal_same_body_at_distinct_times(self):
  # Exact repeat at the same timestamp dedupes; a later occurrence is retained.
  import live_sources as m
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   p=Path(d).resolve()/'rollout.jsonl'
   def event(t):return {'timestamp':t,'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'继续'}]}}
   rows=[event('2026-10-30T10:01:00Z'),event('2026-10-30T10:01:00Z'),event('2026-10-30T10:02:00Z')]
   p.write_text(''.join(json.dumps(x)+'\n' for x in rows))
   class DB:
    def execute(self,*a):return self
    def fetchone(self):return [str(p)]
    def close(self):pass
   state={'files':{},'seen':[],'initialCutoff':'2026-10-30T10:00:00Z','totalNewMessages':0}
   with patch.object(m,'SOURCE_ROOTS',[Path(d).resolve()]),patch.object(m.sqlite3,'connect',return_value=DB()):
    out,st,counts=m.read_messages('science',state,'2026-10-30T11:00:00Z');self.assertEqual(len(out),2)
    self.assertEqual(m.read_messages('science',st,'2026-10-30T11:00:00Z')[0],[])

class MoreLiveTests(unittest.TestCase):
 def setUp(self):
  from unittest.mock import patch
  self.observer=patch('work_observer.refresh_work',side_effect=lambda s,rs,t,**kw:(s,rs));self.observer.start();self.addCleanup(self.observer.stop)
 def test_fixed_cutoff_does_not_skip_later_messages(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'rows';p.write_text('{"timestamp":"2026-10-30T10:01:00Z"}\n{"timestamp":"2026-10-30T10:02:00Z"}\n')
   a,c=read_append(p,{},cutoff='2026-10-30T10:01:30+00:00');self.assertEqual(len(a),1)
   b,c2=read_append(p,c,cutoff='2026-10-30T10:03:00+00:00');self.assertEqual(len(b),1)
 def test_unknown_new_task_namespace_rejected(self):
  with self.assertRaises(ValueError):merge_changes([], [{'id':'random','state':'待核实','evidence':[{'id':'s','quote':'原文'}]}], {'s':{'text':'原文'}}, 'science', {'s'})
 def test_private_generation_cannot_be_served(self):
  from serve import resolve_static
  for path in ['/versions/20261030T142231-05c531/state.json','/versions/../../private/live-state.json','/live-checkpoints/x/state.json']:
   with self.assertRaises(ValueError):resolve_static(path)
 def test_no_change_cycle_does_not_call_model(self):
  import copy
  from unittest.mock import patch
  import live_update as m
  from live_core import publish,atomic_json
  with tempfile.TemporaryDirectory() as d:
   private=Path(d)/'private';live=Path(d)/'live';private.mkdir()
   state={'cycles':0,'employees':{n:{'files':{},'notes':{},'seen':[]} for n in m.IDS}}
   snap={'tasks':[],'employees':[{'id':n,'coverage':{'messages':1,'notes':1,'files':1},'current':'保留既有判断'} for n in m.IDS],'warnings':[]}
   atomic_json(private/'live-checkpoints'/'base'/'state.json',state);publish(live,snap,{},'base')
   native={n:{'status':'idle','queueCount':0} for n in m.IDS}
   with patch.multiple(m,PRIVATE=private,LIVE=live,STATE=private/'state.json'),patch('model_accounts.read_accounts',return_value=None),patch('employee_profiles.refresh_profiles',side_effect=lambda snap,src,st,t:(snap.get('profiles',{}),src,st)),patch.object(m,'read_messages',lambda n,s,t:([],copy.deepcopy(s),{'newMessages':0,'bytesRead':0})),patch.object(m,'read_notes',lambda n,s,t:([],s,[],{})),patch.object(m,'analyze',side_effect=AssertionError('no model on unchanged input')),patch.object(m.subprocess,'run',return_value=type('R',(),{'returncode':0,'stdout':json.dumps(native)})()):
    a=m.run_cycle();b=m.run_cycle();self.assertEqual(b['cycle'],2)
    manifest=json.loads((live/'live.json').read_text());s=json.loads((live/manifest['snapshotUrl'].lstrip('/')).read_text());self.assertTrue(all(e['current']=='保留既有判断' for e in s['employees']))

class NotebookMappingTests(unittest.TestCase):
 def test_organoid_workbook_fields_override_stale_observer_and_keep_id(self):
  from live_update import update_notebooks
  __import__('live_update').ORG_IDS={'08':'organoid-v16'}
  self.addCleanup(setattr,__import__('live_update'),'ORG_IDS',{})
  text='\n'.join(['<!-- employee-work:start -->','- **事情**：v16整合交付','- **现在怎么样**：已办好','- **下一步**：等待明确新反馈','- **这次想做到什么**：真实交付','<!-- employee-work:end -->'])
  old=[{'sourceNotebook':'/role/workbook/08_v16.md','id':'organoid-v16','employee':'organoid','title':'旧标题','kind':'workstream','state':'进行中','evidence':[],'trajectory':[]}]
  a=update_notebooks(old,'organoid',[('/role/workbook/08_v16.md',text,[{'id':'s','text':text,'time':'2026-10-30 22:00:00'}])])
  self.assertEqual(len(a),1);self.assertEqual(a[0]['id'],'organoid-v16');self.assertEqual(a[0]['state'],'已办好');self.assertEqual(len(a[0]['trajectory']),1)
 def test_same_notebook_poll_does_not_duplicate_evidence(self):
  from live_update import update_notebooks
  text='- **事情**：事项\n- **现在怎么样**：进行中\n- **下一步**：完成原交付'
  x=[('/role/book.md',text,[{'id':'s','text':text,'time':'time'}])]
  a=update_notebooks([],'secretary',x);self.assertEqual(a,update_notebooks(a,'secretary',x))

class DirectObservationTests(unittest.TestCase):
 def test_new_public_record_is_observed_without_model_or_invented_task(self):
  import copy
  from unittest.mock import patch
  import live_update as m
  from live_core import publish,atomic_json
  with tempfile.TemporaryDirectory() as d:
   private=Path(d)/'private';live=Path(d)/'live';private.mkdir();state={'cycles':0,'employees':{n:{'files':{},'notes':{},'seen':[]} for n in m.IDS}};snap={'tasks':[],'employees':[{'id':n,'coverage':{'messages':0,'notes':0,'files':0},'current':'original'} for n in m.IDS],'warnings':[]}
   atomic_json(private/'live-checkpoints'/'base'/'state.json',state);publish(live,snap,{},'base')
   record={'id':'public-new','text':'正在核对已有交付','time':'2026-11-02 00:00:00','path':'normal','role':'assistant'}
   native={n:{'status':'idle','queueCount':0} for n in m.IDS}
   with patch.multiple(m,PRIVATE=private,LIVE=live,STATE=private/'state.json'),patch('work_observer.refresh_work',side_effect=lambda s,rs,t,**kw:(s,rs)),patch('model_accounts.read_accounts',return_value=None),patch('employee_profiles.refresh_profiles',side_effect=lambda s,rs,st,t:({},rs,st)),patch.object(m,'read_messages',lambda n,s,t:([record] if n=='secretary' else [],copy.deepcopy(s),{'newMessages':1 if n=='secretary' else 0})),patch.object(m,'read_notes',lambda n,s,t:([],s,[],{})),patch.object(m,'analyze',side_effect=AssertionError('routine observation must not wait on a model')),patch.object(m.subprocess,'run',return_value=type('R',(),{'returncode':0,'stdout':json.dumps(native)})()):
    result=m.run_cycle();updated=json.loads((private/'state.json').read_text());self.assertIsNone(updated['employees']['secretary']['error']);manifest=json.loads((live/'live.json').read_text());data=json.loads((live/manifest['snapshotUrl'].lstrip('/')).read_text());self.assertEqual(data['tasks'],[]);self.assertEqual(data['employees'][0]['coverage']['messages'],1)

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
