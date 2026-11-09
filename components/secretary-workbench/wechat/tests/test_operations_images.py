import unittest,io,hashlib,tempfile
from pathlib import Path
from PIL import Image,ImageDraw
from operations import images,recipes

PEER='group@chatroom';SID='42'
def records():return [dict(peer=PEER,id='41',kind=1,local=1,sender='alice',text='@示例用户\u2005请检查这个独立方案',time=1),dict(peer=PEER,id=SID,kind=3,local=2,sender='alice',meta={'md5':'a'*32,'length':200},time=2),dict(peer=PEER,id='43',kind=1,local=3,sender='alice',text='这处表格请核对修改',time=3)]
def context():return images.build_context(PEER,SID,records())
def sample():
 b=io.BytesIO();Image.new('RGB',(100,60),'white').save(b,format='PNG');return b.getvalue()
def scene(two=False,clipped=False):
 im=Image.new('RGB',(500,400),(249,249,249));d=ImageDraw.Draw(im);d.rectangle((20,100,220,200),fill='white');d.rectangle((35,120,190,135),fill='black')
 if two:d.rectangle((260,100,450,200),fill='white')
 if clipped:d.rectangle((20,55,220,120),fill='white')
 return im
class ImageContextTests(unittest.TestCase):
 def test_context_is_whitelisted_and_unique(self):
  c=context();self.assertEqual(c['sourceId'],SID);self.assertEqual(c['before']['body'],'请检查这个独立方案');self.assertNotIn('meta',c);self.assertEqual(c['sender'],'alice')
 def test_wrong_peer_source_or_non_image(self):
  for peer,sid,kind in [('other@chatroom',SID,3),(PEER,'77',3),(PEER,SID,49)]:
   r=records();r[1]['kind']=kind
   with self.assertRaises(images.ImageReadError):images.build_context(peer,sid,r)
 def test_bad_resource_id_or_wrong_context_sender(self):
  with self.assertRaises(images.ImageReadError):images.build_context(PEER,SID,records(),127,[])
  r=records();r[2]['sender']='other'
  with self.assertRaises(images.ImageReadError):images.build_context(PEER,SID,r)
 def test_multiple_images_or_duplicate_anchor_are_not_guessed(self):
  r=records();r[0]['kind']=3
  with self.assertRaises(images.ImageReadError):images.build_context(PEER,SID,r)
  r=records();r.append(dict(r[0],id='44',local=4))
  with self.assertRaises(images.ImageReadError):images.build_context(PEER,SID,r)
 def test_native_image_length_does_not_add_business_quota(self):
  r=records();r[1]['meta']['hdlength']=10000001
  self.assertEqual(images.build_context(PEER,SID,r)['sourceId'],SID)
class ImageBytesTests(unittest.TestCase):
 def test_real_png_exact_md5_and_decode(self):
  data=sample();m=images.validate_payload(data,hashlib.md5(data).hexdigest());self.assertEqual((m['width'],m['height'],m['format']),(100,60,'PNG'))
 def test_md5_mismatch_never_accepted(self):
  with self.assertRaises(images.ImageReadError):images.validate_payload(sample(),'a'*32)
 def test_cipher_with_matching_hash_is_not_an_image(self):
  data=b'wechat-v2-encrypted'+b'\x00'*400
  with self.assertRaises(images.ImageReadError):images.validate_payload(data,hashlib.md5(data).hexdigest())
 def test_invalid_bytes_rejected_and_actual_wide_image_decodes(self):
  for data in [b'x'*10000001]:
   with self.assertRaises(images.ImageReadError):images.validate_payload(data,hashlib.md5(data).hexdigest())
  b=io.BytesIO();Image.new('1',(8193,1)).save(b,format='PNG');data=b.getvalue()
  self.assertEqual(images.validate_payload(data,hashlib.md5(data).hexdigest())['width'],8193)
class VisibleImageTests(unittest.TestCase):
 def rows(self):return [{'text':'@示例用户请检查这个独立方案','point':[160,40]},{'text':'这处表格请核对修改','point':[160,260]}]
 def test_sole_complete_card_between_exact_anchors(self):
  p=images.locate_visible(scene(),[0,0,500,400],self.rows(),context());self.assertTrue(20<p[0]<220 and 100<p[1]<200)
 def test_two_cards_missing_repeated_or_reversed_anchors_rejected(self):
  for im,rows in [(scene(True),self.rows()),(scene(),self.rows()[:1]),(scene(),self.rows()+[self.rows()[0]]),(scene(),[dict(self.rows()[0],point=[160,300]),self.rows()[1]])]:
   with self.assertRaises(images.ImageReadError):images.locate_visible(im,[0,0,500,400],rows,context())
 def test_clipped_candidate_not_accepted(self):
  with self.assertRaises(images.ImageReadError):images.locate_visible(scene(clipped=True),[0,0,500,400],self.rows(),context())

