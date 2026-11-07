import unittest,tempfile,json,base64,os,time,copy
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import model_accounts as m

class AccountTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();(self.root/'codex_accounts').mkdir();self.key=os.urandom(32);self.now=1793400000
  self.put('secure-account-storage.key',base64.b64encode(self.key).decode(),0o600)
  rows=[]
  for i,email in enumerate(m.EMAILS):
   ident='codex_'+str(i+1)*32;rows.append({'id':ident,'email':email,'plan_type':'pro'});self.detail(ident,email)
  self.put('codex_accounts.json',json.dumps({'accounts':rows,'current_account_id':None}))
 def tearDown(self):self.tmp.cleanup()
 def put(self,path,text,mode=0o600):
  p=self.root/path;p.write_text(text);p.chmod(mode);return p
 def detail(self,ident,email,patch=None):
  d={'id':ident,'email':email,'plan_type':'pro','user_id':'user-'+email,'authorization_status':'authorized','requires_reauth':False,'usage_updated_at':self.now-60,'tokens':{'access_token':'DO-NOT-LEAK','refresh_token':'DO-NOT-LEAK'},'account_password':'DO-NOT-LEAK','account_note':'DO-NOT-LEAK','quota':{'hourly_percentage':62,'hourly_reset_time':self.now+86400,'hourly_window_minutes':10080,'hourly_window_present':True,'weekly_window_present':False},'quota_error':None}
  if patch:d.update(patch)
  nonce=os.urandom(12);e={'version':1,'kind':'codex','algorithm':'AES-256-GCM','key_id':'local-secure-account-storage-v1','nonce':base64.b64encode(nonce).decode(),'ciphertext':base64.b64encode(AESGCM(self.key).encrypt(nonce,json.dumps(d).encode(),None)).decode(),'encrypted_at':self.now-50}
  return self.put('codex_accounts/'+ident+'.json',json.dumps(e))
 def read(self,previous=None):return m.read_accounts(previous=previous,root=self.root,now=self.now,auth_path=self.root/'unused-auth.json')
 def test_path_traversal_refused(self):
  p=self.root/'codex_accounts.json';j=json.loads(p.read_text());j['accounts'][0]['id']='../../auth';p.write_text(json.dumps(j))
  data=self.read();self.assertEqual(data['accounts'][0]['health']['error'],'invalid_account_id');self.assertNotEqual(data['accounts'][1]['health']['error'],'invalid_account_id')
 def test_symlink_and_public_key_refused(self):
  p=self.root/'secure-account-storage.key';p.chmod(0o644)
  self.assertTrue(all(a['health']['error'] for a in self.read()['accounts']))
  p.unlink();p.symlink_to(self.root/'codex_accounts.json');self.assertTrue(all(a['health']['error'] for a in self.read()['accounts']))
 def test_tampered_ciphertext_is_not_published(self):
  p=self.root/'codex_accounts'/('codex_'+'1'*32+'.json');j=json.loads(p.read_text());b=bytearray(base64.b64decode(j['ciphertext']));b[0]^=1;j['ciphertext']=base64.b64encode(b).decode();p.write_text(json.dumps(j))
  data=self.read();self.assertEqual(data['accounts'][0]['health']['error'],'account_unreadable');self.assertIsNone(data['accounts'][1]['health']['error']);self.assertNotIn('DO-NOT-LEAK',json.dumps(data))
 def test_extra_private_fields_never_projected_and_no_writes(self):
  before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()};data=self.read();m.validate_accounts(data)
  self.assertEqual(before,{p:p.read_bytes() for p in before});self.assertNotIn('DO-NOT-LEAK',json.dumps(data));self.assertEqual(data['accounts'][0]['windows'][0]['remainingPercent'],62);self.assertEqual(data['accounts'][0]['windows'][0]['durationMinutes'],10080);self.assertEqual(len(data['accounts'][0]['windows']),1)
 def test_missing_file_preserves_only_its_previous_account(self):
  old=self.read();p=self.root/'codex_accounts'/('codex_'+'1'*32+'.json');p.unlink();data=self.read(old)
  self.assertEqual(data['accounts'][0]['windows'],old['accounts'][0]['windows']);self.assertTrue(data['accounts'][0]['health']['error']);self.assertIsNone(data['accounts'][1]['health']['error'])
 def test_stale_and_past_reset_not_assumed_full(self):
  self.detail('codex_'+'1'*32,m.EMAILS[0],{'usage_updated_at':self.now-2000,'quota':{'hourly_percentage':9,'hourly_reset_time':self.now-1,'hourly_window_minutes':300,'hourly_window_present':True}})
  data=self.read();self.assertTrue(data['accounts'][0]['stale']);self.assertEqual(data['accounts'][0]['windows'][0]['remainingPercent'],9);self.assertTrue(data['accounts'][0]['windows'][0]['resetPassed'])
 def test_online_validator_rejects_secret_extra_and_bad_percent(self):
  data=self.read();data['accounts'][0]['tokens']={'x':'DO-NOT-LEAK'}
  with self.assertRaises(ValueError):m.validate_accounts(data)
  data=self.read();data['accounts'][0]['windows'][0]['remainingPercent']=101
  with self.assertRaises(ValueError):m.validate_accounts(data)
 def test_duplicate_keys_refused(self):
  self.put('codex_accounts.json','{"accounts":[],"accounts":[]}');data=self.read();self.assertTrue(all(a['health']['error'] for a in data['accounts']))
 def test_unknown_fields_and_subject_do_not_become_current(self):
  data=self.read();self.assertEqual(data['desktopLogin']['status'],'unknown')
 def test_current_host_identity_mapping_is_narrow(self):
  self.put('unused-auth.json',json.dumps({'tokens':{'account_id':'user-'+m.EMAILS[1],'access_token':'DO-NOT-LEAK'}}))
  data=self.read();self.assertEqual(data['desktopLogin']['accountId'],data['accounts'][1]['id']);self.assertEqual(data['desktopLogin']['scope'],'local-auth-record')
 def test_missing_key_is_never_created(self):
  p=self.root/'secure-account-storage.key';p.unlink();data=self.read();self.assertFalse(p.exists());self.assertTrue(all(a['health']['error'] for a in data['accounts']))
 def test_encrypted_public_file_is_allowed_but_writable_file_is_not(self):
  p=self.root/'codex_accounts'/('codex_'+'1'*32+'.json');p.chmod(0o644);self.assertIsNone(self.read()['accounts'][0]['health']['error']);p.chmod(0o666);self.assertEqual(self.read()['accounts'][0]['health']['error'],'unsafe_file')
 def test_invalid_field_only_blocks_one_account(self):
  self.detail('codex_'+'1'*32,m.EMAILS[0],{'plan_type':{'injected':'DO-NOT-LEAK'}})
  data=self.read();self.assertEqual(data['accounts'][0]['health']['error'],'account_unreadable');self.assertIsNone(data['accounts'][1]['health']['error'])
 def test_cloud_receiver_rejects_private_field_before_publication(self):
  from cloud_receive import receive
  from online_sync import build_payload
  data=self.read();data['accounts'][0]['password']='DO-NOT-LEAK'
  snap={'tasks':[],'modelAccounts':data,'live':{'revision':'20261031T000000-abcdef'}}
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'live.json').write_text('{"revision":"old"}')
   with self.assertRaises(ValueError):receive(root,'20261031T000000-abcdef',build_payload(snap,{},{}))
   self.assertEqual(json.loads((root/'live.json').read_text())['revision'],'old')
 def test_online_projection_rejects_arbitrary_extra(self):
  from online_sync import make_projection
  data=self.read();data['desktopLogin']['access_token']='DO-NOT-LEAK'
  with self.assertRaises(ValueError):make_projection({'tasks':[],'warnings':[],'modelAccounts':data},{})

def setUpModule():
 from unittest.mock import patch
 import contextlib,collect,send_tool_observer,delivery_obligations,employee_profiles,account_contract,model_accounts
 global _portable_patches
 _portable_patches=contextlib.ExitStack()
 clients={'secretary':'secretary','science':'science','organoid_bp':'organoid','forum_employee':'forum','employee_pilot':'employee-pilot','employee_method':'system','aup_support':'aup-support','research_secretary':'research-secretary'}
 ids={'secretary':'00000000-0000-4000-8000-4344f0fd9daa','science':'00000000-0000-4000-8000-37b7cd446cba','organoid':'00000000-0000-4000-8000-f709f264f942'}
 emails=tuple('fixture'+str(i)+'@example.invalid' for i in range(3))
 for mod,key,value in [(send_tool_observer,'CLIENTS',clients),(collect,'IDS',ids),(delivery_obligations,'CLIENTS',clients),(delivery_obligations,'OWNERS',ids),(employee_profiles,'IDS',ids),(account_contract,'EMAILS',emails),(model_accounts,'EMAILS',emails)]:
  _portable_patches.enter_context(patch.object(mod,key,value))
def tearDownModule():
 _portable_patches.close()
