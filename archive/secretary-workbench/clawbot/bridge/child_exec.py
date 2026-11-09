"""Bounded exec trampoline: limits run AFTER fresh Python exec, never preexec.

No daemon/service. Parent retains timeout ownership; exec preserves child PID.
No arguments prints help. Commands are argv arrays, never shell strings.
"""
import math
import os
from pathlib import Path
import resource
import stat
import subprocess
import sys

MAX_OUTPUT=100*1024*1024

def _validate(command,limit):
    if type(limit) is not int or not 1<=limit<=MAX_OUTPUT:raise ValueError('invalid child output limit')
    if not isinstance(command,(list,tuple)) or not command or not all(isinstance(a,str) and '\0' not in a for a in command) or not os.path.isabs(command[0]):raise ValueError('absolute executable argv required')

def limited_argv(command,limit):
    _validate(command,limit)
    return [sys.executable,'-I',str(Path(__file__).resolve()),str(limit),'--',*command]

def run_limited(command,limit,**kwargs):
    argv=limited_argv(command,limit)
    if 'preexec_fn' in kwargs or kwargs.get('shell',False):raise ValueError('unsafe child launch option')
    timeout=kwargs.get('timeout')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=45:raise ValueError('bounded child timeout required')
    output=kwargs.get('stdout')
    if not hasattr(output,'fileno'):raise ValueError('bounded regular stdout file required')
    st=os.fstat(output.fileno())
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError('private regular stdout file required')
    kwargs.update(shell=False,stdin=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
    return subprocess.run(argv,**kwargs)

def main():
    if len(sys.argv)==1:
        print('Usage: child_exec.py BYTE_LIMIT -- /absolute/executable [args...]');return
    try:
        if len(sys.argv)<4 or sys.argv[2]!='--':raise ValueError()
        limit=int(sys.argv[1]);command=sys.argv[3:];_validate(command,limit)
    except (ValueError,TypeError):raise SystemExit('invalid bounded exec request')
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit))
    os.execv(command[0],command)

if __name__=='__main__':main()
