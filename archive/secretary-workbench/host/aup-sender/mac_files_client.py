#!/usr/bin/env python3
import argparse,base64,hashlib,json,pathlib,subprocess,sys,os,re
def ssh_command():
 target=os.environ.get('SECRETARY_MAC_SSH_TARGET','')
 key=os.environ.get('SECRETARY_MAC_SSH_KEY','')
 known=os.environ.get('SECRETARY_MAC_SSH_KNOWN_HOSTS','')
 if not re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+',target) or not key or not known:raise ValueError('configure explicit scoped Mac target/key/known-hosts')
 for value in [key,known]:
  p=pathlib.Path(value)
  if not p.is_absolute() or '..' in p.parts or any(x.is_symlink() for x in [p,*p.parents]) or not p.is_file():raise ValueError('explicit regular key/known-hosts path required')
 return ['ssh','-oBatchMode=yes','-oConnectTimeout=10','-oIdentitiesOnly=yes','-oStrictHostKeyChecking=yes','-oUserKnownHostsFile='+known,'-i',key,target,'access-v1']
def call(r):
 SSH=ssh_command()
 raw=json.dumps(r,ensure_ascii=False)
 p=subprocess.run(SSH,input=raw,capture_output=True,text=True,timeout=45)
 # Only this readonly/registered-idempotent Mac endpoint is retried, never a WeChat job.
 if p.returncode==255 and not p.stdout.strip() and any(x in p.stderr.lower() for x in ['timed out','connection reset']):
  import shutil
  tail=shutil.which('tailscale')
  if tail:
   try:subprocess.run([tail,'ping','--c','1','--timeout','5s',SSH[-2].split('@',1)[1]],capture_output=True,timeout=7)
   except subprocess.TimeoutExpired:pass
  p=subprocess.run(SSH,input=raw,capture_output=True,text=True,timeout=45)
 try:d=json.loads(p.stdout)
 except ValueError:raise RuntimeError('SSH endpoint failed: '+p.stderr[:200])
 if not d.get('ok'):raise RuntimeError(d.get('reason','request denied'))
 return d['result']
def download(root,path,destination):
 before=call({'op':'stat','root':root,'path':path});target=pathlib.Path(destination);offset=0;h=hashlib.sha256()
 with target.open('xb') as f:
  while offset<before['bytes']:
   part=call({'op':'read','root':root,'path':path,'offset':offset});b=base64.b64decode(part['data'],validate=True)
   if not b or hashlib.sha256(b).hexdigest()!=part['chunkSha256'] or part['bytes']!=before['bytes'] or part['mtimeNs']!=before['mtimeNs']:raise RuntimeError('source changed or corrupt')
   f.write(b);h.update(b);offset+=len(b)
 after=call({'op':'stat','root':root,'path':path})
 if before!=after or h.hexdigest()!=before['sha256']:raise RuntimeError('complete identity mismatch; preserve partial for diagnosis')
 return {**before,'downloaded':str(target),'identityVerified':True}
if __name__=='__main__':
 ap=argparse.ArgumentParser(description='Explicit scoped Mac readonly SSH client, no default requests.');ap.add_argument('--request',action='store_true');a=ap.parse_args()
 if not a.request:ap.print_help();sys.exit(0)
 print(json.dumps(call(json.load(sys.stdin)),ensure_ascii=False))
