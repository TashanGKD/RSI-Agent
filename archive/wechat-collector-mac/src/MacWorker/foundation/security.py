import re
from pathlib import Path
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
import zstandard

MAX_CONTENT = 8 * 1024 * 1024


def safe_path(root, fragment):
    if '\0' in str(fragment) or Path(fragment).is_absolute():
        raise ValueError('invalid path')
    root = Path(root).resolve()
    path = (root / fragment).resolve()
    if not path.is_relative_to(root):
        raise ValueError('path outside account')
    return path


def check_request(host, origin, port):
    expected = f'127.0.0.1:{port}'
    if host != expected or (origin is not None and origin != f'http://{expected}'):
        raise ValueError('request must come from the local reader')


def decode_content(raw):
    if raw is None: return ''
    if isinstance(raw, str):
        if len(raw.encode('utf-8')) > MAX_CONTENT: raise ValueError('message too large')
        return raw
    b = bytes(raw)
    if len(b) > MAX_CONTENT: raise ValueError('message too large')
    if b.startswith(b'\x28\xb5\x2f\xfd'):
        with zstandard.ZstdDecompressor().stream_reader(b) as r:
            b = r.read(MAX_CONTENT + 1)
        if len(b) > MAX_CONTENT: raise ValueError('expanded message too large')
    return b.decode('utf-8', 'replace')


def xml_root(text):
    if len(text)>MAX_CONTENT:raise ValueError('unsafe XML')
    try: return ET.fromstring(text,forbid_dtd=True,forbid_entities=True,forbid_external=True)
    except DefusedXmlException as e: raise ValueError('unsafe XML') from e
    except ET.ParseError: return None


def qid(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name): raise ValueError('invalid database identifier')
    return '"' + name + '"'
