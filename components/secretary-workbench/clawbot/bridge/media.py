"""Bounded, credential-free native media preparation for the official iLink API.

Protocol: reference/official at Tencent commit 874637a0. Media preparation
does not establish that the native model has viewed or heard an attachment.
"""
import base64
import binascii
import fcntl
import hashlib
import http.client
import io
import json
import os
import re
import socket
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

from . import private
from .child_exec import run_limited
from .api import CDN, checked_url

MAX_ITEM_BYTES = 100 * 1024 * 1024
MAX_MESSAGE_BYTES = 200 * 1024 * 1024
MAX_WORKSPACE_BYTES = 512 * 1024 * 1024
MAX_ITEMS = 20
MAX_NATIVE_BYTES = 32 * 1024 * 1024
NODE = 'node'
SILK_MODULE = 'silk-wasm'
FFMPEG = '/opt/homebrew/bin/ffmpeg'


class MediaFailure(ValueError):
    """A fixed, nonsecret diagnostic suitable for the native attachment prompt."""


class TransientDownload(OSError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise MediaFailure('CDN redirect refused')


def download_cdn(url, limit, *, deadline=None):
    """GET only; no auth, redirect, cookie jar, or arbitrary URL support."""
    checked_url(url, cdn=True)
    deadline = min(time.monotonic() + 60, deadline) if deadline is not None else time.monotonic() + 60
    request = urllib.request.Request(url, headers={'Accept': 'application/octet-stream'}, method='GET')
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=max(.1,min(10,deadline-time.monotonic()))) as response:
            status = getattr(response, 'status', None)
            if status != 200:
                if status is not None and 300 <= status < 400: raise MediaFailure('CDN redirect refused')
                if status is not None and status >= 500: raise TransientDownload('CDN unavailable')
                raise MediaFailure('CDN HTTP request failed')
            if response.geturl() != url: raise MediaFailure('CDN redirect refused')
            length = response.headers.get('Content-Length')
            if length is not None:
                if not str(length).isdigit() or int(length) > limit: raise MediaFailure('download size limit exceeded')
            chunks = []; size = 0
            # HTTPResponse.read(n) can wait to fill n while a peer trickles bytes
            # forever. read1 performs at most one raw read before the deadline
            # is checked again.
            read_chunk = getattr(response, 'read1', response.read)
            while True:
                if time.monotonic() >= deadline: raise TransientDownload('CDN download deadline exceeded')
                chunk = read_chunk(min(65536, limit + 1 - size))
                if time.monotonic() >= deadline: raise TransientDownload('CDN download deadline exceeded')
                if not chunk: break
                size += len(chunk)
                if size > limit: raise MediaFailure('download size limit exceeded')
                chunks.append(chunk)
            if length is not None and size != int(length): raise TransientDownload('CDN incomplete response')
            return b''.join(chunks)
    except urllib.error.HTTPError as exc:
        exc.close()
        if 300 <= exc.code < 400: raise MediaFailure('CDN redirect refused') from None
        if exc.code >= 500 or exc.code in (408, 429): raise TransientDownload('CDN temporarily unavailable') from None
        raise MediaFailure('CDN HTTP request failed') from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError, http.client.HTTPException):
        raise TransientDownload('CDN network failure') from None


def _hash(data): return hashlib.sha256(data).hexdigest()


def _safe_text(value, limit=2048):
    # JSON escaping keeps newlines, controls and alleged instructions visibly data.
    return json.dumps(value[:limit] if isinstance(value, str) else '', ensure_ascii=False)


def _clip(text, budget, marker=' [details truncated; full text retained in original incoming message]'):
    encoded = text.encode()
    if len(encoded) <= budget: return text
    return encoded[:budget-len(marker.encode())].decode('utf-8', errors='ignore') + marker


