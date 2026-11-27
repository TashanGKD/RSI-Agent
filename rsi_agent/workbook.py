"""Check or regenerate CURRENT.workbook.md from per-item notes. Stdlib only."""
from collections import Counter
from datetime import date
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote

START = '<!-- rsi-work:start -->'
END = '<!-- rsi-work:end -->'
GENERATED = '<!-- rsi-workbook-current:v1 -->'
TARGET = 'CURRENT.workbook.md'
ARCHIVE = 'archive'
FIELDS = ('事情', '怎么来的', '这次想做到什么', '我的想法', '现在怎么样', '下一步', '时间', '过程笔记')
STATES = ('待推进', '等反馈', '先放放', '已办好', '不做了')
ACTIVE_STATES = ('待推进', '等反馈')
CLOSED_STATES = ('已办好', '不做了')
MAX_ACTIVE_ITEMS = 20
MAX_VISIBLE_ITEMS = 30
MAX_CURRENT_BYTES = 8192
MAX_SUMMARY_CHARS = 1200


def ordinary(path, directory=False):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('symbolic link refused: ' + str(part))
    if directory and not path.is_dir():
        raise ValueError('existing work directory required: ' + str(path))
    if not directory and (not path.is_file() or path.stat().st_size > 1_000_000):
        raise ValueError('ordinary bounded note required: ' + path.name)


def summary_size(row):
    return sum(len(row[field]) for field in FIELDS)


def validate_row(row, name):
    if tuple(row) != FIELDS:
        raise ValueError('eight current fields required in documented order: ' + name)
    if any(not isinstance(value, str) or not value.strip() for value in row.values()):
        raise ValueError('nonempty fields required: ' + name)
    if row['现在怎么样'] not in STATES:
        raise ValueError('known state required: ' + name)
    if row['现在怎么样'] == '等反馈' and not re.search(r'等|待|反馈|确认|提供|恢复|条件', row['下一步'] + row['时间']):
        raise ValueError('waiting must explain missing result/condition: ' + name)


def limit_problems(rows):
    problems = []
    active = [row for row in rows if row['现在怎么样'] in ACTIVE_STATES]
    if len(active) > MAX_ACTIVE_ITEMS:
        problems.append({
            'kind': 'active_items', 'count': len(active), 'limit': MAX_ACTIVE_ITEMS,
            'message': 'active work limit {} exceeded ({}); close or archive an item'.format(
                MAX_ACTIVE_ITEMS, len(active))})
    if len(rows) > MAX_VISIBLE_ITEMS:
        problems.append({
            'kind': 'visible_items', 'count': len(rows), 'limit': MAX_VISIBLE_ITEMS,
            'message': 'visible work limit {} exceeded ({}); archive closed work'.format(
                MAX_VISIBLE_ITEMS, len(rows))})
    for row in rows:
        size = summary_size(row)
        if size > MAX_SUMMARY_CHARS:
            problems.append({
                'kind': 'summary_chars', 'file': row.get('file', row['事情']), 'chars': size,
                'limit': MAX_SUMMARY_CHARS,
                'message': 'current summary exceeds {} characters ({}): {}'.format(
                    MAX_SUMMARY_CHARS, size, row.get('file', row['事情']))})
    return problems


def validate_limits(rows):
    problems = limit_problems(rows)
    if problems:
        raise ValueError('; '.join(problem['message'] for problem in problems))


def collect(root, enforce=True, allow_empty=False):
    root = Path(root).expanduser()
    ordinary(root, directory=True)
    root = root.absolute()
    if root in (Path('/'), Path.home()):
        raise ValueError('choose the specific project memory directory')
    folder = root / 'workbook'
    ordinary(folder, directory=True)
    rows, snapshots, titles = [], {}, set()
    paths = sorted(folder.glob('*.md'))
    if not paths:
        if allow_empty:
            return [], {}
        raise ValueError('no work notes; create actual notes before refreshing')
    for path in paths:
        ordinary(path)
        raw = path.read_bytes()
        text = raw.decode('utf-8')
        if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
            raise ValueError('one current-summary block required: ' + path.name)
        block = text.split(START, 1)[1].split(END, 1)[0]
        pairs = re.findall(r'^- \*\*([^*]+)\*\*：(.+)$', block, re.M)
        if tuple(key for key, _ in pairs) != FIELDS:
            raise ValueError('eight current fields required in documented order: ' + path.name)
        row = {key: value.strip() for key, value in pairs}
        validate_row(row, path.name)
        if row['事情'] in titles:
            raise ValueError('distinct result titles required: ' + path.name)
        titles.add(row['事情'])
        row['file'] = path.name
        rows.append(row)
        snapshots[path] = hashlib.sha256(raw).hexdigest()
    if enforce:
        validate_limits(rows)
    return rows, snapshots


