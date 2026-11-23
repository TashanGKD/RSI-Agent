"""One frozen reply image through the original V2 queue, after its reply text."""
import base64
import binascii
import hashlib
import re

INPUT_LIMIT = 15_000_000  # one base64 image of at most 10 MB plus JSON framing


def image_id(rid, index):
    return rid + '-image-' + str(index)


def send(api, client, rid, peer, index, sha256, data, policy, advance):
    """Submit once under a stable ID, advance it, and report its own native receipt.

    Repeating the call with the same original reads or advances the same job, so
    a lost response can never click Send twice.
    """
    if type(index) is not int or not 0 <= index <= 3 or not re.fullmatch('[a-f0-9]{64}', sha256 or ''):
        raise ValueError('Original reply image index and digest required.')
    text = api.s.get(client, rid)
    if text['peer'] != peer or text['state'] != 'succeeded':
        raise ValueError('Reply images follow the sent original text.')
    identity = image_id(rid, index)
    try:
        job = api.s.get(client, identity)
    except KeyError:
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, TypeError, ValueError):
            raise ValueError('Frozen reply image bytes required.') from None
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError('Reply image bytes differ from the frozen digest.')
        name = 'reply-' + sha256[:16] + ('.png' if raw.startswith(b'\x89PNG') else '.jpg')
        asset = api.call({'op': 'upload', 'client': client, 'name': name, 'sha256': sha256, 'data': data})['id']
        api.call({'op': 'submit', 'job': {'client': client, 'request_id': identity, 'peer': peer,
                  'action': 'send_image', 'execution_mode': 'verified_fast', 'payload': {'asset': asset}}})
        job = api.s.get(client, identity)
    if (job['peer'] != peer or job['action'] != 'send_image'
            or api.assets.get(client, job['payload']['asset'])['sha256'] != sha256):
        raise ValueError('Original reply image request changed.')
    if job['state'] in ('queued', 'confirmed') or (job['state'] == 'awaiting_confirmation'
                                                    and not (job.get('preview') or {}).get('reviewRequired')):
        try:
            advance(api, job, policy)
        except BlockingIOError:
            pass
        job = api.s.get(client, identity)
    proof = job.get('result') or {}
    sent = (job['state'] == 'succeeded' and proof.get('state') == 'accepted' and proof.get('sendClicks') == 1
            and bool(proof.get('serverId')) and proof.get('payloadSha256') == sha256)
    if sent:
        state = 'sent'
    elif job['state'] in ('failed', 'cancelled', 'expired') and proof.get('noSend') is True:
        state = 'not_sent'
    elif job['state'] in ('unknown', 'needs_attention', 'succeeded'):
        state = 'unknown'  # Preserve for reconciliation; never another click.
    else:
        state = 'pending'
    return {'state': state, 'request_id': identity, 'sha256': sha256,
            'server_id': str(proof['serverId']) if sent else None, 'code': proof.get('code')}
