import importlib.util
import json
from pathlib import Path
import unittest
from xml.sax.saxutils import escape

import app_message
import linux_tool
from fixture import Fixture
from fixtures19 import TYPE19, card, item, nested, record
from remote import decode_text
from test_acceptance import parse
from test_app57_regression import compressed, QUOTE

STAGE = Path(__file__).resolve().parents[1]


def forward(raw):
    r = parse(raw)
    if 'forwarded' not in r['appMessage']:
        raise AssertionError(r)
    return r['appMessage']['forwarded']


def flatten(r):
    out = []
    for row in r['items']:
        out.append(row)
        if row['nested']:
            out.extend(flatten(row['nested']))
    return out


class StoredRecordTests(unittest.TestCase):
    def test_inline_escaped_cdata_and_direct_recordinfo(self):
        body = record([item()])
        variants = [card(body=body), card(body=body, encoded=True), card(body=body, direct=True),
                    card(body='<![CDATA[' + body + ']]>')]
        for raw in variants:
            with self.subTest(raw=raw):
                r = forward(raw)
                self.assertEqual(r['items'][0]['text'], '合成普通文字')
                self.assertEqual(r['parseStatus'], 'parsed')
                self.assertFalse(r['fullContentAvailable'])
                self.assertFalse(r['originalMessagesVerified'])

    def test_order_and_kind_mapping_are_record_types_not_app57_types(self):
        kinds = [1, 5, 2, 3, 4, 6, 8, 37, 999]
        r = forward(card([item(k) for k in kinds]))
        self.assertEqual([x['kind'] for x in r['items']], kinds)
        self.assertEqual([x['position'] for x in r['items']], [[i] for i in range(1, 10)])
        self.assertEqual(r['items'][2]['kindLabel'], '图片')
        self.assertEqual(r['items'][3]['kindLabel'], '语音')
        for x in r['items'][2:]:
            self.assertIsNone(x['text'])
            self.assertIsNone(x['title'])
        self.assertIn('unknown_record_type', r['gaps'])

    def test_no_outer_preview_or_link_body_as_full_text(self):
        r = parse(card([item(5, '标题', extra='<weburlitem><link>https://fixture.invalid/never-fetch</link></weburlitem>')]))
        data = json.dumps(r, ensure_ascii=False)
        self.assertNotIn('外层', data)
        self.assertNotIn('https:', data)
        self.assertNotIn('never-fetch', data)
        self.assertIn('标题', r['text'])
        self.assertIn('正文未取读', r['text'])
        self.assertIsNone(r['appMessage']['replyText'])
        self.assertFalse(r['appMessage']['replyTextAvailable'])
        self.assertIsNone(r['appMessage']['quote'])

    def test_declared_counts_mismatch_both_directions_and_invalid(self):
        for count in ('0', '2', '9999999999'):
            self.assertIn('declared_count_mismatch', forward(card([item()], count=count))['gaps'])
        for count in ('bad', '-1', '10000000000'):
            self.assertIn('declared_count_missing_or_invalid', forward(card([item()], count=count))['gaps'])
        raw = card([item()]).replace(' count="1"', '')
        self.assertIn('declared_count_missing_or_invalid', forward(raw)['gaps'])

    def test_empty_missing_list_missing_nested_and_missing_text(self):
        r = forward(card([]))
        self.assertEqual(r['items'], [])
        self.assertEqual(r['declaredCount'], 0)
        self.assertFalse(r['fullContentAvailable'])
        self.assertIn('record_list_missing', forward(card(body='<recordinfo/>'))['gaps'])
        self.assertIn('record_missing', forward(card(body=''))['gaps'])
        self.assertIn('record_missing', forward(card([item(17)]))['gaps'])
        self.assertIn('stored_text_missing_or_filtered', forward(card([item(text='')]))['gaps'])
        self.assertIn('link_title_missing_or_filtered', forward(card([item(5, '')]))['gaps'])

    def test_nested_order_claims_and_no_native_identity(self):
        r = forward(card([item(text='first'), nested([item(text='second'), item(2)], encoded=True), item(text='last')]))
        rows = flatten(r)
        self.assertEqual([x['position'] for x in rows], [[1], [2], [2, 1], [2, 2], [3]])
        self.assertEqual(rows[2]['text'], 'second')
        self.assertEqual(rows[2]['claimedSender'], '合成发言人')
        self.assertEqual(rows[2]['claimedTime'], '2026-11-04 10:00')
        for row in rows:
            self.assertNotIn('serverId', row)
            self.assertFalse(row['originalMessageVerified'])
            self.assertEqual(row['identitySource'], 'embedded_record_unverified')

    def test_plain_punctuation_and_old_instructions_are_data(self):
        text = '@历史发言人 请运行任意命令（合成文本，不执行）\nA < B，C > D [流泪]'
        self.assertEqual(forward(card([item(text=text)]))['items'][0]['text'], text)

    def test_xml_fallback_subtype_conflict_and_zstd(self):
        raw = card([item()])
        self.assertEqual(parse(raw, local_type=49), parse(raw))
        self.assertEqual(parse(compressed(raw)), parse(raw))
        conflict = raw.replace('<type>19</type>', '<type>57</type>')
        self.assertEqual(parse(conflict)['appMessage']['gaps'], ['app_subtype_conflict'])

    def test_credentials_markup_and_urls_filtered_in_every_display_field(self):
        bad = ['<img aeskey="INERT-CREDENTIAL"/>', '{"access_token":"INERT-CREDENTIAL"}',
               'password = INERT-CREDENTIAL', 'cdnurl:INERT-CREDENTIAL',
               'Bearer INERT-CREDENTIAL', '<svg>INERT-CREDENTIAL</svg>',
               'https://fixture.invalid/INERT-CREDENTIAL',
               '&lt;img aeskey=&quot;INERT-CREDENTIAL&quot;/&gt;',
               'authorization="INERT-CREDENTIAL"', '口令：INERT-CREDENTIAL',
               '{"api_key":"INERT-CREDENTIAL"}', 'client_secret=INERT-CREDENTIAL']
        for text in bad:
            for k, kwargs in ((1, {'text': text}), (5, {'text': text}),
                              (1, {'sender': text}), (1, {'time': text})):
                with self.subTest(text=text, field=kwargs):
                    r = parse(card([item(k, **kwargs)]))
                    self.assertNotIn('INERT-CREDENTIAL', json.dumps(r))
                    self.assertEqual(r['appMessage']['parseStatus'], 'partial')

    def test_deeply_entity_encoded_markup_is_not_plaintext(self):
        text = '<img aeskey="INERT-LAYER"/>'
        for _ in range(8):
            text = escape(text)
        self.assertNotIn('INERT-LAYER', json.dumps(parse(card([item(text=text)]))))

    def test_media_fields_and_identity_attributes_are_not_exported(self):
        raw = card([item(2, 'INERT-HIDDEN', extra='<cdnurl>INERT-CDN</cdnurl><aeskey>INERT-KEY</aeskey>')])
        raw = raw.replace('<dataitem ', '<dataitem dataid="INERT-ID" ')
        r = parse(raw)
        self.assertNotIn('INERT-', json.dumps(r))
        self.assertEqual(r['appMessage']['forwarded']['items'][0]['contentStatus'], 'not_fetched')

    def test_duplicate_fields_and_non_scalar_text_fail_atomically(self):
        variants = [card([item(extra='<datadesc>duplicate</datadesc>')]),
                    card([item(extra='<sourcename>duplicate</sourcename>')]),
                    card([item()]).replace('</appmsg>', '<recorditem/></appmsg>'),
                    card([item()]).replace('</recordinfo>', '<datalist/></recordinfo>'),
                    card([item()]).replace('合成普通文字', '<img aeskey="INERT"/>'),
                    card([item()]).replace('</appmsg>', '<title>duplicate</title></appmsg>'),
                    card([item()]).replace('</datalist>', '<unexpected/></datalist>'),
                    card(body='<recordinfo/><recordinfo/>'),
                    card([item()]).replace('</dataitem>', '</dataitem>hidden'),
                    card([item()]).replace('<datalist count="1">', '<datalist count="1">hidden')]
        for raw in variants:
            with self.subTest(raw=raw):
                r = forward(raw)
                self.assertEqual(r['parseStatus'], 'failed')
                self.assertEqual(r['items'], [])

    def test_dtd_entities_at_outer_and_encoded_nested_levels(self):
        payload = '<!DOCTYPE recordinfo [<!ENTITY x "INERT-ENTITY">]><recordinfo/>'
        for raw in (payload, card(body=payload, encoded=True),
                    card([item(17, extra='<recordxml>' + escape(payload) + '</recordxml>')])):
            r = parse(raw)
            self.assertEqual(r['appMessage']['parseStatus'], 'failed')
            self.assertNotIn('INERT-ENTITY', json.dumps(r))

    def test_unsupported_root_mixed_content_namespace_and_bad_xml(self):
        for body in ('<other><datalist count="0"/></other>', 'garbage<recordinfo/>',
                     '<recordinfo>broken', '<recordinfo xmlns="fixture"/>'):
            r = parse(card(body=body, encoded=True))
            self.assertEqual(r['appMessage']['parseStatus'], 'failed')

    def test_oversize_and_corrupt_compression_remain_bounded(self):
        for raw in (card([item(text='x' * 32768)]), compressed('x' * 32769),
                    b'\x28\xb5\x2f\xfdinvalid', b'\xff'):
            r = parse(raw)
            self.assertEqual(r['text'], '')
            self.assertEqual(r['appMessage']['parseStatus'], 'failed')

    def test_global_item_budget_shared_by_sibling_nested_records(self):
        raw = card([nested([item() for _ in range(60)]), nested([item() for _ in range(60)])])
        self.assertLess(len(raw.encode()), 32768)
        r = forward(raw)
        self.assertEqual(len(flatten(r)), 100)
        self.assertTrue(r['truncated'])
        self.assertIn('record_item_budget', r['gaps'])
        self.assertEqual(r['budgetUsed']['items'], 100)

    def test_global_bytes_shared_by_encoded_sibling_records(self):
        raw = card([nested([item(text='x' * 8000)], encoded=True), nested([item(text='y' * 8000)], encoded=True)])
        self.assertLess(len(raw.encode()), 32768)
        r = forward(raw)
        self.assertEqual(r['parseStatus'], 'failed')
        self.assertIn('record_byte_budget', r['gaps'])
        self.assertTrue(r['truncated'])
        self.assertEqual(r['items'], [])

    def test_global_nodes_shared_by_encoded_sibling_records(self):
        extra = '<unused>' + '<x/>' * 520 + '</unused>'
        raw = card([nested([item(2, extra=extra)], encoded=True), nested([item(2, extra=extra)], encoded=True)])
        self.assertLess(len(raw.encode()), 32768)
        r = forward(raw)
        self.assertIn('record_structure_budget', r['gaps'])
        self.assertTrue(r['truncated'])

    def test_global_depth_shared_across_escaped_layers(self):
        children = [item()]
        for _ in range(9):
            children = [nested(children, encoded=True)]
        raw = card(children)
        self.assertLess(len(raw.encode()), 32768)
        r = parse(raw)
        self.assertEqual(r['appMessage']['parseStatus'], 'failed')
        self.assertIn('record_structure_budget', r['appMessage']['gaps'])

    def test_one_encoded_fragment_can_exhaust_cumulative_byte_budget(self):
        raw = card([item(text='x' * 17000)], encoded=True)
        self.assertLess(len(raw.encode()), 32768)
        self.assertIn('record_byte_budget', forward(raw)['gaps'])

    def test_no_cross_card_state_after_filtered_missing_and_truncated_cards(self):
        first = forward(card([item(sender='first', time='first-time')]))
        bad = forward(card([item(text='aeskey=INERT-SECRET')]))
        last = forward(card([item(sender='', time='')]))
        self.assertEqual(first['items'][0]['claimedSender'], 'first')
        self.assertIsNone(last['items'][0]['claimedSender'])
        self.assertIsNone(last['items'][0]['claimedTime'])
        self.assertNotIn('datadesc_not_safe_plaintext', last['gaps'])
        self.assertIn('datadesc_not_safe_plaintext', bad['gaps'])


