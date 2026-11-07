import unittest,tempfile,hashlib
from pathlib import Path
import image_client

class ClientImageTests(unittest.TestCase):
    def test_xml_entity_and_non_image_or_ambiguous_hash_rejected(self):
        for raw,kind in [('<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><msg/>',3),('<msg><img md5="'+'a'*32+'"/></msg>',1),('<msg><img md5="'+'a'*32+'"/><img md5="'+'b'*32+'"/></msg>',3)]:
            with self.assertRaises(ValueError):image_client.source_info(raw,kind)
    def test_click_cannot_target_sidebar_editor_or_send_control(self):
        for point in [[340,300],[1047,751],[695,671],[True,400],[-1,20]]:
            with self.assertRaises(ValueError):image_client.validate_point(point,[495,200,1097,637])
        self.assertEqual(image_client.validate_point([695,420],[495,200,1097,637]),[695,420])
    def test_changed_context_stops_before_gui_action(self):
        with self.assertRaises(ValueError):image_client.check_context(b'new','0'*64)
    def test_mismatched_export_is_not_accepted_as_requested_picture(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td).resolve();(p/'image.png').write_bytes(b'not requested image')
            with self.assertRaises(ValueError):image_client.verify_export(p/'image.png','a'*32,p)
    def test_source_hash_and_size_are_whitelisted_not_aes_keys(self):
        d=image_client.source_info('<msg><img md5="'+'a'*32+'" hdlength="143507" aeskey="do-not-export" cdnmidimgurl="private"/></msg>',3)
        self.assertEqual(d,{'md5':'a'*32,'hdlength':143507})
    def test_window_parser_only_accepts_native_wechat_windows(self):
        s='0x2000f4 "Photos and Videos": ("wechat" "wechat") 1214x521+32+189 +32+189\n0x444 "Save": ("other" "other") 647x432+0+0 +0+0'
        self.assertEqual(image_client.parse_windows(s),[{'id':'0x2000f4','title':'Photos and Videos','x':32,'y':189,'width':1214,'height':521}])
    def test_focus_returns_to_main_only_after_owned_viewer_is_closed(self):
        class C:
            def __init__(self,dialog=None):self.dialog=dialog;self.focused=None
            def one(self,title,optional=False):return self.dialog if title=='Save' else ({'id':'main'} if title=='Weixin' else None)
            def focus(self,w):self.focused=w['id']
        c=C();image_client.restore_main_focus(c);self.assertEqual(c.focused,'main')
        c=C({'id':'save'});image_client.restore_main_focus(c);self.assertIsNone(c.focused)
