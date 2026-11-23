import json,re,hashlib

ACTIONS={
 'send_text':({'text'},set()),'send_image':({'asset'},set()),'send_file':({'asset'},set()),
 'open_chat':(set(),set()),'open_message':({'source_id'},set()),'save_attachment':({'source_id'}, {'resource_id','representation','source_mode'}),
 'join_group':({'inviter','source_id'},set()),'request_friend':({'alias','greeting'},set()),
 'accept_friend':(set(),{'source_id'}),'reply':({'source_id','text'},set()),
 'mention':({'members','text'},set()),'forward':({'source_peer','source_id'},set()),
 'get_group_qr':(set(),set()),'create_group':({'group_name','members'},set()),'invite_members':({'members'},set()),
 'send_sticker':({'md5'},set())}
FAST_ACTIONS={'send_text','send_image','send_file'}
def parse_request(raw):
 if not isinstance(raw,str):raise ValueError('JSON text required')
 def unique(rows):
  x={}
  for k,v in rows:
   if k in x:raise ValueError('duplicate JSON key')
   x[k]=v
  return x
 try:x=json.loads(raw,object_pairs_hook=unique)
 except (ValueError,RecursionError):raise ValueError('invalid JSON') from None
 if not isinstance(x,dict):raise ValueError('JSON object required')
 return x
def ident(x):
 if not isinstance(x,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,95}',x):raise ValueError('invalid stable client/request identifier')
 return x
def peer(x):
 if not isinstance(x,str) or not re.fullmatch('[A-Za-z0-9_@.-]{1,120}',x) or '..' in x:raise ValueError('exact native peer required')
 return x
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def validate_job(x):
 if not isinstance(x,dict) or set(x)-{'client','request_id','action','peer','payload','method','execution_mode'}:raise ValueError('unknown job fields')
 ident(x.get('client'));ident(x.get('request_id'));peer(x.get('peer'))
 a=x.get('action');p=x.get('payload')
 if a not in ACTIONS or not isinstance(p,dict):raise ValueError('unsupported action or payload')
 required,optional=ACTIONS[a]
 if set(p)-required-optional or not required<=set(p):raise ValueError('action payload fields do not match')
 if a=='get_group_qr' and not x['peer'].endswith('@chatroom'):raise ValueError('group QR requires an exact native group peer')
 if a=='create_group' and x['peer'].endswith('@chatroom'):raise ValueError('group creation uses an existing authorised person anchor')
 if a=='invite_members' and not x['peer'].endswith('@chatroom'):raise ValueError('invitation requires a real native group peer')
 if x.get('method','native') not in ('native','visual'):raise ValueError('unsupported execution method')
 if 'execution_mode' in x and (not isinstance(x['execution_mode'],str) or x['execution_mode'] not in ('manual','verified_fast')):raise ValueError('unsupported execution mode')
 if x.get('execution_mode')=='verified_fast' and (a not in FAST_ACTIONS or x.get('method','native')!='native'):raise ValueError('verified fast mode is not supported for this action/method')
 for k,v in p.items():
  if k=='members':
   if not isinstance(v,list) or not v or (a=='mention' and len(v)>20):raise ValueError('native member identities required')
   if a in ('create_group','invite_members') and (len(set(y for y in v if isinstance(y,str)))!=len(v) or any(not isinstance(y,str) or y.endswith('@chatroom') for y in v)):raise ValueError('unique person identities required')
   for y in v:peer(y)
  elif k=='resource_id':
   if type(v) is not int or v<0:raise ValueError('native resource id required')
  elif k=='representation':
   if not isinstance(v,str) or v not in ('original','visible'):raise ValueError('explicit original or visible representation required')
  elif k=='source_mode':
   if v!='inbound':raise ValueError('explicit inbound image source required')
  elif k in ('inviter','source_peer'):peer(v)
  elif k=='asset':
   if not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v):raise ValueError('asset digest required, never a path')
  elif k=='source_id':
   if not isinstance(v,str) or not re.fullmatch('[0-9]{1,20}',v) or int(v)==0:raise ValueError('nonzero native source id required')
  elif k=='md5':
   if not isinstance(v,str) or not re.fullmatch('[a-f0-9]{32}',v):raise ValueError('lowercase native sticker MD5 required')
  elif not isinstance(v,str) or not v.strip() or '\0' in v:raise ValueError('actual nonempty text required')
 return dict(x,method=x.get('method','native'))
