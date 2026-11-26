import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'components' / 'xiaohongshu'))
import xhs_publish  # noqa: E402
from xhs_publish import Jobs, PublishError  # noqa: E402


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        (self.folder / 'a.png').write_bytes(b'\x89PNG fixture')

    def write(self, **fields):
        draft = {'title': '标题', 'body': '第一行\n第二行', 'images': ['a.png'], 'topics': ['天文'],
                 'visibility': '仅自己可见'}
        draft.update(fields)
        path = self.folder / 'draft.json'
        path.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
        return path

    def rejects(self, code, **fields):
        with self.assertRaises(PublishError) as caught:
            xhs_publish.load_draft(self.write(**fields))
        self.assertEqual(caught.exception.code, code)

    def test_valid_draft_resolves_images_and_hashes_content(self):
        draft = xhs_publish.load_draft(self.write())
        self.assertEqual(draft['images'][0]['path'], str((self.folder / 'a.png').resolve()))
        self.assertIsNone(draft['declaration'])
        same = xhs_publish.load_draft(self.write())
        self.assertEqual(xhs_publish.content_sha256(draft), xhs_publish.content_sha256(same))
        (self.folder / 'a.png').write_bytes(b'\x89PNG other')
        changed = xhs_publish.load_draft(self.write())
        self.assertNotEqual(xhs_publish.content_sha256(draft), xhs_publish.content_sha256(changed))

    def test_rejects_drafts_the_editor_would_alter(self):
        self.rejects('DRAFT_TITLE', title='一' * 21)
        self.rejects('DRAFT_BODY', body='看这里 #话题')
        self.rejects('DRAFT_BODY', body='问问 @某人')
        self.rejects('DRAFT_TOPICS', topics=['#天文'])
        self.rejects('DRAFT_VISIBILITY', visibility='所有人')
        self.rejects('DRAFT_DECLARATION', declaration='其它')
        self.rejects('DRAFT_IMAGES', images=[])
        self.rejects('DRAFT_IMAGE_MISSING', images=['missing.png'])
        self.rejects('DRAFT_IMAGE_TYPE', images=['a.gif'])
        self.rejects('DRAFT_UNKNOWN_FIELDS', publish_now=True)

    def test_readback_compares_every_field(self):
        draft = xhs_publish.load_draft(self.write())
        good = {'title': '标题', 'body_text': '第一行\n第二行\n#天文\xa0', 'topics': ['天文'], 'image_count': 1,
                'visibility': '仅自己可见', 'declaration': None}
        self.assertEqual(xhs_publish.readback_matches(draft, good), [])
        self.assertEqual(xhs_publish.readback_matches(draft, dict(good, topics=[], body_text='第一行\n第二行 #天文')),
                         ['body', 'topics'])
        self.assertEqual(xhs_publish.readback_matches(draft, dict(good, visibility='公开可见', image_count=0)),
                         ['images', 'visibility'])


class PathTests(unittest.TestCase):
    def test_windows_paths_map_to_wsl_mounts(self):
        self.assertEqual(xhs_publish.browser_path(r'C:\Users\me\图 1.png', 'wsl'), '/mnt/c/Users/me/图 1.png')
        self.assertEqual(xhs_publish.browser_path('/home/me/a.png', 'wsl'), '/home/me/a.png')
        self.assertEqual(xhs_publish.browser_path(r'C:\a.png', 'native'), r'C:\a.png')


class JobTests(unittest.TestCase):
    def setUp(self):
        self.jobs = Jobs(tempfile.mkdtemp())
        self.job = {'id': '0123456789abcdef', 'content_sha256': '0123456789abcdef' * 4, 'draft': {'title': 't'}}
        self.jobs.transition(self.job, 'prepared')

    def args(self, **values):
        return argparse.Namespace(cdp='http://127.0.0.1:1', timeout=1, **values)

    def test_publish_needs_the_reviewed_confirmation_code(self):
        with self.assertRaises(PublishError) as caught:
            xhs_publish.command_publish(self.args(job=self.job['id'], confirm='ffffffff'), self.jobs)
        self.assertEqual(caught.exception.code, 'CONFIRM_MISMATCH')
        self.assertEqual(self.jobs.load(self.job['id'])['state'], 'prepared')

    def test_a_clicked_job_is_never_clicked_again(self):
        for state in ('publishing', 'unknown', 'published', 'draft_saved'):
            self.jobs.transition(self.job, state)
            with self.assertRaises(PublishError) as caught:
                xhs_publish.command_publish(self.args(job=self.job['id'], confirm='01234567'), self.jobs)
            self.assertEqual(caught.exception.code, 'JOB_STATE')

    def test_unknown_outcomes_are_resolved_by_a_person(self):
        with self.assertRaises(PublishError):
            xhs_publish.command_resolve(argparse.Namespace(job=self.job['id'], outcome='published', evidence='x'), self.jobs)
        self.jobs.transition(self.job, 'unknown')
        xhs_publish.command_resolve(argparse.Namespace(job=self.job['id'], outcome='published', evidence='笔记管理可见'),
                                    self.jobs)
        record = self.jobs.load(self.job['id'])
        self.assertEqual(record['state'], 'published')
        self.assertEqual(record['history'][-1]['evidence'], '笔记管理可见')

    def test_only_one_browser_operation_at_a_time(self):
        with self.jobs.lock():
            with self.assertRaises(PublishError) as caught:
                with self.jobs.lock():
                    pass
        self.assertEqual(caught.exception.code, 'BROWSER_BUSY')
        with self.jobs.lock():
            pass

    def test_job_ids_cannot_escape_the_state_folder(self):
        with self.assertRaises(PublishError):
            self.jobs.path('../../outside')


if __name__ == '__main__':
    unittest.main()

