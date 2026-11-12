"""Read source-bound native media without sending anything."""
import base64
import hashlib
from pathlib import Path

from .reply_io import advance, request_id
from .media import pdf_name

CLIENT = 'rsi-vision'


def cancel_queued_image(root, account, peer, server):
    from operations.cli import load_config
    from operations.store import Store
    from receive_source import sid
    state = root / 'operations-state'
    if not (state / 'queue.sqlite').is_file():
        return
    if load_config(state / 'config.json')['account'] != account:
        raise ValueError('Native image account changed.')
    server = sid(server)
    rid = request_id(account, peer, server, CLIENT)
    store = Store(state)
    try:
        try:
            job = store.get(CLIENT, rid)
        except KeyError:
            return
        if (job['peer'] != peer or job['action'] != 'save_attachment'
                or job['payload'].get('source_id') != server or job['payload'].get('source_mode') != 'inbound'):
            raise ValueError('Original inbound image carrier changed.')
        store.cancel(CLIENT, rid, queued_only=True)
    finally:
        store.close()


def pdf(account, peer, server, allowed_senders, since):
    from linux_tool import ACCOUNT, decode, native, signed
    from operations.exports import cached
    from receive_source import sid

    if account != ACCOUNT:
        raise ValueError('Native PDF account changed.')
    server = sid(server)
    table = 'Msg_' + hashlib.md5(peer.encode()).hexdigest()
    with native('message/message_0.db') as (db, receipt):
        if receipt.get('consistency') != 'committed' or receipt.get('gap'):
            raise ValueError('Committed PDF source required.')
        rows = db.execute('SELECT local_type,message_content,create_time,n.user_name FROM ' + table +
            ' m JOIN Name2Id n ON n.rowid=m.real_sender_id WHERE server_id=?', (signed(server),)).fetchall()
        if len(rows) != 1:
            raise ValueError('Unique native PDF source required.')
        kind, encoded, created, sender = rows[0]
        if sender not in allowed_senders or created < since or int(kind) & 0xffffffff != 49:
            raise ValueError('PDF is outside the confirmed incoming scope.')
        raw = decode(encoded)
        if raw.startswith(sender + ':\n'):
            raw = raw[len(sender) + 2:]
    name = pdf_name(raw)
    if not name:
        return {'state': 'media_attention', 'code': 'PDF_SOURCE_UNPROVEN'}
    try:
        data, proof = cached(peer, server, None, raw)
    except (OSError, ValueError):
        return {'state': 'media_attention', 'code': 'PDF_CACHE_UNAVAILABLE'}
    if (proof['name'] != name or proof['sourceId'] != server or not proof['nativeMessageMD5Matched']
            or not proof['resourceCacheBindingVerified'] or not data.startswith(b'%PDF-')):
        return {'state': 'media_attention', 'code': 'PDF_BYTES_UNPROVEN'}
    return {'state': 'pdf_ready', 'name': name, 'data': base64.b64encode(data).decode(),
            'sha256': hashlib.sha256(data).hexdigest(), 'source_verified': True}


