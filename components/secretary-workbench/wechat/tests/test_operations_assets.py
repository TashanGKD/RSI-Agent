import tempfile,unittest,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.assets import Assets
class AssetTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name).resolve()/'private';self.root.mkdir(mode=0o700);self.a=Assets(self.root)
 def tearDown(self):self.t.cleanup()
 def test_bad_name(self):
  with self.assertRaises(ValueError):self.a.put('alice','../../password',b'a',hashlib.sha256(b'a').hexdigest())
 def test_bad_hash_leaves_no_partial(self):
  with self.assertRaises(ValueError):self.a.put('alice','a.txt',b'a','0'*64)
  self.assertEqual(list(self.a.root.iterdir()),[])
 def test_asset_keeps_original_client_provenance(self):
  x=self.a.put('alice','中文.txt',b'abc',hashlib.sha256(b'abc').hexdigest());self.assertEqual(self.a.get('alice',x['id'])['name'],'中文.txt')
  r=self.a.get('bob',x['id']);self.assertEqual(r['client'],'alice');self.assertEqual(r['id'],x['id'])
 def test_symlink_asset_refused(self):
  x=self.a.put('alice','a.txt',b'abc',hashlib.sha256(b'abc').hexdigest());p=Path(self.a.get('alice',x['id'])['path']);p.unlink();p.symlink_to('/etc/passwd')
  with self.assertRaises(ValueError):self.a.get('alice',x['id'])
 def test_reuse_and_changed_bytes(self):
  sha=hashlib.sha256(b'abc').hexdigest();x=self.a.put('alice','a.txt',b'abc',sha);self.assertEqual(x['id'],self.a.put('alice','a.txt',b'abc',sha)['id'])
  p=Path(self.a.get('alice',x['id'])['path']);p.write_bytes(b'changed')
  with self.assertRaises(ValueError):self.a.get('alice',x['id'])

class ImageBudgets(unittest.TestCase):
 def test_header_budget_precedes_decode(self):
  import io,struct,zlib
  from PIL import Image
  from operations.assets import validate_image
  b=io.BytesIO();Image.new('RGB',(2,2),'white').save(b,format='PNG');data=bytearray(b.getvalue());data[16:24]=struct.pack('>II',5000,5000);data[29:33]=struct.pack('>I',zlib.crc32(data[12:29])&0xffffffff)
  with self.assertRaises(ValueError):validate_image(bytes(data))
 def test_arbitrary_file_not_decoded_as_image(self):
  from operations.assets import validate_image
  with self.assertRaises(ValueError):validate_image(b'not an image')
