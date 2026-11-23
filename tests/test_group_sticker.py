import unittest

from trigger import group_sticker

MD5 = 'c' * 32


class FakeStore:
    def __init__(self):
        self.jobs = {}

    def get(self, client, rid):
        return self.jobs[rid]


class FakeAPI:
    def __init__(self, summary):
        self.s = FakeStore()
        self.summary = summary
        self.calls = []

    def call(self, request):
        self.calls.append(request['op'])
        if request['op'] == 'submit':
            self.s.jobs[request['job']['request_id']] = dict(request['job'], state='queued')
        elif request['op'] == 'confirm':
            assert request['token'] == 'token'
            self.s.jobs[request['request_id']]['state'] = 'confirmed'

    def view(self, job):
        return {'state': job['state'], 'request_id': job['request_id'], 'action': job['action'],
                'outcome': {'status': 'sent' if job['state'] == 'succeeded' else 'pending'},
                'preview': {'available': True, 'summary': self.summary}, 'confirmation_token': 'token'}


def advance(api, job, policy):
    job['state'] = {'queued': 'awaiting_confirmation', 'confirmed': 'succeeded'}.get(job['state'], job['state'])


class GroupStickerTests(unittest.TestCase):
    def summary(self, **changes):
        return dict({'action': 'send_sticker', 'peer': 'g@chatroom', 'md5': MD5,
                     'referencePixelsMatched': True, 'messagesSent': 0}, **changes)

    def test_confirms_only_the_exact_verified_favourite_preview(self):
        api = FakeAPI(self.summary())
        result = group_sticker.handle(api, 'rsi-group', 'r', 'g@chatroom', MD5, {}, advance)
        self.assertEqual((result['state'], result['outcome']), ('succeeded', 'sent'))
        self.assertEqual(api.calls, ['submit', 'confirm'])
        group_sticker.handle(api, 'rsi-group', 'r', 'g@chatroom', MD5, {}, advance)
        self.assertEqual(api.calls, ['submit', 'confirm'])

    def test_mismatched_preview_is_never_confirmed(self):
        for summary in (self.summary(md5='d' * 32), self.summary(referencePixelsMatched=False),
                        self.summary(peer='other@chatroom'), self.summary(messagesSent=1)):
            api = FakeAPI(summary)
            result = group_sticker.handle(api, 'rsi-group', 'r', 'g@chatroom', MD5, {}, advance)
            self.assertEqual(result['state'], 'awaiting_confirmation')
            self.assertNotIn('confirm', api.calls)

    def test_original_request_cannot_change_its_sticker(self):
        api = FakeAPI(self.summary())
        group_sticker.handle(api, 'rsi-group', 'r', 'g@chatroom', MD5, {}, advance)
        with self.assertRaises(ValueError):
            group_sticker.handle(api, 'rsi-group', 'r', 'g@chatroom', 'd' * 32, {}, advance)


if __name__ == '__main__':
    unittest.main()
