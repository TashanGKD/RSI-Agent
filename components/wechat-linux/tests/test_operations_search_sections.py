"""Regression: native results may be below the Internet section, never web clicks."""
import unittest
from operations.selectors import native_search_result

def row(text,y,x=120):return {'text':text,'point':[x,y]}
NAME='合成项目工作群'
PEER='15869074386@chatroom'
class SearchSectionTests(unittest.TestCase):
 def test_internet_above_group_uses_native_group(self):
  rows=[row('Internet search results',18),row(NAME,51),row('Group Chats',86),row(NAME,134)]
  self.assertEqual(native_search_result(rows,NAME,PEER),[120,134])
 def test_group_above_internet_uses_native_group(self):
  rows=[row('Group Chats',18),row(NAME,51),row('Internet search results',86),row(NAME,134)]
  self.assertEqual(native_search_result(rows,NAME,PEER),[120,51])
 def test_web_only_is_never_selected(self):
  with self.assertRaises(ValueError):native_search_result([row('Internet search results',18),row(NAME,51)],NAME,PEER)
 def test_missing_native_section_is_not_inferred(self):
  with self.assertRaises(ValueError):native_search_result([row(NAME,51)],NAME,PEER)
 def test_repeated_group_name_rejected(self):
  with self.assertRaises(ValueError):native_search_result([row('Group Chats',18),row(NAME,51),row(NAME,110)],NAME,PEER)
 def test_same_name_contact_is_not_a_group_result(self):
  rows=[row('Contacts',18),row(NAME,51),row('Group Chats',86),row(NAME,134)]
  self.assertEqual(native_search_result(rows,NAME,PEER),[120,134])
 def test_contacts_can_follow_internet(self):
  rows=[row('Internet search results',18),row('Alice',51),row('Contacts',86),row('Alice',134)]
  self.assertEqual(native_search_result(rows,'Alice','wxid_fixture_a662995929'),[120,134])
 def test_next_non_native_section_ends_group_range(self):
  rows=[row('Group Chats',18),row('Other',51),row('Chat History',86),row(NAME,134)]
  with self.assertRaises(ValueError):native_search_result(rows,NAME,PEER)
 def test_similar_name_or_punctuation_is_not_an_exact_match(self):
  for actual,expected in [('合成项目工作群旧群',NAME),('项目A','项目-A'),('项目-A','项目A')]:
   with self.assertRaises(ValueError):native_search_result([row('Group Chats',18),row(actual,51)],expected,PEER)
 def test_duplicate_section_headers_are_rejected(self):
  rows=[row('Group Chats',18),row('Other',51),row('Group Chats',86),row(NAME,134)]
  with self.assertRaises(ValueError):native_search_result(rows,NAME,PEER)
 def test_unordered_ocr_rows_are_sorted_by_screen_y(self):
  rows=[row(NAME,134),row('Group Chats',86),row(NAME,51),row('Internet search results',18)]
  self.assertEqual(native_search_result(rows,NAME,PEER),[120,134])

 def test_ocr_word_spacing_does_not_remove_punctuation_or_case(self):
  self.assertEqual(native_search_result([row('Contacts',18),row('AliceSmith',51)],'Alice Smith','wxid_fixture_a662995929'),[120,51])
  with self.assertRaises(ValueError):native_search_result([row('Contacts',18),row('aliceSmith',51)],'Alice Smith','wxid_fixture_a662995929')

