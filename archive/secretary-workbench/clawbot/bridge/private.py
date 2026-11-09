import json
import os
import stat
import tempfile
from pathlib import Path


def directory(path):
    p=Path(path).absolute()
    for q in (p,*p.parents):
        if q.is_symlink():raise ValueError('private path symlink refused')
    if not p.exists():p.mkdir(mode=0o700,parents=True)
    s=p.stat()
    if not p.is_dir() or s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('private directory must be owned and mode 0700')
    return p


def read(path):
    p=Path(path).absolute()
    if any(q.is_symlink() for q in (p,*p.parents)):raise ValueError('private file symlink refused')
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW),'r') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>65536:
            raise ValueError('unsafe private file')
        return json.load(f)


def write(path,value):
    p=Path(path);directory(p.parent)
    if p.is_symlink():raise ValueError('private file symlink refused')
    if p.exists():read(p)
    data=json.dumps(value,ensure_ascii=False,indent=2).encode()
    if len(data)>65536:raise ValueError('private file budget')
    fd,name=tempfile.mkstemp(prefix='.'+p.name+'-',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,p)
        d=os.open(p.parent,os.O_RDONLY);os.fsync(d);os.close(d)
    finally:
        if os.path.exists(name):os.unlink(name)
