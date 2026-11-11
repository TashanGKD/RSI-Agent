"""Readable group text, frozen once in the existing ordered V2 batch ledger."""
import hashlib
import re
import unicodedata

from .reply_io import original_status, status

# A readability policy, not an official/mobile-tested WeChat folding threshold.
PART_UNITS = 300
URL = re.compile(r'https?://[^\s<>，。；！？「」“”]+')


def atoms(text):
    """Keep URLs, common emoji sequences, combining marks and CRLF intact."""
    index = 0
    while index < len(text):
        match = URL.match(text, index)
        end = match.end() if match else index + 1
        if not match:
            regional = 0x1f1e6 <= ord(text[index]) <= 0x1f1ff
            if regional and end < len(text) and 0x1f1e6 <= ord(text[end]) <= 0x1f1ff:
                end += 1
            while end < len(text):
                char = text[end]
                if (unicodedata.category(char).startswith('M') or char == '\u200d'
                        or text[end - 1] == '\u200d' or 0x1f3fb <= ord(char) <= 0x1f3ff
                        or 0xe0020 <= ord(char) <= 0xe007f
                        or (char == '\n' and text[end - 1] == '\r')):
                    end += 1
                else:
                    break
        yield text[index:end]
        index = end


def split_text(text):
    pieces = list(atoms(text))
    sizes = [len(p.encode('utf-16-le')) // 2 for p in pieces]
    result, start = [], 0
    while start < len(pieces):
        end, size, preferred = start, 0, []
        while end < len(pieces) and size + sizes[end] <= PART_UNITS:
            size += sizes[end]
            end += 1
            if size >= PART_UNITS // 2 and pieces[end - 1][-1] in '\n。！？；.!?; ':
                preferred.append(end)
        if end == start:
            # A single long URL remains clickable in its own bubble. Never truncate it.
            if not URL.fullmatch(pieces[start]):
                raise ValueError('An indivisible text sequence exceeds the group part budget.')
            end += 1
        elif end < len(pieces) and preferred:
            end = preferred[-1]
        result.append(''.join(pieces[start:end]))
        start = end
    if any(not part.strip() for part in result):
        raise ValueError('Group text contains an empty display part.')
    return result


def part_id(rid, index):
    return rid if index == 0 else rid + '-part-' + str(index + 1)


def originals(api, client, rid, peer):
    """Read and verify the existing immutable batch; never re-split old output."""
    from operations.contract import digest, validate_job
    first = api.s.get(client, rid)
    batch = first.get('dispatch', {}).get('batch_id')
    if batch is None:
        jobs = [first]
    else:
        if batch != rid:
            raise ValueError('Original group batch changed.')
        rows = api.s.c.execute('SELECT j.request_id FROM jobs j JOIN dispatch_metadata d ON d.job_id=j.id '
            "WHERE j.client=? AND json_extract(d.spec,'$.batch_id')=? "
            "ORDER BY json_extract(d.spec,'$.position') LIMIT 21", (client, rid)).fetchall()
        if not 2 <= len(rows) <= 20:
            raise ValueError('Original group batch is incomplete.')
        jobs = [api.s.get(client, row[0]) for row in rows]
        frozen = []
        for index, job in enumerate(jobs):
            meta = job['dispatch']
            if (job['request_id'] != part_id(rid, index) or meta['position'] != index
                    or meta['after'] != ([part_id(rid, index - 1)] if index else [])):
                raise ValueError('Original group part order changed.')
            body = validate_job({key: job[key] for key in
                ('client', 'request_id', 'peer', 'action', 'payload', 'method', 'execution_mode')})
            frozen.append({'job': body, 'dispatch': meta})
        receipt = api.s.c.execute('SELECT hash FROM dispatch_batches WHERE client=? AND batch_id=?',
                                 (client, rid)).fetchone()
        if receipt is None or receipt[0] != digest(frozen):
            raise ValueError('Original group batch content changed.')
    if any(j['peer'] != peer or j['action'] != 'send_text' for j in jobs):
        raise ValueError('Original group request changed.')
    return jobs


def aggregate(api, jobs, client, rid):
    parts = [original_status(api, job, client) for job in jobs]
    if len(parts) == 1:
        return parts[0]
    sent = sum(p['outcome'] == 'sent' for p in parts)
    current = next((p for p in parts if p['outcome'] != 'sent' or p['cleanup_pending']), parts[-1])
    result = dict(current, request_id=rid,
        reply_sha256=hashlib.sha256(''.join(j['payload']['text'] for j in jobs).encode()).hexdigest(),
        parts_total=len(parts), parts_sent=sent, parts=parts,
        recoverable_preinput_failure=sent == 0 and current['recoverable_preinput_failure'])
    if sent == len(parts):
        result.update(state='succeeded', outcome='sent')
    elif current['outcome'] == 'sent':
        result.update(state='needs_attention', outcome='unknown', code='GROUP_PART_CLEANUP_PENDING')
    elif sent and current['outcome'] in ('not_sent', 'unknown', 'review_required'):
        result.update(state='needs_attention', outcome='unknown', code='GROUP_PARTIAL_REPLY_STOPPED')
    return result


def handle(api, client, rid, peer, op, text, policy, advance):
    try:
        jobs = originals(api, client, rid, peer)
    except KeyError:
        if op != 'submit':
            raise
        # Only an absent root can allocate a new batch, never a missing later part.
        try:
            api.s.get(client, rid)
        except KeyError:
            if api.s.c.execute('SELECT 1 FROM dispatch_batches WHERE client=? AND batch_id=?',
                               (client, rid)).fetchone():
                raise ValueError('Original group batch root is missing.')
            parts = split_text(text)
            items = [{'job': {'client': client, 'request_id': part_id(rid, index),
                'peer': peer, 'action': 'send_text', 'payload': {'text': part},
                'execution_mode': 'verified_fast'}} for index, part in enumerate(parts)]
            if len(parts) == 1:
                api.call({'op': 'submit', **items[0]})
            else:
                api.call({'op': 'admit', 'client': client, 'batch_id': rid, 'items': items, 'ordered': True})
            jobs = originals(api, client, rid, peer)
        else:
            raise ValueError('Original group batch is incomplete.')
    if op == 'submit' and ''.join(j['payload']['text'] for j in jobs) != text:
        raise ValueError('Original group reply changed.')
    result = aggregate(api, jobs, client, rid)
    if op == 'advance':
        if len(jobs) == 1:
            return advance(api, jobs[0], policy)
        if result['state'] in ('queued', 'confirmed'):
            current = next(j for j in jobs if status(api.view(j))['outcome'] != 'sent')
            progressed = advance(api, current, policy)
            result = aggregate(api, originals(api, client, rid, peer), client, rid)
            if progressed['state'] == 'busy' and result['state'] in ('queued', 'confirmed'):
                result['state'] = 'busy'
    return result
