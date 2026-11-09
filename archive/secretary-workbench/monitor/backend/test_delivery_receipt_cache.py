# -*- coding: utf-8 -*-
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import send_tool_observer as st
import work_observer as w
from delivery_health import build_health,attach_health
OWNER='00000000-0000-4000-8000-4344f0fd9daa'
OLD='secretary-fixture-a7ae3305-20260101';RETRY=OLD+'-r1';NEW='secretary-fixture-bbd455b2-20260101'
class ReceiptCacheTests(unittest.TestCase):
 def fixture(self):
  body='frozen original';sha=hashlib.sha256(body.encode()).hexdigest();rows=[];sources={'note':{'id':'note','path':'note','text':'original note','time':'','label':'note','role':'note'}}
  for rid,state,t in [(OLD,'failed',100),(RETRY,'succeeded',150)]:
   raw={'client':'secretary','request_id':rid,'peer':'owner','action':'send_text','payload':{'text':body},'state':state,'created':t,'updated':t+1,'result':{'state':'accepted','peer':'owner','serverId':'1234567','nativeStatus':2,'nativeCreateTime':t,'uniqueCandidateCount':1,'senderId':'wxid_fixture_bbb47eb57f','evidence':'native-sender-status-and-operation-semantics','textComparison':{'expectedSHA256':sha,'actualSHA256':sha}} if state=='succeeded' else {'code':'CHAT_POPOUT_NOT_OPENED','noSend':True}}
   j=st.project(raw);safe={k:v for k,v in j.items() if k not in ['text','employee','assetName','outcomeState','resultState','recoveryOwnerThreadId']};j['sourceId']=w.source(sources,'原微信工具:secretary/'+rid,json.dumps(safe,ensure_ascii=False),'2026-11-01T09:00:00Z','receipt');rows.append(j)
  item={'id':'business','employee':'secretary','title':'original delivery','state':'等反馈','commitment':'accepted','sourceId':'note'}
  seed={'businessId':'business','employee':'secretary','ownerThreadId':OWNER,'requestIds':[OLD,RETRY],'sourceId':'note','currentDeliveryObligation':True}
  health=build_health(items=[item],seeds=[seed],jobs=rows,gaps=[],observed_at=500);attach_health({'items':[]},health,rows,sources,'2026-11-01T09:00:00Z',w.source,{})
  return item,seed,rows,sources,health
 def stored(self):
  from delivery_receipt_cache import remember_receipts
  i,s,j,src,h=self.fixture();return i,s,j,src,h,remember_receipts(h,j,src,{'version':1,'entries':[]})[0]
 def test_signature_change_restores_exact_retry_without_recent_windows(self):
  from delivery_receipt_cache import prepare_receipts,apply_receipts
  i,s,j,src,h,cache=self.stored()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();(root/'notebook').mkdir();p=root/'notebook/a.md';p.write_text('- **事情**：original delivery\n- **现在怎么样**：等反馈\n- **过程笔记**：'+OLD+'；恢复后只用-r1成功。')
   role={'id':'secretary','threadId':OWNER,'root':root};notes,prev,_=w.notebook_items(role,{}, {},'2026-11-01T09:00:00Z')
   p.write_text('- **事情**：original delivery\n- **现在怎么样**：等反馈\n- **过程笔记**：'+OLD+'；实际r1已送，之后另有新讨论。')
   notes,_,_=w.notebook_items(role,{},prev,'2026-11-01T10:00:00Z');current=notes[0]['_deliverySeed'];current['businessId']=i['id'];current['sourceId']='note'
   self.assertNotIn(RETRY,current['requestIds'])
   seeds,entries,gaps=prepare_receipts([i],[current],src,cache)
   self.assertIn(RETRY,seeds[0]['requestIds'])
   effective,gap=apply_receipts([i],seeds,[j[0]],src,entries)
   after=build_health(items=[i],seeds=seeds,jobs=effective,gaps=gaps+gap,observed_at=600)
   self.assertEqual(after['incidents'][0]['status'],'resolved');self.assertEqual(after['incidents'][0]['id'],h['incidents'][0]['id']);self.assertTrue(gap)
 def test_new_independent_failed_draft_not_closed_by_old_receipt(self):
  from delivery_receipt_cache import prepare_receipts,apply_receipts
  i,s,j,src,h,cache=self.stored();s['requestIds']=[OLD,NEW]
  new={**j[0],'request_id':NEW,'contentHash':'c'*64,'created':200,'updated':201,'sourceId':j[0]['sourceId']}
  seeds,entries,gaps=prepare_receipts([i],[s],src,cache);jobs,gs=apply_receipts([i],seeds,[j[0],new],src,entries);result=build_health(items=[i],seeds=seeds,jobs=jobs,gaps=gs,observed_at=600)
  self.assertEqual(next(x for x in result['incidents'] if OLD in x['requestIds'])['status'],'resolved');self.assertEqual(next(x for x in result['incidents'] if NEW in x['requestIds'])['status'],'blocked')
 def test_transport_or_budget_gap_keeps_proved_delivery_and_separate_unknown(self):
  from delivery_receipt_cache import prepare_receipts,apply_receipts
  i,s,j,src,h,cache=self.stored();seeds,entries,gaps=prepare_receipts([i],[s],src,cache);jobs,gs=apply_receipts([i],seeds,[],src,entries)
  result=build_health(items=[i],seeds=seeds,jobs=jobs,gaps=['budget exhausted']+gs,observed_at=600)
  self.assertEqual(result['incidents'][0]['status'],'resolved');self.assertIn('budget exhausted',result['coverage']['gaps']);self.assertTrue(gs)
 def test_cross_business_client_peer_content_and_proof_corruption_rejected(self):
  from delivery_receipt_cache import prepare_receipts,apply_receipts
  i,s,j,src,h,cache=self.stored()
  other={**i,'id':'other'};seed={**s,'businessId':'other'};seeds,entries,g=prepare_receipts([other],[seed],src,cache);jobs,gs=apply_receipts([other],seeds,[j[1]],src,entries)
  result=build_health(items=[other],seeds=seeds,jobs=jobs,gaps=gs,observed_at=600);self.assertFalse(any(x['status']=='resolved' for x in result['incidents']))
  for field,value in [('peer','someone-else'),('contentHash','e'*64),('client','science')]:
   broken={**j[1],field:value};seeds,entries,g=prepare_receipts([i],[s],src,cache);jobs,gs=apply_receipts([i],seeds,[broken],src,entries);res=build_health(items=[i],seeds=seeds,jobs=jobs,gaps=gs,observed_at=600)
   if field!='client':self.assertEqual(res['incidents'][0]['status'],'unknown');self.assertEqual(res['incidents'][0]['reasonCode'],'receipt_identity_conflict')
   else:self.assertFalse(any(x.get('client')=='science' and x['nativeReceiptVerified'] for x in res['incidents']))
  damaged=copy.deepcopy(cache);damaged['entries'][0]['businessId']='other';seeds,entries,g=prepare_receipts([other],[seed],src,damaged);self.assertFalse(entries);self.assertTrue(g)
 def test_boolean_only_is_not_a_durable_receipt(self):
  from delivery_receipt_cache import prepare_receipts,remember_receipts
  i,s,j,src,h=self.fixture();j[1].pop('nativeProof',None)
  for k in list(src):
   if src[k].get('path','').endswith(RETRY):
    raw=json.loads(src[k]['text']);raw.pop('nativeProof',None);src[k]['text']=json.dumps(raw)
  state,gaps=remember_receipts(h,j,src,{'version':1,'entries':[]});self.assertFalse(state['entries']);self.assertTrue(gaps)
 def test_legacy_history_is_only_exact_requery_index_until_fresh_proof(self):
  from delivery_receipt_cache import prepare_receipts
  i,s,j,src,h=self.fixture();s['requestIds']=[OLD]
  seeds,entries,gaps=prepare_receipts([i],[s],src,{'version':1,'entries':[]})
  self.assertIn(RETRY,seeds[0]['requestIds']);self.assertFalse(entries)
 def test_sender_or_asset_proof_missing_never_becomes_verified_cache(self):
  from delivery_receipt_cache import remember_receipts
  i,s,j,src,h=self.fixture()
  for bad in [{'kind':'text_exact_sha256'},{'kind':'image_native_committed','assetId':'not-an-asset'}]:
   altered=copy.deepcopy(j);altered[1]['nativeProof']=bad;cache,g=remember_receipts(h,altered,src,{'version':1,'entries':[]});self.assertFalse(cache['entries'])
