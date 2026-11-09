"""Safe read boundary/EOF/deadline return: isolated original ownership records."""
import copy,io,unittest
from types import SimpleNamespace
from unittest.mock import patch
from operations import navigation as n

def w(i,title,width=584,height=750):return dict(id=i,title=title,x=347,y=74,width=width,height=height)
def identity(win):return dict(pid=7,leader='0x7',**{'class':['wechat','wechat']},transientFor='0x30' if win['title']=='Save' else None)
class C:
 def __init__(self,d):self.d=d;self.focused=None;self.calls=[]
 def key(self,key):self.calls.append(('key',self.focused));self.d.windows=[x for x in self.d.windows if x['id']!=self.focused]
 def click(self,x,y):self.calls.append(('close',self.focused));self.d.windows=[x for x in self.d.windows if x['id']!=self.focused]
 def wait(self,_):pass
 def close(self):pass
class ReadYieldTests(unittest.TestCase):
 def setUp(self):
  self.main=w('0x10','Weixin',905,667);self.history=w('0x20','Chat history of "exact"');self.viewer=w('0x30','Photos and Videos',860,854);self.dialog=w('0x40','Save',647,432);self.d=SimpleNamespace(fds=[1],root='/isolated',windows=[self.main,self.history,self.viewer,self.dialog]);self.d.app_windows=lambda:copy.deepcopy(sorted(self.d.windows,key=lambda x:x['id']));self.c=C(self.d);self.j={'id':'a'*32,'peer':'room@chatroom','action':'save_attachment','payload':{'source_id':'42'}};self.v={'state':'ready','main':self.main,'mainIdentity':identity(self.main),'processBirth':'born','beforeWindows':[self.main]};self.owned={x['id']:{'window':x,'identity':identity(x)} for x in [self.history,self.viewer,self.dialog]};self.s=SimpleNamespace(ready_business=lambda:True,active=lambda:None)
 def run_yield(self,force=False,focus_ok=True):
  def focus(c,w):c.focused=w['id']
  def prove(c,w):
   if not focus_ok or c.focused!=w['id']:raise ValueError('focus changed')
  with patch.object(n,'load',return_value=self.v),patch.object(n,'finish',return_value=True) as finish,patch('operations.recipes.controls',return_value=self.c),patch('operations.recipes.activate',side_effect=focus),patch('operations.windows.window_identity',side_effect=identity),patch('operations.lease.birth',return_value='born'),patch('operations.forwarding.require_window_focus',side_effect=prove):
   return n._yield_owned_read(self.d,self.j,self.owned,self.s,force=force),finish.call_count
 def test_ready_business_closes_only_owned_read_windows_then_original_navigation(self):
  r,k=self.run_yield();self.assertTrue(r);self.assertEqual(self.d.windows,[self.main]);self.assertEqual(self.c.calls,[('key','0x40'),('key','0x30'),('close','0x20')]);self.assertEqual(k,1)
 def test_no_ready_business_does_not_change_current_read_step(self):
  self.s.ready_business=lambda:False;r,k=self.run_yield();self.assertIsNone(r);self.assertEqual(self.c.calls,[]);self.assertEqual(k,0)
 def test_completed_one_file_forces_return_even_without_ready_business(self):
  self.s.ready_business=lambda:False;r,k=self.run_yield(force=True);self.assertTrue(r);self.assertEqual(self.d.windows,[self.main])
 def test_foreign_window_or_wrong_owned_identity_prevents_all_close_input(self):
  for wrong in ('foreign','identity','baseline'):
   self.setUp()
   if wrong=='foreign':self.d.windows.append(w('0x99','foreign'))
   elif wrong=='identity':self.owned['0x30']['identity']['pid']=99
   else:self.v['beforeWindows'].append(self.history)
   r,k=self.run_yield();self.assertFalse(r);self.assertEqual(self.c.calls,[]);self.assertEqual(k,0)
 def test_wrong_focus_never_sends_escape_or_close(self):
  r,k=self.run_yield(focus_ok=False);self.assertFalse(r);self.assertEqual(self.c.calls,[])
 def test_another_active_job_or_business_action_is_never_preempted(self):
  self.s.active=lambda:{'id':'b'*32};r,k=self.run_yield();self.assertFalse(r);self.assertEqual(self.c.calls,[])
  self.s.active=lambda:None;self.j['action']='send_text';r,k=self.run_yield();self.assertFalse(r);self.assertEqual(self.c.calls,[])
 def test_waiting_for_model_input_yields_on_ready_business_before_readline(self):
  with patch.object(n,'_yield_owned_read',return_value=True) as release:
   line,settled=n._read_command(self.d,self.j,self.owned,self.s,io.StringIO('must not be read'),9999999999)
  self.assertIsNone(line);self.assertTrue(settled);release.assert_called_once()
 def test_deadline_and_eof_force_same_owned_cleanup_without_new_process(self):
  with patch.object(n,'_yield_owned_read',return_value=True) as release:
   line,settled=n._read_command(self.d,self.j,self.owned,self.s,io.StringIO(''),-1)
  self.assertIsNone(line);self.assertTrue(settled);self.assertTrue(release.call_args.kwargs['force'])
  import os
  fd,writer=os.pipe();os.close(writer)
  with os.fdopen(fd,'r') as stream,patch.object(n,'_yield_owned_read',side_effect=[None,None,True]) as release:
   line,settled=n._read_command(self.d,self.j,self.owned,self.s,stream,9999999999)
  self.assertIsNone(line);self.assertTrue(settled);self.assertTrue(release.call_args.kwargs['force'])
if __name__=='__main__':unittest.main(verbosity=2)
