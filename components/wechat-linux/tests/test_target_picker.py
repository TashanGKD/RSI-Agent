import unittest
import target_picker

class PickerTests(unittest.TestCase):
    def test_picker_refuses_editor_searchbar_and_message_pane(self):
        for p in [[1047,751],[360,175],[695,420],[True,360],[-1,2]]:
            with self.assertRaises(ValueError):target_picker.point(p,[315,199,495,767])
        self.assertEqual(target_picker.point([355,360],[315,199,495,767]),[355,360])
    def test_changed_sidebar_is_rejected_before_click(self):
        with self.assertRaises(ValueError):target_picker.check_sidebar(b'new','0'*64)
    def test_navigation_uses_only_focus_and_mouse_never_text_or_enter(self):
        class C:
            def __init__(self):self.clicks=[]
            def focus(self,w):pass
            def click(self,*p):self.clicks.append(p)
            def wait(self,ms):pass
            def key(self,*a,**kw):raise AssertionError('picker must never issue keys')
            def paste(self,*a,**kw):raise AssertionError('picker must never paste')
        c=C();target_picker.open_visible(c,{'id':'main'},[355,360]);self.assertEqual(c.clicks,[(355,360)])
