import os
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import sender
from operations.driver import NativeDriver
from operations.recipes import search_identity
from operations.windows import parse_app_windows


class HostInstallationTests(unittest.TestCase):
    def test_calibrated_editor_excludes_its_frame_and_still_protects_content(self):
        from PIL import Image, ImageDraw
        path = Path(__file__).resolve().parents[1] / 'host_support/file_transport.py'
        spec = importlib.util.spec_from_file_location('host_file_transport', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        image = Image.new('RGB', (623, 667), 'white')
        draw = ImageDraw.Draw(image)
        draw.line((21, 526, 581, 526), fill=(229, 229, 229))
        ui = SimpleNamespace(cfg={'header_box': [1, 35, 622, 82], 'editor': [280, 554],
                                  'send': [573, 635], 'editor_content_top': 532},
                             ui=SimpleNamespace(screenshot=lambda: image))
        module.require_empty_editor(ui)
        draw.rectangle((50, 545, 70, 565), fill='black')
        with self.assertRaises(ValueError):
            module.require_empty_editor(ui)

    def test_reused_chat_window_keeps_the_editor_inset_when_it_moves(self):
        from PIL import Image, ImageDraw
        from host_support.file_transport import require_empty_editor
        from operations import recipes

        peer = 'fixture@chatroom'
        window = {'id': '0x2', 'title': 'Fixture group', 'x': 0, 'y': 90, 'width': 623, 'height': 667}
        original = {'peer': peer, 'observedTitle': window['title'], 'editor': [280, 614],
                    'editor_content_top': 592}
        target = {'username': peer, 'displayName': window['title']}
        driver = SimpleNamespace(tool=lambda: SimpleNamespace(resolve=lambda _: target),
                                 binding=lambda _: original, app_windows=lambda: [window],
                                 session_bindings={})
        image = Image.new('RGB', (623, 757), 'white')
        draw = ImageDraw.Draw(image)
        draw.line((21, 616, 581, 616), fill=(229, 229, 229))
        with patch.object(recipes, 'main_window', return_value=window), patch.object(recipes, 'controls'), \
             patch.object(recipes, 'activate'), patch.object(recipes, 'screen', return_value=image):
            recipes.selected(driver, {'peer': peer})
        ui = SimpleNamespace(cfg=driver.session_bindings[peer], ui=SimpleNamespace(screenshot=lambda: image))
        require_empty_editor(ui)
        self.assertEqual(original['editor_content_top'], 592)
        draw.rectangle((50, 634, 70, 654), fill='black')
        with self.assertRaisesRegex(ValueError, 'existing contents retained'):
            require_empty_editor(ui)

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
