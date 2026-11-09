import unittest, types, hashlib, tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from operations import image_draft, composer, sending


class Pixbuf:
 def __init__(self, im, padding=0):
  self.im=im;self.n=len(im.getbands());self.stride=im.width*self.n+padding
 def get_width(self):return self.im.width
 def get_height(self):return self.im.height
 def get_n_channels(self):return self.n
 def get_bits_per_sample(self):return 8
 def get_rowstride(self):return self.stride
 def get_pixels(self):
  raw=self.im.tobytes();n=self.im.width*self.n
  return b''.join(raw[y*n:(y+1)*n]+b'\0'*(self.stride-n) for y in range(self.im.height))


class ImageDraftTests(unittest.TestCase):
 def test_sparse_long_image_identity_is_not_a_connected_component(self):
  from operations.visual import attachment_box
  im=Image.new('RGB',(390,2118),'white');im.putpixel((20,50),(10,20,30))
  with self.assertRaises(ValueError):attachment_box(im,[0,1900,390,2000])
  a=image_draft.pixel_identity(Pixbuf(im));b=image_draft.pixel_identity(Pixbuf(im.convert('RGBA'),8))
  self.assertEqual(a,b);self.assertEqual(a['width'],390);self.assertEqual(a['height'],2118)
 def test_pixel_change_shape_and_alpha_are_not_equivalent(self):
  im=Image.new('RGBA',(3,4),(1,2,3,255));a=image_draft.pixel_identity(Pixbuf(im))
  for altered in [Image.new('RGBA',(4,3),(1,2,3,255)),Image.new('RGBA',(3,4),(1,2,3,0)),Image.new('RGBA',(3,4),(1,2,4,255))]:
   self.assertNotEqual(a,image_draft.pixel_identity(Pixbuf(altered)))
 def test_invalid_or_oversized_buffers_are_rejected_before_decoding(self):
  for field,value in [('get_width',lambda:8193),('get_height',lambda:0),('get_rowstride',lambda:1),('get_bits_per_sample',lambda:16),('get_pixels',lambda:b'x')]:
   p=Pixbuf(Image.new('RGB',(3,4)));setattr(p,field,value)
   with self.assertRaises(ValueError):image_draft.pixel_identity(p)
 def test_single_native_image_fragment_and_exact_uri(self):
  raw=b'<WeChatRichEditFormat><EditElement type="1" filepath="/tmp/a.png"></EditElement></WeChatRichEditFormat>'
  image_draft.native_image_fragment(raw,['file:///tmp/a.png'],'file:///tmp/a.png')
  cases=[(raw.replace(b'</WeChat',b'<EditElement type="1" filepath="/tmp/a.png"/></WeChat'),['file:///tmp/a.png'],'file:///tmp/a.png'),(raw.replace(b'type="1"',b'type="0"'),['file:///tmp/a.png'],'file:///tmp/a.png'),(raw,['file:///tmp/a.png'],'extra'),(raw,['file:///tmp/b.png'],'file:///tmp/b.png'),(raw,[],'file:///tmp/a.png'),(b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///x">]>'+raw,['file:///tmp/a.png'],'file:///tmp/a.png'),(raw.replace(b'</EditElement>',b'extra</EditElement>'),['file:///tmp/a.png'],'file:///tmp/a.png')]
  for fragment,uris,text in cases:
   with self.assertRaises(ValueError):image_draft.native_image_fragment(fragment,uris,text)
 def test_cleanup_before_final_preview_only_clears_exact_owned_image(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);j={'id':'a'*32,'peer':'p','action':'send_image','client':'x','payload':{'asset':'b'*64}}
   identity=image_draft.pixel_identity(Pixbuf(Image.new('RGB',(3,4))))
   composer.save(root,j,{'state':'image-paste-pending','imageIdentity':identity,'priorText':'','binding':{},'window':{}})
   class UI:
    cleared=False
    def close(self):pass
   ui=UI()
   def require_empty(_):
    if not ui.cleared:raise ValueError('image remains')
   d=types.SimpleNamespace(root=root,session_bindings={},app_windows=lambda:[],ui=lambda p:ui,_file_helper=lambda:types.SimpleNamespace(require_empty_editor=require_empty))
   with patch('operations.sending.scene',return_value=[]),patch('operations.image_draft.verify',return_value=identity),patch('operations.composer.clear',side_effect=lambda u:setattr(u,'cleared',True)),patch('operations.composer.restore',return_value=True):
    self.assertTrue(sending.cleanup(d,j));self.assertTrue(ui.cleared)
   ui.cleared=False
   with patch('operations.sending.scene',return_value=[]),patch('operations.image_draft.verify',side_effect=ValueError('different/mixed image')),patch('operations.composer.clear',side_effect=AssertionError('must preserve foreign content')):
    self.assertFalse(sending.cleanup(d,j));self.assertFalse(ui.cleared)
   (root/(j['id']+'-attempt.json')).write_text('{}')
   with patch('operations.image_draft.verify',side_effect=AssertionError('never inspect attempted send for cancellation')):
    self.assertFalse(sending.cleanup(d,j))
 def test_verification_copies_the_editor_and_never_trusts_old_paste_clipboard(self):
  expected=Pixbuf(Image.new('RGB',(3,4),'white'))
  class Clip:
   image=expected;text=''
   def set_text(self,t,n):self.text=t;self.image=None
   def wait_for_image(self):return self.image
   def wait_for_text(self):return self.text
   def wait_for_targets(self):return True,[types.SimpleNamespace(name=lambda:'WeChat_RichEdit_Format')]
   def wait_for_uris(self):return ['file:///tmp/a.png']
   def wait_for_contents(self,atom):return types.SimpleNamespace(get_data=lambda:b'<WeChatRichEditFormat><EditElement type="1" filepath="/tmp/a.png"/></WeChatRichEditFormat>')
  class UI:
   cfg={'header_box':[0,0,600,50],'editor':[100,200]};clip=Clip();copy=True;extra='';checks=0
   def check(self):self.checks+=1
   def click(self,p):pass
   def settle(self,n):pass
   def ctrl(self,c):
    if c=='c' and self.copy:self.clip.image=expected;self.clip.text='file:///tmp/a.png'+self.extra
    if c=='v':raise AssertionError('verification never pastes')
  u=UI();identity=image_draft.pixel_identity(expected)
  with patch('operations.image_draft._atom',side_effect=lambda n:n):
   self.assertEqual(image_draft.verify(u,identity),identity);self.assertGreaterEqual(u.checks,3)
   u.copy=False
   with self.assertRaises(ValueError):image_draft.verify(u,identity)
   u.copy=True;u.extra='unexpected text'
   with self.assertRaises(ValueError):image_draft.verify(u,identity)


if __name__=='__main__':unittest.main()
