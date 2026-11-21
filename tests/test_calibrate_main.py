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


if __name__ == '__main__':
    unittest.main()
