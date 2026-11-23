import base64
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from receiver.codex_worker import Jobs, media_file, static_image_kind
from receiver.desktop_reply import freeze_images
from trigger import media_send

THREAD = '00000000-0000-4000-8000-000000000001'
MESSAGE = '00000000-0000-4000-8000-000000000002'


def png(animated=False):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    body = chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
    if animated:
        body += chunk(b'acTL', struct.pack('>II', 2, 0))
    return b'\x89PNG\r\n\x1a\n' + body + chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00')) + chunk(b'IEND', b'')


class ReceiverImageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.jobs = Jobs(self.root)

    def original(self, peer='owner', schema=None):
        packet = {'id': hashlib.sha256(peer.encode()).hexdigest(), 'scope': ['self', peer], 'request': ['42'],
                  'mode': 'chat', 'messages': [{'role': 'user', 'content': 'draw it'}], 'schema': schema}
        accepted = self.jobs.accept(packet)
        self.jobs.update(packet['id'], state='desktop_queued', thread_id=THREAD, desktop_message_id=MESSAGE)
        (self.root / packet['id']).mkdir()  # created when the original was queued to its thread
        return packet, accepted['digest']

    def test_static_png_and_jpeg_only(self):
        self.assertEqual(static_image_kind(png()), 'png')
        self.assertEqual(static_image_kind(b'\xff\xd8\xff\xe0rest'), 'jpeg')
        self.assertIsNone(static_image_kind(png(animated=True)))
        self.assertIsNone(static_image_kind(b'GIF89a'))

    def test_frozen_images_travel_with_the_completion_and_cannot_change(self):
        packet, digest = self.original()
        with tempfile.TemporaryDirectory() as source:
            path = Path(source) / 'draft.png'
            path.write_bytes(png())
            images = freeze_images(self.root / packet['id'], [path])
            self.assertEqual(freeze_images(self.root / packet['id'], [path]), images)
            self.assertTrue(media_file(self.root / packet['id'], images[0]).is_file())
        completion = {'id': packet['id'], 'input_sha256': digest, 'thread_id': THREAD,
                      'turn_id': 'turn', 'text': 'here it is', 'images': images}
        self.jobs.complete_desktop(completion, THREAD)
        self.jobs.complete_desktop(completion, THREAD)
        served = self.jobs.desktop_media(packet['id'], '0')
        self.assertEqual(base64.b64decode(served['data']), png())
        self.assertEqual(served['sha256'], images[0]['sha256'])
        for changed in (dict(completion, images=[dict(images[0], name='image-1.jpg')]),
                        {k: v for k, v in completion.items() if k != 'images'}):
            with self.assertRaises(ValueError):
                self.jobs.complete_desktop(changed, THREAD)
        with self.assertRaises(IndexError):
            self.jobs.desktop_media(packet['id'], '1')

    def test_missing_animated_or_unsent_images_are_refused(self):
        packet, digest = self.original()
        with tempfile.TemporaryDirectory() as source:
            path = Path(source) / 'moving.png'
            path.write_bytes(png(animated=True))
            with self.assertRaises(ValueError):
                freeze_images(self.root / packet['id'], [path])
        missing = {'name': 'image-1.png', 'bytes': len(png()), 'sha256': hashlib.sha256(png()).hexdigest()}
        with self.assertRaises(ValueError):
            self.jobs.complete_desktop({'id': packet['id'], 'input_sha256': digest, 'thread_id': THREAD,
                                        'turn_id': 'turn', 'text': 'x', 'images': [missing]}, THREAD)
        schema = {'type': 'object', 'properties': {'speak': {'type': 'boolean'}, 'text': {'type': 'string'}},
                  'required': ['speak', 'text'], 'additionalProperties': False}
        group, group_digest = self.original('g@chatroom', schema)
        with tempfile.TemporaryDirectory() as source:
            path = Path(source) / 'draft.png'
            path.write_bytes(png())
            images = freeze_images(self.root / group['id'], [path])
        with self.assertRaises(ValueError):
            self.jobs.complete_desktop({'id': group['id'], 'input_sha256': group_digest, 'thread_id': THREAD,
                'turn_id': 'turn', 'text': json.dumps({'speak': False, 'text': ''}), 'images': images}, THREAD)

    def test_receipt_accepts_only_bounded_image_states(self):
        good = {'id': 'x', 'state': 'sent', 'code': None, 'native_request_id': None, 'reply_sha256': None,
                'images': [{'sha256': 'a' * 64, 'state': 'teleported', 'server_id': None}]}
        with self.assertRaisesRegex(ValueError, 'Bounded native delivery receipt'):
            self.jobs.report_delivery(good)


class FakeStore:
    def __init__(self):
        self.jobs = {'rid': {'peer': 'p', 'state': 'succeeded', 'action': 'send_text'}}

    def get(self, client, rid):
        return self.jobs[rid]


class FakeAssets:
    def __init__(self):
        self.items = {}

    def get(self, client, identity):
        return self.items[identity]


class FakeAPI:
    def __init__(self):
        self.s, self.assets, self.calls = FakeStore(), FakeAssets(), []

    def call(self, request):
        self.calls.append(request['op'])
        if request['op'] == 'upload':
            self.assets.items['asset'] = {'sha256': request['sha256']}
            return {'id': 'asset'}
        job = request['job']
        self.s.jobs[job['request_id']] = dict(job, state='queued')


class MediaSendTests(unittest.TestCase):
    def setUp(self):
        self.data = base64.b64encode(png()).decode()
        self.sha = hashlib.sha256(png()).hexdigest()

    def test_one_submit_one_click_then_only_reads_the_same_job(self):
        api = FakeAPI()
        def advance(api_, job, policy):
            job.update(state='succeeded', result={'state': 'accepted', 'sendClicks': 1, 'serverId': '77',
                                                  'payloadSha256': self.sha})
        first = media_send.send(api, 'c', 'rid', 'p', 0, self.sha, self.data, {}, advance)
        second = media_send.send(api, 'c', 'rid', 'p', 0, self.sha, self.data, {}, advance)
        self.assertEqual((first['state'], first['server_id'], first['request_id']), ('sent', '77', 'rid-image-0'))
        self.assertEqual(second, first)
        self.assertEqual(api.calls, ['upload', 'submit'])

    def test_text_first_matching_bytes_and_honest_outcomes(self):
        api = FakeAPI()
        api.s.jobs['rid']['state'] = 'queued'
        with self.assertRaises(ValueError):
            media_send.send(api, 'c', 'rid', 'p', 0, self.sha, self.data, {}, lambda *a: None)
        api = FakeAPI()
        with self.assertRaises(ValueError):
            media_send.send(api, 'c', 'rid', 'p', 0, 'b' * 64, self.data, {}, lambda *a: None)
        for state, result, expected in (('failed', {'noSend': True}, 'not_sent'),
                                         ('unknown', {}, 'unknown'), ('preparing', {}, 'pending')):
            api = FakeAPI()
            def advance(api_, job, policy, state=state, result=result):
                job.update(state=state, result=result)
            self.assertEqual(media_send.send(api, 'c', 'rid', 'p', 1, self.sha, self.data, {}, advance)['state'], expected)


if __name__ == '__main__':
    unittest.main()
