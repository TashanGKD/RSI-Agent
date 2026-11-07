# -*- coding:utf-8 -*-
import copy,json,unittest
from delivery_receipt_cache import prepare_receipts,apply_receipts,decode
from delivery_health import build_health,digest
import test_delivery_receipt_cache as fixtures
import work_observer as w
class PrimaryAssociationTests(unittest.TestCase):
 def test_confirmed_primary_scope_suppresses_old_note_and_legacy_reference_without_erasing_proof(self):
  i,s,j,src,h,stored=fixtures.ReceiptCacheTests().stored();old=copy.deepcopy(stored['entries'][0]);new=copy.deepcopy(old);target='primary-role-work';new_id='delivery-'+digest(target+'|'+old['employee']+'|'+j[0]['request_id'])[:24]
  att=json.loads(old['componentSource']['text']);att.update(id=new_id,businessId=target,businessTitle='原主业务');new.update(businessId=target,componentId=new_id);sid=w.source(src,'交付组件:'+new_id,json.dumps(att,ensure_ascii=False),'2026-11-02T00:00:00Z','主业务复核');new['componentSource']=src[sid];decode(new)
  # W004 can continue quoting the same operation as evidence; that does not make it primary.
  old_seed=copy.deepcopy(s);new_seed={**s,'businessId':target,'requestIds':[]};new_item={**i,'id':target,'title':'原主业务'}
  seeds,entries,gaps=prepare_receipts([i,new_item],[old_seed,new_seed],src,{'version':1,'entries':[new]})
  self.assertFalse(set(seeds[0]['requestIds'])&set(att['requestIds']));self.assertTrue(set(att['requestIds'])<=set(seeds[1]['requestIds']))
  effective,g=apply_receipts([i,new_item],seeds,j,src,entries);after=build_health(items=[i,new_item],seeds=seeds,jobs=effective,gaps=g,observed_at=1000,previous=h,proven_requests={(r['client'],r['request_id']) for r in j})
  self.assertFalse(any(x['businessId']==i['id'] for x in after['incidents']));self.assertEqual(after['incidents'][0]['businessId'],target);self.assertEqual(after['incidents'][0]['status'],'resolved');self.assertEqual(new['memberSources'],old['memberSources'])
 def test_two_explicitly_attested_scopes_and_different_messages_are_not_guessed_away(self):
  i,s,j,src,h,stored=fixtures.ReceiptCacheTests().stored();two=copy.deepcopy(stored);entry=copy.deepcopy(two['entries'][0]);entry['businessId']='other';raw=json.loads(entry['componentSource']['text']);raw['businessId']='other';sid=w.source(src,'交付组件:'+entry['componentId'],json.dumps(raw),'2026-11-02T00:00:00Z','existing second scope');entry['componentSource']=src[sid];decode(entry);two['entries'].append(entry)
  seeds,_,_=prepare_receipts([i],[s],src,two);self.assertTrue(set(s['requestIds'])<=set(seeds[0]['requestIds']))
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