def image(root, account, peer, server, allowed_senders):
    from image_client import source
    from linux_tool import Tool
    from receive_source import sid
    from operations.cli import load_config
    from operations.public_api import PublicAPI
    from operations.assets import INLINE_BYTES
    from attachments import read_bound
    server = sid(server)
    try:
        _, native = source(Tool(), {'peer': peer, 'server_id': server})
    except ValueError:
        from . import finder_cover
        cover = finder_cover.source(Tool(), peer, server)
        if cover is None:
            raise
        if cover['sender'] not in allowed_senders:
            raise ValueError('Cover is outside the confirmed incoming scope.')
        policy = load_config(root / 'operations-state/config.json')
        if policy['account'] != account:
            raise ValueError('Native cover account changed.')
        api = PublicAPI(root / 'operations-state', policy)
        try:
            return finder_cover.read(api, account, peer, server, cover)
        finally:
            api.close()
    if native['senderId'] not in allowed_senders:
        raise ValueError('Image is outside the confirmed incoming scope.')
    policy = load_config(root / 'operations-state/config.json')
    if policy['account'] != account:
        raise ValueError('Native image account changed.')
    rid = CLIENT + '-' + hashlib.sha256((account + '\0' + peer + '\0' + server).encode()).hexdigest()
    api = PublicAPI(root / 'operations-state', policy)
    try:
        try:
            job = api.s.get(CLIENT, rid)
        except KeyError:
            api.call({'op': 'submit', 'job': {'client': CLIENT, 'request_id': rid, 'peer': peer,
                'action': 'save_attachment', 'payload': {'source_id': server, 'source_mode': 'inbound',
                                                       'representation': 'visible'}}})
            job = api.s.get(CLIENT, rid)
        visible = job['payload'].get('representation') == 'visible'
        if job['state'] in ('queued', 'confirmed'):
            advance(api, job, policy)
            job = api.s.get(CLIENT, rid)
        if job['state'] == 'awaiting_confirmation':
            preview = job.get('preview') or {}
            context = preview.get('imageContext') or preview.get('sourceContext') or {}
            if (not preview.get('imageRecipe') or not preview.get('programRecipe')
                    or preview.get('needs_assistance') or preview.get('workflow') or preview.get('reviewRequired')
                    or context.get('peer') != peer or context.get('sourceId') != server
                    or context.get('nativeMD5') != native['imageMetadata']['md5']):
                return {'state': 'media_attention', 'code': 'IMAGE_SOURCE_PREVIEW_UNPROVEN'}
            # Standing image-input authorization applies only to this positive
            # read preview. Send/review/unknown jobs never enter this branch.
            api.s.event(job['id'], 'authorized-image-input', {'messagesSent': 0})
            api.s.confirm(CLIENT, rid, job['confirmation_token'])
            advance(api, api.s.get(CLIENT, rid), policy)
            job = api.s.get(CLIENT, rid)
        if job['state'] != 'succeeded':
            return {'state': 'media_pending' if job['state'] in ('queued', 'confirmed') else 'media_attention',
                    'code': (job.get('result') or {}).get('code', job['state'])}
        proof = job['result']
        identity = (proof.get('nativeSourceIdentityVerified') and proof.get('sourceContextVerified')
                    and proof.get('nativeSourceMD5') == native['imageMetadata']['md5'])
        if (proof.get('sourcePeer') != peer or proof.get('sourceId') != server
                or proof.get('sender') != native['senderId'] or not (proof.get('nativeMessageMD5Matched') or visible and identity)
                or not proof.get('contentReady') or proof.get('messagesSent') != 0
                or any(proof.get(k) for k in ('postActionPending', 'navigationRecoveryPending'))):
            return {'state': 'media_attention', 'code': 'IMAGE_SOURCE_RECEIPT_UNPROVEN'}
        asset = api.assets.get(CLIENT, proof['asset']['id'])
        data = read_bound(root / 'operations-state/assets', Path(asset['path']), INLINE_BYTES)
        if (hashlib.sha256(data).hexdigest() != asset['sha256']
                or hashlib.md5(data).hexdigest() != proof.get('md5', native['imageMetadata']['md5'])
                or proof.get('nativeMessageMD5Matched') and hashlib.md5(data).hexdigest() != native['imageMetadata']['md5']
                or not visible and hashlib.md5(data).hexdigest() != native['imageMetadata']['md5']):
            raise ValueError('Exact source image bytes changed.')
        mime = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'GIF': 'image/gif', 'WEBP': 'image/webp'}.get(proof['format'])
        if not mime:
            return {'state': 'media_attention', 'code': 'MODEL_IMAGE_FORMAT_UNSUPPORTED'}
        return {'state': 'image_ready', 'mime': mime, 'data': base64.b64encode(data).decode(),
                'sha256': asset['sha256'], 'native_md5': native['imageMetadata']['md5'],
                'source_verified': True, 'representation': proof.get('representation', 'original'), 'messages_sent': 0}
    finally:
        api.close()
