"""Review counterexamples: no actionable URL forms in any displayed record scalar."""
import json
import unittest
from fixtures19 import card,item,nested
from test_acceptance import parse

class UnschemedURLReviewTests(unittest.TestCase):
    def assert_filtered(self, value):
        for kind, kwargs in ((1, {'text': value}), (5, {'text': value}),
                             (1, {'sender': value}), (1, {'time': value})):
            with self.subTest(kind=kind, field=kwargs):
                r=parse(card([item(kind, **kwargs)]))
                self.assertNotIn('URL_ONLY_SENTINEL', json.dumps(r))
                self.assertEqual(r['appMessage']['parseStatus'],'partial')
                self.assertFalse(r['appMessage']['forwarded']['fullContentAvailable'])
        r=parse(card([nested([item(text=value)],encoded=True)]))
        self.assertNotIn('URL_ONLY_SENTINEL',json.dumps(r))

    def test_protocol_relative_url_is_not_plain_stored_text(self):
        self.assert_filtered('//fixture.invalid/URL_ONLY_SENTINEL')

    def test_bare_article_hostname_url_is_not_plain_stored_text(self):
        self.assert_filtered('mp.weixin.qq.com/s/URL_ONLY_SENTINEL')

    def test_bare_ipv4_url_is_not_plain_stored_text(self):
        self.assert_filtered('192.0.2.1/URL_ONLY_SENTINEL')
