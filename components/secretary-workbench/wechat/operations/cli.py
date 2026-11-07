"""Standalone operations JSON API or bounded executor. No default action."""
import argparse,json,os,sys,stat
from pathlib import Path
from .contract import parse_request
def load_config(p):
 p=Path(p)
 if p.is_symlink() or not p.is_file() or p.stat().st_mode&0o077 or p.stat().st_uid!=os.getuid() or p.stat().st_size>64000:raise ValueError('private owner configuration required')
 x=parse_request(p.read_text())
 if set(x)!={'account','clients'} or not isinstance(x['clients'],dict):raise ValueError('invalid operation configuration')
 from .driver import Policy
 Policy(x) # Validate restrictions; unknown fields must never be ignored.
 return x
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',nargs='?',choices=['request','admin-request','run','upload-stream']);p.add_argument('--execute',action='store_true');p.add_argument('--root');p.add_argument('--config');p.add_argument('--seconds',type=int,default=60);p.add_argument('--once',action='store_true');a=p.parse_args()
 if not a.execute or not a.mode:p.print_help();return
 if not a.root or not a.config:p.error('explicit root and config required')
 os.umask(0o077);cfg=load_config(a.config)
 if a.mode=='upload-stream':
  from .asset_stream import receive
  print(json.dumps(receive(a.root,cfg,sys.stdin.buffer),ensure_ascii=False));return
 if a.mode in ('request','admin-request'):
  if a.mode=='request':
   from .public_api import PublicAPI as API
  else:from .api import API
  api=API(a.root,cfg)
  try:print(json.dumps(api.call(parse_request(sys.stdin.read())),ensure_ascii=False))
  finally:api.close()
 else:
  from .runtime import run
  from .store import Store
  from .driver import NativeDriver
  s=Store(a.root)
  try:print(json.dumps(run(s,NativeDriver(a.root,cfg),a.seconds,a.once)))
  finally:s.close()
if __name__=='__main__':
 try:main()
 except Exception as e:
  from .public_api import PublicError
  from .driver import PolicyConfigError
  from .assets import AssetBudgetError
  from .owner_prefix import OwnerPrefixError
  print(json.dumps(e.response() if isinstance(e,(PublicError,AssetBudgetError,OwnerPrefixError)) else {'state':'error','error':{'code':'INVALID_CONFIGURATION' if isinstance(e,PolicyConfigError) else 'INTERNAL_ERROR','message':'Tool policy configuration is invalid or unsupported.' if isinstance(e,PolicyConfigError) else 'Tool request failed; use the stable request ID to inspect the outcome.','type':type(e).__name__}},ensure_ascii=False));raise SystemExit(2)
