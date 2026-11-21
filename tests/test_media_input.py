import hashlib
import base64
from contextlib import contextmanager
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import types
import zipfile

from rsi_agent.config import WECHAT_LINUX


@unittest.skipUnless(sys.platform == 'linux', 'requires the native WeChat file adapter')
class InboundPdfTests(unittest.TestCase):
    def test_pdf_reads_the_original_resource_and_rejects_wrong_sender_or_cache(self):
        self.check_document('Paper.pdf', b'%PDF-1.7\noriginal resource fixture\n%%EOF', 3342339)

    def test_pdf_above_the_former_10mb_limit_is_read(self):
        # A real 12.5 MB group PDF was downloaded but rejected by the old 10 MB budget.
        self.check_document('Large.pdf', b'%PDF-1.7\n' + b'0' * 12536000 + b'fixture\n%%EOF', 3342339)

    def test_markdown_reads_the_original_resource_and_rejects_wrong_sender_or_cache(self):
        self.check_document('Guide.md', b'# original resource fixture\n', 3801091)

    def test_word_reads_the_original_resource_and_rejects_wrong_sender_or_cache(self):
        package = io.BytesIO()
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_STORED) as word:
            word.writestr('[Content_Types].xml', '<Types/>')
            word.writestr('word/document.xml', '<w:document><w:body>original resource fixture</w:body></w:document>')
        self.check_document('Brief.docx', package.getvalue(), 3801091)

    def check_document(self, name, data, resource_type):
        sys.path.insert(0, str(WECHAT_LINUX))
        self.addCleanup(sys.path.remove, str(WECHAT_LINUX))
        from trigger.media import document_name, pdf_part, document_part
        from trigger.media_io import pdf, document

        peer, sender = 'fixture@chatroom', 'member'
        table = 'Msg_' + hashlib.md5(peer.encode()).hexdigest()
        read, part = (pdf, pdf_part) if name.endswith('.pdf') else (document, document_part)
        prefix = 'PDF' if name.endswith('.pdf') else 'DOCUMENT'
        digest = hashlib.md5(data).hexdigest()
        raw = ('<msg><appmsg><title>' + name + '</title><type>6</type><appattach><totallen>'
               + str(len(data)) + '</totallen></appattach><md5>' + digest + '</md5></appmsg></msg>')
        self.assertEqual(document_name(raw), name)
        self.assertIsNone(document_name(raw.replace('<type>6', '<type>5')))
        self.assertIsNone(document_name(raw.replace(name, '../' + name)))
        cache_name = 'cached' + Path(name).suffix

        @contextmanager
        def native(name):
            with sqlite3.connect(':memory:') as db:
                db.row_factory = sqlite3.Row
                if name == 'message/message_0.db':
                    db.executescript('CREATE TABLE Name2Id(user_name); CREATE TABLE ' + table +
                                     '(local_type,message_content,create_time,real_sender_id,server_id);')
                    db.execute('INSERT INTO Name2Id VALUES(?)', (sender,))
                    db.execute('INSERT INTO ' + table + ' VALUES(49,?,120,1,42)', (sender + ':\n' + raw,))
                elif name == 'message/message_resource.db':
                    db.executescript('CREATE TABLE ChatName2Id(user_name); '
                                     'CREATE TABLE MessageResourceInfo(message_id,chat_id,message_svr_id); '
                                     'CREATE TABLE MessageResourceDetail(message_id,resource_id,size,status,type,packed_info);'
                                     'INSERT INTO MessageResourceInfo VALUES(1,1,42);')
                    db.execute('INSERT INTO ChatName2Id VALUES(?)', (peer,))
                    db.execute('INSERT INTO MessageResourceDetail VALUES(1,8,?,1,?,?)', (len(data), resource_type, cache_name.encode()))
                else:
                    self.assertEqual(name, 'hardlink/hardlink.db')
                    db.executescript("CREATE TABLE dir2id(username); INSERT INTO dir2id VALUES('2026-11'); "
                                     'CREATE TABLE file_hardlink_info_v4(md5,file_name,file_size,dir1,dir2);')
                    db.execute('INSERT INTO file_hardlink_info_v4 VALUES(?,?,?,1,0)', (digest, cache_name, len(data)))
                yield db, {'consistency': 'committed'}
            db.close()

        with tempfile.TemporaryDirectory() as td:
            profile = Path(td)
            path = profile / 'msg/file/2026-11' / cache_name
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            with patch('linux_tool.ACCOUNT', 'fixture'), patch('linux_tool.PROFILE', profile), patch('linux_tool.native', native):
                result = read('fixture', peer, '42', {sender}, 100)
                self.assertEqual(base64.b64decode(part(lambda _: result, '42', name)['data']), data)
                with patch('operations.exports.MAX_FILE_BYTES', len(data) - 1):
                    self.assertEqual(read('fixture', peer, '42', {sender}, 100)['code'], prefix + '_TOO_LARGE')
                with self.assertRaisesRegex(ValueError, 'incoming scope'):
                    read('fixture', peer, '42', {'somebody_else'}, 100)
                path.write_bytes(data.replace(b'fixture', b'changed'))
                self.assertEqual(read('fixture', peer, '42', {sender}, 100)['code'], prefix + '_CACHE_UNAVAILABLE')


