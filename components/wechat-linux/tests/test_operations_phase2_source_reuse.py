"""Actual source tuples/bytes remain exact while employee attribution is shared."""
import copy,hashlib,io,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from operations import image_verified as v
from operations.assets import Assets
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
class SourceReuseTests(unittest.TestCase):
 def context(self,client='producer'):
  return dict(account='self',client=client,peer='10000000042@chatroom',sourceId='42',localId=268,time=1700000000,sender='wxid_fixture_owner',nativeMD5='1'*32,nativeLength=999,resourceId=17)
 def fixture(self,root):
  out=io.BytesIO();Image.new('RGB',(2,3),'red').save(out,format='PNG');raw=out.getvalue();a=Assets(root).put('producer','visible.png',raw,hashlib.sha256(raw).hexdigest());c=self.context();r=dict(version=1,source=c,asset={k:a[k] for k in v.ASSET_FIELDS},officialFilename='Weixin Image_20231115061320_268_56.png',officialGroupVerified=True,sourceFilenameVerified=True,reviewMethod='official-save-as-native-time-and-local-id',captureComplete=True,format='PNG',width=2,height=3);j=dict(id='b'*32,client='consumer',peer=c['peer'],payload=dict(source_id='42',resource_id=17,representation='visible'));p=v.receipt_path(root,dict(j,client='producer'));p.parent.mkdir(mode=0o700);p.write_text(json.dumps(r));p.chmod(0o600);return raw,a,c,r,j,p
 def test_original_producer_receipt_is_reused_by_other_employee_without_relabel(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();raw,a,c,r,j,p=self.fixture(root);(root/'previews').mkdir();d=types.SimpleNamespace(root=root,assets=Assets(root),previews=root/'previews',policy=types.SimpleNamespace(cfg={'account':'self'}))
   with patch.object(v,'native_context',return_value=self.context('consumer')):got=v.qualified(d,j)
   self.assertIsNotNone(got,'existing positive source proof is hidden behind producer-client key');self.assertEqual(got[2],raw);self.assertEqual(json.loads(p.read_text())['source']['client'],'producer');self.assertEqual(d.assets.get('consumer',a['id'])['id'],a['id'])
 def test_only_attribution_is_excluded_from_exact_source_tuple(self):
  with tempfile.TemporaryDirectory() as td:
   raw,a,c,r,j,p=self.fixture(Path(td).resolve());ctx=self.context('consumer');self.assertTrue(v.validate_receipt(ctx,r,a,'visible')['sourceContextVerified'])
   for k in set(c)-{'client'}:
    changed=copy.deepcopy(r);changed['source'][k]=c[k]+1 if isinstance(c[k],int) else c[k]+'x'
    with self.subTest(field=k),self.assertRaises(ValueError):v.validate_receipt(ctx,changed,a,'visible')
 def test_two_conflicting_source_representations_are_not_silently_selected(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();raw,a,c,r,j,p=self.fixture(root);q=v.receipt_path(root,dict(j,client='second'));second=copy.deepcopy(r);second['source']['client']='second';second['asset']['sha256']='0'*64;q.write_text(json.dumps(second));q.chmod(0o600)
   with self.assertRaises(ValueError):v.read_receipt(root,j)
 def test_prepared_receipt_selection_remains_frozen_after_equivalent_earlier_proof_added(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();raw,a,c,r,j,p=self.fixture(root);(root/'previews').mkdir();d=types.SimpleNamespace(root=root,assets=Assets(root),previews=root/'previews',policy=types.SimpleNamespace(cfg={'account':'self'}))
   with patch.object(v,'native_context',return_value=self.context('consumer')):
    j['preview']=v.prepare(d,j)
    # Search for a stable other producer key before the original key.
    for i in range(100):
     other=v.receipt_path(root,dict(j,client='second'+str(i)))
     if other.name<p.name:break
    self.assertLess(other.name,p.name);cloned=copy.deepcopy(r);cloned['source']['client']='second'+str(i);other.write_text(json.dumps(cloned));other.chmod(0o600)
    got,proof=v.export(d,j);self.assertEqual(got,raw);self.assertEqual(proof['sourceId'],'42')
 def test_actual_bmp_saved_bytes_are_not_returned_with_jpeg_extension(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();raw,a,c,r,j,p=self.fixture(root);stream=io.BytesIO();Image.new('RGB',(2,3),'red').save(stream,format='BMP');raw=stream.getvalue();a=Assets(root).put('producer','visible.bmp',raw,hashlib.sha256(raw).hexdigest());r.update(format='BMP',officialFilename='Weixin Image_20231115061320_268_56.bmp');r['asset']={k:a[k] for k in v.ASSET_FIELDS};p.write_text(json.dumps(r));(root/'previews').mkdir();d=types.SimpleNamespace(root=root,assets=Assets(root),previews=root/'previews',policy=types.SimpleNamespace(cfg={'account':'self'}))
   with patch.object(v,'native_context',return_value=self.context('consumer')):j['preview']=v.prepare(d,j);got,proof=v.export(d,j)
   self.assertEqual(got,raw);self.assertTrue(proof['name'].endswith('.bmp'),proof['name'])
 def test_native_attachment_reader_does_not_apply_two_megabyte_business_quota(self):
  from attachments import read_bound
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();p=root/'actual.bin';raw=b'x'*2000001;p.write_bytes(raw);self.assertEqual(read_bound(root,p),raw)
 def test_decodable_native_md5_image_over_16mp_is_actual_resource_not_permission(self):
  from image_client import verify_export
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();p=root/'actual.png';Image.new('RGB',(4001,4001),'white').save(p,format='PNG');data=p.read_bytes();got,proof=verify_export(p,hashlib.md5(data).hexdigest(),root);self.assertEqual(got,data);self.assertEqual(proof['width'],4001)
if __name__=='__main__':unittest.main(verbosity=2)
