"""Bounded client for Tencent's public iLink Bot protocol. No desktop control.

Protocol provenance: reference/official/reference.json (Tencent, MIT).
Server acceptance and actual recipient delivery are deliberately distinct.
"""
import base64
import hashlib
import json
import os
import re
import socket
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = '2.4.10'
BASE = 'https://ilinkai.weixin.qq.com'
CDN = 'https://novac2c.cdn.weixin.qq.com/c2c'
MAX_RESPONSE = 4_000_000
MAX_IMAGE = 8_000_000


class APIError(RuntimeError):
    def __init__(self, code, operation='api'):
        self.code = code
        self.operation = operation
        super().__init__('%s rejected (%s)' % (operation, code))


class TransportError(RuntimeError):
    """The request may have reached the service; never blindly resend a message."""

class PollTimeout(TransportError):
    pass


def checked_url(url, cdn=False):
    if not isinstance(url, str) or len(url) > 16384 or any(c.isspace() for c in url):
        raise ValueError('invalid URL')
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ''
    valid = (host == 'ilinkai.weixin.qq.com' or host.endswith('.ilinkai.weixin.qq.com'))
    if cdn:
        valid = host == 'novac2c.cdn.weixin.qq.com' or host.endswith('.cdn.weixin.qq.com')
    if p.scheme != 'https' or not valid or p.username or p.password or p.port not in (None,443) or p.fragment:
        raise ValueError('unapproved service URL')
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransportError('redirect refused')


