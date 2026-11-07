#!/usr/bin/env python3
"""Integrate an explicit saved-record allowlist through the public notebook API.
No arguments prints help. --apply is required to write; no source scans or DB access.
"""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules.secretary.cloud_worker import load_config
from modules.notebook.http_port import HTTPNotebookPort

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 temp=path.with_suffix(path.suffix+'.tmp')
 fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,indent=2)
 os.replace(temp,path)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--config',type=Path);p.add_argument('--plan',type=Path);p.add_argument('--output',type=Path);p.add_argument('--apply',action='store_true')
 a=p.parse_args()
 if not all((a.config,a.plan,a.output)):p.print_help();return 0
 entries=json.loads(a.plan.read_text())
 if not isinstance(entries,list) or len(entries)>200 or len({e['recordId'] for e in entries})!=len(entries):p.error('explicit unique allowlist, up to 200 records')
 cfg=load_config(a.config);n=HTTPNotebookPort(cfg['baseUrl'],cfg['deviceToken'],a.output.parent/'http-cache')
 if not a.apply:
  versions={};preview=[]
  for entry in entries:
   rid=entry['recordId'];body=entry['body'];r=n.record_detail(rid)
   if n.work_record_hash(r)!=body['expectedRecordHash']:raise RuntimeError('record changed; rebuild preview: '+rid)
   if r.get('work') is not None:raise RuntimeError('record already integrated; reuse original applied receipt')
   if 'objectId' in body:
    oid=body['objectId']
    if oid not in versions:versions[oid]=n.get_task(oid)['revision']
    body=dict(body,expectedRevision=versions[oid])
    for ref in (r['objectIds'] or [oid]):
     if ref not in versions:versions[ref]=n.get_task(ref)['revision']
     versions[ref]+=1
   preview.append({'recordId':rid,'body':body,'originalRecord':r})
  save(a.output,{'baseUrl':cfg['baseUrl'],'entries':preview,'applied':[]})
  print(json.dumps({'previewed':len(preview),'writes':0}));return 0
 run=json.loads(a.output.read_text())
 if run['baseUrl']!=cfg['baseUrl'] or [e['recordId'] for e in run['entries']]!=[e['recordId'] for e in entries]:raise RuntimeError('preview target mismatch')
 for entry in run['entries']:
  rid=entry['recordId'];result=n.integrate_work_record(rid,entry['body']);read=n.record_detail(rid);old=entry['originalRecord']
  for key in ('id','text','actor','at','sourceRefs','attachments','receipts','processing'):
   if read[key]!=old[key]:raise RuntimeError('original record changed: '+rid+' '+key)
  if result['task']['id'] not in read['objectIds'] or not read.get('work'):raise RuntimeError('independent readback failed')
  receipt={'recordId':rid,'objectId':result['task']['id'],'requestId':entry['body']['requestId']}
  if not any(r['recordId']==rid for r in run['applied']):run['applied'].append(receipt)
  save(a.output,run)
 print(json.dumps({'verified':len(run['applied']),'idempotentRequests':True}))
 return 0
if __name__=='__main__':raise SystemExit(main())