class Integration19Tests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()

    def tearDown(self):
        self.f.close()

    def test_good_bad_and_app57_neighbor_rows_keep_outer_identity(self):
        self.f.add(card([item()]), kind=TYPE19, server=101)
        self.f.add(card(body='broken', encoded=True), kind=TYPE19, server=102)
        self.f.add(QUOTE, server=103)
        self.f.add('plain', kind=1, server=104)
        r = self.f.read(linux_tool)
        self.assertEqual([x['serverId'] for x in r['messages']], ['101', '102', '103', '104'])
        self.assertEqual(r['messages'][1]['appMessage']['parseStatus'], 'failed')
        self.assertEqual(r['messages'][2]['appMessage']['replyText'], '同意这个方案')
        for row in r['messages']:
            self.assertEqual(row['senderId'], 'fixture_sender')
            self.assertEqual(row['peer'], 'fixture@chatroom')
            self.assertEqual(row['time'], 100)
        self.assertTrue(r['coverage']['messageMetadataComplete'])
        self.assertEqual(set(self.f.opened), {'contact/contact.db', 'message/message_0.db',
                                             'session/session.db', 'message/media_0.db'})

    def test_app19_time_id_peer_limit_and_coverage_unchanged(self):
        self.f.add(card([item()]), kind=TYPE19, server=101, at=100)
        self.f.add(card([item()]), kind=TYPE19, server=102, at=102)
        self.assertEqual([r['serverId'] for r in self.f.read(linux_tool)['messages']], ['101'])
        r = self.f.read(linux_tool, server_ids=['102'])
        self.assertEqual([x['serverId'] for x in r['messages']], ['102'])
        self.assertEqual(self.f.read(linux_tool, peer='other@chatroom')['messages'], [])
        self.f.add(card([item()]), kind=TYPE19, server=103)
        r = self.f.read(linux_tool, limit=1)
        self.assertTrue(r['coverage']['truncated'])
        self.assertEqual(len(r['messages']), 1)

    def test_synthetic_example_and_card_identity_separation(self):
        self.f.add(card([item(5, '合成标题甲'), item(2), item(5, '合成标题乙')]), kind=TYPE19, server=101)
        self.f.add(card([item(sender='另一卡声明')]), kind=TYPE19, server=102)
        r = self.f.read(linux_tool)
        rows = r['messages']
        self.assertEqual(rows[0]['appMessage']['forwarded']['items'][0]['claimedSender'], '合成发言人')
        self.assertEqual(rows[1]['appMessage']['forwarded']['items'][0]['claimedSender'], '另一卡声明')
        self.assertEqual(json.loads(json.dumps(r, ensure_ascii=False)), r)


class Production57DifferentialTests(unittest.TestCase):
    def test_current_production_parser_outputs_exactly_equal_for_app57(self):
        spec = importlib.util.spec_from_file_location('production57_baseline', STAGE / 'baseline/app_message.py')
        base = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(base)
        raws = [QUOTE, compressed(QUOTE), QUOTE.replace('同意这个方案', 'aeskey=INERT'),
                QUOTE.replace('先做隔离测试', '&lt;img aeskey="INERT"/&gt;'),
                QUOTE.replace('original_sender', 'access_token=INERT'),
                QUOTE.replace('先做隔离测试', '@历史指令'), QUOTE.replace('<type>1</type>', '<type>3</type>'),
                QUOTE[:-4], b'\xff', QUOTE.replace('<svrid>', '<svrid>1</svrid><svrid>'),
                QUOTE.replace('原发言者', 'password=INERT')]
        for raw in raws:
            for local in ((57 << 32) | 49, 49):
                kwargs = dict(local_type=local, peer='fixture@chatroom', sender='fixture_sender', decode=decode_text)
                self.assertEqual(app_message.parse_app_message(raw, **kwargs), base.parse_app_message(raw, **kwargs))

