import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.navigation import refresh_search

MAIN={'id':'0x400011','title':'Weixin','x':200,'y':80,'width':905,'height':667}
# Observed live: the popup was recorded at 96 px and grew to 162 px when the
# Group Chats section loaded.
RECORDED={'id':'0x400838','title':'wechat','x':273,'y':152,'width':320,'height':96}

class SearchGrowthTests(unittest.TestCase):
 def test_same_owned_popup_may_grow_to_show_its_sections(self):
  v={'search':dict(RECORDED)};grown=dict(RECORDED,height=162)
  self.assertEqual(refresh_search(v,[MAIN,grown],MAIN),grown)
  self.assertEqual(v['search'],grown)

 def test_any_other_change_or_window_is_refused(self):
  for changed in (dict(RECORDED,id='0x400839'),dict(RECORDED,x=274),dict(RECORDED,width=330),
                  dict(RECORDED,title='Weixin'),dict(RECORDED,height=700)):
   v={'search':dict(RECORDED)}
   self.assertIsNone(refresh_search(v,[MAIN,changed],MAIN))
   self.assertEqual(v['search'],RECORDED)
  self.assertIsNone(refresh_search({'search':None},[MAIN],MAIN))
  self.assertIsNone(refresh_search({'search':dict(RECORDED)},[MAIN],MAIN))

if __name__=='__main__':unittest.main()
