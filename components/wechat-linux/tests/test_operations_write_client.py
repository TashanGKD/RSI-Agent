import unittest,tempfile,sys,importlib.util,hashlib,base64
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('write_client',str(__import__('pathlib').Path(__file__).resolve().parents[3]/'archive/secretary-workbench/host/tools/wechat_operations.py'));client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
class ClientTests(unittest.TestCase):
 def test_upload_file_validates_and_transmits_bytes_without_model(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td).resolve()/'a.txt';p.write_bytes(b'owned bytes')
   with patch.object(client,'call',side_effect=lambda r:r) as call:
    v=client.upload_file('secretary',str(p));self.assertEqual(v['op'],'upload');self.assertEqual(base64.b64decode(v['data']),b'owned bytes');self.assertEqual(v['sha256'],hashlib.sha256(b'owned bytes').hexdigest())
 def test_readable_symlink_uploads_exact_fixture_bytes(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();original=root/'owned.txt';original.write_bytes(b'owned bytes');p=root/'link';p.symlink_to(original)
   with patch.object(client,'call',side_effect=lambda r:r) as call:
    result=client.upload_file('secretary',str(p));self.assertEqual(base64.b64decode(result['data']),b'owned bytes');call.assert_called_once()
 def test_new_error_envelope_is_preserved(self):
  import subprocess,json
  r=subprocess.CompletedProcess([],2,json.dumps({'state':'error','error':{'code':'AMBIGUOUS_RECIPIENT','message':'Choose one','details':{'candidates':[{'peer':'x'}]}}}),'')
  with patch.object(client.subprocess,'run',return_value=r):
   with self.assertRaises(client.ToolError) as e:client.call({'op':'resolve','client':'secretary','query':'same'})
  self.assertEqual(e.exception.code,'AMBIGUOUS_RECIPIENT');self.assertEqual(len(e.exception.details['candidates']),1)
 def test_saved_preview_is_verified_and_not_overwritten(self):
  data=b'preview';v={'data':base64.b64encode(data).decode(),'sha256':hashlib.sha256(data).hexdigest(),'mime':'image/png'}
  with tempfile.TemporaryDirectory() as td:
   p=Path(td).resolve()/'preview.png';result=client.save_output(v,str(p));self.assertEqual(p.read_bytes(),data);self.assertNotIn('data',result)
   with self.assertRaises(FileExistsError):client.save_output(v,str(p))
 def test_bad_preview_hash_leaves_no_file(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td).resolve()/'preview.png'
   with self.assertRaises(ValueError):client.save_output({'data':base64.b64encode(b'fake').decode(),'sha256':'0'*64},str(p))
   self.assertFalse(p.exists())
