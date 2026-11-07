import importlib.util,unittest,tempfile,base64,hashlib
from pathlib import Path
spec=importlib.util.spec_from_file_location('wcclient',str(__import__('pathlib').Path(__file__).resolve().parents[2]/'host/tools/wechat_linux.py'));client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
class ClientTests(unittest.TestCase):
    def test_duplicate_json_keys_rejected_before_ssh(self):
        with self.assertRaises(ValueError):client.load_request('{"action":"sessions","action":"send_text"}')
    def test_only_fixed_ssh_command_and_stdin(self):
        seen={}
        class Result:returncode=0;stdout='{"state":"ok"}'
        def run(cmd,**kw):seen.update(cmd=cmd,**kw);return Result()
        text='$(touch /tmp/bad)'
        client.call({'action':'send_text','text':text},run)
        self.assertNotIn(text,' '.join(seen['cmd']));self.assertIn(text,seen['input']);self.assertNotIn('shell',seen)
    def test_media_hash_and_symlink_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td).resolve();(p/'saved').write_bytes(b'keep');(p/'link').symlink_to(p/'saved')
            r={'audio_base64':base64.b64encode(b'hello').decode(),'sha256':hashlib.sha256(b'hello').hexdigest()}
            with self.assertRaises(ValueError):client.save_media(r,p/'link')
            self.assertEqual((p/'saved').read_bytes(),b'keep')
            with self.assertRaises(ValueError):client.save_media({**r,'sha256':'0'*64},p/'new')
            self.assertFalse((p/'new').exists())

