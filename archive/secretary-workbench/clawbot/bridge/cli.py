"""Explicit local send/status CLI. Requires --execute for outbound effects."""
import argparse
import json
from pathlib import Path
from .private import directory,read
from .api import WeixinAPI
from .store import Store
from .worker import Worker,process_lock


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace');p.add_argument('--execute',action='store_true')
    p.add_argument('--queue',action='store_true',help='Persist for the running worker; no inline network send')
    p.add_argument('action',nargs='?',choices=['status','send-text','send-image','flush','cover-in-main'])
    p.add_argument('--evidence-file')
    p.add_argument('--text-file');p.add_argument('--image');p.add_argument('--request-id')
    a=p.parse_args()
    if not a.action:p.print_help();return
    if not a.workspace:p.error('explicit private workspace required')
    if a.action!='status' and not a.execute:
        print(json.dumps({'state':'dry_run','action':a.action}));return
    if a.action=='cover-in-main':
        if a.queue:p.error('cover-in-main is lock-held maintenance, not a queued command')
        if not a.evidence_file:p.error('private evidence-file required')
        from .maintenance import cover_in_main
        print(json.dumps(cover_in_main(a.workspace,read(Path(a.evidence_file)),execute=True),ensure_ascii=False));return
    root=directory(a.workspace);cfg=read(root/'account.json')
    if a.action=='status' and not (root/'state.sqlite').exists():
        print(json.dumps({'state':'bound_not_started'}));return
    s=Store(root/'state.sqlite',cfg['account_id'],cfg['peer_id'])
    try:
        if a.action=='status':print(json.dumps(s.snapshot()));return
        def enqueue():
            if a.action=='send-text':
                if not a.text_file or not a.request_id:p.error('text-file and request-id required')
                f=Path(a.text_file)
                if not f.is_file() or f.is_symlink() or f.stat().st_size>32768:p.error('bounded text file required')
                item=s.enqueue_text(f.read_text(),a.request_id)
            elif a.action=='send-image':
                if not a.image or not a.request_id:p.error('image and request-id required')
                item=s.enqueue_image(a.image,a.request_id)
            else:item=None
            return item
        if a.queue:
            if a.action=='flush':p.error('queue is only for send commands')
            item=enqueue()
            print(json.dumps({'state':item['status'],'outbox_id':item['id'],'network_send':False}));return
        with process_lock(root):
            item=enqueue()
            if item and item['status']!='pending':
                print(json.dumps({'state':item['status'],'duplicate_request':True,'outbox_id':item['id']}));return
            result=Worker(s,WeixinAPI(cfg['base_url'],cfg['token']),None).flush_one()
            print(json.dumps(result))
    finally:s.close()


if __name__=='__main__':main()
