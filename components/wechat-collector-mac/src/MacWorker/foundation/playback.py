"""Cooperative background checkpoints for the Mac player's native flock lease."""
import errno
import fcntl
import os
from pathlib import Path
import stat
import sys
import time


class PlaybackUnavailable(OSError):
    def __init__(self):
        super().__init__('播放状态暂不可用，已停止后台读取')


def noop_checkpoint():
    pass


class PlaybackCheckpoint:
    def __init__(self, path=None):
        # Alternate paths are internal injection for owned fixtures only.
        self.path=Path(path) if path is not None else Path.home()/'Library/Application Support/WechatUiCollector/playback.lock'

    def _active(self):
        fd=None
        try:
            path=self.path
            # macOS system aliases are the only links permitted. Canonicalize
            # these before NOFOLLOW_ANY rejects links anywhere in the path.
            for alias in ('/tmp','/var'):
                prefix=Path(alias)
                if (path==prefix or prefix in path.parents) and prefix.is_symlink() and prefix.resolve()==Path('/private'+alias):
                    path=Path('/private'+str(path))
                    break
            flags=os.O_RDWR|os.O_NONBLOCK|os.O_CLOEXEC
            if sys.platform=='darwin':flags|=0x20000000  # O_NOFOLLOW_ANY, not O_NOFOLLOW
            else:
                flags|=os.O_NOFOLLOW
                if any(p.is_symlink() for p in path.parents):raise PlaybackUnavailable()
            try:fd=os.open(path,flags)
            except FileNotFoundError:return False
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.geteuid():raise PlaybackUnavailable()
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EWOULDBLOCK,errno.EAGAIN):return True
                raise
            return False
        except (OSError,ValueError):
            raise PlaybackUnavailable() from None
        finally:
            if fd is not None:
                try:os.close(fd)
                except OSError:raise PlaybackUnavailable() from None

    def __call__(self):
        while self._active():time.sleep(.1)
