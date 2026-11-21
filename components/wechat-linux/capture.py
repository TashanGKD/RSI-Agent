"""Prepare a bounded, own-child-only capture; no arguments has no effects.

Hook discovery/argument layouts: TANGandXUE/wcdb-key-tool (MIT).
Never attaches to an existing process, changes ptrace policy, or prints key bytes.
"""
import argparse
from pathlib import Path
import re
import os
import hashlib
import json
import stat

BINARY=Path('/var/lib/secretary-wechat/app/opt/wechat/wechat')
ROOT=Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))

def release():
    return json.loads(Path(__file__).with_name('client_release.json').read_text())

def validate_binary(value):
    p=Path(value)
    if str(p) not in release()['binary_paths']:raise ValueError('only approved private WeChat executable allowed')
    return p

def verify_binary(value):
    path=validate_binary(value)
    if path.is_symlink() or not path.is_file():raise ValueError('reviewed regular client executable required')
    with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=release()['binary_sha256']:raise ValueError('client differs from the reviewed executable')
    return path

def validate_offset(value):
    if type(value) is not int or not 0<value<2**32:raise ValueError('invalid ELF virtual address')
    return value

def decode_passphrase(value):
    if not isinstance(value,str) or re.fullmatch('[0-9a-f]{64}',value) is None:raise ValueError('invalid secret shape')
    return bytes.fromhex(value)

def prepare(offset=None,binary=None,root=None):
    approved=release()
    if offset is None:offset=approved['capture_offset']
    validate_offset(offset)
    if offset!=approved['capture_offset']:raise ValueError('reviewed client capture offset required')
    binary=verify_binary(binary or BINARY)
    root=Path(root or ROOT)
    info=root.stat()
    if root.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError('private runtime directory owned by the capture user required')
    authorization=root/'capture-secret.hex'
    if authorization.exists() or authorization.is_symlink():raise ValueError('existing authorization is preserved; verify it instead of capturing again')
    p=root/'capture-child.gdb'
    script=f'''set pagination off
set confirm off
set startup-with-shell off
set disable-randomization off
set follow-fork-mode parent
handle SIGUSR1 nostop noprint pass
handle SIGPIPE nostop noprint pass
python
import gdb, pathlib, hashlib
binary=pathlib.Path({str(binary)!r})
configured=gdb.current_progspace().filename
if configured is None or pathlib.Path(configured).resolve()!=binary.resolve():raise RuntimeError('approved child executable required')
with binary.open('rb') as stream:
    if hashlib.file_digest(stream,'sha256').hexdigest()!={approved['binary_sha256']!r}:raise RuntimeError('reviewed child executable changed')
end
starti
python
import gdb, pathlib, os, struct
pid=gdb.selected_inferior().pid
rows=pathlib.Path('/proc/%d/maps'%pid).read_text().splitlines()
bias=None
for row in rows:
    s=row.split()
    if len(s)>=6 and s[-1]=={str(binary)!r} and int(s[2],16)==0:
        bias=int(s[0].split('-')[0],16);break
if bias is None:raise RuntimeError('approved child mapping not found')
class OwnChildCapture(gdb.Breakpoint):
    def stop(self):
        try:
            inf=gdb.selected_inferior()
            if inf.pid!=pid:raise RuntimeError('foreign inferior')
            rsi=int(gdb.parse_and_eval('$rsi')); rdx=int(gdb.parse_and_eval('$rdx'))
            raw=None
            if rsi and rdx==32:raw=inf.read_memory(rsi,32).tobytes()
            elif rsi:
                v=inf.read_memory(rsi+8,16).tobytes()
                ptr,size=struct.unpack('<QQ',v)
                if ptr and size==32:raw=inf.read_memory(ptr,32).tobytes()
            if raw is not None:
                path={str(root/'capture-secret.hex')!r}
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'w') as f:f.write(raw.hex())
                self.enabled=False
                return True
        except FileExistsError:self.enabled=False
        except Exception:pass
        return False
OwnChildCapture('*0x%x'%(bias+{offset}))
end
continue
detach
quit
'''
    if p.exists() or p.is_symlink():
        if (p.is_symlink() or p.stat().st_uid!=os.getuid() or p.stat().st_mode&0o077
                or p.read_text()!=script):raise ValueError('different existing capture preparation is preserved')
        return p
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:f.write(script)
    return p

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--prepare',action='store_true');a.add_argument('--offset',type=lambda s:int(s,0))
    a.add_argument('--binary',help='Reviewed installed executable; use /opt/wechat/wechat for WSL')
    a.add_argument('--root',help='Existing private runtime owned by the account user')
    v=a.parse_args()
    if not v.prepare:a.print_help()
    else:print(prepare(v.offset,v.binary,v.root))
