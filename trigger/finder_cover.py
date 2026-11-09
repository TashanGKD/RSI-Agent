"""Source-bound WeChat Channels cover images; never claim to read the video."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from rsi_agent.model import NoRedirect
from rsi_agent.wechat import private_file


def descriptor(raw):
    if not isinstance(raw, str) or len(raw.encode()) > 100000 or re.search(r'<!\s*(DOCTYPE|ENTITY)', raw, re.I):
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    apps = root.findall('appmsg')
    if len(apps) != 1 or apps[0].findtext('type') != '51':
        return None
    feed = apps[0].find('finderFeed')
    if feed is None or not feed.findtext('objectId') or feed.findtext('mediaCount') != '1':
        return None
    media = feed.findall('mediaList/media')
    if len(media) != 1:
        return None
    url = media[0].findtext('coverUrl') or ''
    try:
        parts = urlsplit(url)
        valid = (parts.scheme == 'https' and parts.hostname == 'wxapp.tc.qq.com'
                 and parts.port in (None, 443) and not parts.username and not parts.password and not parts.fragment)
    except ValueError:
        return None
    if len(url) > 2048 or any(c.isspace() for c in url) or not valid:
        return None
    caption = '\n'.join(x for x in [apps[0].findtext('title'), feed.findtext('desc')] if x)
    return {'url': url, 'caption': '视频号封面（仅封面，未读取视频内容）：\n' + caption[:2000]}


def annotate(event):
    if event.get('kind') == 49:
        value = descriptor(event.get('text'))
        if value:
            event.update(text=value['caption'], image_kind='finder_cover')
    return event


def source(tool, peer, server):
    from linux_tool import decode, signed
    if tool.resolve(peer)['username'] != peer:
        raise ValueError('Exact native cover peer required.')
    table = 'Msg_' + hashlib.md5(peer.encode()).hexdigest()
    with tool.open('message/message_0.db') as (db, receipt):
        if receipt.get('consistency') != 'committed' or receipt.get('gap'):
            raise ValueError('Committed cover source required.')
        rows = db.execute('SELECT local_type,message_content,real_sender_id FROM ' + table +
                          ' WHERE server_id=?', (signed(server),)).fetchall()
        if len(rows) != 1:
            raise ValueError('Unique native image source required.')
        row = rows[0]
        if int(row['local_type']) & 0xffffffff != 49:
            return None
        sender = db.execute('SELECT user_name FROM Name2Id WHERE rowid=?', (row['real_sender_id'],)).fetchone()
        if not sender:
            raise ValueError('Native cover sender required.')
        raw = decode(row['message_content'])
        if raw.startswith(sender[0] + ':\n'):
            raw = raw[len(sender[0]) + 2:]
        value = descriptor(raw)
        return dict(value, sender=sender[0]) if value else None


def read(api, account, peer, server, value):
    from operations.assets import INLINE_BYTES, validate_image
    from attachments import read_bound
    from PIL import Image
    root = api.s.root
    cache = root / 'finder-covers'
    cache.mkdir(mode=0o700, exist_ok=True)
    if cache.is_symlink() or cache.stat().st_uid != os.getuid() or cache.stat().st_mode & 0o077:
        raise ValueError('Private cover provenance cache required.')
    key = hashlib.sha256((account + '\0' + peer + '\0' + server).encode()).hexdigest()
    path = cache / (key + '.json')
    binding = {'account': account, 'peer': peer, 'source': server, 'sender': value['sender'],
               'url_sha256': hashlib.sha256(value['url'].encode()).hexdigest()}
    if path.exists():
        if not private_file(path):
            raise ValueError('Private original cover receipt required.')
        proof = json.loads(path.read_text())
        if proof['binding'] != binding:
            raise ValueError('Original native cover source changed.')
        asset = api.assets.get('rsi-vision', proof['asset'])
        data = read_bound(root / 'assets', Path(asset['path']), INLINE_BYTES)
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(urllib.request.Request(value['url'], headers={'Accept': 'image/*'}), timeout=25) as response:
                if response.status != 200:
                    raise ValueError('Cover response unavailable.')
                data = response.read(INLINE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError):
            return {'state': 'media_attention', 'code': 'FINDER_COVER_UNAVAILABLE'}
        if not data or len(data) > INLINE_BYTES:
            raise ValueError('Bounded actual cover bytes required.')
        try:
            validate_image(data)
            with Image.open(io.BytesIO(data)) as image:
                fmt = image.format
        except (ValueError, OSError):
            return {'state': 'media_attention', 'code': 'FINDER_COVER_NOT_DECODABLE'}
        mime = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'GIF': 'image/gif', 'WEBP': 'image/webp'}.get(fmt)
        if not mime:
            raise ValueError('Unsupported model cover format.')
        asset = api.assets.put('rsi-vision', 'finder-cover.' + fmt.lower(), data, hashlib.sha256(data).hexdigest())
        proof = {'binding': binding, 'asset': asset['id'], 'mime': mime}
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(proof))
        temporary.chmod(0o600)
        os.replace(temporary, path)
    if hashlib.sha256(data).hexdigest() != asset['sha256']:
        raise ValueError('Original cover bytes changed.')
    return {'state': 'image_ready', 'source_verified': True, 'source_kind': 'finder_cover',
            'cover_only': True, 'mime': proof['mime'], 'data': base64.b64encode(data).decode(),
            'sha256': asset['sha256'], 'messages_sent': 0}
