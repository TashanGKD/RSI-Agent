"""Unified normal send, never mutate another actor's rich draft or replay a click."""
import unittest,tempfile,io,hashlib
from pathlib import Path
from PIL import Image,ImageDraw
from operations import composer,sending
class ImagePreparationTests(unittest.TestCase):
 def test_animated_asset_is_rejected_before_opening_chat(self):
  from unittest.mock import Mock,patch
  from operations.driver import NativeDriver
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'animated.gif'
   Image.new('RGB',(16,16),'red').save(path,save_all=True,
      append_images=[Image.new('RGB',(16,16),'green')],duration=[120,180],loop=0)
   driver=Mock()
   driver.root=Path(td)
   driver.prepare_basic.side_effect=lambda request:sending.prepare(driver,request)
   driver._select.side_effect=AssertionError('Animated input reached chat navigation')
   driver.assets.get.return_value={'path':str(path),'bytes':path.stat().st_size}
   request={'id':'b'*32,'action':'send_image','client':'fixture','peer':'fixture','payload':{'asset':'a'*64}}
   with patch('operations.navigation.begin') as begin:
    with self.assertRaises(sending.PreparationError) as result:NativeDriver.prepare(driver,request)
    self.assertEqual(result.exception.code,'ANIMATED_IMAGE_UNSUPPORTED')
    self.assertTrue(result.exception.clean)
    self.assertTrue(NativeDriver.cleanup(driver,request))
    path.write_bytes(b'invalid image')
    with self.assertRaises(sending.PreparationError) as invalid:NativeDriver.prepare(driver,request)
    self.assertTrue(invalid.exception.clean)
    self.assertTrue(NativeDriver.cleanup(driver,request))
    begin.assert_not_called()
    driver._select.assert_not_called()
    driver.ui.assert_not_called()
    Image.new('RGB',(16,16),'red').save(path)
    driver.assets.get.return_value['bytes']=path.stat().st_size
    with self.assertRaisesRegex(AssertionError,'Animated input reached chat navigation'):
     NativeDriver.prepare(driver,request)
    begin.assert_called_once_with(driver,request)
    driver._select.assert_called_once_with(request)

class DraftTests(unittest.TestCase):
 def test_only_losslessly_plain_text_can_be_parked(self):
  composer.validate_plain('保留的草稿',{'text/plain'},'',False,False)
  for text,mime,html,card,quote in [('@成员 真提及',{'text/plain'},'',False,False),('file.txt',{'text/uri-list'},'',False,False),('a',{'text/html'},'<img src="private">',False,False),('a',{'text/plain'},'',True,False),('a',{'text/plain'},'',False,True)]:
   with self.assertRaises(composer.DraftProtected):composer.validate_plain(text,mime,html,card,quote)
 def test_journal_restore_exactly_once_and_no_plaintext_after_success(self):
  with tempfile.TemporaryDirectory() as td:
   j={'id':'a'*32,'peer':'wxid_fixture_1987fcaa9f','action':'send_text','payload':{'text':'new'}};composer.save(Path(td),j,{'priorText':'old\n中文','priorSHA':hashlib.sha256('old\n中文'.encode()).hexdigest(),'state':'parked'})
   class U:
    text='';calls=0
    def draft(self):return self.text
    def stage(self,text,prior):self.text=text;self.calls+=1
   u=U();self.assertTrue(composer.restore(Path(td),j,u,lambda:None));self.assertEqual(u.text,'old\n中文');self.assertTrue(composer.restore(Path(td),j,u,lambda:None));self.assertEqual(u.calls,1);self.assertIsNone(composer.load(Path(td),j)['priorText'])
 def test_new_foreign_text_never_overwritten_when_restoring(self):
  with tempfile.TemporaryDirectory() as td:
   j={'id':'a'*32,'peer':'x','action':'send_text','payload':{'text':'new'}};composer.save(Path(td),j,{'priorText':'old','state':'parked'})
   class U:
    def draft(self):return 'someone else'
    def stage(self,*a):raise AssertionError('must not replace foreign draft')
   self.assertFalse(composer.restore(Path(td),j,U(),lambda:None));self.assertEqual(composer.load(Path(td),j)['priorText'],'old')
