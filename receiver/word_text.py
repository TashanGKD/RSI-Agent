"""Validate a WeChat Word original and extract its body text with the standard library."""
import argparse
import hashlib
import io
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from receiver.codex_worker import word_package as check

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def paragraph(node):
    parts = []
    for item in node.iter():
        if item.tag == W + 't':
            parts.append(item.text or '')
        elif item.tag == W + 'tab':
            parts.append('\t')
        elif item.tag in (W + 'br', W + 'cr'):
            parts.append('\n')
    return ''.join(parts)


def extract(data):
    """Return paragraphs and table rows of the main document in reading order."""
    check(data)
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        if package.getinfo('word/document.xml').file_size > 50000000:
            raise ValueError('Word body over budget.')
        raw = package.read('word/document.xml')
    if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise ValueError('Word body declares entities.')
    body = ET.fromstring(raw).find(W + 'body')
    lines = []
    for block in [] if body is None else body:
        if block.tag == W + 'p':
            lines.append(paragraph(block))
        elif block.tag == W + 'tbl':
            for row in block.iter(W + 'tr'):
                lines.append(' | '.join('\n'.join(paragraph(p) for p in cell.iter(W + 'p'))
                                        for cell in row.findall(W + 'tc')))
    return '\n'.join(lines).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--sha256', help='Expected SHA-256 from the authenticated original.')
    args = parser.parse_args()
    try:
        data = args.path.read_bytes()
        if args.sha256 and hashlib.sha256(data).hexdigest() != args.sha256.lower():
            raise ValueError('Word file differs from the authenticated original.')
        text = extract(data)
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(1, f'{error}\n')
    sys.stdout.buffer.write(text.encode() + b'\n')


if __name__ == '__main__':
    main()
