"""Bounded names-only protocol: no Store or coordination operation is permitted."""
import io, json, pathlib, subprocess, sys, types, unittest
from unittest.mock import patch
P=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(P/'src/MacWorker/foundation'))
import archive_lock as lock
import archive_lock_driver as driver
NONCE='a'*32
VECTOR=['ß','ss','é','e\u0301','来源','保存']
def frame(names=VECTOR,**changes):
 value=dict(v=2,op='normalizeNames',request=NONCE,names=names);value.update(changes)
 return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')+b'\n'
class NamesTests(unittest.TestCase):
 def run_frame(self,raw):
  out=io.StringIO()
  with patch.object(lock._Store,'__init__',side_effect=AssertionError('Store forbidden')),patch.object(lock,'_ordinary_uid',side_effect=AssertionError('coordination forbidden')),patch.object(lock.os,'open',side_effect=AssertionError('FS forbidden')):
   code=driver._run(['--archive-lock'],io.BytesIO(raw),out,lambda: self.fail('Store factory called'))
  return code,out.getvalue()
 def reject(self,raw):
  code,text=self.run_frame(raw);self.assertEqual(code,64);self.assertEqual(json.loads(text),dict(v=1,status='error',code='invalid_request'))
 def test_01_three_concrete_rejection_controls(self):
  # Duplicate key, cross-version fields/types, invalid scalar/encoding.
  for raw in (frame().replace(b'"names":',b'"names":[],"names":'),frame(targets=[]),frame(v=True),frame().replace('ß'.encode(),b'\xff'),frame().replace('ß'.encode(),b'\\ud800')):
   with self.subTest(raw=raw):self.reject(raw)
 def test_02_actual_valid_unicode_feature(self):
  code,text=self.run_frame(frame());self.assertEqual(code,0,text)
  self.assertEqual(json.loads(text),dict(v=2,op='normalizeNames',status='normalized',request=NONCE,classes=[0,0,1,1,2,3]))
 def test_equivalence_and_valid_filename_scalars(self):
  for names,expected in [(VECTOR,[0,0,1,1,2,3]),(['İ','i\u0307','I','i','ſ','s','Σ','σ','ς'],[0,0,1,1,2,2,3,3,3]),([' ','\t','\n','"','\\','\x01','ß','SS'],[0,1,2,3,4,5,6,6]),(['x'*255],[0])]:
   code,text=self.run_frame(frame(names));self.assertEqual(code,0,text);self.assertEqual(json.loads(text)['classes'],expected)
 def test_input_validation(self):
  for names in ([],[''],['.'],['..'],['a/b'],['\0'],['é'*128],[1],[True],None,{},['a']*2049):
   with self.subTest(names=str(names)[:50]):self.reject(frame(names))
  for changes in (dict(v=2.0),dict(v=3),dict(op='prepare'),dict(request='A'*32),dict(request='a'*31),dict(extra=0),dict(names=[[['x']]])):
   self.reject(frame(**changes))
 def test_frame_depth_lines_budget_and_v1_responsibility(self):
  for raw in (frame()[:-1],frame()+b'\n',frame()+b'{}',frame()+b'{}\n',b' '*8192+frame(),b'[[[[[0]]]]]\n',frame().replace(b'"v":2',b'"v":NaN')):self.reject(raw)
  # Legacy parser accepts raw JSON without LF; only _run owns framing.
  v1=dict(v=1,request=NONCE,targets=[dict(path='/private/fixture',mode='shared')]);self.assertEqual(driver.parse_request(json.dumps(v1).encode()),v1)
  self.assertEqual(driver.parse_request(frame()[:-1])['v'],2)
 def test_exact_input_budget_and_output_budget(self):
  raw=frame(['a']);self.assertEqual(self.run_frame(b' '*(8192-len(raw))+raw)[0],0);self.reject(b' '*(8193-len(raw))+raw)
  # Force an over-budget serialization to exercise the independent output guard.
  dumps=json.dumps
  def oversized(value,**kwargs):
   return ' '*8192 if value.get('status')=='normalized' else dumps(value,**kwargs)
  with patch.object(driver.json,'dumps',side_effect=oversized):
   code,text=self.run_frame(raw)
  self.assertEqual(code,64);self.assertEqual(json.loads(text),dict(v=2,op='normalizeNames',status='error',request=NONCE,code='invalid_request'))
 def test_validated_v2_failure_is_finite_v2_error(self):
  with patch.object(driver,'_fold_leaf',side_effect=RuntimeError('private detail')):
   code,text=self.run_frame(frame())
  self.assertEqual(code,64);self.assertEqual(json.loads(text),dict(v=2,op='normalizeNames',status='error',request=NONCE,code='invalid_request'))
 def test_actual_stdio(self):
  child=subprocess.run([sys.executable,'-I',str(P/'src/MacWorker/mac_worker.py'),'--archive-lock'],input=frame(),capture_output=True)
  self.assertEqual(child.returncode,0,child.stdout);self.assertEqual(child.stderr,b'');self.assertEqual(json.loads(child.stdout)['classes'],[0,0,1,1,2,3])
 def test_identity_fixture_pins(self):
  fixture=types.SimpleNamespace(st_dev=0x12345678,st_ino=0x102030405060708)
  # Constants pinned from unchanged v1 before extraction.
  expected={'ß': '82c5b25e32a52a08822c40a719680578a0537aaf80c1fa89c4cbcfe756ee8297', 'ss': '82c5b25e32a52a08822c40a719680578a0537aaf80c1fa89c4cbcfe756ee8297', 'é': '9970fa49d49517ccbf54ec83224a200cc3a0bcfafb1b1168898e78326b6dbfbf', 'é': '9970fa49d49517ccbf54ec83224a200cc3a0bcfafb1b1168898e78326b6dbfbf', '来源': '3e8d273db80494636644ddb6d220d3de264b149b0d2ae60c08cf9f47dabde69f', '保存': 'c3c90b516670c2124525a4d4be008030eaeae926f14a13aa2e2157cdf65aeefe', 'İ': '552abf2a04a597a08e33b4427bf66d6d5ee641722ac0ea36af2fb6559dc1bae6', 'i̇': '552abf2a04a597a08e33b4427bf66d6d5ee641722ac0ea36af2fb6559dc1bae6'}
  self.assertEqual({s:lock._identity(fixture,s) for s in expected},expected)
if __name__=='__main__':unittest.main()
