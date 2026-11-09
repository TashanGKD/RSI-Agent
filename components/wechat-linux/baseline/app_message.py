"""Bounded type-49 quote extraction from an already selected native row.

No I/O. Identity fields inside XML are claims, never a verified original message.
parseStatus concerns this card's supported fields only, not timeline coverage.
"""
import re
import xml.etree.ElementTree as ET

MAX_BYTES = 32768  # Match the existing Linux decode_text budget.
DECODE_CODES = frozenset(('TEXT_OVER_BUDGET', 'TEXT_COMPRESSED_INVALID',
                          'TEXT_UTF8_INVALID', 'TEXT_NUL', 'TEXT_TYPE_INVALID'))
LABELS = {3: '[图片]', 34: '[语音]', 43: '[视频]', 47: '[表情]',
          48: '[位置]', 49: '[卡片]'}


class CardError(ValueError):
    pass


def field(node, name):
    """Only immediate scalar children; nested titles cannot replace outer text."""
    values = node.findall(name)
    if len(values) > 1:
        raise CardError('ambiguous_xml_field')
    if not values:
        return None
    if len(values[0]):
        raise CardError('non_scalar_xml_field')
    return values[0].text or ''


def number(value):
    if value is None or not re.fullmatch(r'[0-9]{1,10}', value.strip()):
        return None
    return int(value.strip())


def claimed_server_id(value):
    if value is None:
        return None
    value = value.strip()
    if not re.fullmatch(r'-?[1-9][0-9]{0,19}', value):
        return None
    n = int(value)
    if not -(2**63) <= n < 2**64:
        return None
    return str(n & 0xffffffffffffffff)


def safe_plaintext(value):
    """Keep ordinary text; never publish embedded media XML/credential fields."""
    if value is None:
        return True
    return not re.search(
        r'<\s*/?\s*(?:msg|img|appmsg|refermsg|voicemsg|videomsg)\b|'
        r'(?:aeskey|encfilekey|cdn(?:thumb|midimg|bigimg)url|access[_-]?token|'
        r'authorization|password|passwd|secret|密码|口令)\s*[:：=]', value, re.I)


def claimed_name(node, field_name, gaps, *, username=False):
    value = field(node, field_name)
    if value and (not safe_plaintext(value) or
                  (username and not re.fullmatch(r'[A-Za-z0-9_@.-]{1,120}', value))):
        gaps.append('quoted_' + field_name + '_invalid')
        return None
    return value


def parse_app_message(raw, *, local_type, peer, sender, decode):
    """Reuse the caller's bounded decoder; return additive row fields.

    Native high-bit subtype and XML subtype must agree when both are present.
    Quoted media XML is deliberately not exposed or treated as readable media.
    Unsupported app messages retain empty text with an explicit content gap.
    """
    content = {'parseStatus': 'partial', 'appSubtype': None, 'replyText': None,
               'replyTextAvailable': False, 'quote': None, 'gaps': []}
    result = {'text': '', 'appMessage': content}
    gaps = content['gaps']
    try:
        try:
            text = decode(raw)
        except ValueError as error:
            code = getattr(error, 'code', None)
            raise CardError(code if code in DECODE_CODES else 'content_decode_failed') from None
        if not isinstance(text, str):
            raise CardError('TEXT_TYPE_INVALID')
        try:
            size = len(text.encode('utf8'))
        except UnicodeError:
            raise CardError('TEXT_UTF8_INVALID') from None
        if size > MAX_BYTES:
            raise CardError('TEXT_OVER_BUDGET')
        if '\0' in text:
            raise CardError('TEXT_NUL')
        # Unlike skipping to the first '<', this cannot discard arbitrary prefixes.
        if peer.endswith('@chatroom') and sender:
            for prefix in (sender + ':\r\n', sender + ':\n'):
                if text.startswith(prefix):
                    text = text[len(prefix):]
                    break
        text = text.lstrip('\ufeff \t\r\n')
        if re.search(r'<!\s*(DOCTYPE|ENTITY)', text, re.I):
            raise CardError('xml_declaration_forbidden')
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            raise CardError('invalid_xml') from None
        pending = [(root, 1)]
        nodes = 0
        while pending:
            node, depth = pending.pop()
            nodes += 1
            if depth > 32 or nodes > 1024:
                raise CardError('xml_structure_budget')
            pending.extend((child, depth + 1) for child in node)
        apps = [root] if root.tag == 'appmsg' else root.findall('appmsg') if root.tag == 'msg' else []
        if len(apps) != 1:
            raise CardError('outer_appmsg_missing_or_ambiguous')
        app = apps[0]
        native_subtype = (int(local_type) >> 32) & 0xffffffff
        xml_type = field(app, 'type')
        xml_subtype = number(xml_type)
        if xml_type is not None and xml_subtype is None:
            raise CardError('invalid_app_subtype')
        if native_subtype and xml_subtype is not None and native_subtype != xml_subtype:
            raise CardError('app_subtype_conflict')
        subtype = native_subtype or xml_subtype
        content['appSubtype'] = subtype
        if subtype != 57:
            raise CardError('unsupported_app_subtype')
        title = field(app, 'title')
        if not safe_plaintext(title):
            raise CardError('reply_text_not_safe_plaintext')
        quotes = app.findall('refermsg')
        if len(quotes) > 1:
            raise CardError('ambiguous_quote')
        # Parse before publishing any text so malformed structures fail atomically.
        quote = None
        if quotes:
            q = quotes[0]
            kind = number(field(q, 'type'))
            quoted = field(q, 'content') if kind == 1 else None
            if not safe_plaintext(quoted):
                quoted = None
                gaps.append('quoted_text_not_safe_plaintext')
            server = claimed_server_id(field(q, 'svrid'))
            quote = {'serverId': server, 'fromUser': claimed_name(q, 'fromusr', gaps, username=True),
                     'chatUser': claimed_name(q, 'chatusr', gaps, username=True),
                     'displayName': claimed_name(q, 'displayname', gaps),
                     'kind': kind, 'text': quoted if kind == 1 else None,
                     'textAvailable': kind == 1 and bool(quoted and quoted.strip()),
                     'identitySource': 'embedded_refermsg_unverified',
                     'originalMessageVerified': False,
                     'mediaStatus': 'not_applicable' if kind == 1 else 'not_fetched'}
            if server is None:
                gaps.append('quoted_server_id_missing_or_invalid')
            if kind == 1 and not quote['textAvailable']:
                gaps.append('quoted_text_missing')
            if kind != 1:
                gaps.append('quoted_content_not_read')
            gaps.append('quoted_original_not_verified')
        else:
            gaps.append('refermsg_missing')
        content['replyTextAvailable'] = bool(title and title.strip())
        content['replyText'] = title if content['replyTextAvailable'] else None
        if not content['replyTextAvailable']:
            gaps.append('reply_text_missing')
        content['quote'] = quote
        parts = [title] if content['replyTextAvailable'] else []
        if quote:
            summary = quote['text'] if quote['textAvailable'] else LABELS.get(quote['kind'], '[原消息正文未读]')
            parts.append('引用：' + summary)
        result['text'] = '\n'.join(parts)
        content['parseStatus'] = ('parsed' if content['replyTextAvailable'] and quote
                                  and quote['textAvailable'] and quote['serverId'] else 'partial')
    except CardError as error:
        content['parseStatus'] = 'unsupported' if str(error) == 'unsupported_app_subtype' else 'failed'
        gaps.append(str(error))
    return result
