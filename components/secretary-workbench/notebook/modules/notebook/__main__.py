"""Standalone notebook, explicit workspace. No arguments prints usage only."""
import argparse,json,sys
from pathlib import Path
from . import NotebookService
from .legacy_store import strict_json,ValidationError

def main():
 p=argparse.ArgumentParser(description='共同记事本独立入口（不启动网页、模型、信源或定时）')
 p.add_argument('--workspace',type=Path);p.add_argument('--db',type=Path);p.add_argument('--source',type=Path)
 sub=p.add_subparsers(dest='command')
 sub.add_parser('init');q=sub.add_parser('list');q.add_argument('--view',default='all',choices=['all','today','review']);q.add_argument('--domain',default='');q.add_argument('--assignee',default='全部')
 q=sub.add_parser('show');q.add_argument('id')
 sub.add_parser('append');sub.add_parser('create');q=sub.add_parser('record');q.add_argument('id')
 a=p.parse_args()
 if not a.command:p.print_help();return 0
 if not a.workspace:p.error('需要显式--workspace')
 ws=a.workspace.expanduser().resolve();db=a.db or ws/'notebook'/'notebook.sqlite3';src=a.source or ws/'source.json'
 if not db.exists() and a.command!='init':p.error('工作区未初始化，请先显式运行init')
 if a.command=='init':
  ws.mkdir(parents=True,exist_ok=True,mode=0o700)
  if not src.exists():src.write_text('{"records":[]}\n',encoding='utf-8')
 n=NotebookService(db,src,ws)
 try:
  if a.command=='init':result={'initialized':True,'workspace':str(ws)}
  elif a.command=='list':result=n.query(a.view,a.domain,a.assignee)
  elif a.command=='show':result=n.detail(a.id)
  else:
   raw=sys.stdin.buffer.read(128*1024+1)
   if len(raw)>128*1024:raise ValidationError('输入过大')
   obj=strict_json(raw.decode())
   result=n.append_record(obj) if a.command=='append' else n.create_task(obj) if a.command=='create' else n.record(a.id,obj)
  print(json.dumps(result,ensure_ascii=False,indent=2));return 0
 except (ValidationError,ValueError,KeyError) as e:
  print(str(e),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
