"""Owner bulk asset transport/identity cases; isolated files and subprocess stub."""
import base64,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from operations.api import API
from operations.assets import Assets
from operations.contract import parse_request
class ResourceTransportTests(unittest.TestCase):
 def test_actual_asset_over_inline_budget_remains_downloadable_without_new_id(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();a=API(root,{'account':'self','clients':{}});self.addCleanup(a.close);raw=b'x'*11000000;x=a.assets.put('uploader','payload.bin',raw,hashlib.sha256(raw).hexdigest());r=a.call({'op':'download','client':'reader','asset':x['id']});self.assertEqual(base64.b64decode(r['data']),raw);self.assertEqual(r['id'],x['id']);self.assertEqual(r['client'],'uploader')
 def test_json_transport_is_not_a_hidden_15MB_asset_ceiling(self):
  text='x'*15000001;raw=json.dumps({'data':text});self.assertEqual(parse_request(raw)['data'],text)
 def test_metadata_filename_works_with_explicit_test_quota_accounting(self):
  import operations.assets as module
  with tempfile.TemporaryDirectory() as td,patch.object(module,'TOTAL_BYTES',100000):
   root=Path(td).resolve();a=Assets(root);x=a.put('uploader','metadata.json',b'actual',hashlib.sha256(b'actual').hexdigest());y=a.put('uploader','next.bin',b'next',hashlib.sha256(b'next').hexdigest());self.assertEqual(a.get('reader',x['id'])['bytes'],6);self.assertEqual(y['bytes'],4)
 def test_metadata_payload_parent_symlink_still_rejects_even_matching_bytes(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();a=Assets(root);raw=b'actual';x=a.put('uploader','metadata.json',raw,hashlib.sha256(raw).hexdigest());parent=Path(x['path']).parent;parent.rename(parent.with_name('original'));parent.symlink_to(parent.with_name('original'),target_is_directory=True)
   with self.assertRaises(ValueError):a.get('reader',x['id'])
if __name__=='__main__':unittest.main(verbosity=2)