@unittest.skipUnless(sys.platform == 'linux', 'requires original native image reader')
class InboundImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(WECHAT_LINUX))

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(WECHAT_LINUX))

    def source(self):
        return {'peer': 'group@chatroom', 'id': '42', 'kind': 3, 'local': 7,
                'sender': 'member', 'time': 120,
                'meta': {'md5': 'a' * 32, 'length': 200, 'cdnthumbwidth': 200, 'cdnthumbheight': 100}}

    def test_unaccompanied_image_has_explicit_exact_source_mode(self):
        from operations.contract import validate_job
        from operations import images
        job = validate_job({'client': 'rsi-vision', 'request_id': 'read-42', 'peer': 'group@chatroom',
            'action': 'save_attachment', 'payload': {'source_id': '42', 'source_mode': 'inbound'}})
        context = images.build_context('group@chatroom', '42', [self.source()], inbound=True)
        self.assertEqual(context['nativeMD5'], 'a' * 32)
        self.assertEqual(context['sourceMode'], job['payload']['source_mode'])
        self.assertEqual(context['sender'], 'member')

    def test_single_complete_image_uses_native_aspect_without_text_anchors(self):
        from PIL import Image, ImageDraw
        from operations import images
        context = images.build_context('group@chatroom', '42', [self.source()], inbound=True)
        picture = Image.new('RGB', (500, 400), (249, 249, 249))
        draw = ImageDraw.Draw(picture)
        draw.rectangle((20, 80, 220, 180), fill='white')
        draw.rectangle((300, 250, 470, 285), fill=(149, 236, 105))
        point = images.locate_visible(picture, [0, 0, 500, 400], [], context)
        self.assertTrue(20 < point[0] < 220 and 80 < point[1] < 180)
        draw.rectangle((20, 210, 220, 310), fill='white')
        with self.assertRaises(images.ImageReadError):
            images.locate_visible(picture, [0, 0, 500, 400], [], context)

    def test_bytes_still_require_native_md5_and_an_actual_image(self):
        from PIL import Image
        from operations import images
        output = io.BytesIO()
        Image.new('RGB', (40, 30), 'red').save(output, format='PNG')
        data = output.getvalue()
        self.assertEqual(images.validate_payload(data, hashlib.md5(data).hexdigest())['format'], 'PNG')
        with self.assertRaises(images.ImageReadError):
            images.validate_payload(data, 'a' * 32)
        cipher = b'\x07\x08V2' + b'\0' * 100
        with self.assertRaises(images.ImageReadError):
            images.validate_payload(cipher, hashlib.md5(cipher).hexdigest())

    def test_own_long_bubble_at_right_edge_does_not_hide_neutral_background(self):
        from PIL import Image, ImageDraw
        from operations import images
        context = images.build_context('group@chatroom', '42', [self.source()], inbound=True)
        picture = Image.new('RGB', (500, 400), (250, 250, 250))
        draw = ImageDraw.Draw(picture)
        draw.rectangle((20, 80, 220, 180), fill='white')
        # Actual client color; a prior outgoing bubble occupied most of the
        # sampled right edge when the real incoming image was rejected.
        draw.rectangle((300, 10, 499, 380), fill=(157, 242, 159))
        point = images.locate_visible(picture, [0, 0, 500, 400], [], context)
        self.assertTrue(20 < point[0] < 220 and 80 < point[1] < 180)

        dark = Image.new('RGB', (500, 400), (40, 40, 40))
        ImageDraw.Draw(dark).rectangle((20, 80, 220, 180), fill='white')
        with self.assertRaises(images.ImageReadError) as error:
            images.locate_visible(dark, [0, 0, 500, 400], [], context)
        self.assertEqual(error.exception.code, 'UNSUPPORTED_IMAGE_LAYOUT')

    def test_preparation_keeps_margin_around_actual_incoming_card_column(self):
        from PIL import Image, ImageDraw
        from operations import images
        picture = Image.new('RGB', (623, 667), (250, 250, 250))
        ImageDraw.Draw(picture).rectangle((71, 300, 271, 400), fill='white')
        binding = {'header_box': [1, 35, 622, 82], 'editor': [280, 554]}
        driver = types.SimpleNamespace(_select=Mock(), binding=Mock(return_value=binding),
            screenshot=Mock(return_value={}), app_windows=Mock(return_value=[]))
        context = images.build_context('group@chatroom', '42', [self.source()], inbound=True)
        job = {'peer': 'group@chatroom', 'payload': {'source_id': '42', 'source_mode': 'inbound'}}
        with patch('operations.image_verified.prepare', return_value=None), \
                patch('operations.images.load_context', return_value=context), \
                patch('operations.navigation.begin'), \
                patch('operations.recipes.main_window', return_value={'width': 623, 'height': 667}), \
                patch('operations.recipes.screen', return_value=picture), patch('operations.recipes.rows', return_value=[]):
            preview = images.prepare(driver, job)
        self.assertTrue(71 < preview['imagePoint'][0] < 271 and 300 < preview['imagePoint'][1] < 400)

    def test_original_queue_exports_once_then_returns_the_same_verified_asset(self):
        from PIL import Image
        from operations.public_api import PublicAPI
        from trigger.media_io import image
        output = io.BytesIO()
        Image.new('RGB', (40, 30), 'red').save(output, format='PNG')
        data = output.getvalue()
        native = {'senderId': 'member', 'imageMetadata': {'md5': hashlib.md5(data).hexdigest()}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            policy = {'account': 'account', 'clients': {}}
            api = PublicAPI(root / 'operations-state', policy)
            self.addCleanup(api.close)
            (root / 'operations-state/config.json').write_text(json.dumps(policy))
            (root / 'operations-state/config.json').chmod(0o600)

            class Native:
                executions = 0
                review = False
                def acquire(self): return True
                def release(self): pass
                def cleanup(self, job): return True
                def prepare(self, job):
                    return {'imageRecipe': True, 'programRecipe': True, 'context': 'fixture', 'reviewRequired': self.review,
                            'imageContext': {'peer': job['peer'], 'sourceId': job['payload']['source_id'],
                                             'nativeMD5': native['imageMetadata']['md5']}}
                def execute(self, job):
                    self.executions += 1
                    asset = api.assets.put(job['client'], 'image.png', data, hashlib.sha256(data).hexdigest())
                    return {'state': 'accepted', 'asset': asset, 'sourcePeer': job['peer'],
                        'sourceId': job['payload']['source_id'], 'sender': 'member', 'nativeMessageMD5Matched': True,
                        'contentReady': True, 'format': 'PNG', 'messagesSent': 0}

            driver = Native()
            with patch('image_client.source', return_value=({}, native)), patch('linux_tool.Tool'), \
                    patch('operations.driver.NativeDriver', return_value=driver):
                with self.assertRaisesRegex(ValueError, 'incoming scope'):
                    image(root, 'account', 'group@chatroom', '42', {'other'})
                first = image(root, 'account', 'group@chatroom', '42', {'member'})
                second = image(root, 'account', 'group@chatroom', '42', {'member'})
                job = api.s.list_jobs()[0]
                self.assertEqual(job['state'], 'succeeded')
                self.assertEqual(job['payload']['representation'], 'visible')
                driver.review = True
                reviewed = image(root, 'account', 'group@chatroom', '43', {'member'})
                self.assertEqual(reviewed['state'], 'media_attention')
                self.assertEqual(driver.executions, 1)
                api.s.set_state(job['id'], 'unknown', {'reason': 'fixture interrupted result'})
                uncertain = image(root, 'account', 'group@chatroom', '42', {'member'})
                self.assertEqual(uncertain['state'], 'media_attention')
            self.assertEqual(first['state'], 'image_ready')
            self.assertEqual(base64.b64decode(first['data']), data)
            self.assertEqual(first, second)
            self.assertEqual(driver.executions, 1)
            self.assertNotEqual(job.get('execution_mode'), 'verified_fast')

    def test_existing_original_read_failure_is_not_replaced_by_visible_request(self):
        from operations.public_api import PublicAPI
        from trigger.media_io import image,CLIENT
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);policy={'account':'account','clients':{}}
            api=PublicAPI(root/'operations-state',policy);self.addCleanup(api.close)
            (root/'operations-state/config.json').write_text(json.dumps(policy))
            (root/'operations-state/config.json').chmod(0o600)
            rid=CLIENT+'-'+hashlib.sha256(('account\0group@chatroom\0'+'42').encode()).hexdigest()
            old=api.s.submit({'client':CLIENT,'request_id':rid,'peer':'group@chatroom','action':'save_attachment',
                             'payload':{'source_id':'42','source_mode':'inbound'}})
            api.s.set_state(old['id'],'failed',{'code':'UNSUPPORTED_IMAGE_LAYOUT','noSend':True})
            before=api.s.get(CLIENT,rid)
            native={'senderId':'member','imageMetadata':{'md5':'a'*32}}
            with patch('image_client.source',return_value=({},native)),patch('linux_tool.Tool'):
                result=image(root,'account','group@chatroom','42',{'member'})
            self.assertEqual(result,{'state':'media_attention','code':'UNSUPPORTED_IMAGE_LAYOUT'})
            self.assertEqual(api.s.get(CLIENT,rid),before)
