"""Turn a source-qualified native attachment into a Codex input block."""
import base64
import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile


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
    if (1 <= len(name.encode()) <= 180 and name.lower().endswith(('.pdf', '.md', '.txt', '.docx'))
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


def word_document(data):
    """Admit only a bounded, unencrypted Word package containing its main document."""
    try:
        if not data.startswith(b'PK\x03\x04') or len(data) > 25000000:
            raise ValueError
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            entries = package.infolist()
            names = {entry.filename for entry in entries}
            if (len(entries) > 2000 or not {'[Content_Types].xml', 'word/document.xml'} <= names
                    or any(entry.flag_bits & 1 for entry in entries)
                    or sum(entry.file_size for entry in entries) > 200000000):
                raise ValueError
    except (ValueError, zipfile.BadZipFile):
        raise MediaUnavailable('DOCUMENT_WORD_INVALID') from None


def check_document(name, data):
    (word_document if name.lower().endswith('.docx') else text_document)(data)


def document_part(transport, server, name):
    value = transport({'op': 'document', 'server_id': str(server)})
    if value.get('state') != 'document_ready' or value.get('source_verified') is not True:
        raise MediaUnavailable(value.get('code', 'DOCUMENT_NOT_AVAILABLE'))
    data = base64.b64decode(value['data'], validate=True)
    if value['name'] != name or hashlib.sha256(data).hexdigest() != value['sha256']:
        raise MediaUnavailable('DOCUMENT_BYTES_CHANGED')
    check_document(name, data)
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
