"""One isolated owner work branch; GitHub reviews the actual source change."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .wechat import private_file

BRANCH = 'rsi/runtime/owner-work'
REMOTE = 'git@github.com:Yu-Yang-Li/RSI-Agent.git'


def git(workspace, *args, env=None):
    return subprocess.check_output(['git', '-C', str(workspace), *args], text=True,
                                   timeout=40, env=env).strip()


def prepare(workspace):
    if (git(workspace, 'remote', 'get-url', 'origin') != REMOTE
            or git(workspace, 'branch', '--show-current') != BRANCH):
        raise ValueError('The pinned isolated owner work branch changed.')
    if git(workspace, 'status', '--porcelain'):
        raise ValueError('Earlier owner work has uncommitted changes; inspect it before another task.')
    # Never reset a task or its published commit on a model retry.
    git(workspace, 'fetch', 'origin', 'main')
    if git(workspace, 'rev-list', '--count', 'origin/main..HEAD') == '0':
        git(workspace, 'merge', '--ff-only', 'origin/main')
    return git(workspace, 'rev-parse', 'HEAD')


def save_publication(path, value):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def source_tree(workspace, base):
    """Freeze working files, including staged-only edits, without changing the index."""
    fd, name = tempfile.mkstemp(prefix='publication-index-', dir=Path(workspace).parent)
    os.close(fd)
    os.unlink(name)  # read-tree creates an index, not an empty index file.
    try:
        env = dict(os.environ, GIT_INDEX_FILE=name)
        git(workspace, 'read-tree', base, env=env)
        git(workspace, 'add', '-A', env=env)
        return git(workspace, 'write-tree', env=env)
    finally:
        Path(name).unlink(missing_ok=True)


def publisher_idle(workspace):
    # A killed worker can leave validation/Git children behind. Never race or kill them.
    for entry in Path('/proc').glob('[0-9]*'):
        if entry.name == str(os.getpid()):
            continue
        try:
            if os.getuid() != 0 and entry.stat().st_uid != os.getuid():
                continue
            if (entry / 'cwd').resolve(strict=True) == Path(workspace).resolve():
                raise BlockingIOError('Original workspace still has a live process; wait without reexecution.')
        except (FileNotFoundError, ProcessLookupError):
            continue


def publish(workspace, checkpoint, binding):
    """Resume only the frozen publisher, after a positively closed SDK Session."""
    checkpoint = Path(checkpoint)
    if (git(workspace, 'remote', 'get-url', 'origin') != REMOTE
            or git(workspace, 'branch', '--show-current') != BRANCH):
        raise ValueError('Owner work must retain its pinned repository and branch.')
    publisher_idle(workspace)
    # Reject private bytes before even a temporary index writes Git objects.
    paths = (git(workspace, 'diff', '--name-only', '--no-renames', '-z', binding['base'], '--')
             + '\0' + git(workspace, 'ls-files', '--others', '--exclude-standard', '-z')).split('\0')
    allowed = {'.py', '.md', '.json', '.yml', '.yaml', '.toml', '.txt', '.sh', '.js', '.ts', '.tsx', '.html', '.css'}
    for name in filter(None, paths):
        path = Path(workspace) / name
        if (Path(name).suffix not in allowed or name.startswith(('var/', '.env', '.git/', 'memory/private/'))
                or path.is_symlink()):
            raise ValueError('Owner change contains a non-source or private artifact; inspect before publication.')
        if path.exists() and re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[A-Za-z0-9_\-+/=]{20,}', path.read_bytes()):
            raise ValueError('Owner source contains a credential; do not publish it.')
    if checkpoint.exists():
        if not private_file(checkpoint):
            raise ValueError('Private original publication checkpoint required.')
        record = json.loads(checkpoint.read_text())
        if record['binding'] != binding or record['phase'] == 'review':
            raise ValueError('Original publication needs review; do not recreate it.')
    else:
        if git(workspace, 'rev-parse', 'HEAD') != binding['base']:
            raise ValueError('SDK changed the original Git head; inspect its effects before publication.')
        record = {'binding': binding, 'phase': 'prepared', 'commit': None,
                  'index': git(workspace, 'write-tree'), 'tree': source_tree(workspace, binding['base']),
                  'remote': git(workspace, 'ls-remote', 'origin', 'refs/heads/' + BRANCH).split('\t')[0]}
        save_publication(checkpoint, record)

    def review(message):
        record['phase'] = 'review'
        save_publication(checkpoint, record)
        raise ValueError(message)

    base = binding['base']
    head = git(workspace, 'rev-parse', 'HEAD')
    if (head not in (base, record['commit'])
            or git(workspace, 'write-tree') not in (record['index'], record['tree'])
            or source_tree(workspace, base) != record['tree']):
        review('Original publication source, index or head changed; preserve it for review.')
    paths = git(workspace, 'diff-tree', '--no-commit-id', '--name-only', '-r', '-z',
                base, record['tree']).split('\0')
    paths = [name for name in paths if name]
    if not paths:
        record['phase'] = 'completed'
        save_publication(checkpoint, record)
        return None
    # Use the same public gate as ordinary PRs, not the model's assertion.
    if record['phase'] == 'prepared':
        result = subprocess.run(['/usr/bin/python3', '-B', 'scripts/check.py', '--linux'],
            cwd=workspace, capture_output=True, timeout=480)
        log = Path(workspace).parent / 'validation.log'
        log.write_bytes(result.stdout + result.stderr)
        log.chmod(0o600)
        if result.returncode:
            review('Owner source failed the normal Linux gate; preserve the uncommitted change.')
        if source_tree(workspace, base) != record['tree']:
            review('Validation changed the frozen source; inspect before publication.')
        record['phase'] = 'validated'
        save_publication(checkpoint, record)
    publisher_idle(workspace)
    if git(workspace, 'write-tree') not in (record['index'], record['tree']):
        review('Validation changed the original index; preserve its staging for review.')
    if not record['commit']:
        # Save the immutable commit before changing a branch or pushing. Re-entry
        # can then reconcile each effect without another model run or commit.
        record['commit'] = git(workspace, 'commit-tree', record['tree'], '-p', base,
            '-m', 'feat(agent): apply verified owner instruction')
        save_publication(checkpoint, record)
    commit = record['commit']
    if head == base:
        git(workspace, 'update-ref', 'refs/heads/' + BRANCH, commit, base)
    if git(workspace, 'write-tree') != record['tree']:
        git(workspace, 'read-tree', record['tree'])
    remote = git(workspace, 'ls-remote', 'origin', 'refs/heads/' + BRANCH).split('\t')[0]
    if remote != commit:
        if remote != record['remote']:
            review('Remote owner branch changed; do not overwrite it.')
        git(workspace, 'push', 'origin', commit + ':refs/heads/' + BRANCH)
    if git(workspace, 'ls-remote', 'origin', 'refs/heads/' + BRANCH).split('\t')[0] != commit:
        raise OSError('Original publication push is not confirmed yet.')
    record['phase'] = 'completed'
    save_publication(checkpoint, record)
    return {'commit': commit, 'branch': BRANCH,
            'review_url': 'https://github.com/Yu-Yang-Li/RSI-Agent/compare/main...' + BRANCH}
