#!/usr/bin/env python3
"""Explicit SSH client for the Linux WeChat tool; no model, polling, or default action."""
import argparse,base64,hashlib,json,os,stat,subprocess,sys
from pathlib import Path

import shlex
_code=os.environ.get('WECHAT_NATIVE_REMOTE_CODE','/opt/secretary-workbench/wechat')
COMMAND=['/usr/bin/ssh','-oBatchMode=yes','-oConnectTimeout=10',os.environ.get('WECHAT_SSH_HOST','secretary-wechat-host'),'python3 '+shlex.quote(_code+'/remote.py')+' --execute']

def load_request(raw):
    if len(raw.encode())>1500000:raise ValueError('request cap')
    def unique(pairs):
        out={}
        for k,v in pairs:
            if k in out:raise ValueError('duplicate request key')
            out[k]=v
        return out
    try:r=json.loads(raw,object_pairs_hook=unique)
    except (ValueError,RecursionError):raise ValueError('invalid or duplicate-key JSON request') from None
    if not isinstance(r,dict):raise ValueError('request object required')
    return r

def call(request,run=subprocess.run):
    if not isinstance(request,dict):raise ValueError('request object required')
    raw=json.dumps(request,ensure_ascii=False)
    if len(raw.encode())>1500000:raise ValueError('request cap')
    r=run(COMMAND,input=raw,text=True,capture_output=True,timeout=50)
    try:result=json.loads(r.stdout)
    except ValueError:raise ConnectionError('Linux WeChat connection or JSON response unavailable') from None
    if not isinstance(result,dict):raise ValueError('response object required')
    if r.returncode or result.get('state')=='error':raise RuntimeError('Linux WeChat: '+str(result.get('reason') or result.get('error_type') or result.get('errorType') or 'unavailable'))
    return result

def save_media(result,path):
    value=result.get('audio_base64') or result.get('content_base64')
    if not value:raise ValueError('response has no readable media bytes')
    data=base64.b64decode(value,validate=True)
    if hashlib.sha256(data).hexdigest()!=result.get('sha256'):raise ValueError('media checksum mismatch')
    path=Path(path).expanduser().absolute()
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        with os.fdopen(fd,'wb') as out:out.write(data)
    except BaseException:path.unlink(missing_ok=True);raise
    return {k:v for k,v in result.items() if k not in ('audio_base64','content_base64')}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true',help='explicitly contact AUP')
    p.add_argument('--request-file',help='JSON file, or - for stdin')
    p.add_argument('--output-media',help='new absolute private output for validated media')
    a=p.parse_args()
    if not a.execute:p.print_help();return
    if not a.request_file:p.error('--request-file required')
    if a.request_file=='-':raw=sys.stdin.read(1500001)
    else:
        path=Path(a.request_file)
        info=path.stat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size>1500000:p.error('bounded regular request file required')
        with path.open() as f:raw=f.read(1500001)
    r=call(load_request(raw))
    if a.output_media:r=save_media(r,a.output_media)
    print(json.dumps(r,ensure_ascii=False))

if __name__=='__main__':main()
