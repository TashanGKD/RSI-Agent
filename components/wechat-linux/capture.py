"""Prepare a bounded, own-child-only capture; no arguments has no effects.

Hook discovery/argument layouts: TANGandXUE/wcdb-key-tool (MIT).
Never attaches to an existing process, changes ptrace policy, or prints key bytes.
"""
import argparse
from pathlib import Path
import re
import os

BINARY=Path('/var/lib/secretary-wechat/app/opt/wechat/wechat')
ROOT=Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))

def validate_binary(value):
    p=Path(value)
    if p!=BINARY:raise ValueError('only approved private WeChat executable allowed')
    return p

def validate_offset(value):
    if type(value) is not int or not 0<value<2**32:raise ValueError('invalid ELF virtual address')
    return value

def decode_passphrase(value):
    if not isinstance(value,str) or re.fullmatch('[0-9a-f]{64}',value) is None:raise ValueError('invalid secret shape')
    return bytes.fromhex(value)

def prepare(offset):
    validate_offset(offset)
    p=ROOT/'capture-child.gdb'
    script=f'''set pagination off
set confirm off
set startup-with-shell off
set disable-randomization off
set follow-fork-mode parent
handle SIGUSR1 nostop noprint pass
handle SIGPIPE nostop noprint pass
starti
python
import gdb, pathlib, os, struct
pid=gdb.selected_inferior().pid
rows=pathlib.Path('/proc/%d/maps'%pid).read_text().splitlines()
bias=None
for row in rows:
    s=row.split()
    if len(s)>=6 and s[-1]=={str(BINARY)!r} and int(s[2],16)==0:
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
                path={str(ROOT/'capture-secret.hex')!r}
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'w') as f:f.write(raw.hex())
                self.enabled=False
        except FileExistsError:self.enabled=False
        except Exception:pass
        return False
OwnChildCapture('*0x%x'%(bias+{offset}))
end
continue
'''
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:f.write(script)
    return p

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--prepare',action='store_true');a.add_argument('--offset',type=lambda s:int(s,0))
    v=a.parse_args()
    if not v.prepare:a.print_help()
    elif v.offset is None:a.error('explicit reviewed offset required')
    else:print(prepare(v.offset))
