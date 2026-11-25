import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations import navigation

MAIN={'id':'0x400011','title':'Weixin','x':200,'y':80,'width':905,'height':667}
# Observed live: the new group window was recorded as "Weixin" and renamed to
# the group within about a second.
RECORDED={'id':'0x400eb4','title':'Weixin','x':341,'y':80,'width':623,'height':667}
NAMED=dict(RECORDED,title='天文产品开发')

class Display:
 def __init__(self,*frames):self.frames=list(frames)
 def app_windows(self):return self.frames.pop(0) if len(self.frames)>1 else self.frames[0]

class PopoutTitleTests(unittest.TestCase):
 def test_same_owned_window_may_only_change_its_title(self):
  v={'ownPopout':dict(RECORDED)}
  self.assertEqual(navigation.refresh_own(v,[MAIN,NAMED]),NAMED)
  self.assertEqual(v['ownPopout'],NAMED)
  for changed in (dict(NAMED,id='0x400eb5'),dict(NAMED,x=342),dict(NAMED,height=640)):
   v={'ownPopout':dict(RECORDED)}
   self.assertIsNone(navigation.refresh_own(v,[MAIN,changed]))
   self.assertEqual(v['ownPopout'],RECORDED)
  self.assertIsNone(navigation.refresh_own({'ownPopout':None},[MAIN]))

 def test_preparation_waits_for_the_late_title(self):
  v={'ownPopout':dict(RECORDED)}
  with patch.object(navigation.time,'sleep'):
   own=navigation.settle_popout_title(Display([MAIN,RECORDED],[MAIN,NAMED]),v,'天文产品开发')
  self.assertEqual(own,NAMED)
  self.assertEqual(v['ownPopout'],NAMED)

 def test_a_wrong_or_vanished_window_keeps_the_recorded_title(self):
  for frame in ([MAIN,dict(RECORDED,title='Other group')],[MAIN]):
   v={'ownPopout':dict(RECORDED)}
   with patch.object(navigation.time,'sleep'):
    own=navigation.settle_popout_title(Display(frame),v,'天文产品开发')
   self.assertNotEqual(own['title'],'天文产品开发')
   with self.assertRaises(ValueError):
    navigation.prove_popout(own,'天文产品开发',{},{})

if __name__=='__main__':unittest.main()