def cell(text):
    return text.replace('\\', '\\\\').replace('|', '\\|')


def render(rows):
    result = [GENERATED, '# 工作本当前视图', '',
              '从 `workbook/` 未归档笔记的当前摘要生成；要改进展，请改原笔记，再刷新本页。',
              '`CURRENT.md` 仍是项目基线；本页只汇总逐件工作，不替代项目级验收事实。', '']
    for state in STATES:
        subset = [row for row in rows if row['现在怎么样'] == state]
        result += ['## ' + state + ' · ' + str(len(subset)), '']
        if not subset:
            result += ['当前没有记录。', '']
            continue
        result += ['| 事情 | 本轮想得到的结果 | 我接下来怎么做 | 何时再看 |',
                   '|---|---|---|---|']
        for row in subset:
            label = cell(row['事情']).replace('[', '\\[').replace(']', '\\]')
            link = '[{}](workbook/{})'.format(label, quote(row['file']))
            result.append('| ' + ' | '.join([link, cell(row['这次想做到什么']), cell(row['下一步']), cell(row['时间'])]) + ' |')
        result.append('')
    result += ['已归档笔记不进入本页，保留在 `workbook/archive/`。',
               '本页只证明已记录工作的当前视图；不证明所有来源已读、业务事实正确或协作者已接受。', '']
    return '\n'.join(result)


