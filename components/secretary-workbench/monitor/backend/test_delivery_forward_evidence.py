# -*- coding: utf-8 -*-
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from delivery_health import build_health,attach_health,digest
from delivery_receipt_cache import remember_receipts,prepare_receipts,apply_receipts,proof_valid
from send_tool_observer import project
import work_observer as w
OWNER='00000000-0000-4000-8000-4344f0fd9daa'
OLD='secretary-fixture-c4316575-20260101';NEW='secretary-fixture-d05e144e-20260101-r2'
class ForwardEvidenceTests(unittest.TestCase):
 def fixture(self,root):
  work=root/'work';work.mkdir();role={'id':'secretary','threadId':OWNER,'root':root}
  def save(n,j):p=work/n;p.write_text(json.dumps(j,ensure_ascii=False));return str(p)
  payload={'source_peer':'24117802867@chatroom','source_id':'8000147143642714992'};peer='23548425729@chatroom';server='8000180167308444826';sender='wxid_fixture_bbb47eb57f'
  old={'client':'secretary','request_id':OLD,'peer':peer,'action':'forward','payload':payload,'state':'failed','created':100,'updated':110,'result':{'noSend':True,'code':'SOURCE_AMBIGUOUS'}}
  new={**old,'request_id':NEW,'state':'succeeded','created':120,'updated':135,'result':{'state':'accepted','peer':peer,'serverId':server,'evidence':'native-sender-status-and-operation-semantics'}}
  title='Forum article';url='https://mp.weixin.qq.com/s?mid=123&idx=1'
  row={'serverId':server,'senderId':sender,'nativeChat':peer,'kind':49,'timeUnix':130,'raw':sender+':\n<msg><appmsg><type>5</type><title>'+title+'</title><url>'+url.replace('&','&amp;')+'</url></appmsg></msg>'}
  data=(json.dumps(row)+'\n').encode();export=work/'export.jsonl';export.write_bytes(data)
  files={'identity':save('IDENTITY.json',{'actualNativeCard':{'serverId':server,'senderId':sender,'nativeChat':peer,'appType':'5','title':title,'url':url}}),'native':save('NATIVE.json',{'state':'ok','account':sender,'peer':peer,'messages':[{'serverId':server,'senderId':sender,'peer':peer,'kind':49,'time':130}],'coverage':{'messageMetadataComplete':True,'gaps':[],'truncated':False}}),'decision':save('DECISION.json',{'job':{k:new[k] for k in ['client','request_id','peer','action','payload']}}),'export':str(export),'receipt':save('export.jsonl.receipt.json',{'status':'complete','failures':[],'outputBytes':len(data),'outputSha256':hashlib.sha256(data).hexdigest()})}
  item={'id':'biz','employee':'secretary','title':'forward forum invitations','state':'待推进','commitment':'accepted','sourceId':'note'};seed={'businessId':'biz','employee':'secretary','ownerThreadId':OWNER,'requestIds':[OLD],'sourceId':'note','currentDeliveryObligation':True};return role,files,old,new,item,seed
 def registered(self,root):
  from delivery_forward_evidence import register_reference
  r,files,old,new,i,s=self.fixture(root);return r,files,old,new,i,s,register_reference(r,i['id'],files,old,new)
 def test_exact_forward_closes_only_bound_old_component_and_cache_survives_window(self):
  from delivery_forward_evidence import apply_references
  with tempfile.TemporaryDirectory() as d:
   r,f,old,new,i,s,ref=self.registered(Path(d).resolve());src={'note':{'text':'note'}}
   seeds,jobs,g=apply_references(r,[i],[s],[project(old),project(new)],src,[ref],'2026-11-01T22:50:00+08:00')
   h=build_health(items=[i],seeds=seeds,jobs=jobs,gaps=g,observed_at=200);inc=h['incidents'][0]
   self.assertEqual(len(h['incidents']),1);self.assertEqual(inc['id'],'delivery-'+digest('biz|secretary|'+OLD)[:24]);self.assertEqual(inc['status'],'resolved');self.assertEqual(set(inc['requestIds']),{OLD,NEW});self.assertTrue(inc['nativeReceiptVerified']);self.assertEqual(i['state'],'待推进')
   attach_health({'items':[]},h,jobs,src,'now',w.source,{})
   stored,gaps=remember_receipts(h,jobs,src,{});self.assertEqual(len(stored['entries']),1);self.assertFalse(gaps)
   seeds,entries,g=prepare_receipts([i],[s],src,stored);effective,g=apply_receipts([i],seeds,[],src,entries);h2=build_health(items=[i],seeds=seeds,jobs=effective,gaps=g,observed_at=300);self.assertEqual(h2['incidents'][0]['status'],'resolved')
 def test_reject_xml_entities_wrong_card_type_and_different_content(self):
  from delivery_forward_evidence import register_reference
  with tempfile.TemporaryDirectory() as d:
   r,f,old,new,i,s=self.fixture(Path(d).resolve());p=Path(f['export']);original=p.read_bytes()
   for bad in [original.replace(b'<msg>',b'<!DOCTYPE msg [<!ENTITY ex SYSTEM "file:///etc/passwd">]><msg>'),original.replace(b'<type>5</type>',b'<type>6</type>'),original.replace(b'Forum article',b'Unrelated card')]:
    p.write_bytes(bad);receipt=json.loads(Path(f['receipt']).read_text());receipt.update(outputBytes=len(bad),outputSha256=hashlib.sha256(bad).hexdigest());Path(f['receipt']).write_text(json.dumps(receipt))
    with self.assertRaises(ValueError):register_reference(r,i['id'],f,old,new)
 def test_reject_path_escape_symlink_and_checksum_mismatch(self):
  from delivery_forward_evidence import register_reference
  with tempfile.TemporaryDirectory() as d:
   r,f,old,new,i,s=self.fixture(Path(d).resolve());link=Path(d).resolve()/'work/link.json';link.symlink_to(f['identity'])
   for key,val in [('identity','/etc/passwd'),('identity',str(link))]:
    with self.assertRaises(ValueError):register_reference(r,i['id'],dict(f,**{key:val}),old,new)
   Path(f['export']).write_bytes(Path(f['export']).read_bytes()+b' ')
   with self.assertRaises(ValueError):register_reference(r,i['id'],f,old,new)
 def test_reject_other_source_target_sender_action_and_no_bare_success(self):
  from delivery_forward_evidence import register_reference
  with tempfile.TemporaryDirectory() as d:
   r,f,old,new,i,s=self.fixture(Path(d).resolve());self.assertFalse(project(new)['nativeReceiptVerified'])
   for key,val in [('peer','other@chatroom'),('action','send_text'),('payload',dict(new['payload'],source_id='8000042225878023228'))]:
    with self.assertRaises(ValueError):register_reference(r,i['id'],f,old,dict(new,**{key:val}))
   j=json.loads(Path(f['native']).read_text());j['messages'][0]['senderId']='wrong';Path(f['native']).write_text(json.dumps(j))
   with self.assertRaises(ValueError):register_reference(r,i['id'],f,old,new)
 def test_other_business_new_source_other_target_and_same_title_do_not_borrow_proof(self):
  from delivery_forward_evidence import apply_references
  with tempfile.TemporaryDirectory() as d:
   r,f,old,new,i,s,ref=self.registered(Path(d).resolve());src={'note':{'text':'note'}}
   others=[dict(old,request_id='secretary-fixture-b3f9b175-20260101',peer='other@chatroom'),dict(old,request_id='secretary-fixture-46f68250-20260101',payload=dict(old['payload'],source_id='8000042225878023228'))]
   s['requestIds'] += [j['request_id'] for j in others];ss,jobs,g=apply_references(r,[i],[s],[project(j) for j in [old,new]+others],src,[ref],'now');h=build_health(items=[i],seeds=ss,jobs=jobs,gaps=g,observed_at=200)
   self.assertEqual(sum(x['status']=='resolved' for x in h['incidents']),1);self.assertEqual(sum(x['status']=='blocked' for x in h['incidents']),2)
   other={**i,'id':'other'};ss,jobs,g=apply_references(r,[other],[dict(s,businessId='other')],[project(old)],{},[ref],'now');self.assertFalse(any(j['nativeReceiptVerified'] for j in jobs))
 def test_current_identity_conflict_stays_unknown_and_cached_proof_not_bare_flag(self):
  from delivery_forward_evidence import apply_references
  with tempfile.TemporaryDirectory() as d:
   r,f,old,new,i,s,ref=self.registered(Path(d).resolve());src={'note':{'text':'note'}};bad=project(dict(new,peer='other@chatroom'))
   ss,jobs,g=apply_references(r,[i],[s],[project(old),bad],src,[ref],'now');h=build_health(items=[i],seeds=ss,jobs=jobs,gaps=g,observed_at=200);self.assertEqual(h['incidents'][0]['status'],'unknown')
   proof=copy.deepcopy(ref['proof']);proof.pop('macExportSHA256');j=project(new);j.update(nativeReceiptVerified=True,nativeProof=proof);self.assertFalse(proof_valid(j))
 def test_observation_outage_retains_proof_but_changed_normal_artifact_is_conflict(self):
  from delivery_forward_evidence import apply_references
  with tempfile.TemporaryDirectory() as d:
   r,f,old,new,i,s,ref=self.registered(Path(d).resolve());p=Path(f['identity']);raw=p.read_bytes();p.unlink()
   ss,jobs,g=apply_references(r,[i],[s],[],{'note':{'text':'note'}},[ref],'now');h=build_health(items=[i],seeds=ss,jobs=jobs,gaps=g,observed_at=200)
   self.assertTrue(g);self.assertEqual(h['incidents'][0]['status'],'resolved')
   p.write_bytes(raw+b' ');ss,jobs,g=apply_references(r,[i],[s],[],{'note':{'text':'note'}},[ref],'now');h=build_health(items=[i],seeds=ss,jobs=jobs,gaps=g,observed_at=200);self.assertEqual(h['incidents'][0]['status'],'unknown')
 def test_normal_note_signature_change_keeps_exact_reference_not_worker_form(self):
  with tempfile.TemporaryDirectory() as d:
   r,f,old,new,i,s,ref=self.registered(Path(d).resolve());notes=r['root']/'notebook';notes.mkdir();p=notes/'a.md';p.write_text('- **事情**：forward invitations\n- **现在怎么样**：待推进\n- **过程笔记**：'+OLD)
   items,cache,_=w.notebook_items(r,{}, {},'now');cache[str(p)]['forwardReferences']=[ref]
   p.write_text('- **事情**：forward invitations\n- **现在怎么样**：待推进\n- **过程笔记**：A08已交，其余中央执行；此处没有准确请求名。')
   items,cache,_=w.notebook_items(r,{},cache,'later');self.assertEqual(items[0]['_forwardReferences'],[ref]);self.assertEqual(cache[str(p)]['forwardReferences'],[ref])
if __name__=='__main__':unittest.main()

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