if __name__=='__main__':unittest.main()

class ReceiptStabilityTests(unittest.TestCase):
 def test_unchanged_receipt_sampling_does_not_grow_proof_chain_or_notification_key(self):
  from delivery_receipt_cache import prepare_receipts,apply_receipts,remember_receipts
  i,s,j,src,h,cache=ReceiptCacheTests().stored();prior=None;initial=copy.deepcopy(cache)
  for tick in [600,700,800]:
   seeds,entries,gaps=prepare_receipts([i],[s],src,cache);js,gs=apply_receipts([i],seeds,j,src,entries);health=build_health(items=[i],seeds=seeds,jobs=js,gaps=gs,observed_at=tick);attach_health({'items':[]},health,js,src,'2026-11-01T09:00:00Z',w.source,{})
   cache,g=remember_receipts(health,js,src,cache)
   self.assertEqual(cache,initial)
   if prior:self.assertEqual(health['incidents'],prior)
   prior=copy.deepcopy(health['incidents'])
  self.assertNotIn('frozen original',json.dumps(cache))

class DeferredObservationTests(unittest.TestCase):
 def test_deferred_known_no_send_survives_read_gap_without_becoming_delivery_or_cancellation(self):
  from delivery_receipt_cache import prepare_receipts,apply_receipts
  i,s,j,src,h=ReceiptCacheTests().fixture();src={k:v for k,v in src.items() if not v.get('path','').startswith('交付组件:') and not v.get('path','').endswith(RETRY)};i['state']='先放放';s['requestIds']=[OLD];s['businessDeferred']=True
  old=build_health(items=[i],seeds=[s],jobs=j[:1],gaps=[],observed_at=500);attach_health({'items':[]},old,j[:1],src,'2026-11-01T09:00:00Z',w.source,{})
  seeds,entries,g=prepare_receipts([i],[s],src,{'version':1,'entries':[]});jobs,gs=apply_receipts([i],seeds,[],src,entries);new=build_health(items=[i],seeds=seeds,jobs=jobs,gaps=gs,observed_at=600)
  self.assertEqual(new['incidents'][0]['status'],'pending');self.assertEqual(new['incidents'][0]['reasonCode'],'business_deferred_unsent');self.assertFalse(new['incidents'][0]['nativeReceiptVerified']);self.assertTrue(gs)
  s['businessDeferred']=False;i['state']='待推进';seeds,entries,g=prepare_receipts([i],[s],src,{'version':1,'entries':[]});jobs,gs=apply_receipts([i],seeds,[],src,entries);self.assertFalse(any(x.get('retainedReceipt') and x.get('noSend') for x in jobs))

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