def stable(root, snapshots):
    if set((root / 'workbook').glob('*.md')) != set(snapshots):
        raise ValueError('note set changed during refresh; reread before retry')
    for path, digest in snapshots.items():
        ordinary(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('note changed during refresh: ' + path.name)


def operate(root, action, execute=False):
    if action not in ('check', 'refresh'):
        raise ValueError('unknown action: ' + str(action))
    root = Path(root).expanduser()
    ordinary(root, directory=True)
    root = root.absolute()
    rows, snapshots = collect(root, allow_empty=archived_count(root) > 0)
    target = root / TARGET
    before = None
    if target.exists() or target.is_symlink():
        ordinary(target)
        before = target.read_bytes()
        if not before.decode('utf-8').startswith(GENERATED):
            raise ValueError('existing CURRENT.workbook.md is not owned by this generator; preserve and adapt it')
    content = render(rows).encode('utf-8')
    if len(content) > MAX_CURRENT_BYTES:
        raise ValueError(
            'CURRENT.workbook.md exceeds {} bytes ({}); archive closed work or shorten current summaries'.format(
                MAX_CURRENT_BYTES, len(content)))
    stable(root, snapshots)
    if action == 'check':
        if before != content:
            raise ValueError('CURRENT.workbook.md is missing or differs from current notes')
    elif execute:
        fd, temporary = tempfile.mkstemp(prefix='.CURRENT.workbook-', dir=root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            stable(root, snapshots)
            current = None
            if target.exists() or target.is_symlink():
                ordinary(target)
                current = target.read_bytes()
            if current != before:
                raise ValueError('CURRENT.workbook.md changed by another writer; no replacement performed')
            os.replace(temporary, target)
            stable(root, snapshots)
            if target.read_bytes() != content:
                raise ValueError('CURRENT.workbook.md changed after write; reread it')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {'notes': len(rows), 'states': dict(Counter(row['现在怎么样'] for row in rows)),
            'action': action, 'written': action == 'refresh' and execute,
            'consistent': before == content if not (action == 'refresh' and execute) else True,
            'target': str(target), 'bytes': len(content), 'limit': MAX_CURRENT_BYTES,
            'scope': 'local work-note/index structure; not business truth or scheduler verification'}


def slug(title):
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '-', title).strip(' .-')
    value = re.sub(r'\s+', '-', value)
    return (value[:60].rstrip(' .-') or 'work-item')


def note_text(row):
    lines = [START, '# ' + row['事情'], '']
    lines += ['- **{}**：{}'.format(field, row[field]) for field in FIELDS]
    lines += [END, '', '## 过程', '', '- {}：建立工作本条目。'.format(date.today().isoformat()), '']
    return '\n'.join(lines)


def plain_name(file_name):
    if (not isinstance(file_name, str) or not file_name.endswith('.md')
            or '/' in file_name or '\\' in file_name or file_name in ('.md', '..md')
            or re.search(r'[<>:"|?*\x00-\x1f]', file_name)):
        raise ValueError('file name must be a plain .md name')


def clean_value(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('nonempty ' + name + ' required')
    if '\n' in value or '\r' in value:
        raise ValueError(name + ' must stay on one line')
    if START in value or END in value:
        raise ValueError(name + ' cannot contain workbook markers')
    return value.strip()


def create(root, title, source, goal, next_step, thought='待补充当前判断',
           time='未安排复看时间', state='待推进', file_name=None):
    root = Path(root).expanduser()
    ordinary(root, directory=True)
    root = root.absolute()
    if root in (Path('/'), Path.home()):
        raise ValueError('choose the specific project memory directory')
    values = {'事情': title, '怎么来的': source, '这次想做到什么': goal, '我的想法': thought,
              '现在怎么样': state, '下一步': next_step, '时间': time,
              '过程笔记': '建立工作本条目，待补充实际变化。'}
    row = {field: clean_value(field, values[field]) for field in FIELDS}
    validate_row(row, 'new note')
    if file_name is None:
        file_name = slug(title) + '.md'
    plain_name(file_name)
    folder = root / 'workbook'
    if folder.exists() or folder.is_symlink():
        ordinary(folder, directory=True)
    else:
        folder.mkdir()
    path = folder / file_name
    if path.exists() or path.is_symlink():
        raise ValueError('note already exists: ' + file_name)
    existing = sorted(folder.glob('*.md'))
    rows = []
    if existing:
        rows, _ = collect(root, enforce=False)
        if any(existing_row['事情'] == row['事情'] for existing_row in rows):
            raise ValueError('distinct result titles required: ' + file_name)
    for_limits = dict(row, file=file_name)
    validate_limits(rows + [for_limits])
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(note_text(row))
    return {'state': 'created', 'note': str(path), 'title': title, 'status': state}


def choose(root, title=None, file_name=None):
    if (title is None) == (file_name is None):
        raise ValueError('choose exactly one of title or file')
    root = Path(root).expanduser()
    ordinary(root, directory=True)
    root = root.absolute()
    rows, snapshots = collect(root, enforce=False)
    if file_name is not None:
        plain_name(file_name)
        matches = [row for row in rows if row['file'] == file_name]
        label = file_name
    else:
        wanted = clean_value('title', title)
        matches = [row for row in rows if row['事情'] == wanted]
        label = wanted
    if not matches:
        raise ValueError('work note not found: ' + label)
    path = root / 'workbook' / matches[0]['file']
    return path, matches[0], snapshots[path]


def replace_summary(text, row):
    before, rest = text.split(START, 1)
    block, after = rest.split(END, 1)
    lines = []
    for line in block.splitlines():
        match = re.match(r'^- \*\*([^*]+)\*\*：', line)
        if match and match.group(1) in FIELDS:
            lines.append('- **{}**：{}'.format(match.group(1), row[match.group(1)]))
        else:
            lines.append(line)
    return before + START + '\n'.join(lines) + '\n' + END + after


def append_log(text, message):
    line = '- {}：{}'.format(date.today().isoformat(), message)
    if '## 过程' in text:
        return text.rstrip('\n') + '\n' + line + '\n'
    return text.rstrip('\n') + '\n\n## 过程\n\n' + line + '\n'


def atomic_replace(path, expected, content):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        ordinary(path)
        if path.read_bytes() != expected:
            raise ValueError('note changed by another writer: ' + path.name)
        os.replace(temporary, path)
        if path.read_bytes() != content:
            raise ValueError('note changed after write: ' + path.name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def update_note(root, title=None, file_name=None, source=None, goal=None,
                thought=None, state=None, next_step=None, time=None,
                process_note=None, log=None):
    path, row, digest = choose(root, title, file_name)
    changes = {'怎么来的': source, '这次想做到什么': goal, '我的想法': thought,
               '现在怎么样': state, '下一步': next_step, '时间': time,
               '过程笔记': process_note}
    updated = {field: row[field] for field in FIELDS}
    changed = []
    for field, value in changes.items():
        if value is None:
            continue
        updated[field] = clean_value(field, value)
        changed.append(field)
    if log is not None:
        log = clean_value('log', log)
        changed.append('log')
    if not changed:
        raise ValueError('at least one field or log is required')
    validate_row(updated, path.name)
    rows, snapshots = collect(path.parent.parent, enforce=False)
    if snapshots.get(path) != digest:
        raise ValueError('note changed by another writer: ' + path.name)
    replaced = []
    for current in rows:
        if current['file'] == row['file']:
            replacement = dict(updated, file=row['file'])
            replaced.append(replacement)
        else:
            replaced.append(current)
    validate_limits(replaced)
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != digest:
        raise ValueError('note changed by another writer: ' + path.name)
    text = replace_summary(original.decode('utf-8'), updated)
    if log is not None:
        text = append_log(text, log)
    atomic_replace(path, original, text.encode('utf-8'))
    return {'state': 'updated', 'note': str(path), 'title': updated['事情'],
            'changed': changed, 'status': updated['现在怎么样'],
            'archive_ready': updated['现在怎么样'] in CLOSED_STATES}


def archive(root, title=None, file_name=None, execute=False):
    path, row, digest = choose(root, title, file_name)
    if row['现在怎么样'] not in CLOSED_STATES:
        raise ValueError('archive requires 已办好 or 不做了: ' + row['事情'])
    folder = path.parent / ARCHIVE
    target = folder / path.name
    if target.exists() or target.is_symlink():
        raise ValueError('archive target already exists: ' + target.name)
    if not execute:
        return {'state': 'preview', 'note': str(path), 'target': str(target),
                'title': row['事情'], 'written': False}
    if folder.exists() or folder.is_symlink():
        ordinary(folder, directory=True)
    else:
        folder.mkdir()
    ordinary(folder, directory=True)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('note changed by another writer: ' + path.name)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        if path.read_bytes() != raw:
            raise ValueError('note changed before archive: ' + path.name)
        os.replace(path, target)
    except Exception:
        if target.exists() and target.is_file() and target.stat().st_size == 0:
            target.unlink()
        raise
    visible = len(list(path.parent.glob('*.md')))
    return {'state': 'archived', 'note': str(path), 'target': str(target),
            'title': row['事情'], 'visible': visible, 'written': True}


def archived_count(root):
    folder = Path(root) / 'workbook' / ARCHIVE
    if not folder.is_dir() or folder.is_symlink():
        return 0
    return len(list(folder.glob('*.md')))


def review(root):
    root = Path(root).expanduser()
    ordinary(root, directory=True)
    root = root.absolute()
    rows, _ = collect(root, enforce=False, allow_empty=True)
    content = render(rows).encode('utf-8')
    problems = limit_problems(rows)
    if len(content) > MAX_CURRENT_BYTES:
        problems.append({
            'kind': 'current_bytes', 'bytes': len(content), 'limit': MAX_CURRENT_BYTES,
            'message': 'CURRENT.workbook.md exceeds {} bytes ({}); archive closed work or shorten current summaries'.format(
                MAX_CURRENT_BYTES, len(content))})
    target = root / TARGET
    view = 'missing'
    if target.exists() or target.is_symlink():
        ordinary(target)
        raw = target.read_bytes()
        if raw == content:
            view = 'current'
        elif raw.decode('utf-8').startswith(GENERATED):
            view = 'stale'
        else:
            view = 'unowned'
    order = {state: index for index, state in enumerate(STATES)}
    items = [{'title': row['事情'], 'state': row['现在怎么样'], 'next': row['下一步'],
              'time': row['时间'], 'file': row['file'], 'summary_chars': summary_size(row)}
             for row in rows]
    items.sort(key=lambda item: (order[item['state']], item['time'], item['title']))
    return {'notes': len(rows), 'visible': len(rows),
            'active': sum(1 for row in rows if row['现在怎么样'] in ACTIVE_STATES),
            'archived': archived_count(root), 'items': items,
            'limits': {'active': MAX_ACTIVE_ITEMS, 'visible': MAX_VISIBLE_ITEMS,
                       'current_bytes': MAX_CURRENT_BYTES, 'summary_chars': MAX_SUMMARY_CHARS},
            'current_bytes': len(content), 'over': problems, 'view': view,
            'scope': 'local work-note/index structure; not business truth or scheduler verification'}


def refresh(root, execute=False):
    return operate(root, 'refresh', execute)


def check(root):
    return operate(root, 'check', False)