import unittest,tempfile
from pathlib import Path
import attachments
class AttachmentTests(unittest.TestCase):
    def test_path_traversal_symlink_and_size(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();(root/'small').write_bytes(b'x');(root/'big').write_bytes(b'x'*101);(root/'link').symlink_to(root/'small')
            for path in [root/'../etc/passwd',root/'link',root/'big']:
                with self.assertRaises(ValueError):attachments.read_bound(root,path,100)
    def test_real_regular_file_inside_root(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();(root/'small').write_bytes(b'abc');self.assertEqual(attachments.read_bound(root,root/'small'),b'abc')

