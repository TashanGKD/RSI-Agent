"""Frozen official geometry through navigation; controls and pixels are isolated."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from rsi_agent.config import WORKBENCH


@unittest.skipUnless(sys.platform == 'linux', 'native Linux navigation interface')
class NativeSearchPopupTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(WORKBENCH / 'wechat'))
        self.addCleanup(sys.path.remove, str(WORKBENCH / 'wechat'))
        self.fixture = json.loads((Path(__file__).parent / 'fixtures/native_search_popup.json').read_text())
        self.main, self.popup = copy.deepcopy(self.fixture['main']), copy.deepcopy(self.fixture['popup'])
        self.identity = self.fixture['identity']
        self.hostile = False
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.controls = Mock()
        self.image = Image.new('RGB', (1200, 900), 'white')

    def xprop(self, argv, **_):
        child = argv[2] == self.popup['id']
        pid = self.identity['pid'] + int(child and self.hostile)
        transient = ('WM_TRANSIENT_FOR(WINDOW): window id # ' + self.main['id'] if child
                     else 'WM_TRANSIENT_FOR:  not found.')
        kinds = '_NET_WM_WINDOW_TYPE_NORMAL' + (', _NET_WM_WINDOW_TYPE_UTILITY' if child else '')
        raw = ('WM_CLASS(STRING) = "wechat", "wechat"\n_NET_WM_PID(CARDINAL) = ' + str(pid)
               + '\nWM_CLIENT_LEADER(WINDOW): window id # ' + self.identity['leader'] + '\n'
               + transient + '\n_NET_WM_WINDOW_TYPE(ATOM) = ' + kinds + '\n')
        return types.SimpleNamespace(returncode=0, stdout=raw)

    def navigate(self, before=None, title='Fixture group', extra=()):
        from operations.navigation import search_named
        driver = types.SimpleNamespace(root=Path(self.folder.name), session_bindings={}, fast_versions=Mock(),
            app_windows=Mock(side_effect=[[self.main, self.popup, *extra], [self.main], [self.main]]))
        original = {'state': 'started', 'main': self.main, 'mainIdentity': self.identity,
                    'beforeWindows': [self.main] if before is None else before}
        own = {'id': '0x100003', 'title': title, 'x': 60, 'y': 90, 'width': 623, 'height': 667}
        with patch('operations.navigation.load', return_value=original), \
                patch('operations.navigation.save') as save, \
                patch('operations.recipes.controls', return_value=self.controls), \
                patch('operations.recipes.activate'), patch('operations.recipes.paste_field'), \
                patch('operations.recipes.screen', return_value=self.image), \
                patch('operations.navigation.first_native_candidate', return_value=[325, 256]) as candidate, \
                patch('operations.navigation.open_selected_popout', return_value=(own, [self.main, own])), \
                patch('operations.navigation.attach', return_value={'verified': True}) as attach, \
                patch('operations.windows.subprocess.run', side_effect=self.xprop), \
                patch('operations.windows.window_identity', return_value=self.identity):
            try:
                result = search_named(driver, {'id': 'a' * 32, 'peer': 'fixture@chatroom'},
                                      {'displayName': 'Fixture group'}, {}, 'Fixture group')
            finally:
                self.candidate_calls, self.attach_calls = candidate.call_count, attach.call_count
                self.bindings = driver.session_bindings
        self.assertIsNone(result)
        self.assertEqual(self.bindings, {'fixture@chatroom': {'verified': True}})
        return save

    def test_observed_compact_popup_reaches_the_same_verified_recipient_path(self):
        self.navigate()
        self.assertEqual(self.candidate_calls, 1)
        self.assertEqual(self.attach_calls, 1)

    def test_existing_calibrated_popup_retains_the_same_path(self):
        self.popup.update(x=self.main['x'] + 76, y=self.main['y'] + 75, width=333)
        self.navigate()

    def test_same_geometry_from_another_process_never_selects_a_row(self):
        self.hostile = True
        with self.assertRaisesRegex(ValueError, 'official search parent identity'):
            self.navigate()
        self.assertEqual(self.candidate_calls, 0)
        self.controls.click.assert_not_called()
        self.assertEqual(self.bindings, {})

    def test_ambiguous_preexisting_and_unobserved_popups_remain_rejected(self):
        from operations.recipes import PreparationError
        with self.assertRaises(PreparationError):
            self.navigate(extra=[dict(self.popup, id='0x100004')])
        with self.assertRaises(PreparationError):
            self.navigate(before=[self.main, self.popup])
        self.popup['width'] = 320
        with self.assertRaises(PreparationError):
            self.navigate()
        self.assertEqual(self.candidate_calls, 0)
        self.controls.click.assert_not_called()

    def test_verified_popup_never_bypasses_the_final_recipient_title(self):
        from operations.recipes import PreparationError
        with self.assertRaisesRegex(PreparationError, 'exact native target'):
            self.navigate(title='Another group')
        self.assertEqual(self.attach_calls, 0)
        self.assertEqual(self.bindings, {})

    def test_main_window_requires_both_native_parent_and_unchanged_scene(self):
        from operations.recipes import main_window, PreparationError
        box = [self.popup['x'], self.popup['y'], self.popup['x'] + self.popup['width'],
               self.popup['y'] + self.popup['height']]
        scene = {'box': box, 'pixelsSHA256': hashlib.sha256(self.image.crop(box).tobytes()).hexdigest(),
                 'sections': [{'kind': 'group', 'y': 210}, {'kind': 'web', 'y': 350}]}
        for unproven in (True, False):
            with self.subTest(unproven=unproven):
                self.hostile = unproven
                self.controls.reset_mock()
                driver = types.SimpleNamespace(root=Path(self.folder.name),
                    app_windows=Mock(side_effect=[[self.main, self.popup], [self.main, self.popup], [self.main]]))
                with patch('operations.windows.subprocess.run', side_effect=self.xprop), \
                        patch('operations.recipes._search_scene', return_value=scene), \
                        patch('operations.recipes.screen', return_value=self.image), \
                        patch('operations.recipes.controls', return_value=self.controls) as factory:
                    if unproven:
                        with self.assertRaises(PreparationError):
                            main_window(driver)
                        factory.assert_not_called()
                    else:
                        self.assertEqual(main_window(driver), self.main)
                        self.controls.click.assert_called_once_with(self.main['x'] + 500, self.main['y'] + 55)
