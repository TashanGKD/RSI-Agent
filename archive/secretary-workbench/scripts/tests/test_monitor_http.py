"""Synthetic loopback-only HTTP proof; no private employee data or external host."""
import importlib.util,json,sys,tempfile,threading,unittest
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'monitor/backend'))
import serve
from live_core import publish

class MonitorHTTP(unittest.TestCase):
 def test_only_public_projection_and_get_head_are_served(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d).resolve();web=base/'web';web.mkdir();(web/'index.html').write_text('<html>Synthetic monitor</html>')
   live=base/'live';snap={'tasks':[],'employees':[],'warnings':['synthetic-only']};publish(live,snap,{},'20261106T000000-abcdef')
   with patch.multiple(serve,ROOT=web,LIVE=live):
    server=serve.ThreadingHTTPServer(('127.0.0.1',0),serve.Handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    try:
     url='http://127.0.0.1:'+str(server.server_port)
     self.assertIn(b'Synthetic monitor',urlopen(url+'/').read());manifest=json.load(urlopen(url+'/live.json'))
     self.assertEqual(json.load(urlopen(url+manifest['snapshotUrl']))['tasks'],[])
     self.assertEqual(urlopen(Request(url+'/',method='HEAD')).read(),b'')
     for path in ['/private/state.json','/@fs/etc/passwd','/versions/20261106T000000-abcdef/state.json']:
      with self.assertRaises(HTTPError) as error:urlopen(url+path)
      self.assertEqual(error.exception.code,404)
     with self.assertRaises(HTTPError) as error:urlopen(Request(url+'/',data=b'{}',method='POST'))
     self.assertEqual(error.exception.code,501)
     with self.assertRaises(HTTPError) as error:urlopen(Request(url+'/',headers={'Host':'foreign.invalid'}))
     self.assertEqual(error.exception.code,403)
    finally:server.shutdown();server.server_close();t.join(3)
