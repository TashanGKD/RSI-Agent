"""Build, inspect or query the private owner knowledge index."""
from trigger import owner_knowledge


def index(db_path, root, now=None):
    return owner_knowledge.index(root, db_path, now=now)


def status(db_path, now=None):
    inbox = owner_knowledge.owner_db(db_path)
    report = owner_knowledge.status(owner_knowledge.index_path(inbox), now=now)
    report['note'] = 'Read-only; rebuild the index after changing indexed files.'
    return report


def search(db_path, query='', show_text=False, now=None):
    inbox = owner_knowledge.owner_db(db_path)
    report = owner_knowledge.search(owner_knowledge.index_path(inbox), query, now=now)
    results = []
    for row in report['results']:
        item = {key: row[key] for key in ('title', 'path', 'heading', 'updated', 'score')}
        if show_text:
            item['text'] = row['text']
        results.append(item)
    report['results'] = results
    report['note'] = 'Read-only; text is hidden unless --show-text is set.'
    return report