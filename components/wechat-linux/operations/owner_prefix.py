"""Presentation-only check for new owner-DM prose. Never rewrite or authorise.

The private rule is a finite projection of existing client/role facts. It is
not a caller-provided identity claim, an employee service or a new ACL.
"""
import json,os,re,stat
from pathlib import Path
from .contract import ident

ACCOUNT=os.environ.get('WECHAT_ACCOUNT_ID','wxid_fixture_operator')
OWNER=os.environ.get('WECHAT_OWNER_ID','wxid_fixture_owner')

class OwnerPrefixError(ValueError):
 def __init__(self,code,message,details=None):
  super().__init__(message);self.code=code;self.details=details or {}
 def response(self):return {'state':'error','error':{'code':self.code,'message':str(self),'details':self.details}}

def load_rule(root):
 p=Path(root)/'owner-dm-prefix.json'
 try:
  if p.is_symlink():raise ValueError('symlink rule')
  if not p.exists():return None # Existing independent roots/fixtures opt in at activation.
  fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  try:
   s=os.fstat(fd)
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>16384:raise ValueError('private bounded rule required')
   data=os.read(fd,16385)
  finally:os.close(fd)
  def unique(pairs):
   value={}
   for k,v in pairs:
    if k in value:raise ValueError('duplicate rule field')
    value[k]=v
   return value
  v=json.loads(data,object_pairs_hook=unique)
  if not isinstance(v,dict) or set(v)!={'version','account','owner_peer','activated_at','roles'} or type(v['version']) is not int or v['version']!=1 or v['account']!=ACCOUNT or v['owner_peer']!=OWNER or type(v['activated_at']) not in (int,float) or not 0<v['activated_at']<1e12 or not isinstance(v['roles'],dict) or not v['roles']:raise ValueError('exact presentation scope required')
  names=set()
  for client,role in v['roles'].items():
   ident(client)
   if not isinstance(role,dict) or set(role)!={'name','thread_id'}:raise ValueError('exact original role fact required')
   name=role['name'];thread=role['thread_id']
   if not isinstance(name,str) or not name or len(name)>80 or name!=name.strip() or any(c in name for c in '[]\r\n\0') or name in names or not isinstance(thread,str) or not re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',thread):raise ValueError('unique current role required')
   names.add(name)
  return v
 except (OSError,ValueError,TypeError,KeyError,RecursionError):
  raise OwnerPrefixError('OWNER_DM_PREFIX_POLICY_INVALID','The current owner-DM presentation rule is unavailable or invalid; preserve the draft for its original author.',{'jobCreated':False,'textRewritten':False}) from None

def check_new(root,j):
 # The owner withdrew the tool-enforced presentation gate. Keep author text
 # and all original rows unchanged; any prefix is now the author's choice.
 return None

def capability(root):
 return {'enabled':False,'version':2,'required':False,'rewritesText':False,'isAuthorization':False,'oldRowsRevalidated':False,'presentationByOriginalAuthor':True}
