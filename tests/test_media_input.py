import hashlib
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from rsi_agent.config import WORKBENCH


@unittest.skipUnless(sys.platform == 'linux', 'requires original native image reader')
class InboundImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(WORKBENCH / 'wechat'))

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(WORKBENCH / 'wechat'))

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

    def test_original_queue_exports_once_then_returns_the_same_verified_asset(self):
        from PIL import Image
        from operations.public_api import PublicAPI
        from rsi_agent.media_io import image
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
                def acquire(self): return True
                def release(self): pass
                def cleanup(self, job): return True
                def prepare(self, job):
                    return {'imageRecipe': True, 'programRecipe': True, 'context': 'fixture',
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
            self.assertEqual(first['state'], 'image_ready')
            self.assertEqual(base64.b64decode(first['data']), data)
            self.assertEqual(first, second)
            self.assertEqual(driver.executions, 1)
            job = api.s.list_jobs()[0]
            self.assertNotEqual(job.get('execution_mode'), 'verified_fast')
            self.assertEqual(job['state'], 'succeeded')
