"""Readable group text, frozen once in the existing ordered V2 batch ledger."""
import hashlib
import re

from .reply_io import original_status, status

# A readability policy, not an official/mobile-tested WeChat folding threshold.
PART_UNITS = 300
URL = re.compile(r'https?://[^\s<>，。！？「」“”]+')
PARAGRAPH_BREAK = re.compile(r'(?:\r?\n[^\S\r\n]*){2,}')
SENTENCE_END = re.compile(r"""[。！？!?]+[”’」』）)\]】"'》]*|\.+[”’」』）)\]】"'》]*(?=\s|$)""")
ABBREVIATION = re.compile(r'\b(?:e\.g|i\.e|et al|figs?|eqs?|refs?|vs|dr|mr|mrs|ms|prof|no|[a-z])\.$', re.I)


def units(text):
    return len(text.strip().encode('utf-16-le')) // 2


def split_at(text, offsets):
    start = 0
    for end in offsets:
        yield text[start:end]
        start = end
    if start < len(text):
        yield text[start:]


def sentences(paragraph):
    # Mask URLs without shifting offsets or treating punctuation in a URL as a cut.
    masked = URL.sub(lambda match: 'x' * len(match[0]), paragraph)
    ends = []
    for mark in SENTENCE_END.finditer(masked):
        if mark[0].startswith('.') and ABBREVIATION.search(masked[:mark.start() + 1]):
            continue
        # Keep a directly following source URL with the sentence it supports.
        if URL.match(paragraph[mark.end():].lstrip()):
            continue
        ends.append(mark.end())
    return list(split_at(paragraph, ends))


def pack(chunks, budget):
    parts = []
    current = ''
    for chunk in chunks:
        if current.strip() and chunk.strip() and units(current + chunk) > budget:
            parts.append(current)
            current = ''
        current += chunk
    if current:
        parts.append(current)
    return parts


def split_text(text):
    """Return source slices, keeping every sentence and separator in order."""
    paragraphs = list(split_at(text, (m.end() for m in PARAGRAPH_BREAK.finditer(text)
                                     if text[:m.start()].strip())))
    budget = PART_UNITS
    while True:
        parts = []
        short = []
        for paragraph in paragraphs:
            if units(paragraph) <= budget:
                short.append(paragraph)
            else:
                parts.extend(pack(short, budget))
                short.clear()
                parts.extend(pack(sentences(paragraph), budget))
        parts.extend(pack(short, budget))
        if len(parts) <= 20:
            return parts
        # Widen the target instead of cutting sentences to fit the V2 batch cap.
        budget += 50


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
        if not 1 <= len(rows) <= 20:
            raise ValueError('Original group batch is incomplete.')
        jobs = [api.s.get(client, row[0]) for row in rows]
        if len(jobs) == 1 and 'group_reply_source' not in jobs[0]['dispatch']:
            raise ValueError('Original group batch is incomplete.')
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
    for job in jobs:
        source = job.get('dispatch', {}).get('group_reply_source')
        if source is not None and source.strip() != job['payload']['text']:
            raise ValueError('Original group reply source does not match its payload.')
    return jobs


def original_text(jobs):
    return ''.join(job.get('dispatch', {}).get('group_reply_source', job['payload']['text']) for job in jobs)


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
        part = {'request_id': job['request_id'], 'expected_text': expected, 'actual_text': actual}
        source = job.get('dispatch', {}).get('group_reply_source')
        if source is not None:
            part['source_text'] = source
        parts.append(part)
    return parts


def aggregate(api, jobs, client, rid):
    parts = [original_status(api, job, client) for job in jobs]
    if len(parts) == 1 and 'group_reply_source' not in jobs[0].get('dispatch', {}):
        return parts[0]
    sent = sum(p['outcome'] == 'sent' for p in parts)
    index = next((i for i, p in enumerate(parts) if p['outcome'] != 'sent' or p['cleanup_pending']), len(parts) - 1)
    current = parts[index]
    result = dict(current, request_id=rid,
        reply_sha256=hashlib.sha256(original_text(jobs).encode()).hexdigest(),
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
                'peer': peer, 'action': 'send_text', 'payload': {'text': part.strip()},
                'execution_mode': 'verified_fast'}} for index, part in enumerate(parts)]
            for part, item in zip(parts, items):
                if part != part.strip():
                    item['dispatch'] = {'group_reply_source': part}
            if len(parts) == 1 and 'dispatch' not in items[0]:
                api.call({'op': 'submit', **items[0]})
            else:
                api.call({'op': 'admit', 'client': client, 'batch_id': rid, 'items': items, 'ordered': True})
            jobs = originals(api, client, rid, peer)
        else:
            raise ValueError('Original group batch is incomplete.')
    if op == 'submit' and original_text(jobs) != text:
        raise ValueError('Original group reply changed.')
    result = aggregate(api, jobs, client, rid)
    if op == 'advance':
        if len(jobs) == 1 and 'group_reply_source' not in jobs[0].get('dispatch', {}):
            return advance(api, jobs[0], policy)
        if result['state'] in ('queued', 'confirmed'):
            current = next(j for j in jobs if status(api.view(j))['outcome'] != 'sent')
            progressed = advance(api, current, policy)
            result = aggregate(api, originals(api, client, rid, peer), client, rid)
            if progressed['state'] == 'busy' and result['state'] in ('queued', 'confirmed'):
                result['state'] = 'busy'
    return result
