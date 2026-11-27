"""Verify the single image actually copied from the official composer, not a ROI."""
import hashlib,re,secrets,os,stat,io,struct,zlib
from pathlib import Path
from urllib.parse import urlsplit,unquote
from xml.etree import ElementTree
from .composer import editor_point,deselect


def pixel_identity(pix):
 """Canonical RGBA rows; padding and RGB-vs-opaque-RGBA do not change identity."""
 from PIL import Image
 w,h,n,bits,stride=pix.get_width(),pix.get_height(),pix.get_n_channels(),pix.get_bits_per_sample(),pix.get_rowstride()
 if any(type(v) is not int for v in (w,h,n,bits,stride)) or w<=0 or h<=0 or n not in (3,4) or bits!=8 or stride<w*n:raise ValueError('invalid decoded image')
 raw=bytes(pix.get_pixels())
 if not (h-1)*stride+w*n<=len(raw)<=h*stride:raise ValueError('incomplete decoded pixels')
 sha=hashlib.sha256()
 for y in range(h):
  row=raw[y*stride:y*stride+w*n]
  if n==3:row=Image.frombytes('RGB',(w,1),row).convert('RGBA').tobytes()
  sha.update(row)
 return {'width':w,'height':h,'pixelsSHA256':sha.hexdigest(),'pixelFormat':'RGBA8'}


def native_image_fragment(raw,uris,text):
 """One native image element, one URI and no other selected editor content.

 Return only the validated reference to the private verifier, never the API.
 A URI-only clipboard is read only through native_reference_identity's bound
 account/InputTemp sandbox; other references are never opened or fetched.
 """
 if not isinstance(raw,bytes) or not 1<=len(raw)<=50000 or not isinstance(text,str) or len(text.encode())>20000 or re.search(br'<!\s*(DOCTYPE|ENTITY)',raw,re.I):raise ValueError('bounded native image fragment required')
 try:root=ElementTree.fromstring(raw)
 except ElementTree.ParseError:raise ValueError('malformed native image fragment') from None
 if root.tag!='WeChatRichEditFormat' or root.attrib or (root.text or '').strip() or len(root)!=1:raise ValueError('composer must contain exactly one native image')
 node=root[0]
 if node.tag!='EditElement' or set(node.attrib)!={'type','filepath'} or node.get('type')!='1' or len(node) or (node.text or '').strip() or (node.tail or '').strip():raise ValueError('mixed or unknown native editor content')
 if not isinstance(uris,(list,tuple)) or len(uris)!=1 or not isinstance(uris[0],str) or text.strip()!=uris[0]:raise ValueError('native image selection also contains different text or URIs')
 uri=urlsplit(uris[0]);path=node.get('filepath','')
 if uri.scheme!='file' or uri.netloc or uri.query or uri.fragment or not path.startswith('/') or len(path)>4096 or any(c in path for c in '\r\n\0') or unquote(uri.path,errors='strict')!=path:raise ValueError('native image reference mismatch')
 return path


