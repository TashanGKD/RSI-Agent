"""Owner bulk asset transport/identity cases; isolated files and subprocess stub."""
import base64,hashlib,importlib.util,json,os,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from operations.api import API
from operations.assets import Assets
from operations.contract import parse_request
HERE=Path(__file__).resolve().parent
class ResourceTransportTests(unittest.TestCase):
 def mac(self):
  spec=importlib.util.spec_from_file_location('wrapper',HERE.parents[2]/'archive/secretary-workbench/host/tools/wechat_operations.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_actual_asset_over_inline_budget_remains_downloadable_without_new_id(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();a=API(root,{'account':'self','clients':{}});self.addCleanup(a.close);raw=b'x'*11000000;x=a.assets.put('uploader','payload.bin',raw,hashlib.sha256(raw).hexdigest());r=a.call({'op':'download','client':'reader','asset':x['id']});self.assertEqual(base64.b64decode(r['data']),raw);self.assertEqual(r['id'],x['id']);self.assertEqual(r['client'],'uploader')
 def test_json_transport_is_not_a_hidden_15MB_asset_ceiling(self):
  text='x'*15000001;raw=json.dumps({'data':text});self.assertEqual(parse_request(raw)['data'],text)
 def test_mac_control_transport_can_return_actual_large_asset_response(self):
  m=self.mac();raw=json.dumps({'data':'x'*15000001});response=types.SimpleNamespace(stdout=raw,stderr='',returncode=0)
  with patch.object(m.subprocess,'run',return_value=response):r=m.call({'op':'download','client':'reader','asset':'a'*64})
  self.assertEqual(len(r['data']),15000001)
 def test_mac_operations_stdin_ingestion_keeps_full_actual_request(self):
  import sys,io
  m=self.mac();raw=json.dumps({'op':'upload','client':'reader','name':'x','data':'A'*15000001,'sha256':'a'*64});seen=[]
  with patch.object(sys,'argv',['wrapper','--execute','--request-file','-']),patch.object(sys,'stdin',io.StringIO(raw)),patch.object(m,'call',side_effect=lambda r:seen.append(r) or {'state':'ok'}),patch('builtins.print'):m.main()
  self.assertEqual(len(seen[0]['data']),15000001)
 def test_mac_native_output_can_use_actual_relative_parent_alias(self):
  import io,sys
  spec=importlib.util.spec_from_file_location('native_wrapper',HERE.parents[2]/'archive/secretary-workbench/host/tools/wechat_linux.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();(root/'real').mkdir();(root/'alias').symlink_to(root/'real',target_is_directory=True);old=Path.cwd();os.chdir(root)
   try:
    raw=b'actual';r={'content_base64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()};m.save_media(r,'alias/output.bin');self.assertEqual((root/'real/output.bin').read_bytes(),raw)
   finally:os.chdir(old)
 def test_metadata_filename_works_with_explicit_test_quota_accounting(self):
  import operations.assets as module
  with tempfile.TemporaryDirectory() as td,patch.object(module,'TOTAL_BYTES',100000):
   root=Path(td).resolve();a=Assets(root);x=a.put('uploader','metadata.json',b'actual',hashlib.sha256(b'actual').hexdigest());y=a.put('uploader','next.bin',b'next',hashlib.sha256(b'next').hexdigest());self.assertEqual(a.get('reader',x['id'])['bytes'],6);self.assertEqual(y['bytes'],4)
 def test_metadata_payload_parent_symlink_still_rejects_even_matching_bytes(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();a=Assets(root);raw=b'actual';x=a.put('uploader','metadata.json',raw,hashlib.sha256(raw).hexdigest());parent=Path(x['path']).parent;parent.rename(parent.with_name('original'));parent.symlink_to(parent.with_name('original'),target_is_directory=True)
   with self.assertRaises(ValueError):a.get('reader',x['id'])
if __name__=='__main__':unittest.main(verbosity=2)
