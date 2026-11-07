import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sender
from operations.driver import NativeDriver
from operations.recipes import search_identity
from operations.windows import parse_app_windows


class HostInstallationTests(unittest.TestCase):
    def test_reparented_window_uses_absolute_screen_coordinates(self):
        raw = '  0x400019 "File Transfer": ("wechat" "wechat") 600x642+0+0  +393+300\n'
        window = parse_app_windows(raw)[0]
        self.assertEqual((window['x'], window['y']), (393, 300))
        root = parse_app_windows('  0x12 "Weixin": ("wechat" "wechat") 905x667+20+30\n')[0]
        self.assertEqual((root['x'], root['y']), (20, 30))

    def test_filehelper_localization_keeps_the_native_identity(self):
        target = {'username': 'filehelper', 'displayName': '文件传输助手'}
        self.assertEqual(sender.visual_title(target, 'File Transfer'), 'File Transfer')
        self.assertEqual(search_identity(target, {'observedTitle': 'File Transfer'}),
                         ('文件传输助手', ['File Transfer']))
        for wrong in ({'username': 'other', 'displayName': '文件传输助手'},
                      {'username': 'filehelper', 'displayName': 'Changed'}):
            with self.assertRaises(ValueError):
                sender.visual_title(wrong, 'File Transfer')
        with self.assertRaises(ValueError):
            sender.visual_title(target, 'File Transfer copy')

    def test_native_guard_is_runtime_state_with_read_only_source(self):
        import operations.driver as driver
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'desktop-control-20261026').mkdir()
            source = base / 'source'
            source.mkdir()
            state = base / 'operations-state'
            d = NativeDriver(state, {'account': 'self', 'clients': {}})
            d.work_class = 'delivery'
            original_open = os.open

            def private_open(path, *args, **kwargs):
                if Path(path).parent == source:
                    raise PermissionError('installed source is read only')
                return original_open(path, *args, **kwargs)

            with patch.object(driver, 'BASE', base), patch.object(driver, 'COMMON', source), patch.object(driver.os, 'open', side_effect=private_open):
                try:
                    self.assertTrue(d.acquire())
                    self.assertTrue((base / 'native-control.lock').is_file())
                finally:
                    d.release()
