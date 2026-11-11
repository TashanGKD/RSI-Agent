import contextlib
from email.message import Message
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from trigger.link_reader import content, fetch, linked_pages, shared_link, urls
from rsi_agent.config import WECHAT_LINUX


class LinkReaderTests(unittest.TestCase):
    def test_bilibili_card_fetches_only_verified_metadata_for_the_exact_part(self):
        url = 'https://www.bilibili.com/video/BV1zJiGBREPB/?p=2&share_source=fixture'
        card = '<msg><appmsg><type>4</type><title>Video</title><url>' + url.replace('&', '&amp;') + '</url></appmsg></msg>'
        self.assertEqual(shared_link(card)['url'], url)
        self.assertIsNone(shared_link(card.replace('www.bilibili.com', 'example.com')))
        connection = Mock()
        headers = Message()
        headers['Content-Type'] = 'application/json'
        payload = {'code': 0, 'data': {'bvid': 'BV1zJiGBREPB', 'title': 'Video', 'desc': 'Description',
            'pages': [{'page': 1, 'cid': 4, 'part': 'First'}, {'page': 2, 'cid': 5, 'part': 'Second'}]}}
        connection.getresponse.return_value = Mock(status=200, headers=headers, read=Mock(
            return_value=json.dumps(payload).encode()))
        with patch('trigger.link_reader.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
                patch('trigger.link_reader.http.client.HTTPSConnection', return_value=connection), \
                patch('trigger.link_reader.ssl.create_default_context'), \
                patch('trigger.link_reader.socket.create_connection'):
            result = fetch(url)
        self.assertEqual((result['kind'], result['part'], result['part_title']), ('bilibili_video', 2, 'Second'))
        self.assertEqual(result['description'], 'Description')
        self.assertEqual(result['content_scope'], 'metadata')
        self.assertNotIn('subtitle_text', result)
        self.assertEqual(result['canonical_url'], 'https://www.bilibili.com/video/BV1zJiGBREPB/?p=2')
        self.assertEqual(connection.request.call_args.args, ('GET', '/x/web-interface/view?bvid=BV1zJiGBREPB'))
        connection.request.assert_called_once()

    def test_bilibili_short_link_cannot_redirect_outside_video_routes(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 302
        response.getheader.return_value = 'https://example.com/video/BV1zJiGBREPB/'
        with patch('trigger.link_reader.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
                patch('trigger.link_reader.http.client.HTTPSConnection', return_value=connection), \
                patch('trigger.link_reader.ssl.create_default_context'), \
                patch('trigger.link_reader.socket.create_connection'):
            result = fetch('https://b23.tv/Abc123?share_source=fixture')
        self.assertEqual(result['code'], 'BILIBILI_SHORT_TARGET_UNSUPPORTED')
        self.assertEqual(result['kind'], 'bilibili_video')
        self.assertEqual(connection.request.call_args.args, ('GET', '/Abc123'))
        connection.request.assert_called_once()

    def test_wechat_shared_article_preserves_query_and_accepts_large_html(self):
        url = 'https://mp.weixin.qq.com/s?__biz=fixture==&mid=1&idx=1&sn=abc&scene=1#rd'
        html = (b'<meta property="og:title" content="Article headline"><main>navigation</main>'
                b'<script>' + b' ' * 1_000_000 + b'</script><div id="js_content">Actual body</div>')
        headers = Message()
        headers['Content-Type'] = 'text/html; charset=utf-8'
        connection = Mock()
        connection.getresponse.return_value = Mock(status=200, headers=headers)
        connection.getresponse.return_value.read.side_effect = lambda size: html[:size]
        with patch('trigger.link_reader.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
                patch('trigger.link_reader.http.client.HTTPSConnection', return_value=connection), \
                patch('trigger.link_reader.ssl.create_default_context'), \
                patch('trigger.link_reader.socket.create_connection'):
            result = fetch(url)
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['title'], 'Article headline')
        self.assertEqual(result['text'], 'Actual body')
        self.assertEqual(result['url'], url)
        self.assertEqual(connection.request.call_args.args, ('GET', '/s?__biz=fixture==&mid=1&idx=1&sn=abc&scene=1'))
        self.assertIn('Mozilla/5.0', connection.request.call_args.kwargs['headers']['User-Agent'])

    def test_wechat_challenge_is_reported_without_following_redirect(self):
        url = 'https://mp.weixin.qq.com/s/fixture'
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 302
        response.getheader.return_value = 'https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha?poc_token=fixture'
        with patch('trigger.link_reader.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
                patch('trigger.link_reader.http.client.HTTPSConnection', return_value=connection), \
                patch('trigger.link_reader.ssl.create_default_context'), \
                patch('trigger.link_reader.socket.create_connection'):
            result = fetch(url)
        self.assertEqual(result, {'state': 'unavailable', 'url': url, 'code': 'WECHAT_VERIFICATION_REQUIRED'})
        connection.request.assert_called_once()

    def test_wechat_body_is_extracted_but_verification_and_empty_pages_are_not_articles(self):
        url = 'https://mp.weixin.qq.com/s/fixture'
        html = '<html><head><title>Sample article</title><script>not article</script></head><body>navigation<div id="js_content"><p>Actual body</p><p>More evidence</p></div>footer</body></html>'
        result = content(url, html.encode())
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['title'], 'Sample article')
        self.assertIn('Actual body', result['text'])
        self.assertNotIn('navigation', result['text'])
        self.assertNotIn('not article', result['text'])
        self.assertEqual(result['source_sha256'], hashlib.sha256(html.encode()).hexdigest())
        for blocked in ['<html><body>环境异常，请完成验证</body></html>',
                        '<html><body>navigation<div id="js_content"></div></body></html>']:
            self.assertEqual(content(url, blocked.encode())['state'], 'unavailable')

    def test_wechat_rich_media_content_class_is_extracted(self):
        url = 'https://mp.weixin.qq.com/s/fixture-rich'
        html = ('<html><head><meta property="og:title" content="Rich title"></head><body>'
                '<div class="rich_media_content rich_media_content_full"><p>正文段落</p>'
                '<p>第二段</p></div></body></html>')
        result = content(url, html.encode())
        self.assertEqual(result['state'], 'ready')
        self.assertEqual(result['title'], 'Rich title')
        self.assertIn('正文段落', result['text'])

    def test_only_bounded_current_https_links_and_real_link_cards_are_selected(self):
        self.assertEqual(urls('read https://example.com/a。 https://example.com/a https://example.com/b'),
                         ['https://example.com/a', 'https://example.com/b'])
        self.assertEqual(urls('https://user:secret@example.com/a http://localhost/a'), [])
        card = '<msg><appmsg><type>5</type><title>Article</title><url>https://example.com/a</url></appmsg></msg>'
        self.assertEqual(shared_link(card)['url'], 'https://example.com/a')
        self.assertIsNone(shared_link(card.replace('<type>5', '<type>57')))
        self.assertIsNone(shared_link('<!DOCTYPE msg>' + card))
        legacy = card.replace('https://example.com/a', 'http://mp.weixin.qq.com/s/fixture')
        self.assertEqual(shared_link(legacy)['url'], 'https://mp.weixin.qq.com/s/fixture')
        self.assertIn('http://mp.weixin.qq.com/s/fixture', shared_link(legacy)['text'])
        self.assertEqual(urls('http://mp.weixin.qq.com/s/fixture'), ['https://mp.weixin.qq.com/s/fixture'])

    def test_private_network_resolution_is_refused_before_connection(self):
        with patch('trigger.link_reader.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]), \
                patch('trigger.link_reader.http.client.HTTPSConnection') as connection:
            self.assertEqual(fetch('https://example.com/article')['state'], 'unavailable')
        connection.assert_not_called()

    def test_public_address_is_pinned_and_redirects_are_not_followed(self):
        connection = Mock()
        connection.getresponse.return_value.status = 302
        with patch('trigger.link_reader.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
                patch('trigger.link_reader.http.client.HTTPSConnection', return_value=connection), \
                patch('trigger.link_reader.ssl.create_default_context'), \
                patch('trigger.link_reader.socket.create_connection') as connect:
            result = fetch('https://example.com/article')
        self.assertEqual(result['code'], 'HTTP_302')
        self.assertEqual(connect.call_args.args[0], ('93.184.216.34', 443))
        connection.request.assert_called_once()
        headers = connection.request.call_args.kwargs['headers']
        self.assertNotIn('Authorization', headers)
        self.assertNotIn('Cookie', headers)

    def test_original_read_is_cached_before_model_retry_or_restart(self):
        page = {'state': 'ready', 'url': 'https://example.com/a', 'text': 'Original fetched body'}
        with tempfile.TemporaryDirectory() as folder, patch('trigger.link_reader.subprocess.run',
                return_value=Mock(returncode=0, stdout=json.dumps(page))) as run:
            path = Path(folder) / 'cache.sqlite'
            db = sqlite3.connect(path)
            self.assertEqual(linked_pages(db, 'original-native-id', page['url']), [page])
            db.close()
            db = sqlite3.connect(path)
            self.assertEqual(linked_pages(db, 'original-native-id', page['url']), [page])
            db.close()
        run.assert_called_once()

    def test_timeout_is_saved_as_unavailable_without_repeated_fetches(self):
        with sqlite3.connect(':memory:') as db, patch('trigger.link_reader.subprocess.run',
                side_effect=subprocess.TimeoutExpired('reader', 20)) as run:
            first = linked_pages(db, 'native-id', 'https://example.com/a')
            self.assertEqual(first[0]['state'], 'unavailable')
            self.assertEqual(linked_pages(db, 'native-id', 'https://example.com/a'), first)
        run.assert_called_once()


@unittest.skipUnless(sys.platform == 'linux', 'uses original native source receipts')
class NativeOwnerLinkTests(unittest.TestCase):
    def test_native_link_metadata_survives_source_capture_and_ack(self):
        from trigger.reply_io import source
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dbpath = root / 'native.sqlite'
            table = 'Msg_' + hashlib.md5(b'owner').hexdigest()
            with sqlite3.connect(dbpath) as db:
                db.executescript("CREATE TABLE Name2Id(user_name TEXT);INSERT INTO Name2Id VALUES('self'),('owner');"
                    'CREATE TABLE ' + table + '(local_id INTEGER,server_id INTEGER,local_type INTEGER,'
                    'real_sender_id INTEGER,create_time INTEGER,sort_seq INTEGER,message_content TEXT);')
                card = '<msg><appmsg><type>5</type><title>Article</title><url>https://mp.weixin.qq.com/s/fixture</url></appmsg></msg>'
                db.execute('INSERT INTO ' + table + ' VALUES(?,?,?,?,?,?,?)', (1, 11, (5 << 32) | 49, 2, 120, 1, card))
            sys.path.insert(0, str(WECHAT_LINUX))
            self.addCleanup(sys.path.remove, str(WECHAT_LINUX))
            import linux_tool

            @contextlib.contextmanager
            def opened(_):
                db = sqlite3.connect(dbpath)
                db.row_factory = sqlite3.Row
                try:
                    yield db, {'consistency': 'committed'}
                finally:
                    db.close()

            owner = {'account': 'self', 'owner_peer': 'owner', 'send_scope': {'mode': 'owner-private-text', 'since': 100}}
            with patch.object(linux_tool, 'native', opened), patch.object(linux_tool, 'decode', lambda value: value or ''):
                batch = source(root, owner, {'op': 'read'})
                self.assertEqual(batch['events'][0]['link']['url'], 'https://mp.weixin.qq.com/s/fixture')
                self.assertEqual(batch['events'][0]['server_id'], 11)
                source(root, owner, {'op': 'ack', **{k: batch[k] for k in ('batch_id', 'batch_hash', 'ack_ids')}})
                self.assertEqual(source(root, owner, {'op': 'read'})['events'], [])
