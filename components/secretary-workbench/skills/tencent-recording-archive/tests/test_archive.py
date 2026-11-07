"""Local-only integration checks; generated fixtures, no accounts or network."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from unittest.mock import patch
from types import SimpleNamespace

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'recording_archive.py'


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.video = self.root / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=s=64x64:r=10', '-f', 'lavfi', '-i',
                        'anullsrc=r=8000:cl=mono', '-t', '0.3', '-c:v',
                        'mpeg4', '-c:a', 'aac', str(self.video)], check=True)
        self.md = self.root / 'source.md'
        self.md.write_text('# 测试会议逐字稿\n\n机器转写，未人工校订。\n\nP0 00:00:00 测试人：你好。\n')
        self.out = self.root / 'archive'

    def call(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True)

    def args(self, **overrides):
        values = {'video': self.video, 'transcript': self.md, 'output': self.out,
                  'title': '测试；$(不执行)', 'date': '2026-10-10', 'record-id': '123'}
        values.update(overrides)
        return ['archive'] + [part for k, v in values.items() for part in ['--' + k, str(v)]]

    def rejected(self, result, error):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(error, result.stderr)
        self.assertFalse(self.out.exists())

    def test_no_args_only_usage(self):
        r = self.call()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('usage:', r.stdout)

    def test_dry_run_no_files(self):
        r = self.call(*self.args())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'], 'dry_run')
        self.assertFalse(self.out.exists())

    def test_reject_partial_download(self):
        pending = self.root / 'video.mp4.crdownload'
        pending.write_bytes(self.video.read_bytes())
        self.rejected(self.call(*self.args(video=pending), '--apply'), 'incomplete_download')

    def test_reject_html_as_video(self):
        self.video.write_text('<html>login</html>')
        self.rejected(self.call(*self.args(), '--apply'), 'invalid_video')

    def test_reject_symlink_destination(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        self.out.symlink_to(elsewhere, target_is_directory=True)
        r = self.call(*self.args(), '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('symlink', r.stderr)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_existing_directory_never_overwritten(self):
        self.out.mkdir()
        keep = self.out / 'keep.txt'
        keep.write_text('保留')
        r = self.call(*self.args(), '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(keep.read_text(), '保留')
        self.assertEqual(list(self.out.iterdir()), [keep])

    def test_archive_verify_repeat_and_tamper(self):
        r = self.call(*self.args(), '--apply')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.out / 'video.mp4').read_bytes(), self.video.read_bytes())
        self.assertEqual(self.call('verify', self.out).returncode, 0)
        repeat = self.call(*self.args(), '--apply')
        self.assertEqual(repeat.returncode, 0, repeat.stderr)
        self.assertEqual(json.loads(repeat.stdout)['status'], 'already_archived')
        (self.out / 'transcript.md').write_text('changed')
        failed = self.call('verify', self.out)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('hash_mismatch', failed.stderr)

    def test_reject_invalid_date(self):
        self.rejected(self.call(*self.args(date='2026-02-30'), '--apply'), 'invalid_date')

    def transcript_fixture(self):
        raw = self.root / 'raw.json'
        pids = self.root / 'pids.json'
        raw.write_text(json.dumps({'minutes': {'paragraphs': [
            {'pid': '1', 'start_time': 2000, 'end_time': 2500,
             'speaker': {'user_name': '乙'}, 'sentences': [{'words': [{'text': '再见。'}]}]},
            {'pid': '0', 'start_time': 0, 'end_time': 1000,
             'speaker': {'user_name': '甲'}, 'sentences': [{'words': [{'text': '你好。'}]}]}
        ]}}, ensure_ascii=False))
        pids.write_text(json.dumps({'pids': [{'pid': '0'}, {'pid': '1'}], 'total': 2}))
        return raw, pids

    def test_transcript_keeps_all_text_order_speakers(self):
        raw, pids = self.transcript_fixture()
        dest = self.root / 'transcript.md'
        r = self.call('transcript', '--input', raw, '--pids', pids,
                      '--title', '测试', '--output', dest, '--apply')
        self.assertEqual(r.returncode, 0, r.stderr)
        text = dest.read_text()
        self.assertLess(text.index('你好。'), text.index('再见。'))
        self.assertIn('甲', text)
        self.assertIn('乙', text)
        self.assertIn('00:00:02', text)

    def test_transcript_missing_pid_rejected(self):
        raw, pids = self.transcript_fixture()
        pids.write_text(json.dumps({'pids': [{'pid': str(i)} for i in range(3)], 'total': 3}))
        dest = self.root / 'transcript.md'
        r = self.call('transcript', '--input', raw, '--pids', pids,
                      '--title', '测试', '--output', dest, '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('incomplete_transcript', r.stderr)
        self.assertFalse(dest.exists())

    def test_transcript_occupied_output_preserved(self):
        raw, pids = self.transcript_fixture()
        r = self.call('transcript', '--input', raw, '--pids', pids,
                      '--title', '测试', '--output', self.md, '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('exists', r.stderr)
        self.assertIn('测试会议', self.md.read_text())

    def test_empty_transcript_not_reported_complete(self):
        raw, pids = self.transcript_fixture()
        raw.write_text(json.dumps({'minutes': {'paragraphs': []}}))
        pids.write_text(json.dumps({'pids': [], 'total': 0}))
        dest = self.root / 'empty.md'
        r = self.call('transcript', '--input', raw, '--pids', pids,
                      '--title', '测试', '--output', dest, '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('empty_transcript', r.stderr)
        self.assertFalse(dest.exists())

    def test_failed_copy_cleans_staging_and_preserves_source(self):
        spec = importlib.util.spec_from_file_location('recording_archive', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        args = SimpleNamespace(video=self.video, transcript=self.md, output=self.out,
                               title='测试', date='2026-10-10', record_id='123', apply=True)
        original = self.video.read_bytes()
        def broken_copy(source, dest):
            pathlib.Path(dest).write_bytes(b'partial')
            raise OSError('simulated disk full')
        with patch.object(module.shutil, 'copyfile', side_effect=broken_copy):
            with self.assertRaises(OSError):
                module.archive(args)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.video.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.archive*')))


if __name__ == '__main__':
    unittest.main()
