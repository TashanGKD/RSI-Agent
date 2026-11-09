"""One bounded authenticated-SSH upload: JSON metadata line then exact raw bytes to EOF."""
import io,os,select,time
from .assets import Assets,descriptor
from .contract import parse_request
class DeadlineReader:
 def __init__(self,source,deadline):
  self.source=source;self.deadline=deadline
  try:self.fd=source.fileno()
  except (AttributeError,io.UnsupportedOperation):self.fd=None
 def read(self,n):
  left=self.deadline-time.monotonic() if self.deadline is not None else 20
  if left<=0:raise ValueError('upload deadline')
  if self.fd is None:return self.source.read(n)
  ready=select.select([self.fd],[],[],min(left,20))[0]
  if not ready:raise ValueError('upload idle/deadline timeout')
  return os.read(self.fd,n)
def receive(root,config,source,*,seconds=None):
 deadline=None if seconds is None else time.monotonic()+seconds
 stream=DeadlineReader(source,deadline if deadline is not None else time.monotonic()+20);header=bytearray()
 for _ in range(4097):
  b=stream.read(1)
  if b==b'\n':break
  if not b:raise ValueError('missing upload header')
  header.extend(b)
 else:raise ValueError('upload header cap')
 x=parse_request(header.decode('utf-8'))
 if set(x)!={'client','name','bytes','sha256'}:raise ValueError('upload metadata fields invalid; server paths never accepted')
 descriptor(x['client'],x['name'],x['bytes'],x['sha256'])
 stream.deadline=deadline
 result=Assets(root).put_stream(x['client'],x['name'],stream,x['bytes'],x['sha256'],deadline=deadline);result.pop('path',None)
 return dict(result,uploadTransport='bounded-ssh-stream')
