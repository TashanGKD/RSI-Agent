#!/usr/bin/env python3
"""Read-only source-package check; report categories/locations, never matched values."""
import argparse,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RULES={
 'private-home':r'/Users/(?!operator/|example/)[A-Za-z][A-Za-z0-9_-]+/',
 'live-native-identity':r'\bwxid_(?!fixture_)[A-Za-z0-9_]+',
 'live-native-thread':r'\b01a[0-9a-f]{5}-[0-9a-f-]{27,}',
 'credentialed-url':r'https?://[^\s/@:]+:[^\s/@]+@',
 'provider-token':r'\b(?:github_pat_|gh[pousr]_|sk_live_)[A-Za-z0-9_]{16,}',
}
BAD_SUFFIX={'.db','.sqlite','.sqlite3','.pem','.key','.p12','.pfx','.mp4','.mp3','.silk','.wav','.zip','.jsonl'}
def candidates():
 if (ROOT/'.git').exists():
  r=subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT,capture_output=True,check=True)
  return sorted({ROOT/x for x in r.stdout.decode().split('\0') if x})
 return [p for p in ROOT.rglob('*') if p.is_file() and not any(x in p.relative_to(ROOT).parts for x in ['node_modules','__pycache__','.git','var','.runtime'])]
def main():
 argparse.ArgumentParser(description=__doc__).parse_args();issues=[];count=0
 for p in candidates():
  rel=p.relative_to(ROOT).as_posix();count+=1
  if p.is_symlink():issues.append({'file':rel,'category':'symlink'});continue
  if p.suffix.lower() in BAD_SUFFIX or any(x in p.parts for x in ['source-mirror','xwechat_files','.runtime']):issues.append({'file':rel,'category':'excluded-artifact'})
  try:s=p.read_text(encoding='utf-8-sig')
  except UnicodeDecodeError:issues.append({'file':rel,'category':'unreviewed-binary'});continue
  if p.resolve()==Path(__file__).resolve():continue
  for category,pattern in RULES.items():
   for m in re.finditer(pattern,s):
    if category=='credentialed-url' and '/tests/' in '/'+rel and m.group(0)=='https://fixture:invalid@':continue
    issues.append({'file':rel,'line':s.count('\n',0,m.start())+1,'category':category})
 print(json.dumps({'scannedFiles':count,'findings':issues,'readOnly':True},ensure_ascii=False,indent=2));return int(bool(issues))
if __name__=='__main__':raise SystemExit(main())
