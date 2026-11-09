"""Reuse owner-private official image evidence with a fresh exact native source.

No caller path, GUI control, decryptor, network fetch or new queue. A visible
variant is opt-in and never satisfies the default original-byte contract.
"""
import hashlib
import io
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .contract import digest, ident, peer, parse_request
from .runtime import BeforeEffect

SOURCE_FIELDS = {'account', 'client', 'peer', 'sourceId', 'localId', 'time',
                 'sender', 'nativeMD5', 'nativeLength', 'resourceId'}
ASSET_FIELDS = {'id', 'client', 'name', 'bytes', 'sha256', 'md5'}
RECEIPT_FIELDS = {'version', 'source', 'asset', 'officialFilename',
                  'officialGroupVerified', 'sourceFilenameVerified', 'reviewMethod',
                  'captureComplete', 'format', 'width', 'height'}


def receipt_path(root, job):
    client = ident(job['client']); target = peer(job['peer'])
    source = job['payload']['source_id']
    if not isinstance(source, str) or not re.fullmatch('[0-9]{1,20}', source) or int(source) == 0:
        raise ValueError('exact native source ID required')
    key = digest({'client': client, 'peer': target, 'sourceId': source})
    return Path(root) / 'verified-image-sources' / (key + '.json')


def _read_source_receipt(path):
    directory = path.parent
    if directory.is_symlink():
        raise ValueError('source evidence directory cannot be a symlink')
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError('source evidence cannot be a symlink')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or not 0 < info.st_size <= 32768:
            raise ValueError('bounded private source evidence required')
        raw = os.read(fd, 32769)
        if len(raw) != info.st_size:
            raise ValueError('source evidence changed during read')
    finally:
        os.close(fd)
    return parse_request(raw.decode('utf-8')), hashlib.sha256(raw).hexdigest()



def read_receipt(root, job):
    own = receipt_path(root, job)
    directory = own.parent
    if directory.is_symlink():
        raise ValueError('source evidence directory cannot be a symlink')
    if own.is_symlink():
        raise ValueError('source evidence cannot be a symlink')
    matches = []
    preferred = None
    if not directory.exists():
        return None
    for path in sorted(directory.glob('*.json')):
        if not re.fullmatch(r'[a-f0-9]{64}\.json', path.name):
            continue
        try:
            loaded = _read_source_receipt(path)
        except (OSError, ValueError):
            if path == own:
                raise
            continue
        if loaded is None:
            continue
        receipt, receipt_sha = loaded
        source = receipt.get('source')
        if not isinstance(source, dict) or source.get('peer') != job['peer'] or source.get('sourceId') != job['payload']['source_id']:
            continue
        requested = job['payload'].get('resource_id')
        if requested is not None and source.get('resourceId') != requested:
            continue
        matches.append(loaded)
        if path == own:
            preferred = loaded
    if not matches:
        return None
    # An already prepared request is bound to its original receipt bytes. New
    # cache records cannot retarget it, even when they are equivalent files.
    frozen_sha = (job.get('preview') or {}).get('verifiedSourceReceiptSHA256')
    if frozen_sha:
        frozen = [value for value in matches if value[1] == frozen_sha]
        if not frozen:
            raise ValueError('original prepared source receipt changed or disappeared')
        return frozen[0]
    # Duplicate attribution records for the same bytes are reusable. Actual
    # conflicting source/representation evidence stays ambiguous, not guessed.
    def identity(value):
        receipt = value[0]
        source = {k:v for k,v in receipt['source'].items() if k != 'client'}
        asset = {k:v for k,v in receipt.get('asset', {}).items() if k not in ('id','client')}
        return digest(dict(receipt, source=source, asset=asset))
    if len({identity(value) for value in matches}) != 1:
        raise ValueError('multiple distinct source representations; use the exact existing file/asset evidence')
    return preferred or matches[0]


