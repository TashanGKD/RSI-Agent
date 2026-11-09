"""Catch role/template confusion and synthetic-demo data/side effects; no live employee."""
import importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('fixed_role_seed',ROOT/'examples/seed_monitor.py')
seed=importlib.util.module_from_spec(spec);spec.loader.exec_module(seed)

class FixedRoleExamples(unittest.TestCase):
 def test_failure_preserves_existing_output_and_other_files(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();existing=root/'instance';existing.mkdir();note=existing/'original';note.write_text('keep')
   with self.assertRaises(ValueError):seed.seed(existing)
   self.assertEqual(note.read_text(),'keep')
   link=root/'alias';link.symlink_to(existing,target_is_directory=True)
   with self.assertRaises(ValueError):seed.seed(link)
   self.assertTrue(link.is_symlink());self.assertEqual(note.read_text(),'keep')
   dangling=root/'dangling';dangling.symlink_to(root/'absent')
   with self.assertRaises(ValueError):seed.seed(dangling)
   self.assertTrue(dangling.is_symlink())
 def test_bad_workbook_is_not_published_or_silently_dropped(self):
  with tempfile.TemporaryDirectory() as d:
   output=Path(d).resolve()/'demo'
   # Same real-shape error as the original workbook parser: required field missing.
   files=seed.read_example()
   name='workbook/W001-materials.md'
   files[name]='\n'.join(line for line in files[name].splitlines() if not line.startswith('- **\u4e0b\u4e00\u6b65**'))
   with patch.object(seed,'read_example',return_value=files):
    with self.assertRaisesRegex(ValueError,'eight current fields required'):seed.seed(output)
   self.assertFalse(output.exists())
 def test_publication_failure_cleans_only_new_output(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();output=root/'demo';sibling=root/'keep';sibling.write_text('unrelated')
   with patch.object(seed,'publish',side_effect=ValueError('snapshot refers to missing evidence')) as publish:
    with self.assertRaises(ValueError):seed.seed(output)
   publish.assert_called_once();self.assertFalse(output.exists());self.assertEqual(sibling.read_text(),'unrelated')
 def test_non_synthetic_channel_or_native_receipt_is_not_exported(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve()
   for change in [{'channels':{'wechat':{'peer':'fixture-peer'}}},{'receipts':{'system_onboarding':[],'deliveries':[{'state':'accepted','serverId':'fake-native-proof'}]}},{'example':{'synthetic':False}}]:
    files=seed.read_example();state=json.loads(files['STATE.json']);state.update(change);files['STATE.json']=json.dumps(state);output=root/'demo'
    with patch.object(seed,'read_example',return_value=files),self.assertRaises(ValueError):seed.seed(output)
    self.assertFalse(output.exists())
 def test_parent_alias_and_relative_new_temporary_output_are_supported(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();parent=root/'actual';parent.mkdir();(root/'alias').symlink_to(parent,target_is_directory=True);old=Path.cwd()
   try:
    os.chdir(root);result=seed.seed('alias/new-demo');self.assertEqual(Path(result['destination']),parent/'new-demo');self.assertTrue((parent/'new-demo/employee/CURRENT.md').is_file())
   finally:os.chdir(old)
 def test_selectable_duties_and_three_workbooks_are_distinct(self):
  folder=ROOT/'workspace-template/role-profiles'
  for name in ['people-method','wechat-tool-maintenance','workbench-monitor','shared-notebook','mechanical-sender']:
   self.assertTrue((folder/(name+'.md')).is_file(),name)
  index=(folder/'README.md').read_text()
  self.assertIn('不是五个必须新建的员工',index)
  self.assertIn('个人工作本',index);self.assertIn('共同业务记事本',index);self.assertIn('只读监控',index)
  sender=(folder/'mechanical-sender.md').read_text();self.assertIn('不是必经审批',sender)
 def test_complete_synthetic_example_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();output=root/'demo'
   # No business/model/sender process may run while using library APIs.
   with patch('subprocess.run',side_effect=AssertionError('no external call')),patch('subprocess.Popen',side_effect=AssertionError('no process')):
    try:result=seed.seed(output)
    except ValueError as error:self.fail('new temporary synthetic workspace rejected: '+str(error))
   self.assertTrue(result['synthetic']);self.assertEqual(result['workNotes'],3)
   config=json.loads((output/'installation.example.json').read_text());self.assertEqual(config['paths'],{'monitor_workspace':'.'})
   employee=output/'employee';self.assertTrue((employee/'ROLE.md').is_file());self.assertTrue((employee/'CURRENT.md').is_file())
   state=json.loads((employee/'STATE.json').read_text());self.assertEqual(state['channels'],{});self.assertEqual(state['receipts']['deliveries'],[])
   self.assertTrue(seed.workbook.operate(employee,'check',False)['consistent'])
   manifest=json.loads((output/'live/live.json').read_text());snap=json.loads((output/'live'/manifest['snapshotUrl'].lstrip('/')).read_text())
   self.assertEqual(len(snap['tasks']),3);self.assertTrue(snap['synthetic']);self.assertIn('synthetic',snap['warnings'][0].lower())
   self.assertEqual(snap['employees'][0]['queueCount'],None);self.assertTrue(all(not t.get('nativeReceiptVerified') for t in snap['tasks']))
   sources=json.loads((output/'live'/manifest['sourcesUrl'].lstrip('/')).read_text())
   from work_contract import validate_work
   validate_work(snap['workOverview'],sources)
   import employee_profiles
   with patch.object(employee_profiles,'IDS',{'fixture-worker':'00000000-0000-4000-8000-000000000001'}):employee_profiles.validate_profile(snap['profiles']['fixture-worker'],sources)
   self.assertEqual(len(snap['profiles']['fixture-worker']['relations']),3)
   self.assertEqual({t['state'] for t in snap['tasks']},{'待推进','等反馈','已办好'})
   self.assertNotIn('accepted',json.dumps(state));self.assertFalse((output/'registry.json').exists())
 def test_preview_does_not_create_output(self):
  with tempfile.TemporaryDirectory() as d:
   output=Path(d).resolve()/'preview';before=set(Path(d).iterdir())
   with patch.object(sys,'argv',['seed_monitor.py','--output',str(output)]),patch('builtins.print') as printed:seed.main()
   self.assertEqual(before,set(Path(d).iterdir()));self.assertTrue(printed.called,'explicit output without execute must return a structured no-write preview');value=json.loads(printed.call_args.args[0]);self.assertEqual(value['execute'],False)
