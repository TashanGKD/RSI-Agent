import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('calibrate_main', ROOT / 'deploy/wechat-gui/calibrate_main.py')
calibrate_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibrate_main)


class CalibrateMainTests(unittest.TestCase):
    def test_only_the_default_official_main_window_is_selected(self):
        tree = '\n'.join([
            '     0x400011 "Weixin": ("wechat" "wechat")  880x640+0+0  +200+80',
            '     0x400007 "Weixin": ("wechat" "wechat")  280x380+0+0  +500+210',
            '     0x400012 "Weixin": ("wechat" "wechat")  905x667+0+0  +200+80',
            '     0x400040 "Group": ("wechat" "wechat")  880x640+0+0  +341+80',
            '     0x800001 "Weixin": ("other" "other")  880x640+0+0  +10+10',
        ])
        self.assertEqual(calibrate_main.default_main_windows(tree), ['0x400011'])

    def test_an_unfocused_calibrated_main_window_is_activated(self):
        tree = '\n'.join([
            '     0x400011 "Weixin": ("wechat" "wechat")  905x667+0+0  +200+80',
            '     0x400040 "Group": ("wechat" "wechat")  623x667+0+0  +341+80',
        ])
        for unset in ('XGetWindowProperty[_NET_ACTIVE_WINDOW] failed (code=1)\n',
                      '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n'):
            self.assertIsNone(calibrate_main.active_window(unset))
            self.assertEqual(calibrate_main.main_window_to_focus(tree, calibrate_main.active_window(unset)), '0x400011')

    def test_existing_focus_and_ambiguous_mains_are_left_alone(self):
        tree = '     0x400011 "Weixin": ("wechat" "wechat")  905x667+0+0  +200+80'
        focused = calibrate_main.active_window('_NET_ACTIVE_WINDOW(WINDOW): window id # 0x400040\n')
        self.assertEqual(focused, '0x400040')
        self.assertIsNone(calibrate_main.main_window_to_focus(tree, focused))
        two = tree + '\n     0x400012 "Weixin": ("wechat" "wechat")  905x667+0+0  +200+80'
        self.assertIsNone(calibrate_main.main_window_to_focus(two, None))
        login = '     0x400007 "Weixin": ("wechat" "wechat")  280x380+0+0  +500+210'
        self.assertIsNone(calibrate_main.main_window_to_focus(login, None))

    def test_a_restored_main_window_near_the_calibrated_size_is_corrected(self):
        tree = '\n'.join([
            '     0x400011 "Weixin": ("wechat" "wechat")  903x667+0+0  +200+80',
            '     0x400007 "Weixin": ("wechat" "wechat")  280x380+0+0  +500+210',
            '     0x400040 "Group": ("wechat" "wechat")  903x667+0+0  +341+80',
        ])
        self.assertEqual(calibrate_main.default_main_windows(tree), ['0x400011'])


if __name__ == '__main__':
    unittest.main()
