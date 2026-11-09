"""Exact supported scene proofs are synthetic; no native commands are executed."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from operations.recipes import main_window, PreparationError


class PackagedSearchScene(unittest.TestCase):
    def test_verified_native_parent_and_frozen_scene_can_close_owned_search(self):
        main = {'id': '0x1', 'title': 'Weixin', 'x': 181, 'y': 117, 'width': 905, 'height': 667}
        popup = {'id': '0x2', 'title': 'wechat', 'x': 257, 'y': 192, 'width': 333, 'height': 69}
        image = Image.new('RGB', (1200, 900), 'white')
        box = [257, 192, 590, 261]
        scene = {'box': box, 'pixelsSHA256': hashlib.sha256(image.crop(box).tobytes()).hexdigest(), 'sections': []}
        class Controls:
            def __init__(self): self.clicked = []
            def click(self, *point): self.clicked.append(point)
            def wait(self, _): pass
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory:
            class Driver:
                root = Path(directory)
                calls = 0
                def app_windows(self):
                    self.calls += 1
                    return [main, popup] if self.calls <= 2 else [main]
            control = Controls()
            with patch('operations.windows.search_parent_proof', return_value={'verified': True}), \
                 patch('operations.recipes._search_scene', return_value=scene), \
                 patch('operations.recipes.screen', return_value=image), \
                 patch('operations.recipes.controls', return_value=control):
                self.assertEqual(main_window(Driver()), main)
            self.assertEqual(control.clicked, [(681, 172)])

    def test_absent_native_parent_never_obtains_controls(self):
        class Driver:
            def app_windows(self):
                return [{'id': '0x1', 'title': 'Weixin', 'x': 181, 'y': 117, 'width': 905, 'height': 667},
                        {'id': '0x2', 'title': 'wechat', 'x': 257, 'y': 192, 'width': 333, 'height': 69}]
        with patch('operations.windows.search_parent_proof', side_effect=ValueError('unproven')), \
             patch('operations.recipes.controls') as controls:
            with self.assertRaises(PreparationError): main_window(Driver())
            controls.assert_not_called()
