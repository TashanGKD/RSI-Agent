"""One native favourite sticker for a quiet group batch, through the original V2 queue."""
import hashlib
import re

from .reply_io import status


def request_id(client, account, peer, server):
    return client + '-sticker-' + hashlib.sha256((account + '\0' + peer + '\0' + server).encode()).hexdigest()


def handle(api, client, rid, peer, md5, policy, advance):
    """Submit once, confirm only the exact verified favourite preview, then advance.

    The request ID is derived from the original group message, so repeating this
    call reads or advances the same job and can never click a second sticker.
    """
    if not isinstance(md5, str) or not re.fullmatch('[a-f0-9]{32}', md5):
        raise ValueError('Configured favourite sticker MD5 required.')
    try:
        job = api.s.get(client, rid)
    except KeyError:
        api.call({'op': 'submit', 'job': {'client': client, 'request_id': rid, 'peer': peer,
                                          'action': 'send_sticker', 'payload': {'md5': md5}}})
        job = api.s.get(client, rid)
    if job['peer'] != peer or job['action'] != 'send_sticker' or job['payload'] != {'md5': md5}:
        raise ValueError('Original group sticker request changed.')
    if job['state'] in ('queued', 'preparing'):
        advance(api, job, policy)
        job = api.s.get(client, rid)
    if job['state'] == 'awaiting_confirmation':
        view = api.view(job)
        preview = view.get('preview') or {}
        summary = preview.get('summary') or {}
        if (preview.get('available') is True and view.get('confirmation_token')
                and summary.get('action') == 'send_sticker' and summary.get('peer') == peer
                and summary.get('md5') == md5 and summary.get('referencePixelsMatched') is True
                and summary.get('messagesSent') == 0):
            api.call({'op': 'confirm', 'client': client, 'request_id': rid, 'token': view['confirmation_token']})
            job = api.s.get(client, rid)
    if job['state'] in ('confirmed', 'unknown', 'needs_attention'):
        # Unknown and attention only run the original read-only proof/settlement.
        advance(api, job, policy)
        job = api.s.get(client, rid)
    return dict(status(api.view(job)), md5=md5)
