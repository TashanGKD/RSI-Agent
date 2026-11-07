"""App19 stored-field reader. No I/O; no URL, media, or original-message lookup."""
import html
import re
import xml.etree.ElementTree as ET

from app_message import CardError, MAX_BYTES, field, number, safe_plaintext

MAX_NODES = 1024
MAX_DEPTH = 32
MAX_ITEMS = 100  # New, conservative item limit; never Windows' 500 / 16 MiB.
KINDS = {1: '文字', 2: '图片', 3: '语音', 4: '视频', 5: '链接',
         6: '位置', 8: '文件', 17: '嵌套合并记录', 37: '表情'}
STRUCTURE = re.compile(r'<!\s*(?:DOCTYPE|ENTITY)', re.I)
TAG = re.compile(r'<\s*(?:[!?]|/?\s*[A-Za-z_][\w:.-]*(?=[\s/>]))')
PRIVATE = re.compile(
    r'(?:aeskey|encfilekey|cdn[\w-]*|access[_-]?token|authorization|'
    r'password|passwd|secret|token|credential|api[_-]?key|client[_-]?secret|'
    r'(?:private|secret|access)[_-]?key|密码|口令)[\s\"\x27]*[:：=]|'
    r'\bBearer\s+\S+|-----BEGIN [^-]*PRIVATE KEY', re.I)
# Display-only guard: also withhold protocol-relative and scheme-less URL forms.
# Domain-shaped ordinary tokens can be conservatively withheld with an explicit gap.
URL = re.compile(
    r'\b(?:[a-z][a-z0-9+.-]*://|www\.)|\b(?:data|javascript):|'
    r'(?<![A-Za-z0-9_@.-])(?:'
    r'//[A-Za-z0-9\[]|'
    r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+'
    r'(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]{2,59})(?![A-Za-z0-9_-])|'
    r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![A-Za-z0-9_.-]))', re.I)
ENTITY = re.compile(r'&(?:#[xX]?[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);')


def safe_stored(value):
    """Conservatively reject markup, URL and credential-shaped display fields.

    Probe limited entity-decoding layers too, but never return decoded markup.
    Plain comparison punctuation such as 'A < B，C > D' remains ordinary text.
    """
    if value is None:
        return True
    probe = value
    for _ in range(4):
        if (not safe_plaintext(probe) or TAG.search(probe) or PRIVATE.search(probe)
                or URL.search(probe) or any(ord(c) < 32 and c not in '\n\r\t' for c in probe)):
            return False
        decoded = html.unescape(probe)
        if decoded == probe:
            return True
        probe = decoded
    return not ENTITY.search(probe) and safe_plaintext(probe) and not (
        TAG.search(probe) or PRIVATE.search(probe) or URL.search(probe))


def no_mixed_content(node):
    if (node.text or '').strip() or any((child.tail or '').strip() for child in node):
        raise CardError('record_mixed_content')


def unique_children(node):
    no_mixed_content(node)
    names = [child.tag for child in node]
    if len(names) != len(set(names)):
        raise CardError('duplicate_record_field')


class Budget:
    """One budget for outer XML AND all embedded/re-encoded nested XML."""
    def __init__(self, root, input_bytes):
        self.bytes = input_bytes
        self.nodes = 0
        self.items = 0
        self.depths = {}
        self.register(root, 1)

    def register(self, root, depth):
        pending = [(root, depth)]
        while pending:
            node, d = pending.pop()
            self.nodes += 1
            if self.nodes > MAX_NODES or d > MAX_DEPTH:
                raise CardError('record_structure_budget')
            self.depths[node] = d
            pending.extend((child, d + 1) for child in node)

    def expand(self, text, container):
        # Count work on expanded documents cumulatively, not per recursion level.
        self.bytes += len(text.encode('utf8'))
        if self.bytes > MAX_BYTES:
            raise CardError('record_byte_budget')
        if STRUCTURE.search(text):
            raise CardError('record_xml_declaration_forbidden')
        try:
            root = ET.fromstring(text.strip())
        except ET.ParseError:
            raise CardError('record_invalid_xml') from None
        self.register(root, self.depths[container] + 1)
        return root


def empty_record():
    return {'items': [], 'declaredCount': None, 'storedCount': 0, 'emittedCount': 0,
            'parseStatus': 'partial', 'truncated': False, 'gaps': [],
            'contentScope': 'stored_text_and_titles_only', 'fullContentAvailable': False,
            'originalMessagesVerified': False}


def record_root(container, budget):
    if container.tag == 'recordinfo':
        return container
    if len(container):
        if (len(container) != 1 or container[0].tag != 'recordinfo'
                or (container.text or '').strip() or (container[0].tail or '').strip()):
            raise CardError('record_container_ambiguous')
        return container[0]
    if not (container.text or '').strip():
        return None
    root = budget.expand(container.text, container)
    if root.tag != 'recordinfo':
        raise CardError('record_root_unsupported')
    return root


def display_field(node, name, gaps, limit=MAX_BYTES):
    value = field(node, name)
    if value is None or not value.strip():
        return None
    if len(value.encode('utf8')) > limit or not safe_stored(value):
        gaps.append(name + '_not_safe_plaintext')
        return None
    return value


