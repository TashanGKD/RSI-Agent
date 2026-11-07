"""Shared request contract; no network or writes on import."""
import pathlib,re,os,stat
SID=os.environ.get('SECRETARY_SENDER_THREAD_ID','00000000-0000-4000-8000-000000000000')
UUID=re.compile(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}')
ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}')
def validate(r):
 if not isinstance(r,dict):raise ValueError('object required')
 fields={'inspect':set(),'read':{'limit'},'assign':{'request_id','text','caller','client_message_id'},'status':{'request_id'},'report':{'request_id','text'},'context':set()}
 op=r.get('op')
 if op not in fields or set(r)-({'op'}|fields[op]):raise ValueError('unknown action or fields')
 if op in ['assign','status','report'] and not (isinstance(r.get('request_id'),str) and ID.fullmatch(r['request_id'])):raise ValueError('invalid request ID')
 if op in ['assign','report'] and not (isinstance(r.get('text'),str) and r['text'].strip() and '\0' not in r['text'] and len(r['text'].encode())<=64000):raise ValueError('bounded nonempty text required')
 if op=='assign':
  c=r.get('caller')
  if not isinstance(c,dict) or (not {'host','threadId'}<=set(c) or set(c)-{'host','threadId','replyMode'}) or c['host'] not in ['mac','aup'] or not isinstance(c['threadId'],str) or not UUID.fullmatch(c['threadId']) or c['threadId']==SID:raise ValueError('real non-self caller host/thread required')
  if c.get('replyMode','native' if c['host']=='mac' else 'inline') not in ['native','inline']:raise ValueError('invalid return transport')
  if 'client_message_id' in r and not (isinstance(r['client_message_id'],str) and ID.fullmatch(r['client_message_id'])):raise ValueError('invalid native client ID')
 if 'limit' in r and (type(r['limit'])!=int or not 1<=r['limit']<=8):raise ValueError('read limit must be 1..8')
 return r
def checked_path(value,root,existing=False):
 if not isinstance(value,str) or '\0' in value:raise ValueError('invalid path')
 p=pathlib.Path(value);base=pathlib.Path(root)
 if not p.is_absolute() or '..' in p.parts or not p.is_relative_to(base):raise ValueError('path outside owned work root')
 for a in [p,*p.parents]:
  if a.is_symlink():raise ValueError('symlink refused')
 if existing and (not p.is_file() or not stat.S_ISREG(p.stat().st_mode)):raise ValueError('regular source required')
 return p
