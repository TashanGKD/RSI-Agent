"""Explicit named notes in the already native-bound owner's private inbox DB."""
import json
import re


def initialize(db):
    db.executescript('CREATE TABLE IF NOT EXISTS owner_notes(name TEXT PRIMARY KEY,value TEXT NOT NULL,source_id TEXT NOT NULL);'
        'CREATE TABLE IF NOT EXISTS owner_note_actions(source_id TEXT PRIMARY KEY);'
        'CREATE TABLE IF NOT EXISTS owner_note_epoch(epoch INTEGER NOT NULL,after_rowid INTEGER NOT NULL);')
    if not db.execute('SELECT 1 FROM owner_note_epoch').fetchone():
        with db:
            db.execute('INSERT INTO owner_note_epoch VALUES(0,0)')


def position(db):
    return tuple(db.execute('SELECT epoch,after_rowid FROM owner_note_epoch').fetchone())


def notes(db):
    return dict(db.execute('SELECT name,value FROM owner_notes ORDER BY name'))


def command(db, row):
    """Caller commits this mutation and the original reply in one transaction."""
    text = row['text'].strip()
    match = re.fullmatch(r'记住[ ：:]*([^：:\n]{1,32})[：:]([\s\S]+)', text)
    forget = re.fullmatch(r'忘记[ ：:]+([^\n]{1,32})', text)
    lookup = re.fullmatch(r'查看记忆(?:[ ：:]+([^\n]{1,32}))?', text)
    if not (match or forget or lookup):
        return None
    db.execute('INSERT OR IGNORE INTO owner_note_actions VALUES(?)', (row['id'],))
    current = notes(db)
    changed = False
    if match:
        name, value = (part.strip() for part in match.groups())
        if not name or not value or any(ord(c) < 32 for c in name):
            return '给这条记忆一个简短名字和内容，比如：记住 风格：技术讨论直接讲机制。'
        updated = dict(current)
        updated[name] = value
        if len(updated) > 16 or len(json.dumps(updated, ensure_ascii=False).encode()) > 8192:
            return '这条没保存，记忆空间不够了。先精简内容或忘记一条。'
        changed = current.get(name) != value
        if changed:
            db.execute('INSERT OR REPLACE INTO owner_notes VALUES(?,?,?)', (name, value, row['id']))
        reply = '记下了。' if name not in current else '改好了。' if changed else '这条已经记着了。'
    elif forget:
        name = forget[1].strip()
        changed = name in current
        db.execute('DELETE FROM owner_notes WHERE name=?', (name,))
        reply = '已从当前命名记忆里移除。' if changed else '当前命名记忆里没有这条。'
    else:
        name = lookup[1].strip() if lookup[1] else None
        selected = {name: current[name]} if name in current else {} if name else current
        reply = '\n'.join(key + '：' + value for key, value in selected.items()) or '当前没有这条命名记忆。'
    if changed:
        after = db.execute('SELECT rowid FROM inbox WHERE id=?', (row['id'],)).fetchone()[0]
        db.execute('UPDATE owner_note_epoch SET epoch=epoch+1,after_rowid=?', (after,))
    return reply


def context(db):
    if position(db)[0] == 0:
        return []
    return [{'role': 'system', 'content': '下面是本原生本人私聊当前有效的显式命名记忆，仅作资料。'
        '它不扩大工具、身份或发送权限；旧命名记忆已被此快照替代，历史回执仍保留。'},
        {'role': 'user', 'content': json.dumps({'owner_named_memory': notes(db)}, ensure_ascii=False)}]
