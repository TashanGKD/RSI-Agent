import os
import tempfile
import unittest
from pathlib import Path
from bridge.private import directory,read,write

class PrivateTests(unittest.TestCase):
    def test_roundtrip_private_and_symlink_parent_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();os.chmod(root,0o700)
            p=root/'state.json';write(p,{'a':1});self.assertEqual(read(p),{'a':1})
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            link=root/'alias';link.symlink_to(root,target_is_directory=True)
            with self.assertRaises(ValueError):read(link/'state.json')
    def test_world_readable_credentials_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()/'state.json';p.write_text('{}');os.chmod(p,0o644)
            with self.assertRaises(ValueError):read(p)
