"""Explicit QR login. No arguments display help; no automatic reauthentication."""
import argparse
import json
import time
from .api import WeixinAPI, checked_url, bounded_string, TransportError
from .private import directory, read, write


def start(root):
    if (root/'account.json').exists():raise ValueError('account already exists; no implicit replacement')
    data=WeixinAPI().login_start()
    bounded_string(data.get('qrcode'),'QR value',8192)
    bounded_string(data.get('qrcode_img_content'),'QR contents',8192)
    write(root/'login.json',{'created':time.time(),'base_url':'https://ilinkai.weixin.qq.com','data':data})
    return {'state':'awaiting_scan','challenge_file':str(root/'login.json')}


def poll(root, seconds, verify_code=None):
    pending=read(root/'login.json')
    if time.time()-pending['created']>600:return {'state':'expired'}
    api=WeixinAPI(pending['base_url'])
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:r=api.login_poll(pending['data']['qrcode'],verify_code)
        except TransportError:return {'state':'network_unavailable'}
        state=r.get('status')
        if state=='confirmed':
            checked_url(r.get('baseurl') or api.base)
            account={'base_url':r.get('baseurl') or api.base,'token':bounded_string(r.get('bot_token'),'bot token',16384),
                     'account_id':bounded_string(r.get('ilink_bot_id'),'account identity',512),
                     'peer_id':bounded_string(r.get('ilink_user_id'),'peer identity',512),'bound_at':time.time()}
            if (root/'account.json').exists():raise ValueError('account already saved')
            write(root/'account.json',account)
            return {'state':'bound','credentials_saved':True}
        if state=='scaned_but_redirect':
            checked_url('https://'+r['redirect_host'])
            pending['base_url']='https://'+r['redirect_host'];write(root/'login.json',pending)
            api=WeixinAPI(pending['base_url']);continue
        if state in ('expired','need_verifycode','verify_code_blocked','binded_redirect'):
            return {'state':state}
        if state not in ('wait','scaned'):return {'state':'unknown_response'}
        time.sleep(1)
    return {'state':'awaiting_scan'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=False)
    parser.add_argument('action',nargs='?',choices=['start','poll'])
    parser.add_argument('--seconds',type=int,default=45)
    parser.add_argument('--verify-code-file')
    args=parser.parse_args()
    if not args.action:parser.print_help();return
    if not args.workspace:parser.error('explicit private workspace required')
    if not 1<=args.seconds<=600:parser.error('seconds must be 1..600')
    root=directory(args.workspace)
    code=read(args.verify_code_file).get('code') if args.verify_code_file else None
    result=start(root) if args.action=='start' else poll(root,args.seconds,code)
    print(json.dumps(result))


if __name__=='__main__':main()