def native_reference_identity(path,account):
 """Decode only an owned, bounded official InputTemp UUID PNG; no arbitrary path."""
 from .driver import BASE
 from .assets import validate_image
 from PIL import Image
 if not isinstance(account,str) or not re.fullmatch(r'wxid_[A-Za-z0-9]{6,64}',account) or not isinstance(path,str):raise ValueError('configured native account required')
 # The client keeps xwechat_files under its own home (WECHAT_PROFILE's parent on
 # the WSL host), not under the tool root; use the configured profile when set.
 profile=os.environ.get('WECHAT_PROFILE')
 root=Path(profile).parent if profile else BASE/'xwechat_files'
 try:parts=Path(path).relative_to(root).parts
 except ValueError:raise ValueError('reference outside official input cache') from None
 if len(parts)!=4 or not re.fullmatch(re.escape(account)+r'_[0-9a-f]{4}',parts[0]) or parts[1:3]!=('temp','InputTemp') or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.png',parts[3]):raise ValueError('reference is not a bounded current-account InputTemp PNG')
 if profile and parts[0]!=Path(profile).name:raise ValueError('reference is not in the configured profile')
 fds=[];fd=None
 try:
  flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
  fds.append(os.open(root,flags))
  for name in (None,*parts[:-1]):
   if name is not None:fds.append(os.open(name,flags,dir_fd=fds[-1]))
   s=os.fstat(fds[-1])
   if s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('private owned native input directory required')
  fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fds[-1]);before=os.fstat(fd)
  # Official InputTemp uses one additional cache hardlink for this copied PNG.
  # Read only: bounded aliases + unchanged stat + exact frozen pixels are all
  # required; no referenced file is ever modified, deleted or returned.
  if not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_mode&0o077 or before.st_nlink not in (1,2) or before.st_size<33:raise ValueError('private regular native PNG required')
  header=os.read(fd,33)
  if len(header)!=33 or header[:16]!=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' or struct.unpack('>I',header[29:33])[0]!=zlib.crc32(header[12:29])&0xffffffff:raise ValueError('valid native PNG header required')
  width,height,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',header[16:29])
  if width<=0 or height<=0 or depth!=8 or color not in (2,6) or compression or filtering or interlace:raise ValueError('single 8-bit native RGB/RGBA PNG required')
  # Qt converts uploaded JPEG to lossless PNG. Its encoded size is independent
  # of the upload's 10MB transport budget. Bound this private conversion by its
  # actual raw scanlines plus deflate framing/PNG metadata, before allocating.
  raw_bytes=height*(1+width*(3 if color==2 else 4))
  encoded_limit=raw_bytes+(raw_bytes>>12)+(raw_bytes>>14)+(raw_bytes>>25)+13+1048576
  chunks=[header];n=len(header)
  while n<=before.st_size:
   chunk=os.read(fd,min(1048576,before.st_size+1-n))
   if not chunk:break
   chunks.append(chunk);n+=len(chunk)
  after=os.fstat(fd)
  stamp=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink,s.st_mode,s.st_uid)
  if n!=before.st_size or stamp(before)!=stamp(after):raise ValueError('native image reference changed during read')
  data=b''.join(chunks);validate_image(data,encoded_byte_limit=encoded_limit)
  with Image.open(io.BytesIO(data)) as image:
   if image.format!='PNG' or getattr(image,'n_frames',1)!=1:raise ValueError('single native PNG required')
   pixels=image.convert('RGBA')
   return {'width':pixels.width,'height':pixels.height,'pixelsSHA256':hashlib.sha256(pixels.tobytes()).hexdigest(),'pixelFormat':'RGBA8'}
 except OSError:raise ValueError('native image reference unavailable or unsafe') from None
 finally:
  if fd is not None:os.close(fd)
  for value in reversed(fds):os.close(value)


def _atom(name):
 from gi.repository import Gdk
 return Gdk.Atom.intern(name,False)


def verify(ui,expected):
 """Replace clipboard with a nonce first: a stale original paste cannot pass."""
 ui.check();ui.click(editor_point(ui.cfg));ui.settle(70)
 ui.clip.set_text('IMAGE_COPY_PROBE_'+secrets.token_hex(16),-1);ui.settle(70)
 ui.ctrl('a');ui.ctrl('c')
 # Qt publishes the native copy only after encoding its PNG. Observe that
 # completion condition without replacing the clipboard or issuing Copy again.
 # Large images need not complete within the old fixed 200ms observation.
 targets=set()
 for probes,delay in enumerate((100,200,400,800,1600,2400),1):
  ui.settle(delay);ui.check()
  ok,atoms=ui.clip.wait_for_targets();targets={v.name() for v in atoms} if ok else set()
  if 'WeChat_RichEdit_Format' in targets:break
 else:raise ValueError('native single-image format unavailable after bounded copy readiness observation')
 ui.imageCopyProbes=probes
 pix=ui.clip.wait_for_image()
 data=ui.clip.wait_for_contents(_atom('WeChat_RichEdit_Format'));raw=bytes(data.get_data()) if data else b''
 text=ui.clip.wait_for_text() or ''
 path=native_image_fragment(raw,ui.clip.wait_for_uris() or [],text)
 actual=pixel_identity(pix) if pix is not None else native_reference_identity(path,ui.cfg.get('paired_account'))
 if actual!=expected:raise ValueError('composer image pixels differ from uploaded asset')
 deselect(ui);ui.check();return actual
