import json
import unittest
import os
import tempfile
from pathlib import Path

from bridge.api import WeixinAPI, APIError, TransportError, checked_url, image_item


class APITests(unittest.TestCase):
    def fake(self, body=None):
        calls = []
        def send(url, data, headers, timeout):
            calls.append((url, json.loads(data) if data else None, headers))
            return json.dumps(body if body is not None else {'ret': 0}).encode(), {}
        return calls, send

    def test_reject_untrusted_hosts_and_credentials(self):
        for url in ['http://ilinkai.weixin.qq.com', 'https://evil.test',
                    'https://ilinkai.weixin.qq.com.evil.test', 'https://fixture:invalid@ilinkai.weixin.qq.com',
                    'https://ilinkai.weixin.qq.com:8443', 'https://127.0.0.1']:
            with self.assertRaises(ValueError): checked_url(url)

    def test_text_peer_context_and_client_id(self):
        calls, send = self.fake()
        api = WeixinAPI(token='test-secret', transport=send)
        api.send_text('peer', 'hello', 'context', 'request-1')
        msg = calls[0][1]['msg']
        self.assertEqual((msg['to_user_id'], msg['context_token'], msg['client_id']), ('peer', 'context', 'request-1'))
        self.assertEqual(msg['message_type'], 2)
        self.assertEqual(msg['message_state'], 2)
        self.assertEqual(msg['item_list'], [{'type':1, 'text_item':{'text':'hello'}}])

    def test_missing_context_and_text_rejected_before_network(self):
        calls, send = self.fake()
        api = WeixinAPI(token='s', transport=send)
        for text, ctx in [('', 'c'), ('hello', ''), ('x'*40000, 'c')]:
            with self.assertRaises(ValueError): api.send_text('peer', text, ctx, 'req')
        self.assertEqual(calls, [])

    def test_business_failure_not_http_success(self):
        for response in [{'ret':-2,'errmsg':'secret=abcdef'}, {'errcode':-14}]:
            _, send = self.fake(response)
            api = WeixinAPI(token='s', transport=send)
            with self.assertRaises(APIError) as ctx: api.send_text('p', 'hi', 'c', 'r')
            self.assertNotIn('abcdef', str(ctx.exception))

    def test_official_empty_success_response_is_acceptance_only(self):
        _,send=self.fake({})
        self.assertEqual(WeixinAPI(token='s',transport=send).send_text('p','hi','c','r'),{})

    def test_cursor_poll_and_empty_not_error(self):
        calls, send = self.fake({'ret':0,'msgs':[],'get_updates_buf':'next'})
        result = WeixinAPI(token='s',transport=send).poll('old', timeout=2)
        self.assertEqual(calls[0][1]['get_updates_buf'],'old')
        self.assertEqual(result['get_updates_buf'],'next')

    def test_qr_login_has_no_bearer(self):
        calls, send = self.fake({'qrcode':'q','qrcode_img_content':'https://weixin.qq.com/q/abc'})
        api = WeixinAPI(transport=send)
        self.assertEqual(api.login_start()['qrcode'],'q')
        self.assertNotIn('Authorization',calls[0][2])
        self.assertEqual(calls[0][1],{'local_token_list':[]})

    def test_login_error_redacts_query(self):
        _, send = self.fake({'ret':-1})
        with self.assertRaises(APIError) as ctx:
            WeixinAPI(transport=send).login_poll('SECRET_QR','123456')
        self.assertNotIn('SECRET_QR',str(ctx.exception))
        self.assertNotIn('123456',str(ctx.exception))

    def test_real_empty_poll_omits_default_ret(self):
        _, send = self.fake({'msgs':[],'sync_buf':'unused','get_updates_buf':'next'})
        self.assertEqual(WeixinAPI(token='s',transport=send).poll('')['get_updates_buf'],'next')

    def test_invalid_cursor_or_absent_messages_rejected(self):
        for body in [{'ret':0,'get_updates_buf':'next'}, {'ret':0,'msgs':[],'get_updates_buf':9}]:
            _, send=self.fake(body)
            with self.assertRaises(APIError):WeixinAPI(token='s',transport=send).poll('old')

    def test_invalid_json_and_response_budget(self):
        for payload in [b'not json', b'[]', b'x'*4_000_001]:
            api = WeixinAPI(token='s',transport=lambda *args:(payload,{}))
            with self.assertRaises(APIError):api.poll('')

    def test_image_item_encoding(self):
        obj = image_item('opaque', bytes(range(16)), 32)
        self.assertEqual(obj['type'],2)
        self.assertEqual(obj['image_item']['mid_size'],32)
        self.assertEqual(obj['image_item']['media']['encrypt_type'],1)
        self.assertEqual(obj['image_item']['media']['aes_key'],'MDAwMTAyMDMwNDA1MDYwNzA4MDkwYTBiMGMwZDBlMGY=')

    def test_token_header_control_characters_rejected(self):
        for token in ['FAKE_SECRET\r\nx','FAKE_SECRET\x01','中文']:
            with self.assertRaises(ValueError) as ctx:WeixinAPI(token=token)
            self.assertNotIn('FAKE_SECRET',str(ctx.exception))

    def test_multibyte_cursor_budget(self):
        _,send=self.fake({'msgs':[],'get_updates_buf':'汉'*30000})
        with self.assertRaises(APIError):WeixinAPI(token='s',transport=send).poll('')

    def test_image_upload_and_send_preserve_payload(self):
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        calls=[];key=None
        raw=b'\x89PNG\r\n\x1a\n'+b'test-byte-payload'
        def send(url,data,headers,timeout):
            nonlocal key
            calls.append((url,headers))
            if 'getuploadurl' in url:
                body=json.loads(data);key=bytes.fromhex(body['aeskey'])
                self.assertEqual(body['rawsize'],len(raw))
                return b'{"upload_full_url":"https://novac2c.cdn.weixin.qq.com/c2c/upload?x=1"}',{}
            if '/c2c/upload' in url:
                self.assertNotIn('Authorization',headers)
                self.assertEqual(unpad(AES.new(key,AES.MODE_ECB).decrypt(data),16),raw)
                return b'',{'x-encrypted-param':'opaque-param'}
            body=json.loads(data)
            self.assertEqual(body['msg']['item_list'][0]['type'],2)
            return b'{}',{}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()/'x.png';p.write_bytes(raw)
            WeixinAPI(token='s',transport=send).send_image('peer',p,'context','request')
        self.assertEqual(len(calls),3)


if __name__ == '__main__':unittest.main()