class SearchWorkflowTests(unittest.TestCase):
 def run_selection(self,rows,title_ok):
  import tempfile,types
  from pathlib import Path
  from unittest.mock import Mock,patch
  from PIL import Image
  from operations.recipes import selected
  main={'id':'m','title':'Weixin','x':181,'y':117,'width':905,'height':667}
  popup={'id':'p','title':'wechat','x':257,'y':192,'width':333,'height':170}
  class Tool:
   def resolve(self,q):return {'username':PEER,'displayName':NAME,'alias':''}
  class D:
   active_window=None;session_bindings={}
   def tool(self):return Tool()
   def app_windows(self):return [main,popup]
   def binding(self,p):return {'header_box':[495,152,1097,199]}
  control=Mock();verify=Mock(side_effect=None if title_ok else ValueError('different title'))
  with tempfile.TemporaryDirectory() as td:
   driver=D();driver.root=Path(td)
   with patch.dict('sys.modules',{'sender':types.SimpleNamespace(validate_binding=verify)}),patch('operations.recipes.controls',return_value=control),patch('operations.recipes.main_window',return_value=main),patch('operations.recipes.activate'),patch('operations.recipes.paste_field'),patch('operations.recipes.screen',return_value=Image.new('RGB',(1280,900),'white')),patch('operations.recipes.rows',return_value=rows):
    try:return selected(driver,{'peer':PEER},force_search=True),control,verify
    except Exception as e:return e,control,verify
 def test_native_group_below_web_is_clicked_and_header_independently_checked(self):
  result,control,verify=self.run_selection([row('Internet search results',210),row(NAME,240),row('Group Chats',275),row(NAME,320)],True)
  self.assertIsNone(result);control.click.assert_called_once_with(120,320);verify.assert_called_once()
 def test_two_same_native_names_do_not_click_either(self):
  result,control,verify=self.run_selection([row('Group Chats',210),row(NAME,240),row(NAME,320)],True)
  self.assertEqual(result.code,'RECIPIENT_NOT_VISIBLE');control.click.assert_not_called();verify.assert_not_called()
 def test_matching_result_with_wrong_header_still_fails(self):
  result,control,verify=self.run_selection([row('Group Chats',210),row(NAME,240)],False)
  self.assertEqual(result.code,'RECIPIENT_NOT_VERIFIED');verify.assert_called_once()

class SearchOCRLayoutTests(unittest.TestCase):
 def test_internet_icon_ocr_prefix_still_ends_native_section(self):
  rows=[row('Group Chats',18),row('Other',51),row('和Internetsearchresults',86),row(NAME,134)]
  with self.assertRaises(ValueError):native_search_result(rows,NAME,PEER)
 def test_headers_and_name_column_can_be_read_independently(self):
  from operations.selectors import native_search_bounds
  headers=[row('和Internetsearchresults',16),row('Q'+NAME,53),row('GroupChats',87),row('ais收字中国穴事学生开',135)]
  self.assertEqual(native_search_bounds(headers,PEER),(87,float('inf')))
  self.assertEqual(native_search_result(headers,NAME,PEER,name_rows=[row(NAME,134)]),[120,134])

class UnnamedGroupTests(unittest.TestCase):
 def test_empty_native_name_uses_verified_member_and_title_aliases(self):
  from operations.recipes import search_identity
  target={'username':'room@chatroom','displayName':'room@chatroom','alias':''};cfg={'observedTitle':'魏达、猪肉八元一斤(3)','nativeMemberIds':['self','prof','owner'],'paired_account':'self'}
  query,names=search_identity(target,cfg,['self','prof','owner'],{'魏达':'prof','猪肉八元一斤':'owner'})
  self.assertEqual(query,'魏达');self.assertEqual(set(names),{'魏达、猪肉八元一斤','魏达、猪肉八元一斤(3)'})
 def test_changed_membership_or_unverified_query_is_rejected(self):
  from operations.recipes import search_identity
  t={'username':'room@chatroom','displayName':'room@chatroom','alias':''};c={'observedTitle':'老师、本人(3)','nativeMemberIds':['self','prof','owner'],'paired_account':'self'}
  for members,names in [(['self','other','owner'],{'老师':'prof'}),(['self','prof','owner'],{'老师':'other'})]:
   with self.assertRaises(ValueError):search_identity(t,c,members,names)
 def test_unnamed_title_requires_all_visible_member_names_unique(self):
  from operations.recipes import search_identity
  t={'username':'room@chatroom','displayName':'room@chatroom','alias':''};c={'observedTitle':'魏达、本人(3)','nativeMemberIds':['self','prof','owner'],'paired_account':'self'}
  with self.assertRaises(ValueError):search_identity(t,c,['self','prof','owner'],{'本人':'owner'})
