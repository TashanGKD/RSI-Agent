import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.visual import attachment_box
from PIL import Image,ImageDraw
class AttachmentTests(unittest.TestCase):
 def test_caret_does_not_change_card_identity_region(self):
  a=Image.new('RGB',(200,100),'#FAFAFA');d=ImageDraw.Draw(a);d.rectangle((10,10,110,70),fill='#EFEFEF');box=attachment_box(a,[0,0,200,100]);d.line((140,15,140,35),fill='black');self.assertEqual(box,attachment_box(a,[0,0,200,100]))
 def test_no_attachment_is_not_guessed(self):
  with self.assertRaises(ValueError):attachment_box(Image.new('RGB',(200,100),'white'),[0,0,200,100])
 def test_tiny_caret_is_not_attachment(self):
  a=Image.new('RGB',(200,100),'white');ImageDraw.Draw(a).line((20,20,20,40),fill='black')
  with self.assertRaises(ValueError):attachment_box(a,[0,0,200,100])
 def test_widget_edge_antialias_does_not_change_inner_content(self):
  import hashlib
  a=Image.new('RGB',(200,100),'#FAFAFA');ImageDraw.Draw(a).rectangle((10,10,110,70),fill='#EFEFEF');box=attachment_box(a,[0,0,200,100]);sha=hashlib.sha256(a.crop(tuple(box)).tobytes()).hexdigest();a.putpixel((110,13),(250,250,250));self.assertEqual(hashlib.sha256(a.crop(tuple(box)).tobytes()).hexdigest(),sha)
