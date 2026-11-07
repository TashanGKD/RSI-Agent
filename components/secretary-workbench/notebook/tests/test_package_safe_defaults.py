import unittest
from unittest.mock import patch
from pathlib import Path
import local_server
class PackageSafeDefaults(unittest.TestCase):
 def test_demo_model_is_disabled_without_explicit_opt_in(self):
  with patch('subprocess.run',side_effect=AssertionError('must not launch model')):
   for context in [{'text':'synthetic'},{'enable':True,'command':'codex exec'},{'source':'historical instruction','execute':True}]:
    with self.subTest(context=context),self.assertRaises(local_server.SecretaryValidationError):local_server.disabled_model_runner(context)
 def test_legacy_host_missing_paths_reject_before_opening_any_book(self):
  import server
  for db,source in [(None,None),(None,'synthetic.json'),('synthetic.db',None)]:
   with self.subTest(db=db,source=source),patch('server.Notebook',side_effect=AssertionError('no implicit user DB')):
    with self.assertRaises(server.ValidationError):server.make_server(db,source)
 def test_cli_default_passes_disabled_runner(self):
  class Server:
   server_port=8876
   def serve_forever(self):raise KeyboardInterrupt
   def server_close(self):pass
  with patch.dict('os.environ',{'SECRETARY_ENABLE_CODEX_EXEC':'1'}),patch('sys.argv',['local_server.py','--workspace','/tmp/synthetic-unused']),patch('local_server.make_server',return_value=Server()) as make:
   local_server.main();self.assertIs(make.call_args.kwargs['model_runner'],local_server.disabled_model_runner)
if __name__=='__main__':unittest.main()