def _regular_bytes(path, limit):
    p = Path(path).absolute()
    if any(q.is_symlink() for q in (p, *p.parents)): raise ValueError('media symlink refused')
    with os.fdopen(os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                before.st_mode & 0o777 != 0o600 or before.st_nlink != 1 or before.st_size > limit):
            raise ValueError('unsafe private media file')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(raw) != before.st_size:
            raise ValueError('media changed during read')
    return raw


def _key(obj, kind):
    value = obj.get('aeskey') if kind == 2 else None
    if value is not None:
        if not isinstance(value, str) or not re.fullmatch('[0-9a-fA-F]{32}', value): raise MediaFailure('invalid image AES key')
        return bytes.fromhex(value)
    value = obj.get('media', {}).get('aes_key')
    if value is None:
        if kind == 2: return None
        raise MediaFailure('missing media AES key')
    if not isinstance(value, str) or len(value) > 64: raise MediaFailure('invalid media AES key')
    try: raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error): raise MediaFailure('invalid media AES key') from None
    if len(raw) == 16: return raw
    if len(raw) == 32 and re.fullmatch(b'[0-9a-fA-F]{32}', raw): return bytes.fromhex(raw.decode('ascii'))
    raise MediaFailure('invalid media AES key')


def _image_extension(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'): return 'png'
    if raw.startswith(b'\xff\xd8\xff'): return 'jpg'
    if raw.startswith((b'GIF87a', b'GIF89a')): return 'gif'
    if len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP': return 'webp'
    return None


def _wav(raw, rate, bits=16):
    if type(rate) is not int or rate not in (8000, 12000, 16000, 24000, 32000, 44100, 48000):
        raise MediaFailure('unsupported PCM sample rate')
    if bits != 16 or len(raw) % 2: raise MediaFailure('unsupported PCM format (mono signed 16-bit required)')
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(raw)
    return out.getvalue()


def _directory(path):
    result = private.directory(path)
    if result.stat().st_mode & 0o777 != 0o700: raise ValueError('private media directory must have mode 0700')
    return result


class MediaPreparer:
    """prepare(message_id, items) -> prompt, inputs, manifest_path, manifest_hash.

    ``download`` is an injectable ``(approved_url, byte_limit) -> bytes`` function.
    Final manifests (including explicit failures) are immutable on subsequent calls.
    A checkpoint after each item reuses successful preparation after interruption.
    """
    def __init__(self, root, download=None):
        self.root = _directory(root)
        self.media_root = _directory(self.root / 'media')
        self.download = download or download_cdn

    def _usage(self):
        total = 0
        def reject_walk_error(error): raise ValueError('unreadable private media workspace') from None
        for directory, dirs, files in os.walk(self.media_root, followlinks=False, onerror=reject_walk_error):
            _directory(directory)
            for name in dirs: _directory(Path(directory) / name)
            for name in files:
                p = Path(directory) / name
                s = p.lstat()
                if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o777 != 0o600 or s.st_nlink != 1:
                    raise ValueError('unsafe managed media workspace')
                total += s.st_size
        return total

    def _validate(self, manifest, target):
        if not isinstance(manifest.get('assets'), list): raise ValueError('invalid media manifest')
        paths = set()
        for asset in manifest['assets']:
            p = Path(asset['path'])
            if p.parent != target or not re.fullmatch(r'item-\d{2}-(original|audio)\.[a-z0-9]+', p.name):
                raise ValueError('unmanaged media asset')
            raw = _regular_bytes(p, MAX_ITEM_BYTES)
            if len(raw) != asset['size'] or _hash(raw) != asset['sha256']: raise ValueError('saved media integrity mismatch')
            if str(p) in paths: raise ValueError('duplicate media asset')
            paths.add(str(p))
        if any(i.get('path') not in paths or i.get('type') not in ('localImage', 'localAudio') for i in manifest.get('inputs', [])):
            raise ValueError('unmanaged native media input')

    def _save(self, path, value):
        encoded = json.dumps(value, ensure_ascii=False, indent=2).encode()
        # The old manifest remains allocated until the atomic replacement.
        if self._usage() + len(encoded) > MAX_WORKSPACE_BYTES: raise MediaFailure('media workspace size limit exceeded')
        private.write(path, value)

    def _result(self, path, manifest):
        return {'prompt': manifest['prompt'], 'inputs': manifest['inputs'],
                'manifest_path': str(path), 'manifest_hash': _hash(_regular_bytes(path, 65536)),
                'voice_transcripts':manifest.get('voice_transcripts',[])}

    def prepare(self, message_id, items, *, voice_text=False):
        if not isinstance(message_id, str) or not message_id or len(message_id.encode()) > 1024: raise ValueError('invalid media message id')
        if not isinstance(items, list): raise ValueError('invalid media items')
        source_hash = _hash(json.dumps(items, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode())
        from .voice_text import platform_text
        self.voice_text=voice_text
        # A message with usable platform text never waits on ANY original voice.
        self.defer_voice=voice_text and any(platform_text(i) for i in items if isinstance(i,dict))
        self.voice_deadline=time.monotonic()+60 if voice_text else None
        lock = self.media_root / '.lock'
        with os.fdopen(os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), 'r+b') as handle:
            s = os.fstat(handle.fileno())
            if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_nlink != 1 or s.st_mode & 0o777 != 0o600: raise ValueError('unsafe media lock')
            try:fcntl.flock(handle, fcntl.LOCK_EX | (fcntl.LOCK_NB if self.defer_voice else 0))
            except BlockingIOError:raise MediaFailure('media workspace busy; original audio not downloaded') from None
            self._usage()
            target = _directory(self.media_root / _hash(message_id.encode()))
            path = target / 'manifest.json'
            if path.exists() or path.is_symlink():
                manifest = private.read(path)
                if manifest.get('message_id') != message_id or manifest.get('source_hash') != source_hash: raise ValueError('media message changed')
                self._validate(manifest, target)
                if manifest.get('state') == 'ready': return self._result(path, manifest)
            else:
                manifest = {'version': 1, 'message_id': message_id, 'source_hash': source_hash,
                            'state': 'preparing', 'assets': [], 'inputs': [], 'outcomes': [], 'prompt': ''}
                if voice_text:manifest['voice_transcripts']=[]
            if len(items) > MAX_ITEMS:
                manifest['outcomes'] = [{'status': 'rejected', 'notice': 'Media failed: message exceeds 20 item limit; no attachments downloaded.'}]
            else:
                for index in range(len(manifest['outcomes']), len(items)):
                    item = items[index]
                    outcome = self._item(index, item, target, manifest)
                    outcome['notice'] = _clip(outcome.get('notice', ''), 900)
                    manifest['outcomes'].append(outcome)
                    self._save(path, manifest)
            notices = [o['notice'] for o in manifest['outcomes'] if o.get('notice')]
            manifest['items'] = [{'index': i, 'status': o['status']} for i, o in enumerate(manifest['outcomes'])]
            # Item facts/ASR provenance remain in this private receipt. Channel
            # policy is workspace-owned, never repeated in the visible message.
            manifest['prompt'] = '\n'.join(notices)
            # Checkpoint notices are already represented by the final prompt.
            del manifest['outcomes']
            manifest['state'] = 'ready'
            self._save(path, manifest)
            return self._result(path, manifest)

    def _download(self, obj, kind):
        ref = obj.get('media')
        if not isinstance(ref, dict): raise MediaFailure('missing CDN media reference')
        key = _key(obj, kind)
        url = ref.get('full_url')
        if not url:
            param = ref.get('encrypt_query_param')
            if not isinstance(param, str) or not param or len(param) > 16000: raise MediaFailure('missing CDN download reference')
            url = CDN + '/download?' + urllib.parse.urlencode({'encrypted_query_param': param})
        try:
            checked_url(url, cdn=True)
            url.encode('ascii')
        except (ValueError, TypeError, UnicodeError): raise MediaFailure('unapproved CDN URL') from None
        for attempt in range(3):
            try:
                deadline=getattr(self,'voice_deadline',None) if kind==3 else None
                if deadline is not None and time.monotonic()>=deadline:raise MediaFailure('voice preparation deadline exceeded')
                if deadline is not None and self.download is download_cdn:
                    raw=self.download(url,MAX_ITEM_BYTES+(16 if key else 0),deadline=deadline)
                else:raw = self.download(url, MAX_ITEM_BYTES + (16 if key else 0))
                break
            except (OSError, urllib.error.URLError, http.client.HTTPException):
                if attempt == 2: raise MediaFailure('CDN download failed after 3 attempts') from None
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_ITEM_BYTES + (16 if key else 0): raise MediaFailure('download size limit exceeded')
        if key:
            try:
                from Crypto.Cipher import AES
                from Crypto.Util.Padding import unpad
                raw = unpad(AES.new(key, AES.MODE_ECB).decrypt(raw), 16)
            except ValueError: raise MediaFailure('AES decryption failed') from None
        if not raw or len(raw) > MAX_ITEM_BYTES: raise MediaFailure('plaintext size limit exceeded')
        if kind == 4 and 'len' in obj:
            length = obj['len']
            if not isinstance(length, str) or not re.fullmatch(r'[0-9]{1,12}', length) or int(length) != len(raw): raise MediaFailure('attachment length mismatch')
        if kind == 4 and obj.get('md5') is not None:
            expected = obj['md5']
            if not isinstance(expected, str) or not re.fullmatch('[0-9a-fA-F]{32}', expected) or hashlib.md5(raw).hexdigest() != expected.lower(): raise MediaFailure('attachment MD5 mismatch')
        return raw

    def _asset(self, target, index, role, ext, raw, manifest, kind, original_name=None):
        if len(raw) > MAX_ITEM_BYTES: raise MediaFailure('media file size limit exceeded')
        if sum(a['size'] for a in manifest['assets']) + len(raw) > MAX_MESSAGE_BYTES: raise MediaFailure('message media size limit exceeded')
        if self._usage() + len(raw) + 65536 > MAX_WORKSPACE_BYTES: raise MediaFailure('media workspace size limit exceeded')
        path = target / ('item-%02d-%s.%s' % (index, role, ext))
        if path.is_symlink(): raise ValueError('media destination symlink refused')
        if path.exists(): _regular_bytes(path, MAX_ITEM_BYTES)
        fd, tmp = tempfile.mkstemp(prefix='.media-', dir=target)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(raw); out.flush(); os.fsync(out.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        asset = {'path': str(path), 'size': len(raw), 'sha256': _hash(raw), 'kind': kind}
        if original_name is not None:
            asset['original_name'] = _clip(original_name, 512)
            if asset['original_name'] != original_name: asset['original_name_truncated'] = True
        manifest['assets'].append(asset)
        return str(path)

    def _attach(self, kind, path, manifest):
        sizes = {a['path']: a['size'] for a in manifest['assets']}
        if sum(sizes[i['path']] for i in manifest['inputs']) + sizes[path] > MAX_NATIVE_BYTES: return False
        manifest['inputs'].append({'type': kind, 'path': path})
        return True

    def _audio(self, obj, raw, source, target):
        encoding = obj.get('encode_type')
        if encoding == 1:
            if obj.get('channels', 1) != 1: raise MediaFailure('unsupported PCM channel count')
            return _wav(raw, obj.get('sample_rate'), obj.get('bits_per_sample', 16))
        cap = min(MAX_ITEM_BYTES, MAX_WORKSPACE_BYTES - self._usage() - 65536)
        if cap < 44: raise MediaFailure('media workspace size limit exceeded')
        if encoding == 6 or raw.startswith((b'#!SILK_V3', b'\x02#!SILK_V3')):
            if not Path(NODE).is_file() or not Path(SILK_MODULE).is_file(): raise MediaFailure('SILK decoder unavailable; original audio retained, not heard')
            script = ('const fs=require("fs");const silk=require(process.argv[1]);'
                      'silk.decode(fs.readFileSync(process.argv[2]),24000).then(r=>{'
                      'if(!r.data.length||r.data.length>Number(process.argv[3]))process.exit(2);'
                      'fs.writeFileSync(1,r.data);}).catch(()=>process.exit(3));')
            command = [NODE, '--max-old-space-size=192', '-e', script, SILK_MODULE, source, str(cap - 44)]
            pcm = True
        elif encoding in (5, 7, 8):
            if not Path(FFMPEG).is_file(): raise MediaFailure('ffmpeg unavailable; original audio retained, not heard')
            fmt = {5: 'amr', 7: 'mp3', 8: 'ogg'}[encoding]
            command = [FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-protocol_whitelist', 'file,pipe',
                       '-f', fmt, '-i', source, '-vn', '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le',
                       '-fs', str(cap), '-f', 'wav', 'pipe:1']
            pcm = False
        else: raise MediaFailure('unsupported voice encoding; original audio retained, not heard')
        fd, temporary = tempfile.mkstemp(prefix='.audio-', dir=target)
        try:
            with os.fdopen(fd, 'w+b') as out:
                try:
                    proc = run_limited(command, cap, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.DEVNULL,
                                          timeout=max(.1,min(30,self.voice_deadline-time.monotonic())) if getattr(self,'voice_deadline',None) else 30, check=False, env={'PATH': '/usr/bin:/bin', 'LANG': 'C'},
                                          )
                except (OSError, subprocess.TimeoutExpired): raise MediaFailure('audio conversion failed or timed out; original audio retained, not heard') from None
                if proc.returncode or out.tell() >= cap: raise MediaFailure('audio conversion failed or output limit exceeded; original audio retained, not heard')
                out.seek(0); converted = out.read(cap + 1)
            if pcm: return _wav(converted, 24000)
            if not converted.startswith(b'RIFF') or converted[8:12] != b'WAVE': raise MediaFailure('invalid converted audio; original audio retained, not heard')
            return converted
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def _item(self, index, item, target, manifest):
        prefix = 'Item %d' % (index + 1)
        if not isinstance(item, dict): return {'status': 'failed', 'notice': prefix + ' failed: malformed message item.'}
        kind = item.get('type')
        if type(kind) is not int: kind = None
        notices = []
        reference_notice = ''
        reference = item.get('ref_msg')
        if isinstance(reference, dict):
            quoted = reference.get('message_item')
            summary = {'title': reference.get('title', ''), 'svr_id': reference.get('svr_id', '')}
            if isinstance(quoted, dict):
                summary['type'] = quoted.get('type')
                for key, field in (('text_item', 'text'), ('voice_item', 'text'), ('file_item', 'file_name')):
                    if isinstance(quoted.get(key), dict): summary[field] = quoted[key].get(field, '')
            # No recursive download or interpretation of quoted attachments.
            safe = {k: v[:1024] if isinstance(v, str) else v if type(v) is int else '' for k, v in summary.items()}
            reference_notice = prefix + ' quoted reference (untrusted, quoted media not downloaded): ' + json.dumps(safe, ensure_ascii=True)
        if kind == 1: return {'status': 'text', 'notice': reference_notice}
        if kind not in (2, 3, 4):
            notices.append(prefix + ' unsupported item type %s; content not downloaded.' % _safe_text(str(kind), 80))
            if reference_notice: notices.append(reference_notice)
            return {'status': 'unsupported', 'notice': '\n'.join(notices)}
        obj = item.get({2: 'image_item', 3: 'voice_item', 4: 'file_item'}[kind])
        if not isinstance(obj, dict): return {'status': 'failed', 'notice': prefix + ' failed: missing media body.'}
        if kind==3 and getattr(self,'defer_voice',False):
            from .voice_text import platform_text
            text=platform_text(item)
            if text is not None:
                manifest.setdefault('voice_transcripts',[]).append({'index':index,'text':text,'provenance':'wechat',
                    'original_audio_obtained':False,'locator':{'message_id':manifest['message_id'],'item_index':index,'store':'incoming.body'}})
            return {'status':'deferred','notice':prefix+' 原音未下载、未核听；原始入站媒体定位保存在 incoming.body 对应消息ID及item索引。'+(' 微信转写已直接交付正文。' if text else ' 本条无可用转写，仍为未读缺口。')+('\n'+reference_notice if reference_notice else '')}
        status = 'ready'
        starting_assets = len(manifest['assets'])
        voice_notice = None
        if kind == 3 and isinstance(obj.get('text'), str) and obj['text']:
            voice_notice = prefix + ' platform voice transcript (ASR, current sender): ' + _safe_text(obj['text'], 1024) + (' [transcript truncated]' if len(obj['text']) > 1024 else '')
        try:
            raw = self._download(obj, kind)
            extension = _image_extension(raw) if kind == 2 else {3: 'audio', 4: 'bin'}[kind]
            if kind == 4 and isinstance(obj.get('file_name'), str):
                suffix = obj['file_name'].rsplit('.', 1)[-1].lower()
                if '.' in obj['file_name'] and re.fullmatch('[a-z0-9]{1,12}', suffix): extension = suffix
            source = self._asset(target, index, 'original', extension or 'bin', raw, manifest,
                                 {2: 'image-original', 3: 'voice-original', 4: 'file'}[kind], obj.get('file_name') if kind == 4 and isinstance(obj.get('file_name'), str) else None)
            if kind == 2:
                if extension:
                    notices.append(prefix + ' image: ' + source)
                    if not self._attach('localImage', source, manifest):
                        status = 'partial'
                        notices.append(prefix + ' image not attached natively (32MiB transport budget); inspect local file with tools.')
                else:
                    status = 'unsupported'
                    notices.append(prefix + ' unsupported image format; original retained at ' + source)
            elif kind == 3:
                notices.append(prefix + ' original voice audio: ' + source)
                converted = self._audio(obj, raw, source, target)
                audio = self._asset(target, index, 'audio', 'wav', converted, manifest, 'voice-wav')
                notices.append(prefix + ' converted voice audio (native listening required): ' + audio)
                if getattr(self,'voice_text',False):
                    from .voice_text import local_asr
                    try:
                        remaining=self.voice_deadline-time.monotonic()
                        if remaining<=0:raise ValueError('voice deadline')
                        transcript=local_asr(audio,timeout=min(45,remaining))
                        manifest.setdefault('voice_transcripts',[]).append({'index':index,'text':transcript['text'],
                            'provenance':'local','model':transcript.get('model'),'human_verified':False,'original_audio_obtained':True})
                    except (ValueError,OSError,subprocess.TimeoutExpired,ImportError,IndexError,KeyError):
                        status='partial'
                        notices.append(prefix+' local ASR unavailable, failed or timed out; no verified transcript.')
                if not self._attach('localAudio', audio, manifest):
                    status = 'partial'
                    notices.append(prefix + ' audio not attached natively (32MiB transport budget); inspect local file with tools; not listened to.')
            else:
                notices.append(prefix + ' file path=' + source + '; bytes=' + str(len(raw)) + '; sha256=' + _hash(raw) +
                               '; read this local file as required by the user task; original_name (untrusted): ' +
                               _safe_text(_clip(obj.get('file_name', '') if isinstance(obj.get('file_name'), str) else '', 512)))
        except MediaFailure as exc:
            status = 'partial' if len(manifest['assets']) > starting_assets else 'failed'
            notices.append(prefix + ' failed: ' + str(exc) + '.')
        if voice_notice: notices.append(voice_notice)
        if reference_notice: notices.append(reference_notice)
        return {'status': status, 'notice': '\n'.join(notices)}
