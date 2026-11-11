"""Readable group text, frozen once in the existing ordered V2 batch ledger."""
import hashlib
import re
import unicodedata

from .reply_io import original_status, status

# A readability policy, not an official/mobile-tested WeChat folding threshold.
PART_UNITS = 300
URL = re.compile(r'https?://[^\s<>，。；！？「」“”]+')
SPACE_BREAK = re.compile(r'(?<![ \t])[ \t]+\r?\n\s*')


def atoms(text):
    """Keep URLs, common emoji sequences, combining marks and CRLF intact."""
    index = 0
    while index < len(text):
        start = index
        separator = SPACE_BREAK.match(text, index)
        if separator:
            # Keep an internal space-plus-newline on the next text atom.
            index = separator.end()
            if index == len(text):
                yield text[start:]
                break
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
        yield text[start:end]
        index = end


def partition(pieces, sizes, budget, prefer_boundaries):
    result, start, leading = [], 0, ''
    while start < len(pieces):
        end, size, preferred = start, 0, []
        while end < len(pieces) and size + sizes[end] <= budget:
            size += sizes[end]
            end += 1
            if size >= budget // 2 and (pieces[end - 1][-1] in '\n。！？；.!?; '
                    or (end < len(pieces) and SPACE_BREAK.match(pieces[end]))):
                preferred.append(end)
        if end == start:
            # Keep indivisible URLs/emoji intact even above the readability target.
            end += 1
        elif end < len(pieces) and preferred and prefer_boundaries:
            end = preferred[-1]
        part = ''.join(pieces[start:end])
        if not part.strip():
            # Blank native messages are invalid. Preserve separators on an adjacent bubble.
            if result:
                result[-1] += part
            else:
                leading += part
        else:
            result.append(leading + part)
            leading = ''
        start = end
    return result


def split_text(text):
    pieces = list(atoms(text))
    sizes = [len(p.encode('utf-16-le')) // 2 for p in pieces]
    result = partition(pieces, sizes, PART_UNITS, True)
    if len(result) > 20:
        # Full 6000-byte replies must remain sendable within V2's 20-job limit.
        # First drop preferred breaks; widen only if protected atoms still need it.
        budget = PART_UNITS
        result = partition(pieces, sizes, budget, False)
        while len(result) > 20:
            budget += 50
            result = partition(pieces, sizes, budget, False)
    return result


def part_id(rid, index):
    return rid if index == 0 else rid + '-part-' + str(index + 1)


def originals(api, client, rid, peer):
    """Read and verify the existing immutable batch; never re-split old output."""
    from operations.contract import digest, validate_job
    first = api.s.get(client, rid)
    batch = first.get('dispatch', {}).get('batch_id')
    receipt = api.s.c.execute('SELECT hash FROM dispatch_batches WHERE client=? AND batch_id=?',
                             (client, rid)).fetchone()
    if batch is None:
        if receipt is not None:
            raise ValueError('Original group batch membership is missing.')
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
        if receipt is None or receipt[0] != digest(frozen):
            raise ValueError('Original group batch content changed.')
    if any(j['peer'] != peer or j['action'] != 'send_text' for j in jobs):
        raise ValueError('Original group request changed.')
    return jobs


def untouched_part(store, job):
    if job['state'] == 'queued' and job.get('result') is None:
        states = ['queued']
    elif job['state'] == 'cancelled' and job.get('result') == {
            'reason': 'caller_cancelled_before_preparation', 'noSend': True}:
        states = ['queued', 'cancelled']
    else:
        return False
    if any(job.get(key) is not None for key in ('preview', 'expires')):
        return False
    history = store.c.execute('SELECT state FROM events WHERE job_id=? ORDER BY seq', (job['id'],))
    return [row[0] for row in history] == states and not any(store.root.glob(job['id'] + '-*'))


def native_text_parts(jobs, sent):
    from operations.proof import text_mode
    parts = []
    for index, job in enumerate(jobs):
        expected = job['payload']['text']
        actual = None
        if index < sent:
            comparison = (job.get('result') or {}).get('textComparison') or {}
            actual = comparison.get('actualText')
            if not isinstance(actual, str):
                return None
            if comparison.get('expectedText') != expected or text_mode(expected, actual) is None:
                raise ValueError('Original group native text comparison changed.')
        parts.append({'request_id': job['request_id'], 'expected_text': expected, 'actual_text': actual})
    return parts


def aggregate(api, jobs, client, rid):
    parts = [original_status(api, job, client) for job in jobs]
    if len(parts) == 1:
        return parts[0]
    sent = sum(p['outcome'] == 'sent' for p in parts)
    index = next((i for i, p in enumerate(parts) if p['outcome'] != 'sent' or p['cleanup_pending']), len(parts) - 1)
    current = parts[index]
    result = dict(current, request_id=rid,
        reply_sha256=hashlib.sha256(''.join(j['payload']['text'] for j in jobs).encode()).hexdigest(),
        parts_total=len(parts), parts_sent=sent, parts=parts,
        recoverable_preinput_failure=sent == 0 and current['recoverable_preinput_failure'])
    if sent == len(parts):
        result.update(state='busy' if current['cleanup_pending'] else 'succeeded', outcome='sent')
    elif (0 < sent == index and current['outcome'] == 'not_sent' and current['recoverable_preinput_failure']
            and all(untouched_part(api.s, job) for job in jobs[index + 1:])):
        result.update(state='failed', outcome='partial')
    elif current['outcome'] == 'sent':
        result.update(state='busy', outcome='pending', code='GROUP_PART_CLEANUP_PENDING')
    elif sent and current['outcome'] in ('not_sent', 'unknown', 'review_required'):
        result.update(state='needs_attention', outcome='unknown', code='GROUP_PARTIAL_REPLY_STOPPED')
    if result['outcome'] in ('sent', 'partial'):
        proven = native_text_parts(jobs, sent)
        if proven is None:
            result.update(state='needs_attention', outcome='unknown', code='GROUP_PART_TEXT_PROOF_MISSING')
        else:
            result['native_parts'] = proven
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
