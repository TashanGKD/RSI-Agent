"""One isolated owner work branch; GitHub reviews the actual source change."""
import re
import subprocess
from pathlib import Path

BRANCH = 'rsi/runtime/owner-work'
REMOTE = 'git@github.com:Yu-Yang-Li/RSI-Agent.git'


def git(workspace, *args):
    return subprocess.check_output(['git', '-C', str(workspace), *args], text=True, timeout=40).strip()


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


def publish(workspace):
    if (git(workspace, 'remote', 'get-url', 'origin') != REMOTE
            or git(workspace, 'branch', '--show-current') != BRANCH):
        raise ValueError('Owner work must retain its pinned repository and branch.')
    paths = git(workspace, 'ls-files', '--modified', '--others', '--exclude-standard', '-z').split('\0')
    paths = [p for p in paths if p]
    if not paths:
        return None
    allowed = {'.py', '.md', '.json', '.yml', '.yaml', '.toml', '.txt', '.sh', '.js', '.ts', '.tsx', '.html', '.css'}
    for name in paths:
        path = Path(workspace) / name
        if (Path(name).suffix not in allowed or name.startswith(('var/', '.env', '.git/', 'memory/private/'))
                or path.is_symlink()):
            raise ValueError('Owner change contains a non-source or private artifact; inspect before publication.')
        if path.exists() and re.search(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[A-Za-z0-9_\-+/=]{20,}', path.read_bytes()):
            raise ValueError('Owner source contains a credential; do not publish it.')
    # Use the same public gate as ordinary PRs, not the model's assertion.
    result = subprocess.run(['/usr/bin/python3', '-B', 'scripts/check.py', '--linux'],
        cwd=workspace, capture_output=True, timeout=480)
    log = Path(workspace).parent / 'validation.log'
    log.write_bytes(result.stdout + result.stderr)
    log.chmod(0o600)
    if result.returncode:
        raise ValueError('Owner source failed the normal Linux gate; preserve the uncommitted change.')
    git(workspace, 'add', '--', *paths)
    git(workspace, 'commit', '-m', 'feat(agent): apply verified owner instruction')
    commit = git(workspace, 'rev-parse', 'HEAD')
    git(workspace, 'push', 'origin', 'HEAD:refs/heads/' + BRANCH)
    return {'commit': commit, 'branch': BRANCH,
            'review_url': 'https://github.com/Yu-Yang-Li/RSI-Agent/compare/main...' + BRANCH}