def read_record(container, budget, path=()):
    out = empty_record()
    gaps = out['gaps']
    root = record_root(container, budget)
    if root is None:
        gaps.append('record_missing')
        return out
    unique_children(root)
    lists = root.findall('datalist')
    if not lists:
        gaps.append('record_list_missing')
        return out
    listing = lists[0]
    no_mixed_content(listing)
    if any(child.tag != 'dataitem' for child in listing):
        raise CardError('unsupported_record_list_child')
    declared = number(listing.get('count'))
    out['declaredCount'] = declared
    out['storedCount'] = len(listing)
    if declared is None:
        gaps.append('declared_count_missing_or_invalid')
    elif declared != len(listing):
        gaps.append('declared_count_mismatch')
    for index, node in enumerate(listing, 1):
        if budget.items >= MAX_ITEMS:
            out['truncated'] = True
            gaps.append('record_item_budget')
            break
        budget.items += 1
        unique_children(node)
        kind = number(node.get('datatype'))
        item_gaps = []
        item_path = (*path, index)
        row = {'position': list(item_path), 'kind': kind, 'kindLabel': KINDS.get(kind, '未知类型'),
               'text': None, 'title': None, 'claimedSender': None, 'claimedTime': None,
               'identitySource': 'embedded_record_unverified', 'originalMessageVerified': False,
               'contentStatus': 'not_fetched', 'nested': None, 'gaps': item_gaps}
        row['claimedSender'] = display_field(node, 'sourcename', item_gaps, 256)
        row['claimedTime'] = display_field(node, 'sourcetime', item_gaps, 80)
        if kind == 1:
            row['text'] = display_field(node, 'datadesc', item_gaps)
            row['contentStatus'] = 'stored_text' if row['text'] is not None else 'missing_or_filtered'
            if row['text'] is None:
                item_gaps.append('stored_text_missing_or_filtered')
        elif kind == 5:
            row['title'] = display_field(node, 'datatitle', item_gaps)
            row['contentStatus'] = 'title_only'
            item_gaps.append('link_body_not_fetched')
            if row['title'] is None:
                item_gaps.append('link_title_missing_or_filtered')
        elif kind == 17:
            nested = node.find('recordxml')
            row['contentStatus'] = 'nested_stored_fields'
            row['nested'] = read_record(nested, budget, item_path) if nested is not None else empty_record()
            if nested is None:
                row['nested']['gaps'].append('record_missing')
            item_gaps.extend(row['nested']['gaps'])
            out['truncated'] |= row['nested']['truncated']
        elif kind in KINDS:
            item_gaps.append('media_not_fetched')
        else:
            row['contentStatus'] = 'unsupported'
            item_gaps.append('unknown_record_type')
        known_fields = {'sourcename', 'sourcetime', 'datadesc', 'datatitle'}
        if kind == 17:
            known_fields.add('recordxml')
        if any(child.tag not in known_fields for child in node):
            item_gaps.append('additional_item_fields_not_read')
        out['items'].append(row)
        gaps.extend(item_gaps)
    out['emittedCount'] = len(out['items'])
    out['parseStatus'] = 'partial' if gaps else 'parsed'
    out['gaps'] = list(dict.fromkeys(gaps))
    return out


def render(record):
    lines = []
    for row in record['items']:
        position = '.'.join(map(str, row['position']))
        if row['kind'] == 1:
            text = row['text'] if row['text'] is not None else '[文字缺失或已过滤]'
        elif row['kind'] == 5:
            text = '[链接标题；正文未取读]' + (row['title'] or '[标题缺失或已过滤]')
        elif row['kind'] == 17:
            text = '[嵌套合并记录；仅已存字段]'
        else:
            text = '[' + row['kindLabel'] + '未取读]'
        lines.append(position + '. ' + text)
        if row['nested']:
            lines.extend(render(row['nested']))
    return lines


def parse_forwarded(app, root, input_bytes):
    """Atomically fail this card on malformed structure; keep neighbors upstream."""
    out = empty_record()
    try:
        unique_children(app)
        containers = [child for child in app if child.tag in ('recorditem', 'recordinfo')]
        if len(containers) > 1:
            raise CardError('record_container_ambiguous')
        if not containers:
            out['gaps'].append('record_missing')
        else:
            budget = Budget(root, input_bytes)
            out = read_record(containers[0], budget)
            out['budgetUsed'] = {'bytes': budget.bytes, 'nodes': budget.nodes, 'items': budget.items}
    except CardError as error:
        # Do not retain possibly misleading partial rows after a malformed card.
        out = empty_record()
        out['parseStatus'] = 'failed'
        out['gaps'] = [str(error)]
        out['truncated'] = str(error) in ('record_byte_budget', 'record_structure_budget')
    out['gaps'].append('original_messages_unverified')
    lines = render(out)
    text = '[合并记录：仅已存文字/标题；原消息未核验]\n' + '\n'.join(lines) if lines else ''
    if out['truncated']:
        text += '\n[已达解析预算，内容未完整展开]'
    return text, out
