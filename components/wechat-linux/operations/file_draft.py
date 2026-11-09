"""Bounded local official file-draft evidence; never reads a clipboard path."""
import re,secrets,hashlib
from xml.etree import ElementTree as ET
from urllib.parse import urlsplit,unquote
from .composer import editor_point,deselect

def exact_file_uri(value,expected_path):
 # Compare two independent encodings only after strict, single-pass parsing.
 # Never normalize paths, trim clipboard text, or open the referenced file.
 if not isinstance(expected_path,str) or not expected_path.startswith('/') or len(expected_path.encode('utf-8'))>4096 or any(ord(c)<32 or ord(c)==127 or c=='\\' for c in expected_path):raise ValueError('invalid frozen file path')
 if not isinstance(value,str) or not value.startswith('file:///') or len(value.encode('utf-8'))>4096 or any(c.isspace() or ord(c)<32 or ord(c)==127 or c=='\\' for c in value):raise ValueError('one complete local file URI required')
 if '?' in value or '#' in value or re.search(r'%(?![0-9A-Fa-f]{2})',value) or re.search(r'%(?:25|2f|5c)',value,re.I):raise ValueError('ambiguous file URI encoding')
 u=urlsplit(value)
 if u.scheme!='file' or u.netloc or u.query or u.fragment or unquote(u.path,errors='strict')!=expected_path:raise ValueError('exact local file reference required')
 return True

def native_file_fragment(raw,uris,text,expected_path):
 # Actual official type=3 single-file shape was observed in a controlled
 # ordinary prepare/cancel. Type=1 is an image, not a file fallback.
 describe(raw,uris,text,{'path':expected_path,'name':''})
 root=ET.fromstring(raw.decode('utf-8'))
 if root.tag!='WeChatRichEditFormat' or root.attrib or (root.text or '').strip() or len(root)!=1:raise ValueError('one exact native file required')
 node=root[0]
 if node.tag!='EditElement' or set(node.attrib)!={'type','filepath'} or node.get('type')!='3' or len(node) or (node.text or '').strip() or (node.tail or '').strip() or node.get('filepath')!=expected_path:raise ValueError('native file differs from the frozen asset')
 if len(uris)!=1:raise ValueError('one file URI required')
 exact_file_uri(uris[0],expected_path)
 exact_file_uri(text,expected_path)
 return True

def describe(raw,uris,text,asset):
 if not isinstance(raw,bytes) or not 0<len(raw)<=50000 or b'\0' in raw or not isinstance(text,str) or len(text.encode())>20000 or not isinstance(uris,(list,tuple)) or len(uris)>20:raise ValueError('bounded native file observation required')
 try:source=raw.decode('utf-8',errors='strict')
 except UnicodeError:raise ValueError('native observation encoding unsupported') from None
 if re.search(r'<!\s*(DOCTYPE|ENTITY)',source,re.I):raise ValueError('unsafe native observation')
 try:root=ET.fromstring(source)
 except ET.ParseError:raise ValueError('malformed native observation') from None
 if len(list(root.iter()))>40:raise ValueError('native observation node budget')
 safe=lambda v:v if isinstance(v,str) and re.fullmatch('[A-Za-z_][A-Za-z0-9_-]{0,63}',v) else 'unknown'
 def expected_uri(v):
  try:return exact_file_uri(v,asset['path'])
  except (ValueError,TypeError,UnicodeError):return False
 nodes=[]
 for node in list(root)[:10]:
  nodes.append({'tag':safe(node.tag),'keys':sorted(safe(k) for k in node.attrib),'type':node.get('type') if re.fullmatch('[0-9]{1,3}',node.get('type','')) else None,'assetPathAttributes':sorted(safe(k) for k,v in node.attrib.items() if v==asset['path']),'childCount':len(node),'textEmpty':not (node.text or '').strip(),'tailEmpty':not (node.tail or '').strip()})
 return {'observationReady':True,'rootTag':safe(root.tag),'rootKeys':sorted(safe(k) for k in root.attrib),'rootTextEmpty':not (root.text or '').strip(),'childCount':len(root),'children':nodes,'nativeBytes':len(raw),'nativeSHA256':hashlib.sha256(raw).hexdigest(),'uriCount':len(uris),'urisMatchAsset':len(uris)==1 and expected_uri(uris[0]),'textMatchesAssetPath':text==asset['path'],'textMatchesAssetURI':expected_uri(text),'textEmpty':not text,'assetNameInText':text==asset['name']}

def read(ui,asset):
 from .image_draft import _atom
 try:
  ui.check();ui.click(editor_point(ui.cfg));ui.settle(70);ui.clip.set_text('FILE_COPY_PROBE_'+secrets.token_hex(16),-1);ui.settle(70);ui.ctrl('a');ui.ctrl('c');ui.settle(220);ui.check()
  ok,atoms=ui.clip.wait_for_targets();targets={v.name() for v in atoms} if ok else set()
  if 'WeChat_RichEdit_Format' not in targets:raise ValueError('native file fragment unavailable')
  data=ui.clip.wait_for_contents(_atom('WeChat_RichEdit_Format'));raw=bytes(data.get_data()) if data else b''
  uris=ui.clip.wait_for_uris() or [];text=ui.clip.wait_for_text() or '';result=describe(raw,uris,text,asset)
  try:result['nativeFileVerified']=native_file_fragment(raw,uris,text,asset['path'])
  except ValueError:result['nativeFileVerified']=False
  return result
 except (ValueError,TypeError,UnicodeError):return {'observationReady':False,'reason':'NATIVE_FILE_FRAGMENT_UNAVAILABLE'}
 finally:deselect(ui);ui.check()

def verify(ui,asset):
 result=read(ui,asset)
 if result.get('nativeFileVerified') is not True:raise ValueError('exact single native file draft not proven')
 return result
