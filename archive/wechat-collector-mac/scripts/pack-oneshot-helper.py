"""Pack an explicitly accepted helper as opaque data (never execute it).

Usage: python scripts/pack-oneshot-helper.py --accepted-helper /absolute/wxkey --output /absolute/oneshot-helper.pack
No arguments/help perform no filesystem mutation. Output must not exist.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

LIMIT=32*1024*1024

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accepted-helper',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        if not args.accepted_helper.is_absolute() or not args.output.is_absolute():raise ValueError()
        if args.accepted_helper==args.output or args.accepted_helper.resolve()==args.output.resolve():raise ValueError()
        for path in (args.accepted_helper,args.output.parent):
            if any(part.is_symlink() for part in (path,*path.parents)):raise ValueError()
        fd=os.open(args.accepted_helper,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<before.st_size<=LIMIT:raise ValueError()
            raw=bytearray()
            while len(raw)<=LIMIT:
                block=os.read(fd,min(65536,LIMIT+1-len(raw)))
                if not block:break
                raw.extend(block)
            def pin(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode,s.st_nlink
            if len(raw)!=before.st_size or pin(os.fstat(fd))!=pin(before) or pin(args.accepted_helper.lstat())!=pin(before):raise ValueError()
        finally:os.close(fd)
        sealed=json.dumps(dict(v=1,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),image=base64.b64encode(raw).decode('ascii')),separators=(',',':')).encode('ascii')
        output=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,0o600)
        try:
            view=memoryview(sealed)
            while view:
                n=os.write(output,view)
                if n<=0:raise ValueError()
                view=view[n:]
            os.fsync(output)
        finally:os.close(output)
        print(json.dumps(dict(v=1,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))))
        return 0
    except Exception:
        print('helper pack rejected',file=sys.stderr)
        return 64

if __name__=='__main__':raise SystemExit(main())
