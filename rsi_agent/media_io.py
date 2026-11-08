"""Read one bound image through the original V2 source/export/asset pipeline."""
import base64
import hashlib
from pathlib import Path

from .reply_io import advance

CLIENT = 'rsi-vision'


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
