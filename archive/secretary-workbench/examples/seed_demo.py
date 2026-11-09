#!/usr/bin/env python3
"""Create synthetic notebook data in a new explicit workspace. Dry-run by default."""
import argparse,json,sys,os
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'notebook'))
from modules.notebook import NotebookService

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
 if not a.workspace:p.print_help();return
 ws=a.workspace.absolute()
 if ws.exists() or ws.is_symlink():p.error('New, nonexistent workspace required; existing work is never overwritten')
 for parent in ws.parents:
  if parent.is_symlink():p.error('Symlink parent refused')
 if not a.apply:print(json.dumps({'dryRun':True,'workspace':str(ws),'syntheticObjects':3}));return
 os.umask(0o077);ws.mkdir(parents=True,mode=0o700);src=ws/'source.json';src.write_text('{"records":[]}');src.chmod(0o600)
 n=NotebookService(ws/'notebook'/'notebook.sqlite3',src,ws)
 day=datetime.now(timezone(timedelta(hours=8))).date().isoformat();ids=[]
 for title,state,summary in [('复核示例方案','待办','仅合成样例：核对三项要求并回复。'),('等待示例材料','等对方','仅合成样例：收到后再安排复核。'),('已交付示例文件','已完成','仅合成样例：关闭本轮交付，历史仍保留。')]:
  t=n.create_task({'title':title,'summary':summary,'state':state,'domain':'他山','planDate':day if state=='待办' else None,'confirm':True,'requestId':'DEMO-'+str(len(ids)+1)})
  n.record(t['id'],{'expectedRevision':t['revision'],'note':'演示备注：这是程序生成的合成资料。','requestId':'DEMO-NOTE-'+str(len(ids)+1)})
  ids.append(t['id'])
 print(json.dumps({'created':True,'workspace':str(ws),'syntheticObjectIds':ids,'realSourcesAccessed':False},ensure_ascii=False))
if __name__=='__main__':main()
