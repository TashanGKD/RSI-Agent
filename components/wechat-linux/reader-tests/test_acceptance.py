import unittest
from app_message import parse_app_message
from remote import decode_text
from fixtures19 import card, item, TYPE19


def parse(raw, local_type=TYPE19):
    return parse_app_message(raw, local_type=local_type, peer='fixture@chatroom',
                             sender='fixture_sender', decode=decode_text)


class AcceptanceTests(unittest.TestCase):
    def test_stored_plaintext_is_visible(self):
        r = parse(card([item(1, '应当可读的合成文字')]))
        self.assertIn('应当可读的合成文字', r['text'])
        self.assertNotIn('外层预览', r['text'])

    def test_link_image_link_kinds_have_honest_boundaries(self):
        r = parse(card([item(5, '安全标题甲'), item(2, '不得展示的媒体标题'), item(5, '安全标题乙')]))
        self.assertIn('forwarded', r['appMessage'])
        rows = r['appMessage']['forwarded']['items']
        self.assertEqual([x['kind'] for x in rows], [5, 2, 5])
        self.assertFalse(r['appMessage']['forwarded']['fullContentAvailable'])
        self.assertEqual(rows[1]['contentStatus'], 'not_fetched')

    def test_missing_record_is_explicit(self):
        r = parse('<appmsg><type>19</type><title>不是全文</title></appmsg>')
        self.assertIn('record_missing', r['appMessage']['gaps'])
        self.assertNotIn('不是全文', r['text'])
