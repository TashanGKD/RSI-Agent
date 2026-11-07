"""Generated GIF and account directories only; no network, real account or keys."""
import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path
import unittest

WORKER = Path(__file__).resolve().parents[2] / 'src/MacWorker/mac_worker.py'
spec = importlib.util.spec_from_file_location('sticker_worker_fixture', WORKER)
worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
GIF = bytes.fromhex('47494638396101000100800000000000ffffff2c00000000010001000002014c003b')

class LocalSticker(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='sticker-local-')
        self.base = Path(self.folder.name); self.root = self.base / 'source/fixture'; self.root.mkdir(parents=True)
        self.archive = self.base / 'archive'; self.archive.mkdir()
        self.hash = hashlib.md5(GIF).hexdigest()
        self.message = dict(account='fixture', chat='fixture-chat', source='message/message_0.db', time=1700000000,
                            local_id='1', server_id='10', kind=47, metadata=json.dumps({'md5': self.hash}))
        owner = self
        class Library:
            state = owner.archive
            def message(self, mid): return owner.message
            def account_path(self, account):
                if account != 'fixture': raise ValueError('foreign account')
                return owner.root
        self.media = worker.Media(Library())
    def tearDown(self): self.folder.cleanup()
    def candidate(self, directory='emoji', content=GIF):
        path = self.root / directory / (self.hash + '.gif'); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
        return path
    def test_rejects_wrong_content_even_with_matching_name(self):
        self.candidate(content=b'wrong local data')
        with self.assertRaises(ValueError): self.media.attachment('fixture')
    def test_rejects_linked_file_and_parent(self):
        outside = self.base / 'outside.gif'; outside.write_bytes(GIF)
        self.candidate().unlink(); (self.root / 'emoji' / (self.hash + '.gif')).symlink_to(outside)
        with self.assertRaises(ValueError): self.media.attachment('fixture')
        (self.root / 'emoji' / (self.hash + '.gif')).unlink(); (self.root / 'emoji').rmdir()
        (self.root / 'emoji').symlink_to(self.base, target_is_directory=True)
        (self.base / (self.hash + '.gif')).write_bytes(GIF)
        with self.assertRaises(ValueError): self.media.attachment('fixture')
    def test_rejects_oversized_and_foreign_account(self):
        path = self.candidate()
        with path.open('r+b') as file: file.truncate(8 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError): self.media.attachment('fixture')
    def test_rejects_hardlink_to_unrelated_data(self):
        outside = self.base / 'outside.gif'; outside.write_bytes(GIF)
        path = self.candidate(); path.unlink(); os.link(outside, path)
        with self.assertRaises(ValueError): self.media.attachment('fixture')
        self.message['account'] = 'foreign'
        with self.assertRaises(ValueError): self.media.attachment('fixture')
    def test_all_original_local_directories_preserve_gif_bytes(self):
        for directory in ('business/emoticon', 'emoticon', 'emoji', 'msg/emotion', 'msg/emoji'):
            with self.subTest(directory=directory):
                path = self.candidate(directory)
                try: found, mime = self.media.attachment('fixture')
                except ValueError: self.fail('verified local GIF directory is not searched: ' + directory)
                self.assertEqual(Path(found).resolve(), path.resolve())
                self.assertEqual(mime, 'image/gif'); self.assertEqual(path.read_bytes(), GIF)
                path.unlink()

if __name__ == '__main__': unittest.main()
