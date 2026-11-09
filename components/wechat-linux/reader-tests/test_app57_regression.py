import ctypes
import ctypes.util
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True

import linux_tool
from app_message import parse_app_message
from remote import decode_text
from fixture import Fixture, PEER, SENDER, QUOTE

spec = importlib.util.spec_from_file_location('baseline_tool', ROOT / 'baseline/linux_tool.py')
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def parse(raw=QUOTE, local_type=(57 << 32) | 49, peer=PEER, sender=SENDER):
    return parse_app_message(raw, local_type=local_type, peer=peer, sender=sender, decode=decode_text)


def compressed(raw):
    """Synthetic zstd frame, produced by the host's already installed library."""
    lib = ctypes.CDLL(ctypes.util.find_library('zstd'))
    lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
    lib.ZSTD_compressBound.restype = ctypes.c_size_t
    lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    lib.ZSTD_compress.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    data = raw.encode()
    out = ctypes.create_string_buffer(lib.ZSTD_compressBound(len(data)))
    n = lib.ZSTD_compress(out, len(out), data, len(data), 1)
    assert not lib.ZSTD_isError(n)
    return out.raw[:n]


class ParserTests(unittest.TestCase):
    def test_text_quote_and_uint64_identity(self):
        r = parse()
        self.assertEqual(r['text'], '同意这个方案\n引用：先做隔离测试')
        c = r['appMessage']
        self.assertEqual(c['parseStatus'], 'parsed')
        self.assertEqual(c['quote']['serverId'], '18446744073709551615')
        self.assertEqual(c['quote']['fromUser'], 'original_sender')
        self.assertEqual(c['quote']['chatUser'], PEER)
        self.assertFalse(c['quote']['originalMessageVerified'])
        self.assertEqual(c['gaps'], ['quoted_original_not_verified'])

    def test_local_type_49_xml_fallback_and_native_subtype_fallback(self):
        self.assertEqual(parse(local_type=49)['text'], parse()['text'])
        no_type = QUOTE.replace('<type>57</type>', '')
        self.assertEqual(parse(no_type)['text'], parse()['text'])
        self.assertIn('unsupported_app_subtype', parse(no_type, local_type=49)['appMessage']['gaps'])

    def test_subtype_conflict_and_bad_subtype_fail_closed(self):
        for xml in (QUOTE.replace('<type>57</type>', '<type>18</type>'),
                    QUOTE.replace('<type>57</type>', '<type>broken</type>')):
            with self.subTest(xml=xml):
                self.assertEqual(parse(xml)['text'], '')
                self.assertEqual(parse(xml)['appMessage']['parseStatus'], 'failed')

    def test_direct_root_bom_xml_declaration_and_cdata(self):
        raw = QUOTE.removeprefix('<msg>').removesuffix('</msg>')
        raw = raw.replace('同意这个方案', '<![CDATA[同意这个方案]]>')
        self.assertEqual(parse('\ufeff<?xml version="1.0"?>' + raw)['text'], parse()['text'])

    def test_group_prefix_exact_only(self):
        for newline in ('\n', '\r\n'):
            self.assertEqual(parse(SENDER + ':' + newline + QUOTE)['text'], parse()['text'])
        for args in ({'sender': 'other'}, {'peer': 'private'}, {'sender': None}):
            self.assertEqual(parse(SENDER + ':\n' + QUOTE, **args)['text'], '')
        self.assertEqual(parse('garbage' + QUOTE)['text'], '')

    def test_zstd_and_utf8_bytes(self):
        self.assertEqual(parse(compressed(QUOTE)), parse())
        self.assertEqual(parse(QUOTE.encode()), parse())

    def test_bad_encoding_compression_null_and_budget(self):
        cases = [(b'\xff', 'TEXT_UTF8_INVALID'),
                 (b'\x28\xb5\x2f\xfdinvalid', 'TEXT_COMPRESSED_INVALID'),
                 (QUOTE + '\0', 'TEXT_NUL'), (None, 'TEXT_TYPE_INVALID'),
                 ('x' * 32769, 'TEXT_OVER_BUDGET'),
                 (compressed('x' * 32769), 'TEXT_OVER_BUDGET')]
        for raw, code in cases:
            with self.subTest(code=code, type=type(raw)):
                r = parse(raw)
                self.assertEqual(r['text'], '')
                self.assertEqual(r['appMessage']['gaps'], [code])

    def test_malformed_and_entity_xml(self):
        for raw in (QUOTE[:-5], '<!DOCTYPE msg [<!ENTITY x "hidden">]>' + QUOTE,
                    '<!DOCTYPE msg SYSTEM "file:///no-such-fixture">' + QUOTE):
            self.assertEqual(parse(raw)['appMessage']['parseStatus'], 'failed')

    def test_xml_depth_and_node_count_budget(self):
        for extension in ('<x>' * 33 + '</x>' * 33, '<x/>' * 1025):
            r = parse(QUOTE.replace('</appmsg>', extension + '</appmsg>'))
            self.assertEqual(r['appMessage']['gaps'], ['xml_structure_budget'])

    def test_duplicate_and_nested_fields_not_silently_selected(self):
        variants = [QUOTE.replace('<title>', '<title>wrong</title><title>'),
                    QUOTE.replace('<svrid>', '<svrid>123</svrid><svrid>'),
                    QUOTE.replace('</refermsg>', '</refermsg><refermsg/>'),
                    QUOTE.replace('</msg>', '<appmsg/></msg>'),
                    QUOTE.replace('同意这个方案', '<x>hidden</x>')]
        for raw in variants:
            with self.subTest(raw=raw):
                self.assertEqual(parse(raw)['text'], '')
                self.assertEqual(parse(raw)['appMessage']['parseStatus'], 'failed')

    def test_nested_card_title_never_becomes_reply(self):
        raw = QUOTE.replace('<title>同意这个方案</title>', '')
        raw = raw.replace('<refermsg>', '<refermsg><appmsg><title>内层标题</title></appmsg>')
        r = parse(raw)
        self.assertEqual(r['text'], '引用：先做隔离测试')
        self.assertFalse(r['appMessage']['replyTextAvailable'])
        self.assertIn('reply_text_missing', r['appMessage']['gaps'])
        self.assertEqual(parse('<wrapper>' + QUOTE + '</wrapper>')['text'], '')

    def test_image_quote_never_claims_media_or_exposes_xml(self):
        raw = QUOTE.replace('<type>1</type>', '<type>3</type>').replace(
            '先做隔离测试', '&lt;img aeskey="fixture-only"/&gt;')
        r = parse(raw)
        self.assertEqual(r['text'], '同意这个方案\n引用：[图片]')
        self.assertNotIn('fixture-only', json.dumps(r))
        self.assertEqual(r['appMessage']['quote']['mediaStatus'], 'not_fetched')
        self.assertFalse(r['appMessage']['quote']['textAvailable'])
        self.assertIn('quoted_content_not_read', r['appMessage']['gaps'])

    def test_other_quoted_kinds_and_missing_type_remain_partial(self):
        for kind in ('34', '43', '49', '999', 'bad'):
            r = parse(QUOTE.replace('<type>1</type>', '<type>' + kind + '</type>'))
            self.assertEqual(r['appMessage']['parseStatus'], 'partial')
            self.assertIsNone(r['appMessage']['quote']['text'])

    def test_other_unsupported_card_title_is_not_full_body(self):
        raw = QUOTE.replace('<type>57</type>', '<type>18</type>')
        r = parse(raw, local_type=(18 << 32) | 49)
        self.assertEqual(r['text'], '')
        self.assertEqual(r['appMessage']['parseStatus'], 'unsupported')

    def test_missing_quote_and_empty_text_explicit(self):
        r = parse('<appmsg><type>57</type><title>回复</title></appmsg>')
        self.assertEqual(r['text'], '回复')
        self.assertEqual(r['appMessage']['parseStatus'], 'partial')
        self.assertIn('refermsg_missing', r['appMessage']['gaps'])
        r = parse(QUOTE.replace('先做隔离测试', ''))
        self.assertIn('quoted_text_missing', r['appMessage']['gaps'])

    def test_signed_identity_normalized_invalid_identity_not_invented(self):
        def with_id(value):
            return parse(QUOTE.replace('18446744073709551615', value))['appMessage']
        self.assertEqual(with_id('-1')['quote']['serverId'], '18446744073709551615')
        for value in ('0', '01', '18446744073709551616', '-9223372036854775809', '1.0', 'junk', ''):
            with self.subTest(value=value):
                c = with_id(value)
                self.assertIsNone(c['quote']['serverId'])
                self.assertIn('quoted_server_id_missing_or_invalid', c['gaps'])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()

    def tearDown(self):
        self.f.close()

    def test_old_empty_new_readable_with_same_envelope(self):
        self.f.add()
        old = self.f.read(baseline)
        new = self.f.read(linux_tool)
        self.assertEqual(old['messages'][0]['text'], '同意这个方案\n引用：先做隔离测试')
        self.assertEqual(new['messages'][0]['text'], '同意这个方案\n引用：先做隔离测试')
        row = dict(new['messages'][0])
        row.pop('appMessage')
        row['text'] = old['messages'][0]['text']
        old['messages'][0].pop('appMessage')
        self.assertEqual(row, old['messages'][0])
        self.assertEqual(new['coverage'], old['coverage'])
        self.assertEqual(new['receipts'], old['receipts'])

    def test_bad_card_does_not_drop_neighbor_text_or_quote(self):
        self.f.add('<msg>broken', server=101)
        self.f.add('plain text', kind=1, server=102)
        self.f.add(compressed(QUOTE), server=103)
        rows = self.f.read(linux_tool)['messages']
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['appMessage']['parseStatus'], 'failed')
        self.assertEqual(rows[1]['text'], 'plain text')
        self.assertNotIn('appMessage', rows[1])
        self.assertTrue(rows[2]['appMessage']['quote']['textAvailable'])

    def test_time_identity_peer_and_limit_contract_unchanged(self):
        self.f.add(server=101, at=100)
        self.f.add(server=102, at=102)  # end is exclusive
        self.assertEqual([r['serverId'] for r in self.f.read(linux_tool)['messages']], ['101'])
        r = self.f.read(linux_tool, server_ids=['102'])
        self.assertEqual([x['serverId'] for x in r['messages']], ['102'])
        r = self.f.read(linux_tool, server_ids=['103'])
        self.assertEqual(r['messages'], [])
        self.assertEqual(r['coverage']['missingIds'], ['103'])
        self.assertEqual(self.f.read(linux_tool, peer='other@chatroom')['messages'], [])
        self.f.add(server=103)
        self.assertTrue(self.f.read(linux_tool, limit=1)['coverage']['truncated'])
        with self.assertRaises(ValueError):
            self.f.read(linux_tool, start=0, end=32*86400)

    def test_existing_text_and_media_rows_identical_to_baseline(self):
        self.f.add('ordinary text', kind=1)
        self.f.add(b'not-text', kind=3, server=102)
        self.assertEqual(self.f.read(linux_tool), self.f.read(baseline))

    def test_no_quote_lookup_or_native_opener(self):
        self.f.add()
        # Bound injected opener is used; a card cannot fetch its referenced ID.
        with patch.object(linux_tool, 'native', side_effect=AssertionError('no live access')):
            r = self.f.read(linux_tool)
        self.assertEqual(self.f.opened, ['contact/contact.db', 'message/message_0.db',
                                        'session/session.db', 'session/session.db', 'message/media_0.db'])
        self.assertFalse(r['messages'][0]['appMessage']['quote']['originalMessageVerified'])

    def test_later_old_window_message_not_mistaken_for_complete_timeline(self):
        self.f.add(server=101, at=100)
        first = self.f.read(linux_tool)
        self.f.add(server=102, at=101)
        later = self.f.read(linux_tool)
        self.assertTrue(first['coverage']['messageMetadataComplete'])
        self.assertTrue(later['coverage']['messageMetadataComplete'])
        self.assertEqual(len(first['messages']), 1)
        self.assertEqual(len(later['messages']), 2)


if __name__ == '__main__':
    unittest.main()