class ImageExecutionTests(unittest.TestCase):
 def fixture(self,td):
  import types
  from unittest.mock import Mock
  from operations.contract import digest
  image=scene();windows=[{'id':'main','title':'Weixin'}];c=context();p={'imageRecipe':True,'context':digest(c),'imageContext':c,'imageWindows':windows,'imagePane':[0,0,500,400],'imagePaneSHA256':hashlib.sha256(image.tobytes()).hexdigest(),'imagePoint':[120,150]}
  data=sample();c['nativeMD5']=hashlib.md5(data).hexdigest();p['context']=digest(c)
  p['uiBinding']={'peer':PEER,'header_sha256':'selected-current-binding'}
  j={'id':'a'*32,'client':'test','request_id':'read','peer':PEER,'action':'save_attachment','payload':{'source_id':SID},'preview':p}
  driver=types.SimpleNamespace(root=Path(td),previews=Path(td),lease='owned',check_lease=Mock(),tool=Mock(),app_windows=Mock(return_value=windows))
  result={'peer':PEER,'serverId':SID,'senderId':'alice','messageMd5Matched':True,'contentReady':True,'content_base64':__import__('base64').b64encode(data).decode()}
  return driver,j,c,image,result
 def run_export(self,td,change=None):
  from unittest.mock import patch,Mock
  import types
  driver,j,c,image,result=self.fixture(td)
  if change:change(driver,j,c,image,result)
  adapter=types.SimpleNamespace(locked=lambda root:None,dispatch=Mock(return_value=result))
  with patch.dict('sys.modules',{'image_client':adapter}),patch('operations.images.load_context',return_value=c),patch('operations.recipes.screen',return_value=image):return images.export(driver,j),adapter
 def test_programmatic_export_returns_bytes_and_whitelisted_proof(self):
  with tempfile.TemporaryDirectory() as td:
   (data,p),adapter=self.run_export(td);self.assertEqual(data,sample());self.assertTrue(p['exportPerformedThisRequest']);self.assertFalse(p['cacheReused']);self.assertFalse(p['businessAIReadClaimed']);self.assertEqual(p['messagesSent'],0);adapter.dispatch.assert_called_once()
   bound=adapter.dispatch.call_args.kwargs['ui'];self.assertEqual(bound.config({'username':PEER})['header_sha256'],'selected-current-binding')
   with self.assertRaises(ValueError):bound.config({'username':'other@chatroom'})
 def test_wrong_source_export_receipt_is_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(images.ImageReadError):self.run_export(td,lambda d,j,c,im,r:r.update(peer='other@chatroom'))
 def test_owned_image_navigation_must_settle_before_bytes_are_returned(self):
  from unittest.mock import patch
  for settled in (True,False):
   with self.subTest(settled=settled),tempfile.TemporaryDirectory() as td,patch('operations.navigation.load',return_value={'state':'ready'}),patch('operations.navigation.finish',return_value=settled) as finish:
    if settled:
     (data,proof),_=self.run_export(td);self.assertEqual(data,sample());self.assertTrue(proof['navigationRestored'])
    else:
     with self.assertRaises(images.ImageReadError) as error:self.run_export(td)
     self.assertEqual(error.exception.code,'IMAGE_CLEANUP_UNPROVEN');self.assertFalse(error.exception.clean)
    finish.assert_called_once()
 def test_changed_pane_is_rejected_before_adapter(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(images.ImageReadError):self.run_export(td,lambda d,j,c,im,r:j['preview'].update(imagePaneSHA256='0'*64))
 def test_cleanup_uncertain_never_accepts_bytes(self):
  with tempfile.TemporaryDirectory() as td:
   def change(d,j,c,im,r):d.app_windows.side_effect=[j['preview']['imageWindows'],[{'id':'foreign'}]]
   with self.assertRaises(images.ImageReadError) as e:self.run_export(td,change)
   self.assertEqual(e.exception.code,'IMAGE_CLEANUP_UNPROVEN')
 def test_wrong_native_target_is_rejected_before_adapter(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaises(images.ImageReadError):self.run_export(td,lambda d,j,c,im,r:j.update(peer='other@chatroom'))
 def test_error_path_restores_adapter_and_rejects_failed_save(self):
  import types
  from unittest.mock import patch,Mock
  with tempfile.TemporaryDirectory() as td:
   d,j,c,im,r=self.fixture(td);locked=object();adapter=types.SimpleNamespace(locked=locked,dispatch=Mock(side_effect=ValueError('do not expose raw XML here')))
   with patch.dict('sys.modules',{'image_client':adapter}),patch('operations.images.load_context',return_value=c),patch('operations.recipes.screen',return_value=im):
    with self.assertRaises(images.ImageReadError) as e:images.export(d,j)
   self.assertIs(adapter.locked,locked);self.assertNotIn('raw XML',str(e.exception));self.assertEqual(e.exception.code,'IMAGE_EXPORT_NOT_PROVEN')

class ImageRoutingTests(unittest.TestCase):
 def test_uncached_image_in_native_only_group_uses_proven_session_binding(self):
  import os,types
  from unittest.mock import Mock,patch
  from operations import navigation
  if not hasattr(os,'getuid'):self.skipTest('private navigation journal requires Linux')
  with tempfile.TemporaryDirectory() as td:
   main=dict(id='0x10',title='Weixin',x=0,y=0,width=905,height=667)
   chat=dict(id='0x20',title='Fixture group',x=0,y=0,width=623,height=667)
   identity=dict(pid=123,leader='0x1',**{'class':['wechat','wechat']})
   registry=dict(peer=PEER,displayName=chat['title'],paired_account='self')
   c=images.build_context(PEER,SID,records(),inbound=True)
   image=Image.new('RGB',(905,667),(249,249,249));ImageDraw.Draw(image).rectangle((100,200,350,400),fill='white')
   j=dict(id='b'*32,client='test',request_id='native-only-image',peer=PEER,action='save_attachment',payload={'source_id':SID,'source_mode':'inbound'})
   d=types.SimpleNamespace(root=Path(td),fds=[1],active_window=None,session_bindings={},fast_versions=Mock(),name_peer=lambda name:PEER)
   d.tool=lambda:types.SimpleNamespace(resolve=lambda peer:dict(username=peer,displayName=chat['title']))
   d.app_windows=lambda:[main,chat] if d.active_window else [main]
   d.binding=lambda peer:d.session_bindings.get(peer,registry)
   d._select=lambda job:recipes.selected(d,job)
   d.screenshot=lambda job:{}
   def native_search(driver,job,target,cfg,query):
    self.assertEqual(navigation.load(driver.root,job)['state'],'started')
    self.assertEqual(query,chat['title'])
    driver.active_window=chat
    driver.session_bindings[PEER]=dict(cfg,header_box=[1,35,622,82],editor=[280,554],send=[573,635],nativeTargetProof={'peer':PEER})
   with patch.dict('sys.modules',{'sender':types.SimpleNamespace(validate_binding=Mock(side_effect=AssertionError('static calibration must not be used')))}),patch('operations.image_verified.prepare',return_value=None),patch('operations.images.load_context',return_value=c),patch('operations.recipes.controls',return_value=Mock()),patch('operations.recipes.activate'),patch('operations.windows.window_identity',return_value=identity),patch('operations.lease.birth',return_value='fixture-birth'),patch('operations.recipes.main_window',side_effect=lambda driver:driver.active_window or main),patch('operations.recipes.screen',return_value=image),patch('operations.recipes.rows',return_value=[]),patch('operations.navigation.search_named',side_effect=native_search):
    result=images.prepare(d,j)
   self.assertTrue(result['imageRecipe']);self.assertEqual(result['imageContext'],c)
   self.assertEqual(result['uiBinding']['nativeTargetProof']['peer'],PEER)
   self.assertEqual(result['imagePoint'],[225,300]);self.assertNotIn('header_box',registry)
 def test_existing_save_attachment_routes_images_to_internal_program(self):
  import types
  from unittest.mock import patch
  d=types.SimpleNamespace(_native_source=lambda j:{'kind':3});j={'action':'save_attachment','peer':PEER,'payload':{'source_id':SID}}
  with patch('operations.images.prepare',return_value={'imageRecipe':True}) as program:
   try:value=recipes.prepare(d,j)
   except Exception as e:value={'rejected':getattr(e,'code',type(e).__name__)}
  self.assertEqual(value,{'imageRecipe':True});program.assert_called_once()
 def test_raw_metadata_authorization_fields_are_never_returned(self):
  r=records();r[1]['meta'].update(aeskey='private',cdnmidimgurl='private');c=images.build_context(PEER,SID,r)
  text=__import__('json').dumps(c);self.assertNotIn('aeskey',text);self.assertNotIn('cdnmidimgurl',text)
 def test_unknown_native_sender_is_not_proven_by_two_missing_names(self):
  r=records()
  for v in r:v['sender']=None
  with self.assertRaises(images.ImageReadError):images.build_context(PEER,SID,r)

class AdditionalFormatTests(unittest.TestCase):
 def test_actual_jpeg_and_gif_source_bytes_decode_with_exact_format(self):
  for fmt in ('JPEG','GIF'):
   b=io.BytesIO();Image.new('RGB',(50,40),'white').save(b,format=fmt);data=b.getvalue()
   self.assertEqual(images.validate_payload(data,hashlib.md5(data).hexdigest())['format'],fmt)
