import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.navigation import resize_own_popout

class Driver:
 def __init__(self,sizes):self.sizes=list(sizes)
 def app_windows(self):
  w,h=self.sizes.pop(0) if len(self.sizes)>1 else self.sizes[0]
  return [{'id':'0x1','title':'Weixin','x':0,'y':0,'width':905,'height':667},{'id':'0x2','title':'Group','x':10,'y':0,'width':w,'height':h}]

class PopoutResizeTests(unittest.TestCase):
 def test_default_own_popout_is_resized_and_reobserved(self):
  own={'id':'0x2','title':'Group','x':10,'y':0,'width':598,'height':640}
  with patch('subprocess.run') as run,patch('operations.navigation.time.sleep'):
   current,after=resize_own_popout(Driver([(598,640),(623,667)]),own)
  run.assert_called_once()
  self.assertEqual(run.call_args.args[0],['xdotool','windowsize','0x2','623','667'])
  self.assertEqual((current['width'],current['height']),(623,667))
  self.assertEqual(len(after),2)
 def test_unchanged_popout_keeps_the_original_failure_path(self):
  own={'id':'0x2','title':'Group','x':10,'y':0,'width':598,'height':640}
  with patch('subprocess.run'),patch('operations.navigation.time.sleep'):
   current,_=resize_own_popout(Driver([(598,640)]),own)
  self.assertEqual((current['width'],current['height']),(598,640))

if __name__=='__main__':unittest.main()
