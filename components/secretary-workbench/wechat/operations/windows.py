import re,subprocess

def parse_window_identity(raw):
 if not isinstance(raw,str) or len(raw.encode())>4096:raise ValueError('bounded official window properties required')
 def one(pattern):
  values=re.findall(pattern,raw,re.M)
  if len(values)!=1:raise ValueError('official window identity absent or ambiguous')
  return values[0]
 cls=one(r'^WM_CLASS\(STRING\) = "([^"]+)", "([^"]+)"$')
 pid=int(one(r'^_NET_WM_PID\(CARDINAL\) = ([0-9]{1,10})$'))
 leader=one(r'^WM_CLIENT_LEADER\(WINDOW\): window id # (0x[0-9a-fA-F]+)$').lower()
 trans=re.findall(r'^WM_TRANSIENT_FOR\(WINDOW\): window id # (0x[0-9a-fA-F]+)$',raw,re.M)
 absent=re.findall(r'^WM_TRANSIENT_FOR:  not found\.$',raw,re.M)
 if len(trans)+len(absent)!=1:raise ValueError('official transient relation absent or ambiguous')
 kinds=one(r'^_NET_WM_WINDOW_TYPE\(ATOM\) = ([A-Z0-9_, ]+)$').split(', ')
 if not 0<pid<2**31 or int(leader,16)==0 or any(not re.fullmatch('[A-Z_]+',v) for v in kinds):raise ValueError('invalid official window identity')
 return {'class':list(cls),'pid':pid,'leader':leader,'transientFor':trans[0].lower() if trans else None,'types':kinds}

def search_parent_proof(popup,parent):
 for w in (popup,parent):
  if not isinstance(w.get('id'),str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,16}',w['id']):raise ValueError('exact native window ID required')
 if popup['id']==parent['id']:raise ValueError('popup cannot own itself')
 values=[]
 for w in (popup,parent):
  try:r=subprocess.run(['xprop','-id',w['id'],'WM_CLASS','WM_TRANSIENT_FOR','WM_CLIENT_LEADER','_NET_WM_PID','_NET_WM_WINDOW_TYPE'],capture_output=True,text=True,timeout=3)
  except (OSError,subprocess.TimeoutExpired):raise ValueError('official window properties unavailable') from None
  if r.returncode:raise ValueError('official window properties unavailable')
  values.append(parse_window_identity(r.stdout))
 child,host=values
 normal={'_NET_WM_WINDOW_TYPE_NORMAL','_KDE_NET_WM_WINDOW_TYPE_OVERRIDE'};utility=normal|{'_NET_WM_WINDOW_TYPE_UTILITY'}
 if child['class']!=['wechat','wechat'] or host['class']!=child['class'] or child['pid']!=host['pid'] or child['leader']!=host['leader'] or child['transientFor']!=parent['id'].lower() or host['transientFor'] is not None or not {'_NET_WM_WINDOW_TYPE_UTILITY','_NET_WM_WINDOW_TYPE_NORMAL'}<=set(child['types'])<=utility or not {'_NET_WM_WINDOW_TYPE_NORMAL'}<=set(host['types'])<=normal:raise ValueError('official search parent identity is not proven')
 return {'popupId':popup['id'],'parentId':parent['id'],'pid':host['pid'],'leader':host['leader'],'transientFor':child['transientFor']}

def parse_app_windows(raw):
 # xwininfo does not escape quotation marks inside the window title. Parse
 # one entire native line and its structural suffix, never across newlines.
 pattern=r'^\s*(0x[0-9a-fA-F]+) (?:"([^\r\n]*)"|\(has no name\)): \("([^"\r\n]*)" "([^"\r\n]*)"\)\s+(\d+)x(\d+)\+(-?\d+)\+(-?\d+)(?:\s+[+-]\d+[+-]\d+)?\s*$'
 result=[]
 for ident,title,cls,klass,w,h,x,y in re.findall(pattern,raw,re.M):
  if len(title)>2048 or any(ord(c)<32 for c in title):continue
  if (cls,klass) not in [('wechat','wechat'),('com.tencent.wechatappex','WeChatAppEx'),('WeChatAppEx','WeChatAppEx')]:continue
  if int(w)<40 or int(h)<40:continue
  result.append({'id':ident,'title':title or 'WeChatAppEx','x':int(x),'y':int(y),'width':int(w),'height':int(h)})
 return result
def visible():
 r=subprocess.run(['xwininfo','-root','-tree'],capture_output=True,text=True,timeout=5)
 if r.returncode or len(r.stdout)>100000:raise ValueError('native window list unavailable')
 out=[]
 for w in parse_app_windows(r.stdout):
  s=subprocess.run(['xwininfo','-id',w['id']],capture_output=True,text=True,timeout=5)
  if s.returncode==0 and 'Map State: IsViewable' in s.stdout:out.append(w)
 return sorted(out,key=lambda x:x['id'])


def window_identity(w):
 if not isinstance(w,dict) or not re.fullmatch(r'0x[0-9a-fA-F]{1,16}',w.get('id','')):raise ValueError('exact window ID required')
 r=subprocess.run(['xprop','-id',w['id'],'WM_CLASS','WM_TRANSIENT_FOR','WM_CLIENT_LEADER','_NET_WM_PID','_NET_WM_WINDOW_TYPE'],capture_output=True,text=True,timeout=3)
 if r.returncode:raise ValueError('official window properties unavailable')
 return parse_window_identity(r.stdout)
