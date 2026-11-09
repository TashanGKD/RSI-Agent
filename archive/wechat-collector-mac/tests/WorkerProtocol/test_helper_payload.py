"""Generated-only payload invariants: sealed bytes, no replacement, no wire paths."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/MacWorker/foundation'))
try:
    import helper_payload as payload
except ImportError:
    payload = None

class Payload(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(payload, 'sealed payload implementation required')
        self.tmp = tempfile.TemporaryDirectory(dir='/private/tmp', prefix='wechat-c8-payload-')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        (self.home / 'Library/Application Support').mkdir(parents=True)
        self.raw = b'generated opaque executable bytes\x00\xff'
        self.value = dict(v=1, sha256=hashlib.sha256(self.raw).hexdigest(), bytes=len(self.raw), image=base64.b64encode(self.raw).decode())
    def seal(self, **changes):
        return json.dumps(dict(self.value, **changes)).encode()
    def test_reject_duplicate_unknown_deep_and_bad_hash_before_publication(self):
        for raw in (b'{"v":1,"v":1}', self.seal(extra='secret'), self.seal(image='[['), self.seal(bytes=True), self.seal(sha256='0'*64), b'{"v":'+b'['*10+b'0'+b']'*10+b'}'):
            with self.subTest(raw=raw[:30]), self.assertRaises(payload.PayloadError):
                payload.materialize(_sealed=raw, _home=str(self.home))
        self.assertFalse((self.home/'Library/Application Support/WechatCollectorMac').exists())
    def test_identical_reuse_and_corrupt_existing_preserved(self):
        path = Path(payload.materialize(_sealed=self.seal(), _home=str(self.home)))
        before = path.stat()
        self.assertEqual(self.raw, path.read_bytes())
        self.assertEqual(0o500, stat.S_IMODE(before.st_mode))
        self.assertEqual(str(path), payload.materialize(_sealed=self.seal(), _home=str(self.home)))
        self.assertEqual(before.st_ino, path.stat().st_ino)
        os.chmod(path, 0o700); path.write_bytes(b'corrupt'); os.chmod(path, 0o500)
        corrupt = path.read_bytes(); inode = path.stat().st_ino
        with self.assertRaises(payload.PayloadError): payload.materialize(_sealed=self.seal(), _home=str(self.home))
        self.assertEqual((corrupt,inode), (path.read_bytes(),path.stat().st_ino))
    def test_link_and_unsafe_cache_refused_without_parent_chmod(self):
        base=self.home/'Library/Application Support'; original=base.stat().st_mode
        app=base/'WechatCollectorMac'; app.mkdir(mode=0o755)
        with self.assertRaises(payload.PayloadError): payload.materialize(_sealed=self.seal(), _home=str(self.home))
        self.assertEqual(0o755, stat.S_IMODE(app.stat().st_mode)); self.assertEqual(original,base.stat().st_mode)
        app.rmdir(); app.symlink_to(base,target_is_directory=True)
        with self.assertRaises(payload.PayloadError): payload.materialize(_sealed=self.seal(), _home=str(self.home))
    def test_raw_and_encoded_limits_and_strict_base64(self):
        for raw in (b' '* (48*1024*1024+1), self.seal(bytes=32*1024*1024+1), self.seal(image=self.value['image']+'\n'), self.seal(v=True)):
            with self.assertRaises(payload.PayloadError): payload.decode(raw)


    def test_existing_helper_hardlink_acl_and_replacement_refused(self):
        from unittest import mock
        import connection
        path=Path(payload.materialize(_sealed=self.seal(),_home=str(self.home)))
        before=(path.stat().st_ino,path.read_bytes())
        linked=Path(self.tmp.name)/'generated-hardlink';os.link(path,linked)
        with self.assertRaises(payload.PayloadError):payload.materialize(_sealed=self.seal(),_home=str(self.home))
        self.assertEqual(before,(path.stat().st_ino,path.read_bytes()));linked.unlink()
        subprocess.run(['/bin/chmod','+a','everyone allow read',str(path)],check=True,capture_output=True)
        try:
            with self.assertRaises(payload.PayloadError):payload.materialize(_sealed=self.seal(),_home=str(self.home))
            self.assertEqual(before,(path.stat().st_ino,path.read_bytes()))
        finally:subprocess.run(['/bin/chmod','-N',str(path)],check=True)
        original=connection._no_acl;swapped=[];moved=path.parent/'generated-original-helper'
        def gate(fd):
            original(fd)
            if os.fstat(fd).st_ino==before[0] and not swapped:
                swapped.append(True);path.rename(moved);path.write_bytes(self.raw);path.chmod(0o500)
        with mock.patch.object(connection,'_no_acl',gate),self.assertRaises(payload.PayloadError):payload.materialize(_sealed=self.seal(),_home=str(self.home))
        self.assertEqual(before,(moved.stat().st_ino,moved.read_bytes()))
        self.assertNotEqual(before[0],path.stat().st_ino)

    def test_os_home_anchor_deny_delete_acl_does_not_block_private_code_leaf(self):
        subprocess.run(['/bin/chmod','+a','everyone deny delete',str(self.home/'Library/Application Support')],check=True,capture_output=True)
        try:
            path=Path(payload.materialize(_sealed=self.seal(),_home=str(self.home)))
            self.assertEqual(self.raw,path.read_bytes());self.assertEqual(0o500,stat.S_IMODE(path.stat().st_mode))
        finally:subprocess.run(['/bin/chmod','-N',str(self.home/'Library/Application Support')],check=True)

class Packaging(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[2]
        self.tmp=tempfile.TemporaryDirectory(dir='/private/tmp',prefix='wechat-c8-packer-');self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
    def call(self,name,*args):
        return subprocess.run([sys.executable,str(self.root/'scripts'/name),*map(str,args)],cwd=self.directory,capture_output=True,timeout=8)
    def test_noargs_and_help_are_no_mutation(self):
        runtime=self.root/'.runtime';before=set(runtime.iterdir())
        for script in ('pack-oneshot-helper.py','build-worker.py'):
            self.assertNotEqual(0,self.call(script).returncode)
            self.assertEqual(0,self.call(script,'--help').returncode)
            self.assertEqual([],list(self.directory.iterdir()))
        self.assertEqual(before,set(runtime.iterdir()))
    def test_pack_explicit_input_output_and_reject_links_same_nonregular(self):
        binary=self.directory/'accepted';binary.write_bytes(b'generated\x00opaque')
        output=self.directory/'sealed'
        result=self.call('pack-oneshot-helper.py','--accepted-helper',binary,'--output',output)
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual(binary.read_bytes(),payload.decode(output.read_bytes())[1])
        before=(output.stat().st_ino,output.read_bytes())
        self.assertNotEqual(0,self.call('pack-oneshot-helper.py','--accepted-helper',binary,'--output',output).returncode)
        self.assertEqual(before,(output.stat().st_ino,output.read_bytes()))
        linked=self.directory/'link';linked.symlink_to(binary)
        for source,target in ((binary,binary),(linked,self.directory/'new'),(self.directory,self.directory/'new')):
            self.assertNotEqual(0,self.call('pack-oneshot-helper.py','--accepted-helper',source,'--output',target).returncode)
        self.assertFalse((self.directory/'new').exists())

if __name__=='__main__':unittest.main()