def validate_receipt(context, receipt, asset, representation):
    if representation not in ('original', 'visible'):
        raise ValueError('explicit original or visible representation required')
    if set(context) != SOURCE_FIELDS or not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise ValueError('exact source evidence schema required')
    if type(receipt['version']) is not int or receipt['version'] != 1 or not isinstance(receipt['source'], dict) or {k:v for k,v in receipt['source'].items() if k!='client'} != {k:v for k,v in context.items() if k!='client'}:
        raise ValueError('native source identity changed')
    ident(receipt['source'].get('client')) # provenance shape only, never a reader permission
    if not isinstance(receipt['asset'], dict) or set(receipt['asset']) != ASSET_FIELDS:
        raise ValueError('frozen client asset identity required')
    if any(asset.get(k) != v for k, v in receipt['asset'].items()):
        raise ValueError('source asset identity or client changed')
    if not re.fullmatch('[a-f0-9]{64}', str(asset.get('id', ''))):
        raise ValueError('content-addressed source asset required')
    for name in ('officialGroupVerified', 'sourceFilenameVerified', 'captureComplete'):
        if receipt[name] is not True:
            raise ValueError('positive official source evidence required')
    if receipt['reviewMethod'] != 'official-save-as-native-time-and-local-id':
        raise ValueError('unsupported source identity evidence')
    if any(type(context[k]) is not int or context[k] <= 0 for k in ('localId', 'time', 'nativeLength', 'resourceId')):
        raise ValueError('native time, local ID, image size and resource required')
    stamp = datetime.fromtimestamp(context['time'], ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d%H%M%S')
    name = receipt['officialFilename']
    pattern = r'Weixin Image_' + stamp + '_' + str(context['localId']) + r'_[0-9]+\.[A-Za-z0-9]+'
    if not isinstance(name, str) or not re.fullmatch(pattern, name):
        raise ValueError('official filename does not match exact native time/local ID')
    if not isinstance(receipt['format'], str) or not receipt['format'] or any(type(receipt[k]) is not int or receipt[k] <= 0 for k in ('width', 'height')):
        raise ValueError('bounded decoded image required')
    original = asset['md5'] == context['nativeMD5'] and asset['bytes'] == context['nativeLength']
    if representation == 'original' and not original:
        raise ValueError('visible variant cannot satisfy original MD5/size requirement')
    return {'sourceId': context['sourceId'], 'sender': context['sender'],
            'resourceId': context['resourceId'], 'format': receipt['format'],
            'width': receipt['width'], 'height': receipt['height'],
            'bytes': asset['bytes'], 'md5': asset['md5'], 'sha256': asset['sha256'],
            'nativeSourceMD5': context['nativeMD5'],
            'nativeMessageMD5Matched': original, 'originalFileVerified': original,
            'representation': 'original' if original else 'official-visible-variant',
            'sourceContextVerified': True, 'nativeSourceIdentityVerified': True,
            'sourceIdentityMethod': receipt['reviewMethod'],
            'officialDefaultFilename': name, 'sourceLocalId': context['localId'],
            'sourceCreateTime': context['time'], 'origin': 'verified-official-client-source-file',
            'cacheReused': True, 'exportPerformedThisRequest': False,
            'contentReady': True, 'businessAIReadClaimed': False, 'messagesSent': 0,
            'UIInputPerformed': False, 'cleanupVerified': True}


def native_context(driver, job, resource):
    from linux_tool import native, signed, decode, ACCOUNT
    from image_client import source_info
    target = job['peer']; sid = job['payload']['source_id']
    if ACCOUNT != driver.policy.cfg['account']:
        raise ValueError('native account changed')
    requested = job['payload'].get('resource_id')
    if requested is not None and requested != resource:
        raise ValueError('requested resource differs from exact source evidence')
    table = 'Msg_' + hashlib.md5(target.encode()).hexdigest()
    with native('message/message_0.db') as (db, receipt):
        if receipt.get('consistency') != 'committed':
            raise ValueError('native source snapshot gap')
        rows = db.execute('SELECT local_id,local_type,message_content,create_time,real_sender_id FROM ' + table + ' WHERE server_id=?', (signed(sid),)).fetchall()
        if len(rows) != 1 or int(rows[0]['local_type']) & 0xffffffff != 3:
            raise ValueError('unique native image source required')
        row = rows[0]
        sender = db.execute('SELECT user_name FROM Name2Id WHERE rowid=?', (row['real_sender_id'],)).fetchone()
        if not sender:
            raise ValueError('native sender unresolved')
        raw = decode(row['message_content'])
        if target.endswith('@chatroom') and raw.startswith(sender[0] + ':\n'):
            raw = raw[len(sender[0]) + 2:]
        image = source_info(raw, 3)
    with native('message/message_resource.db') as (db, receipt):
        if receipt.get('consistency') != 'committed':
            raise ValueError('native resource snapshot gap')
        rows = db.execute('SELECT d.resource_id FROM MessageResourceDetail d JOIN MessageResourceInfo i ON i.message_id=d.message_id JOIN ChatName2Id n ON n.rowid=i.chat_id WHERE n.user_name=? AND i.message_svr_id=? AND d.resource_id=? LIMIT 2', (target, signed(sid), resource)).fetchall()
        if len(rows) != 1:
            raise ValueError('native resource is absent or not uniquely bound')
    return {'account': ACCOUNT, 'client': job['client'], 'peer': target, 'sourceId': sid,
            'localId': row['local_id'], 'time': row['create_time'], 'sender': sender[0],
            'nativeMD5': image['md5'], 'nativeLength': image['length'], 'resourceId': resource}


def qualified(driver, job):
    loaded = read_receipt(driver.root, job)
    if loaded is None:
        return None
    receipt, receipt_sha = loaded
    if not isinstance(receipt.get('source'), dict) or type(receipt['source'].get('resourceId')) is not int:
        raise ValueError('qualified native resource evidence required')
    context = native_context(driver, job, receipt['source']['resourceId'])
    asset = driver.assets.get(job['client'], receipt.get('asset', {}).get('id'))
    proof = validate_receipt(context, receipt, asset, job['payload'].get('representation', 'original'))
    from attachments import read_bound
    data = read_bound(driver.root, Path(asset['path']), cap=None)
    if len(data) != asset['bytes'] or hashlib.sha256(data).hexdigest() != asset['sha256'] or hashlib.md5(data).hexdigest() != asset['md5']:
        raise ValueError('source asset bytes changed')
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(io.BytesIO(data)) as im:
        if (im.format, im.width, im.height) != (proof['format'], proof['width'], proof['height']):
            raise ValueError('decoded source file differs from evidence')
        im.verify()
    with Image.open(io.BytesIO(data)) as im:
        im.load()
    return context, proof, data, receipt_sha


def prepare(driver, job):
    value = qualified(driver, job)
    if value is None:
        return None
    context, proof, data, receipt_sha = value
    from PIL import Image, ImageDraw, ImageOps
    photo = Image.open(io.BytesIO(data)).convert('RGB')
    canvas = Image.new('RGB', (1200, 900), 'white')
    canvas.paste(ImageOps.contain(photo, (580, 850)), (15, 25))
    draw = ImageDraw.Draw(canvas)
    labels = ['Verified official-client visible content' if not proof['originalFileVerified'] else 'Native-MD5 original image',
              'peer: ' + context['peer'], 'source: ' + context['sourceId'],
              'native local ID: ' + str(context['localId']),
              'time: ' + datetime.fromtimestamp(context['time'], ZoneInfo('Asia/Shanghai')).isoformat(),
              'sender: ' + context['sender'], 'resource: ' + str(context['resourceId']),
              'representation: ' + proof['representation'],
              'native MD5 matched: ' + str(proof['nativeMessageMD5Matched']),
              'Stored file reused; no UI or message Send',
              'Read full returned file; outside-photo contents unproven.']
    for number, text in enumerate(labels):
        draw.text((610, 45 + number * 38), text, fill='black')
    path = driver.previews / (job['id'] + '.png')
    canvas.save(path); path.chmod(0o600)
    return {'artifact': job['id'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'width': canvas.width, 'height': canvas.height, 'screenshotBytes': path.stat().st_size,
            'imageRecipe': True, 'verifiedImageSourceRecipe': True, 'programRecipe': True,
            'sourceContext': context, 'context': digest(context),
            'verifiedSourceReceiptSHA256': receipt_sha, 'verifiedSourceProof': proof,
            'uiReadOnlyNoInput': True,
            'summary': {'peer': job['peer'], 'action': 'save_attachment',
                        'source_id': context['sourceId'], 'representation': proof['representation'],
                        'nativeMessageMD5Matched': proof['nativeMessageMD5Matched']}}


def export(driver, job):
    value = qualified(driver, job)
    if value is None:
        raise BeforeEffect('verified source file disappeared; do not open a different image')
    context, proof, data, receipt_sha = value
    preview = job['preview']
    if digest(context) != preview['context'] or receipt_sha != preview['verifiedSourceReceiptSHA256'] or proof != preview['verifiedSourceProof']:
        raise BeforeEffect('exact source file evidence changed since preview')
    suffix = {'JPEG':'jpg','TIFF':'tiff'}.get(proof['format'],proof['format'].lower())
    return data, dict(proof, name='image-' + context['sourceId'] + '-' + proof['representation'] + '.' + suffix)
