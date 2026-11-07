import unittest,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.driver import NativeDriver
from operations.selectors import unique_line
class AutonomyTests(unittest.TestCase):
 def test_expired_navigation_has_no_owned_draft_to_clear(self):
  with tempfile.TemporaryDirectory() as td:
   d=object.__new__(NativeDriver);d.root=Path(td)
   d.ui=lambda peer:(_ for _ in ()).throw(AssertionError('must preserve foreign/current draft'))
   self.assertTrue(d.cleanup({'id':'a'*32,'action':'send_text','peer':'x','payload':{'text':'x'},'preview':{'needs_assistance':True,'navigationBounds':[0,0,10,10]}}))
 def test_exact_ocr_not_substring_or_fuzzy(self):
  rows=[{'text':'Alice Corp','point':[5,5]},{'text':'Alice','point':[6,6]}]
  self.assertEqual(unique_line(rows,'Alice'),[6,6])
  with self.assertRaises(ValueError):unique_line(rows,'Ali')
 def test_same_name_two_rows_is_ambiguous(self):
  with self.assertRaises(ValueError):unique_line([{'text':'同名','point':[1,2]},{'text':'同名','point':[2,3]}],'同名')
 def test_scroll_thumb_ignores_long_window_border(self):
  from PIL import Image,ImageDraw
  from operations.selectors import scroll_thumb
  im=Image.new('RGB',(100,300),'white');d=ImageDraw.Draw(im);d.rectangle((90,0,90,299),fill=(150,150,150));d.rectangle((94,100,98,127),fill=(170,170,170));self.assertEqual(scroll_thumb(im,[89,0,100,300]),[96,113])
 def test_no_scroll_thumb_is_not_a_guess(self):
  from PIL import Image
  from operations.selectors import scroll_thumb
  with self.assertRaises(ValueError):scroll_thumb(Image.new('RGB',(100,300),'white'),[89,0,100,300])
 def test_round_scroll_thumb_is_one_component(self):
  from PIL import Image,ImageDraw
  from operations.selectors import scroll_thumb
  im=Image.new('RGB',(100,300),'white');d=ImageDraw.Draw(im);d.rounded_rectangle((94,100,98,127),radius=2,fill=(170,170,170));self.assertEqual(scroll_thumb(im,[89,0,100,300]),[96,113])
 def test_old_geometry_without_native_parent_is_rejected(self):
  from operations.recipes import main_window
  from unittest.mock import patch
  main={'id':'m','title':'Weixin','x':181,'y':117,'width':905,'height':667};pop={'id':'p','title':'wechat','x':257,'y':192,'width':333,'height':69}
  class D:
   n=0
   def app_windows(self):self.n+=1;return [main,pop] if self.n==1 else [main]
  class C:
   clicked=[]
   def click(self,*p):self.clicked.append(p)
   def wait(self,x):pass
   def close(self):pass
  c=C()
  with patch('operations.recipes.controls',return_value=c):
   with self.assertRaises(ValueError):main_window(D())
  self.assertEqual(c.clicked,[])
 def test_unrelated_modal_is_not_dismissed(self):
  from operations.recipes import main_window,PreparationError
  from unittest.mock import patch
  class D:
   def app_windows(self):return [{'id':'m','title':'Weixin','x':181,'y':117,'width':905,'height':667},{'id':'p','title':'Save','x':0,'y':0,'width':600,'height':400}]
  with patch('operations.recipes.controls') as c:
   with self.assertRaises(PreparationError):main_window(D())
   c.assert_not_called()
 def test_selected_sidebar_row_is_detected_without_name_guessing(self):
  from PIL import Image,ImageDraw
  from operations.selectors import selected_chat_row
  im=Image.new('RGB',(300,500),'white');ImageDraw.Draw(im).rectangle((0,180,299,245),fill=(7,174,114));self.assertEqual(selected_chat_row(im,[0,0,300,500]),[150,212])
 def test_popout_is_adapted_by_native_identity_without_caller_coordinates(self):
  from operations.recipes import selected
  from unittest.mock import patch
  from PIL import Image
  main={'id':'0x1','title':'Weixin','x':181,'y':117,'width':905,'height':667};pop={'id':'0x2','title':'本人','x':328,'y':117,'width':623,'height':667}
  class Tool:
   def resolve(self,q):return {'username':'wxid_fixture_1987fcaa9f','displayName':'本人'}
  class D:
   active_window=None;session_bindings={}
   def tool(self):return Tool()
   def app_windows(self):return [main,pop]
  class C:
   def close(self):pass
  d=D()
  with patch('operations.recipes.controls',return_value=C()),patch('operations.recipes.activate') as activate,patch('operations.recipes.screen',return_value=Image.new('RGB',(1280,900),'white')):
   selected(d,{'peer':'wxid_fixture_1987fcaa9f'});activate.assert_called_once()
  self.assertEqual(d.active_window['id'],'0x2');self.assertEqual(d.session_bindings['wxid_fixture_1987fcaa9f']['editor'],[608,671])
 def test_popout_name_must_map_back_to_requested_native_peer(self):
  from operations.recipes import selected,PreparationError
  from unittest.mock import patch
  class Tool:
   def resolve(self,q):return {'username':'wxid_fixture_4c90539d6a' if q=='本人' else 'wxid_fixture_1987fcaa9f','displayName':'本人'}
  class D:
   def tool(self):return Tool()
   def app_windows(self):return [{'id':'0x2','title':'本人','x':328,'y':117,'width':623,'height':667}]
  with patch('operations.recipes.controls') as c:
   with self.assertRaises(PreparationError):selected(D(),{'peer':'wxid_fixture_1987fcaa9f'})
   c.assert_not_called()
 def test_visible_source_is_used_before_scroll_or_navigation(self):
  from operations.recipes import locate_source
  from unittest.mock import patch
  class D:
   def binding(self,p):return {'header_box':[329,152,950,199],'editor':[608,671]}
  class C:
   def close(self):pass
  with patch('operations.recipes.controls',return_value=C()),patch('operations.recipes.rows',return_value=[{'text':'write-v2.txt','point':[700,547]}]),patch('operations.recipes.main_window',side_effect=AssertionError('must not navigate')):
   self.assertEqual(locate_source(D(),{'peer':'owner'},{'kind':49,'text':'<msg><appmsg><title>write-v2.txt</title></appmsg></msg>'}),[700,547])
 def test_quote_verification_uses_original_pixels_before_contrast(self):
  from operations.recipes import verify_quote
  from unittest.mock import patch
  cfg={'header_box':[329,152,950,199],'editor':[608,671],'send':[901,752]}
  with patch('operations.recipes.rows',return_value=[{'text':'示例助手: write-v2.txt','point':[430,692]}]) as r:
   verify_quote(object(),cfg,{'kind':49,'text':'<msg><appmsg><title>write-v2.txt</title></appmsg></msg>'})
  self.assertFalse(r.call_args.kwargs.get('contrast',False))
 def test_wrong_quote_does_not_pass(self):
  from operations.recipes import verify_quote,PreparationError
  from unittest.mock import patch
  cfg={'header_box':[329,152,950,199],'editor':[608,671],'send':[901,752]}
  with patch('operations.recipes.rows',return_value=[{'text':'wrong-file.txt','point':[430,692]}]):
   with self.assertRaises(PreparationError):verify_quote(object(),cfg,{'kind':49,'text':'<msg><appmsg><title>write-v2.txt</title></appmsg></msg>'})
 def test_quote_close_rejects_round_bullet_without_cross(self):
  from operations.selectors import quote_close
  from PIL import Image,ImageDraw
  im=Image.new('RGB',(300,80),'white');d=ImageDraw.Draw(im);d.ellipse((100,22,113,35),fill=(210,210,210))
  with self.assertRaises(ValueError):quote_close(im,[0,0,300,80])
  d.line((104,26,109,31),fill='white',width=1);d.line((109,26,104,31),fill='white',width=1)
  self.assertEqual(quote_close(im,[0,0,300,80]),[106,28])
 def test_reply_cleanup_never_uses_marker_after_send_attempt(self):
  from operations.recipes import cleanup_reply
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as td:
   class D:root=Path(td)
   (D.root/('a-attempt.json')).write_text('{}')
   with patch('operations.recipes.controls') as c:self.assertFalse(cleanup_reply(D(),{'id':'a'}));c.assert_not_called()
 def test_repeated_native_source_labels_are_rejected_before_ui_guess(self):
  from operations.recipes import source_label,PreparationError
  with self.assertRaises(PreparationError) as e:source_label({'kind':1,'text':'重复正文','sourceLocatorUnique':False})
  self.assertEqual(e.exception.code,'SOURCE_AMBIGUOUS')
 def test_tall_geometry_without_native_parent_is_rejected(self):
  from operations.recipes import main_window
  from unittest.mock import patch
  main={'id':'m','title':'Weixin','x':181,'y':117,'width':905,'height':667};pop={'id':'p','title':'wechat','x':257,'y':192,'width':333,'height':579}
  class D:
   n=0
   def app_windows(self):self.n+=1;return [main,pop] if self.n==1 else [main]
  class C:
   def click(self,*p):pass
   def wait(self,x):pass
   def close(self):pass
  with patch('operations.recipes.controls',return_value=C()):
   with self.assertRaises(ValueError):main_window(D())
