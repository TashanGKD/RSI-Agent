"""Install one user LaunchAgent; no arguments only show the proposed configuration."""
import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from .private import directory,read

LABEL='cn.tashan.weixin-bridge'
ROOT=Path(__file__).resolve().parents[1]


def configuration(workspace):
    return {'Label':LABEL,'ProgramArguments':[sys.executable,'-m','bridge.worker','--workspace',str(workspace),'--execute','--seconds','3600'],
            'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,
            'ProcessType':'Background','LimitLoadToSessionType':'Aqua',
            'EnvironmentVariables':{'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'en_US.UTF-8'},
            'StandardOutPath':str(workspace/'worker.log'),'StandardErrorPath':str(workspace/'worker-error.log')}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace');p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if not a.workspace:p.print_help();return
    workspace=directory(a.workspace);read(workspace/'account.json')
    target=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    config=configuration(workspace)
    if not a.apply:print('Dry run:',target);return
    if target.is_symlink():raise ValueError('LaunchAgent symlink refused')
    if target.exists():
        old=plistlib.loads(target.read_bytes())
        if old!=config:raise ValueError('existing LaunchAgent differs; review before replacing')
    else:
        with os.fdopen(os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as f:plistlib.dump(config,f)
    for name in ('worker.log','worker-error.log'):
        path=workspace/name
        if path.is_symlink():raise ValueError('log symlink refused')
        fd=os.open(path,os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW,0o600);os.close(fd)
    domain='gui/'+str(os.getuid())
    status=subprocess.run(['launchctl','print',domain+'/'+LABEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if status.returncode:
        subprocess.run(['launchctl','bootstrap',domain,str(target)],check=True)
    print('Installed',LABEL)


if __name__=='__main__':main()
