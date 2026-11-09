"""Exact deterministic selectors; caller sees business previews, never coordinates."""
from .ocr import normalized

def unique_line(rows,phrase):
 target=normalized(phrase);found=[x['point'] for x in rows if target and normalized(x['text'])==target]
 if len(found)!=1:raise ValueError('exact visible text is absent or ambiguous')
 return found[0]

def scroll_thumb(image,box):
 """Find the sole short neutral connected component in a calibrated rail."""
 w=box[2]-box[0];h=box[3]-box[1]
 if not 0<w<=30 or not 0<h<=2000:raise ValueError('bounded scrollbar rail required')
 pixels=image.crop(tuple(box)).convert('RGB');mask=bytearray(1 if max(v)-min(v)<10 and 100<=min(v)<220 else 0 for v in pixels.getdata());candidates=[]
 for index in range(w*h):
  if not mask[index]:continue
  stack=[index];mask[index]=0;x0=w;x1=0;y0=h;y1=0;n=0
  while stack:
   i=stack.pop();y,x=divmod(i,w);n+=1;x0=min(x0,x);x1=max(x1,x);y0=min(y0,y);y1=max(y1,y)
   for k in ([i-1] if x else [])+([i+1] if x+1<w else [])+([i-w] if y else [])+([i+w] if y+1<h else []):
    if mask[k]:mask[k]=0;stack.append(k)
  if n>=20 and x1-x0>=1 and 10<=y1-y0+1<=120:candidates.append([box[0]+(x0+x1)//2,box[1]+(y0+y1)//2])
 if len(candidates)!=1:raise ValueError('no unique scrollbar thumb in calibrated rail')
 return candidates[0]

def selected_chat_row(image,box):
 runs=[];start=None
 for y in range(box[1],box[3]+1):
  green=0
  if y<box[3]:
   for x in [box[2]-3,box[2]-5,box[2]-7]:
    r,g,b=image.getpixel((x,y))[:3];green+=g>=100 and g>r+50 and g>b+25
  on=green>=2
  if on and start is None:start=y
  if not on and start is not None:
   if 40<=y-start<=95:runs.append([sum(box[::2])//2,(start+y-1)//2])
   start=None
 if len(runs)!=1:raise ValueError('no unique selected sidebar row')
 return runs[0]

def quote_close(image,box):
 """Only the small neutral circular X in the verified quote strip."""
 im=image.crop(tuple(box)).convert('RGB');w,h=im.size
 if w*h>150000:raise ValueError('quote region over budget')
 mask=bytearray(max(v)-min(v)<8 and 175<=min(v)<235 for v in im.getdata());found=[]
 for i in range(w*h):
  if not mask[i]:continue
  mask[i]=0;stack=[i];pts=[]
  while stack:
   p=stack.pop();y,x=divmod(p,w);pts.append((x,y))
   for q in ([p-1] if x else [])+([p+1] if x+1<w else [])+([p-w] if y else [])+([p+w] if y+1<h else []):
    if mask[q]:mask[q]=0;stack.append(q)
  xs,ys=zip(*pts);x0,x1=min(xs),max(xs);y0,y1=min(ys),max(ys)
  if not 11<=x1-x0+1<=18 or abs((x1-x0)-(y1-y0))>1:continue
  cx=(x0+x1)//2;cy=(y0+y1)//2
  white=lambda x,y:min(im.getpixel((x,y)))>240
  # X diagonals are white; its four axial neighbors remain gray.
  if not white(cx,cy):continue
  if not all(any(white(cx+sx*dx,cy+sy*dy) for dx in (1,2,3) for dy in (1,2,3)) for sx,sy in [(-1,-1),(1,1),(-1,1),(1,-1)]):continue
  if sum(not white(cx+dx,cy+dy) for dx,dy in [(0,-4),(0,4),(-4,0),(4,0)])<3:continue
  found.append([box[0]+cx,box[1]+cy])
 if len(found)!=1:raise ValueError('quote close control absent or ambiguous')
 return found[0]


def _search_section(text):
 headings={
  'Group Chats':'group','群聊':'group','Contacts':'contact','联系人':'contact',
  'Internet search results':'web','网络搜索结果':'web',
  'Chat History':'other','聊天记录':'other','Messages':'other',
  'Official Accounts':'other','公众号':'other','Mini Programs':'other','小程序':'other',
  'Files':'other','文件':'other','Services':'other','服务':'other',
 }
 labels={normalized(k):v for k,v in headings.items()};text=normalized(text)
 if text in labels:return labels[text]
 # The native web-search icon can OCR as a short extra glyph before its title.
 # This only adds a forbidden boundary; never use suffix matches for recipients.
 for heading in ('internetsearchresults','网络搜索结果'):
  if text.endswith(heading) and 0<len(text)-len(heading)<=3:return 'web'
 return None

def native_search_bounds(rows,peer):
 """Require one explicit native section; the next heading closes its range."""
 wanted='group' if peer.endswith('@chatroom') else 'contact'
 sections=sorted((v['point'][1],_search_section(v['text'])) for v in rows if _search_section(v['text']))
 starts=[y for y,kind in sections if kind==wanted]
 if len(starts)!=1 or len({y for y,_ in sections})!=len(sections):raise ValueError('native search section missing or ambiguous')
 start=starts[0];end=min((y for y,_ in sections if y>start),default=float('inf'))
 return start,end

def native_search_result(rows,phrase,peer,name_rows=None):
 """One exact name in its native section; web order and avatar OCR are irrelevant.

 Full-width OCR provides headings. An optional narrow name-column OCR avoids
 avatar glyphs. OCR word spacing may vary; punctuation and case stay significant.
 """
 start,end=native_search_bounds(rows,peer);exact=lambda value:''.join(value.split())
 names={exact(v) for v in ([phrase] if isinstance(phrase,str) else phrase)}
 matches=[v['point'] for v in (rows if name_rows is None else name_rows) if start<v['point'][1]<end and not _search_section(v['text']) and exact(v['text']) in names]
 if len(matches)!=1:raise ValueError('exact native recipient absent or ambiguous in its own section')
 return matches[0]
