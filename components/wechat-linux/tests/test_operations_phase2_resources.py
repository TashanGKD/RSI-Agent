"""Isolated positive work cases; no WeChat/UI/network traffic."""
import hashlib,io,json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from operations.assets import Assets,validate_image
from operations.public_api import PublicAPI
from operations.contract import validate_job
from operations.fast import final_scene
from operations.image_draft import pixel_identity
from operations.audit import attempt_evidence

class ResourceAndReuseTests(unittest.TestCase):
 def asset(self,root,name='source.bin',data=b'actual frozen file'):
  return Assets(root).put('original-uploader',name,data,hashlib.sha256(data).hexdigest())
 def test_existing_asset_is_reusable_by_another_attribution_without_relabel(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();a=self.asset(root)
   try:b=Assets(root).get('another-employee',a['id'])
   except PermissionError as e:self.fail('Residual asset tenant wall: '+str(e))
   self.assertEqual((b['id'],b['client'],b['sha256']),(a['id'],'original-uploader',a['sha256']))
 def test_expected_existing_asset_does_not_assume_uploader_equals_submitter(self):
  with tempfile.TemporaryDirectory() as td:
   api=PublicAPI(Path(td).resolve(),{'account':'self','clients':{}})
   try:
    a=self.asset(Path(td).resolve());j={'client':'another-employee','request_id':'one','peer':'wxid_fixture_actual','action':'send_file','payload':{'asset':a['id']},'execution_mode':'verified_fast'}
    item={'job':j,'dispatch':{'expected_asset':{k:a[k] for k in ['name','bytes','sha256']}}}
    try:r=api.call({'op':'admit','client':j['client'],'batch_id':'one','items':[item]})
    except Exception as e:self.fail('Attribution-only existing material cannot be admitted: '+str(e))
    self.assertEqual(r['jobs'][0]['state'],'queued')
   finally:api.close()
 def test_fast_preview_keeps_exact_shared_asset_identity(self):
  with tempfile.TemporaryDirectory() as td:
   a=self.asset(Path(td).resolve());j={'client':'another-employee','peer':'wxid_fixture_actual','action':'send_file','execution_mode':'verified_fast','payload':{'asset':a['id']}}
   p={'senderRecipe':True,'programRecipe':True,'sha256':'a'*64,'sendWindows':[],'uiBinding':{'peer':j['peer']},'summary':{'peer':j['peer'],'action':j['action']},'asset':a,'fastVersions':{'registeredBindingSHA256':'b'*64,'bindingIdentitySHA256':'c'*64,'scopeSHA256':'d'*64}}
   try:final_scene(j,p)
   except ValueError as e:self.fail('Uploader attribution still blocks frozen asset proof: '+str(e))
   bad=dict(j,payload={'asset':'e'*64})
   with self.assertRaises(ValueError):final_scene(bad,p)
 def test_attempt_audit_preserves_original_uploader_descriptor_not_caller_wall(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();api=PublicAPI(root,{'account':'self','clients':{}})
   try:
    a=self.asset(root);j=api.s.submit({'client':'another-employee','request_id':'one','peer':'wxid_fixture_actual','action':'send_file','payload':{'asset':a['id']},'execution_mode':'verified_fast'});api.s.claim();v=api.s.preview(j['id'],{'sha256':'f'*64});api.s.confirm('another-employee','one',v['confirmation_token']);api.s.begin_execution(j['id']);api.s.set_state(j['id'],'succeeded',{'state':'accepted','serverId':'91','sendClicks':1})
    (root/(j['id']+'-attempt.json')).write_text(json.dumps({'clickScheduled':True,'peer':j['peer'],'action':'send_file','startedAt':1.0,'beforeIds':['90'],'asset':a}));(root/(j['id']+'-attempt.json')).chmod(0o600)
    proof,error=attempt_evidence(api.s,api.s.by_id(j['id']));self.assertIsNone(error,'uploader attribution must not invalidate real attempt asset');self.assertEqual(proof['asset']['client'],'original-uploader')
   finally:api.close()
 def test_upload_uses_actual_free_space_without_256MiB_extra_reserve(self):
  with tempfile.TemporaryDirectory() as td:
   with patch('operations.assets.shutil.disk_usage',return_value=types.SimpleNamespace(free=64)):
    try:a=self.asset(Path(td).resolve(),data=b'fits')
    except Exception as e:self.fail('Artificial free-space reserve blocks a fitting file: '+str(e))
   self.assertEqual(a['bytes'],4)
 def test_real_long_filename_and_metadata_json_are_valid_attachments(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve()
   for name in ['x'*200+'.bin','metadata.json']:
    with self.subTest(name=name):
     try:a=self.asset(root,name=name);b=Assets(root).get('original-uploader',a['id'])
     except Exception as e:self.fail('OS-valid actual attachment name rejected: '+str(e))
     self.assertEqual(b['name'],name);self.assertEqual(Path(b['path']).name,name);self.assertEqual(Path(b['path']).read_bytes(),b'actual frozen file')
 def test_decodable_bmp_larger_than_10MB_is_not_an_image_permission_error(self):
  out=io.BytesIO();Image.new('RGB',(3000,1200),'white').save(out,format='BMP');data=out.getvalue();self.assertGreater(len(data),10000000)
  try:validate_image(data)
  except ValueError as e:self.fail('Decodable format/bytes blocked by image quota: '+str(e))
 def test_decodable_width_over_8192_and_area_over_16MP_are_not_rejected(self):
  for size in [(8193,1),(4001,4001)]:
   with self.subTest(size=size):
    out=io.BytesIO();Image.new('RGB',size,'white').save(out,format='PNG')
    try:validate_image(out.getvalue())
    except ValueError as e:self.fail('Artificial image dimension gate: '+str(e))
 def test_actual_pixbuf_width_is_not_subject_to_8192_cap(self):
  raw=b'\0'*(9001*4);pix=types.SimpleNamespace(get_width=lambda:9001,get_height=lambda:1,get_n_channels=lambda:4,get_bits_per_sample=lambda:8,get_rowstride=lambda:9001*4,get_pixels=lambda:raw)
  try:r=pixel_identity(pix)
  except ValueError as e:self.fail('Actual frozen pixels blocked by fixed width cap: '+str(e))
  self.assertEqual(r['width'],9001)
 def test_author_text_over_20KB_is_kept_verbatim(self):
  text='原作者正文'*5000;j={'client':'author','request_id':'one','peer':'wxid_fixture_actual','action':'send_text','payload':{'text':text}}
  try:r=validate_job(j)
  except ValueError as e:self.fail('Author text rejected by fixed byte quota: '+str(e))
  self.assertEqual(r['payload']['text'],text)
 def test_wrong_asset_bytes_still_report_actual_original_identity_change(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();a=self.asset(root);Path(a['path']).write_bytes(b'different bytes')
   with self.assertRaises(ValueError):Assets(root).get('original-uploader',a['id'])

 def test_audit_accepts_large_verified_image_preparation(self):
  from operations.audit import receipt_match
  a={'id':'b'*64,'sha256':'c'*64}
  j={'action':'send_image','preview':{'imageIdentity':{'pixelFormat':'RGBA8','pixelsSHA256':'d'*64,'width':9001,'height':2000},'asset':a}}
  self.assertTrue(receipt_match(j,{'asset':a},{'kind':3}), 'Actual verified image preparation must not become unknown due to old size quota')
  j['preview']['imageIdentity']['width']=0
  self.assertFalse(receipt_match(j,{'asset':a},{'kind':3}))

if __name__=='__main__':unittest.main(verbosity=2)
