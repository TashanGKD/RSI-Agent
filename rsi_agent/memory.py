"""Read-only inspection of the native owner's private named memory."""
import os
from pathlib import Path
import sqlite3

from trigger import owner_memory


def _path(value):
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError('existing private inbox database required')
    path = path.resolve()
    if os.name == 'posix':
        from .wechat import private_file
        if not private_file(path):
            raise ValueError('private inbox database required')
    return path


def review(db_path, query='', show_values=False, now=None):
    path = _path(db_path)
    try:
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        try:
            report = owner_memory.inspect(db, query=query, now=now)
        finally:
            db.close()
    except sqlite3.Error as error:
        raise ValueError('readable private inbox database required: ' + str(error)) from None
    items = []
    for item in report['items']:
        value = {'name': item['name'], 'kind': item['kind'],
                 'updated': owner_memory.format_date(item['updated']),
                 'review_at': (owner_memory.format_date(item['review_at'])
                               if item['review_at'] is not None else None),
                 'stale': owner_memory.stale(item, now)}
        if show_values:
            value['value'] = item['value']
        items.append(value)
    return {'state': 'ok', 'db': str(path), 'scope': report['scope'],
            'read_only': True, 'notes': report['notes'], 'fresh': report['fresh'],
            'stale': report['stale'], 'items': items, 'selected': report['selected'],
            'context_bytes': report['context_bytes'],
            'note': 'Native owner chat is the only mutation path.'}