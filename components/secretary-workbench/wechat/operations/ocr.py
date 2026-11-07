import os
"""Offline OCR selectors. No model/API. Ambiguity is a failure, never a guess."""
import csv,io,re,subprocess,time
from pathlib import Path
def normalized(s):return re.sub(r'[^\w\u4e00-\u9fff]','',s).lower()
def parse_tsv(raw,offset=(0,0),scale=1):
 groups={}
 for row in csv.DictReader(io.StringIO(raw),delimiter='\t',quoting=csv.QUOTE_NONE):
  text=row.get('text','').strip()
  if not text:continue
  key=tuple(row.get(k) for k in ['page_num','block_num','par_num','line_num']);x=int(row['left']);y=int(row['top']);w=int(row['width']);h=int(row['height'])
  a=groups.setdefault(key,{'text':'','box':[x,y,x+w,y+h]});a['text']+=text;a['box']=[min(a['box'][0],x),min(a['box'][1],y),max(a['box'][2],x+w),max(a['box'][3],y+h)]
 out=[]
 for a in groups.values():
  b=a['box'];a['point']=[int(offset[0]+(b[0]+b[2])/(2*scale)),int(offset[1]+(b[1]+b[3])/(2*scale))];out.append(a)
 return out
def find_line(rows,phrase):
 p=normalized(phrase);matches=[x['point'] for x in rows if p and p in normalized(x['text'])]
 if len(matches)!=1:raise ValueError('OCR control/text absent or ambiguous')
 return matches[0]
def observe(image,root,box=None,psm=11,lang="chi_sim+eng"):
 if lang not in ("chi_sim+eng","eng"):raise ValueError("unsupported internal OCR language")
 if psm not in (6,11):raise ValueError("unsupported internal OCR mode")
 base=Path(os.environ.get('WECHAT_OCR_ROOT','/usr/share/tesseract-ocr/5'));root=Path(root);p=root/'ocr-current.png';im=image.crop(tuple(box)) if box else image;scale=2;im=im.resize((im.width*scale,im.height*scale));im.save(p);p.chmod(0o600);start=time.monotonic()
 cmd=['/usr/bin/tesseract',str(p),'stdout','--tessdata-dir',str(base/'tessdata'),'-l',lang,'--psm',str(psm),'-c','tessedit_create_tsv=1']
 r=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
 if r.returncode or len(r.stdout)>500000 or not r.stdout.startswith('level\t'):raise ValueError('offline OCR unavailable, wrong output format or over budget')
 return parse_tsv(r.stdout,offset=box[:2] if box else (0,0),scale=scale),time.monotonic()-start