class ButtonTests(unittest.TestCase):
 def button(self,enabled=True):
  im=Image.new('RGB',(300,200),'white');ImageDraw.Draw(im).rounded_rectangle((180,150,280,181),radius=5,fill=(7,193,96) if enabled else (230,230,230));return im
 def test_exact_enabled_send_region_required(self):
  self.assertEqual(sending.send_button(self.button(),[230,165]),[230,165])
  with self.assertRaises(ValueError):sending.send_button(self.button(False),[230,165])
 def test_two_green_controls_not_first_selected(self):
  im=self.button();ImageDraw.Draw(im).rectangle((165,125,190,147),fill=(7,193,96))
  with self.assertRaises(ValueError):sending.send_button(im,[230,165])
 def test_plain_wechat_text_exposes_standard_rich_format_markers(self):
  composer.validate_plain('普通文字\n第二行',{'text/plain','WeChat_RichEdit_Format','QQ_Unicode_RichEdit_Format','x-application-mimetype-xwechat'},'',False,False)
  with self.assertRaises(composer.DraftProtected):composer.validate_plain('内嵌对象\ufffc',{'text/plain'},'',False,False)
 def test_public_normal_send_preview_excludes_sidebar(self):
  import types
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as td:
   im=Image.new('RGB',(300,200),'red');ImageDraw.Draw(im).rectangle((100,0,299,199),fill='blue');d=types.SimpleNamespace(previews=Path(td));u=types.SimpleNamespace(cfg={'header_box':[100,20,300,40]})
   with patch('operations.recipes.screen',return_value=im):p=sending.preview(d,{'id':'a'*32},u,{'x':0,'y':0,'width':300,'height':200})
   with Image.open(Path(td)/('a'*32+'.png')) as out:self.assertEqual(out.size,(200,165));self.assertEqual(set(out.convert('RGB').getdata()),{(0,0,255)})
   self.assertTrue(p['targetChatOnly'])
 def test_nontext_editor_is_protected_before_creating_journal(self):
  import types
  with tempfile.TemporaryDirectory() as td:
   class U:
    def draft(self):return ''
   class F:
    def require_empty_editor(self,u):raise ValueError('media draft')
   d=types.SimpleNamespace(root=Path(td),_file_helper=lambda:F());j={'id':'a'*32,'peer':'x','action':'send_text','payload':{'text':'x'}}
   with self.assertRaises(composer.DraftProtected):composer.park(d,j,U(),{})
   self.assertIsNone(composer.load(Path(td),j))
 def test_attachment_cancel_unselects_card_before_identity_hash(self):
  import types
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);j={'id':'a'*32,'peer':'x','action':'send_file','payload':{'asset':'b'*64},'preview':{}}
   original=Image.new('RGB',(100,100),'white');ImageDraw.Draw(original).rectangle((0,0,20,20),fill='blue');changed=original.copy();ImageDraw.Draw(changed).rectangle((0,0,20,20),fill='green')
   class U:
    cfg={'header_box':[0,0,100,10],'editor':[10,50]};selected=False;cleared=False
    def draft(self):self.selected=True;return ''
    def click(self,p):
     if p[0]>20:self.selected=False
    def settle(self,n):pass
    def close(self):pass
   u=U();u.ui=types.SimpleNamespace(screenshot=lambda:changed if u.selected else original)
   p={'attachmentBox':[0,0,21,21],'attachmentContext':hashlib.sha256(original.crop((0,0,21,21)).tobytes()).hexdigest()};composer.save(root,j,{'state':'staged','preview':p,'priorText':'','binding':u.cfg,'window':{}})
   def empty(ui):
    if not ui.cleared:raise ValueError('card remains')
   d=types.SimpleNamespace(root=root,session_bindings={},ui=lambda peer:u,_file_helper=lambda:types.SimpleNamespace(require_empty_editor=empty),app_windows=lambda:[])
   with patch('operations.sending.scene',return_value=[]),patch('operations.composer.clear',side_effect=lambda ui:setattr(ui,'cleared',True)):
    self.assertTrue(sending.cleanup(d,j))
 def test_safe_editor_point_is_outside_left_attached_file_card(self):
  cfg={'header_box':[495,152,1097,199],'editor':[746,671]};self.assertEqual(composer.editor_point(cfg),[1042,671]);self.assertGreater(composer.editor_point(cfg)[0],755)