def transport(url, data, headers, timeout):
    request = urllib.request.Request(url, data=data, headers=headers, method='POST' if data is not None else 'GET')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE + 1)
            if len(body) > MAX_RESPONSE: raise TransportError('response budget exceeded')
            return body, {k.lower():v for k,v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        raise APIError('http-%s' % exc.code) from None
    except (socket.timeout, TimeoutError):
        raise PollTimeout('request timed out') from None
    except (urllib.error.URLError, OSError):
        raise TransportError('network request unconfirmed') from None


def bounded_string(value, name, limit):
    if not isinstance(value,str) or not value or len(value.encode()) > limit or '\x00' in value:
        raise ValueError('invalid ' + name)
    return value


def image_item(param, key, size):
    return {'type':2,'image_item':{'media':{'encrypt_query_param':param,
            'aes_key':base64.b64encode(key.hex().encode()).decode(),'encrypt_type':1},'mid_size':size}}


class WeixinAPI:
    def __init__(self, base_url=BASE, token=None, transport=transport):
        checked_url(base_url)
        p = urllib.parse.urlsplit(base_url)
        if p.path not in ('','/') or p.query: raise ValueError('API origin required')
        if token is not None:
            bounded_string(token,'token',16384)
            if not token.isascii() or any(ord(c)<33 or ord(c)>126 for c in token):raise ValueError('invalid token characters')
        self.base = base_url.rstrip('/')
        self.token = token
        self.transport = transport

    def request(self, path, body=None, *, get=False, auth=True, base_info=True, timeout=35, require_ret=True):
        if not path.startswith('/ilink/bot/') or '\n' in path: raise ValueError('invalid operation')
        operation=urllib.parse.urlsplit(path).path.rsplit('/',1)[-1]
        headers = {'iLink-App-Id':'bot','iLink-App-ClientVersion':str((2<<16)|(4<<8)|10)}
        if not get:
            headers.update({'Content-Type':'application/json','AuthorizationType':'ilink_bot_token',
                            'X-WECHAT-UIN':base64.b64encode(str(int.from_bytes(os.urandom(4),'big')).encode()).decode()})
        if auth:
            if not self.token: raise ValueError('login required')
            headers['Authorization'] = 'Bearer ' + self.token
        payload = None
        if not get:
            body = dict(body or {})
            if base_info: body['base_info']={'channel_version':VERSION,'bot_agent':'TashanSecretary/0.1.0'}
            payload = json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()
            if len(payload)>MAX_RESPONSE: raise ValueError('request budget exceeded')
        raw,_ = self.transport(self.base+path, payload, headers, timeout)
        try:
            if len(raw)>MAX_RESPONSE: raise ValueError()
            result=json.loads(raw)
            if not isinstance(result,dict): raise ValueError()
        except (ValueError,UnicodeError,RecursionError):
            raise APIError('invalid-response',operation) from None
        for key in ('ret','errcode'):
            if key in result and (type(result[key]) is not int or result[key]!=0):
                code=result[key] if type(result[key]) is int else 'invalid-code'
                raise APIError(code,operation)
        if require_ret and result.get('ret')!=0: raise APIError('missing-result',operation)
        return result

    def login_start(self):
        return self.request('/ilink/bot/get_bot_qrcode?bot_type=3',{'local_token_list':[]},auth=False,base_info=False,require_ret=False)

    def login_poll(self, qr, verify_code=None):
        bounded_string(qr,'QR identity',8192)
        query={'qrcode':qr}
        if verify_code is not None:
            if not re.fullmatch('[0-9]{4,12}',verify_code):raise ValueError('invalid verification code')
            query['verify_code']=verify_code
        return self.request('/ilink/bot/get_qrcode_status?'+urllib.parse.urlencode(query),get=True,auth=False,require_ret=False,timeout=35)

    def poll(self, cursor='', timeout=35):
        if not isinstance(cursor,str) or len(cursor.encode())>65536 or '\x00' in cursor:raise ValueError('invalid cursor')
        try:result=self.request('/ilink/bot/getupdates',{'get_updates_buf':cursor},timeout=timeout,require_ret=False)
        except PollTimeout:return {'msgs':[],'get_updates_buf':cursor}
        if not isinstance(result.get('msgs'),list) or len(result['msgs'])>500:raise APIError('invalid-messages')
        returned_cursor=result.get('get_updates_buf',cursor)
        if not isinstance(returned_cursor,str) or len(returned_cursor.encode())>65536 or '\x00' in returned_cursor:raise APIError('invalid-cursor')
        result['get_updates_buf']=returned_cursor or cursor
        return result

    def send_item(self, peer, item, context, client_id):
        bounded_string(peer,'peer',512);bounded_string(context,'context',16384)
        if not isinstance(client_id,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',client_id):raise ValueError('invalid client id')
        # Like the official client, allow omitted proto3 zero return fields.
        # This establishes API acceptance only; the worker never claims phone delivery.
        return self.request('/ilink/bot/sendmessage',{'msg':{'from_user_id':'','to_user_id':peer,
            'client_id':client_id,'message_type':2,'message_state':2,'context_token':context,'item_list':[item]}},require_ret=False)

    def send_text(self, peer, text, context, client_id):
        bounded_string(text,'text',32768)
        return self.send_item(peer,{'type':1,'text_item':{'text':text}},context,client_id)

    def send_image(self, peer, filename, context, client_id, expected_sha256=None):
        bounded_string(peer,'peer',512);bounded_string(context,'context',16384)
        p=Path(filename).absolute()
        if any(q.is_symlink() for q in (p,*p.parents)):raise ValueError('image symlink rejected')
        with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
            before=os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=MAX_IMAGE:raise ValueError('image size invalid')
            raw=f.read(MAX_IMAGE+1)
            after=os.fstat(f.fileno())
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or len(raw)!=before.st_size:
                raise ValueError('image changed during read')
        if len(raw)>MAX_IMAGE or not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff')):
            raise ValueError('PNG or JPEG required')
        if expected_sha256 and hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('queued image changed')
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        key=os.urandom(16);filekey=os.urandom(16).hex();cipher=AES.new(key,AES.MODE_ECB).encrypt(pad(raw,16))
        upload=self.request('/ilink/bot/getuploadurl',{'filekey':filekey,'media_type':1,'to_user_id':peer,
            'rawsize':len(raw),'rawfilemd5':hashlib.md5(raw).hexdigest(),'filesize':len(cipher),
            'no_need_thumb':True,'aeskey':key.hex()},require_ret=False)
        url=upload.get('upload_full_url')
        if not url:
            param=bounded_string(upload.get('upload_param'),'upload parameter',16000)
            url=CDN+'/upload?'+urllib.parse.urlencode({'encrypted_query_param':param,'filekey':filekey})
        checked_url(url,cdn=True)
        _,headers=self.transport(url,cipher,{'Content-Type':'application/octet-stream'},60)
        param=bounded_string(headers.get('x-encrypted-param'),'download parameter',16000)
        return self.send_item(peer,image_item(param,key,len(cipher)),context,client_id)
