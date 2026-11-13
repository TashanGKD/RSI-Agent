"""Turn a source-qualified native attachment into a Codex input block."""
import base64
import hashlib
import re
import xml.etree.ElementTree as ET


class MediaPending(ValueError):
    pass


class MediaUnavailable(ValueError):
    pass


def document_name(raw):
    if not isinstance(raw, str) or len(raw.encode()) > 100000 or re.search(r'<!\s*(DOCTYPE|ENTITY)', raw, re.I):
        return None
    try:
        apps = ET.fromstring(raw).findall('appmsg')
    except ET.ParseError:
        return None
    if len(apps) != 1 or apps[0].findtext('type') != '6':
        return None
    name = apps[0].findtext('title') or ''
    if (1 <= len(name.encode()) <= 180 and name.lower().endswith(('.pdf', '.md', '.txt'))
            and all(c.isprintable() and c not in '/\\' for c in name)):
        return name
    return None


def pdf_name(raw):
    name = document_name(raw)
    return name if name and name.lower().endswith('.pdf') else None


def text_document(data):
    if not data or len(data) > 1000000 or b'\0' in data:
        raise MediaUnavailable('DOCUMENT_TEXT_INVALID_OR_TOO_LARGE')
    try:
        data.decode('utf-8-sig')
    except UnicodeError:
        raise MediaUnavailable('DOCUMENT_UTF8_REQUIRED') from None


def document_part(transport, server, name):
    value = transport({'op': 'document', 'server_id': str(server)})
    if value.get('state') != 'document_ready' or value.get('source_verified') is not True:
        raise MediaUnavailable(value.get('code', 'DOCUMENT_NOT_AVAILABLE'))
    data = base64.b64decode(value['data'], validate=True)
    if value['name'] != name or hashlib.sha256(data).hexdigest() != value['sha256']:
        raise MediaUnavailable('DOCUMENT_BYTES_CHANGED')
    text_document(data)
    return {'type': 'document', 'name': name, 'data': value['data']}


def pdf_part(transport, server, name):
    value = transport({'op': 'pdf', 'server_id': str(server)})
    if value.get('state') != 'pdf_ready' or value.get('source_verified') is not True:
        raise MediaUnavailable(value.get('code', 'PDF_NOT_AVAILABLE'))
    data = base64.b64decode(value['data'], validate=True)
    if value['name'] != name or not data.startswith(b'%PDF-') or hashlib.sha256(data).hexdigest() != value['sha256']:
        raise MediaUnavailable('PDF_BYTES_CHANGED')
    return {'type': 'pdf', 'name': name, 'data': value['data']}


def image_part(transport, server):
    value = transport({'op': 'image', 'server_id': str(server)})
    if value.get('state') == 'media_pending':
        raise MediaPending('The original image export is pending.')
    if value.get('state') != 'image_ready' or value.get('source_verified') is not True:
        raise MediaUnavailable(value.get('code', 'IMAGE_NOT_AVAILABLE'))
    data = base64.b64decode(value['data'], validate=True)
    if not data or hashlib.sha256(data).hexdigest() != value['sha256']:
        raise MediaUnavailable('IMAGE_BYTES_CHANGED')
    if value['mime'] not in ('image/png', 'image/jpeg', 'image/gif', 'image/webp'):
        raise MediaUnavailable('IMAGE_TYPE_UNSUPPORTED')
    return {'type': 'image_url', 'image_url': {'url': 'data:' + value['mime'] + ';base64,' + value['data']}}
