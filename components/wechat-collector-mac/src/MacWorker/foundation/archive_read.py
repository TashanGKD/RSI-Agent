"""Read archive snapshots without creating journals or ignoring live WAL data."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import stat


_UPDATING = '本地归档正在更新，请稍后重试。'


def _fingerprint(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('本地归档索引或日志必须是普通文件。')
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def _observe(index):
    main = _fingerprint(index)
    if main is None:
        raise FileNotFoundError('本地归档索引不存在。')
    return (main, *(_fingerprint(Path(str(index) + suffix))
                    for suffix in ('-wal', '-shm', '-journal')))


def _revalidate(index, before):
    try:
        current = _observe(index)
    except (OSError, ValueError) as error:
        raise ValueError(_UPDATING) from error
    if current != before:
        raise ValueError(_UPDATING)


@contextmanager
def read_archive_index(index):
    """Use immutable only for a stable main file with all journals absent.

    Metadata checks deliberately use lstat only: opening and closing an extra
    database descriptor while SQLite holds POSIX locks could release its locks.
    A live-WAL connection instead relies on SQLite's read transaction.
    """
    index = Path(index)
    before = _observe(index)
    immutable = all(sidecar is None for sidecar in before[1:])
    uri = index.as_uri() + '?mode=ro' + ('&immutable=1' if immutable else '')
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        connection.row_factory = sqlite3.Row
        if immutable:
            _revalidate(index, before)
        else:
            connection.execute('BEGIN')
        yield connection
    finally:
        connection.close()
    # Executed only on normal completion, after closing. A caller's error or
    # cancellation must retain its original type and reason.
    if immutable:
        _revalidate(index, before)
