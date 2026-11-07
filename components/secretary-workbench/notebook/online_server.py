#!/usr/bin/env python3
"""Explicit private online host. No model credentials or source acquisition."""
import argparse
import json
import os
import stat
from pathlib import Path
from local_server import make_server
from modules.access import AccessService
from modules.secretary.cloud_queue import CloudSecretaryQueue

def main():
    p=argparse.ArgumentParser(description='他山私人在线记事本（仅回环，由HTTPS网关转发）')
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--origin',required=True)
    p.add_argument('--port',type=int,required=True)
    p.add_argument('--initialize',type=Path,help='首次初始化使用的本人600权限凭证文件；不打印凭证')
    a=p.parse_args()
    if not 1024<=a.port<=65535:p.error('端口无效')
    os.umask(0o077)
    init={}
    if a.initialize:
        fd=os.open(a.initialize,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd) as f:
            st=os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode)!=0o600 or st.st_uid!=os.getuid():p.error('初始化文件须本人拥有且权限600')
            init=json.load(f)
        if set(init)!={'activationToken','deviceToken'}:p.error('初始化字段无效')
    access=AccessService(a.workspace,a.origin,activation_token=init.get('activationToken'),device_token=init.get('deviceToken'))
    if a.initialize:
        print('访问凭证已初始化；明文初始化文件可移除。',flush=True)
        return
    s=make_server(a.workspace,port=a.port,access=access,secretary_factory=CloudSecretaryQueue)
    print('私人在线记事本已就绪；仅监听回环。',flush=True)
    try:s.serve_forever()
    except KeyboardInterrupt:pass
    finally:s.server_close()

if __name__=='__main__':main()
