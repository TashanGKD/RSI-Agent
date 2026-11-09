import tempfile,unittest
from pathlib import Path
import read_metadata
class MetadataTests(unittest.TestCase):
    def test_identity_survives_process_restart_without_body_copy(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'receipt.sqlite';m=read_metadata.Metadata(p);m.remember('peer','123','peer','native-unread');m.close()
            m=read_metadata.Metadata(p);self.assertEqual(m.get('peer','123')['senderId'],'peer');self.assertIsNone(m.get('other','123'));m.close()
    def test_conflict_does_not_overwrite_prior_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            m=read_metadata.Metadata(Path(td)/'receipt.sqlite');m.remember('peer','123','peer','native-unread')
            with self.assertRaises(ValueError):m.remember('peer','123','different','new')
            self.assertEqual(m.get('peer','123')['senderId'],'peer');m.close()

