import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.windows import search_geometry

MAIN={'x':200,'y':80,'width':905,'height':667}

def popup(dx,dy,width,title='wechat'):
 return {'title':title,'x':MAIN['x']+dx,'y':MAIN['y']+dy,'width':width,'height':298}

class SearchGeometryTests(unittest.TestCase):
 def test_reviewed_server_and_local_wsl_shapes_are_candidates(self):
  for shape in ((76,75,333),(74,73,321),(73,72,320)):
   self.assertTrue(search_geometry(popup(*shape),MAIN),shape)
 def test_other_offsets_or_titles_are_not_candidates(self):
  self.assertFalse(search_geometry(popup(72,71,320),MAIN))
  self.assertFalse(search_geometry(popup(73,72,320,title='Weixin'),MAIN))

if __name__=='__main__':unittest.main()
