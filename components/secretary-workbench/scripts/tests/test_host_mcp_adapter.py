"""Synthetic host boundary tests: no daemon, source DB or network calls."""
import importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'host/aup-sender'))
import sender_work_tools as m
import mac_files_client as mac

class MCPAdapter(unittest.TestCase):
 def test_no_configuration_does_not_execute_sdk(self):
  with patch.dict(os.environ,{},clear=True),patch('subprocess.run',side_effect=AssertionError('no host call')):
   adapter=m.Lazy('isolated_sdk',ROOT/'host/tools/wechat_operations.py','write')
   with self.assertRaises(ValueError):adapter.call({'op':'capabilities'})
   self.assertIsNone(adapter.loaded)
 def test_mutation_requires_real_owner_file_and_preserves_request(self):
  with tempfile.TemporaryDirectory() as d,patch.object(m,'ROOT',Path(d)),patch.object(m,'SDK') as sdk:
   p=Path(d)/'OWNER.json';p.write_text('{"phase":"paused"}')
   r={'op':'submit','client':'fixture','request_id':'synthetic-1'}
   with self.assertRaises(PermissionError):m.operation(r)
   sdk.call.assert_not_called();p.write_text('{"phase":"active"}')
   m.operation(r);sdk.call.assert_called_once_with(r)
 def test_read_uses_same_sdk_without_native_submission(self):
  with patch.object(m,'SDK') as sdk,patch('subprocess.Popen',side_effect=AssertionError('no model')):
   sdk.call.return_value={'jobs':[]};r={'op':'get_many','client':'fixture','request_ids':['x']}
   self.assertEqual(m.operation(r),{'jobs':[]});sdk.call.assert_called_once_with(r)
 def test_unknown_operation_does_not_bypass_owner_gate(self):
  with tempfile.TemporaryDirectory() as d,patch.object(m,'ROOT',Path(d)),patch.object(m,'SDK') as sdk:
   (Path(d)/'OWNER.json').write_text('{"phase":"paused"}')
   with self.assertRaises(PermissionError):m.operation({'op':'invented'})
   sdk.call.assert_not_called()
 def test_local_command_quotes_operator_paths_and_stream_contract(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d).resolve();code=base/'code with space';code.mkdir();state=base/'state';state.mkdir();cfg=base/'own config.json';cfg.write_text('{}')
   env={'SECRETARY_OPERATIONS_CODE':str(code),'SECRETARY_OPERATIONS_STATE':str(state),'SECRETARY_OPERATIONS_CONFIG':str(cfg)}
   with patch.dict(os.environ,env,clear=True):
    sdk=m.Lazy('isolated_sdk2',ROOT/'host/tools/wechat_operations.py','write');self.assertTrue(callable(sdk.call));cmd=sdk.loaded.COMMAND
    self.assertEqual(cmd[:2],['/bin/sh','-c']);self.assertIn("'"+str(code)+"'",cmd[-1]);self.assertIn('operations.cli request --execute',cmd[-1])
 def test_mac_endpoint_requires_pinned_explicit_transport(self):
  with patch.dict(os.environ,{},clear=True),patch('subprocess.run',side_effect=AssertionError('no SSH')):
   with self.assertRaises(ValueError):mac.call({'op':'stat'})
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();key=root/'key';pins=root/'known';key.write_text('fixture');pins.write_text('fixture')
   env={'SECRETARY_MAC_SSH_TARGET':'operator@fixture-host','SECRETARY_MAC_SSH_KEY':str(key),'SECRETARY_MAC_SSH_KNOWN_HOSTS':str(pins)}
   with patch.dict(os.environ,env,clear=True):
    command=mac.ssh_command();self.assertIn('-oStrictHostKeyChecking=yes',command);self.assertEqual(command[-1],'access-v1')
   pins.unlink();pins.symlink_to(key)
   with patch.dict(os.environ,env,clear=True),self.assertRaises(ValueError):mac.ssh_command()
