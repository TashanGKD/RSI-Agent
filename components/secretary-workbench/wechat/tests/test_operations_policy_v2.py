"""Isolated owner-authorized workflow positives; no GUI or real dispatch."""
import tempfile,unittest,hashlib,io,json
from pathlib import Path
from operations.driver import Policy
from operations.public_api import PublicAPI,PublicError
from operations.owner_prefix import check_new,capability

CFG={'account':'self','clients':{'forum_employee':{'peers':['old-room'],'actions':['send_text'],'peer_actions':{'old-room':['send_text']}}}}
ROWS=[{'peer':'new-peer','name':'新联系人','alias':''},{'peer':'12345000001@chatroom','name':'Fixture forum group','alias':''}]
def job(client='forum_employee',peer='new-peer',action='send_text',rid='original',payload=None):
 return {'client':client,'request_id':rid,'peer':peer,'action':action,'payload':payload if payload is not None else {'text':'author frozen text'}}

class OwnerAuthorizedAccessTests(unittest.TestCase):
 def test_client_labels_do_not_deny_recipient_action_or_original_source(self):
  p=Policy(CFG)
  for j in [job(),job(action='send_file',payload={'asset':'a'*64}),job(client='new-employee'),job(action='forward',payload={'source_peer':'another-room','source_id':'12'})]:
   with self.subTest(j=j):
    try:p.check(j)
    except PermissionError as e:self.fail('Owner-authorized work blocked by legacy client ACL: '+str(e))
 def test_attribution_metadata_does_not_require_legacy_permission_fields(self):
  try:p=Policy({'account':'self','clients':{'new-employee':{}}});p.check(job(client='new-employee'))
  except ValueError as e:self.fail('Attribution still requires a permission registration: '+str(e))
 def test_stream_upload_accepts_an_unregistered_attribution_label(self):
  from operations.asset_stream import receive
  data=b'owner-authorized stream fixture';header={'client':'new-employee','name':'fixture.txt','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
  with tempfile.TemporaryDirectory() as td:
   try:r=receive(Path(td).resolve(),CFG,io.BytesIO(json.dumps(header).encode()+b'\n'+data))
   except PermissionError as e:self.fail('Stream still treats attribution as a permission tenant: '+str(e))
   self.assertEqual(r['client'],'new-employee');self.assertEqual(r['sha256'],header['sha256'])
 def test_resolve_searches_actual_directory_not_client_list(self):
  with tempfile.TemporaryDirectory() as td:
   api=PublicAPI(Path(td).resolve(),CFG,contacts=lambda peers:ROWS)
   try:
    for client in ['forum_employee','new-employee']:
     try:r=api.call({'op':'resolve','client':client,'query':'新联系人'})
     except PublicError as e:self.fail('Global native target hidden by client list: '+str(e))
     self.assertEqual(r['peer'],'new-peer')
   finally:api.close()
 def test_actual_name_ambiguity_still_reports_real_identity_condition(self):
  with tempfile.TemporaryDirectory() as td:
   api=PublicAPI(Path(td).resolve(),CFG,contacts=lambda peers:[dict(ROWS[0]),dict(ROWS[0],peer='different-peer')])
   try:
    with self.assertRaises(PublicError) as cm:api.call({'op':'resolve','client':'forum_employee','query':'新联系人'})
    self.assertEqual(cm.exception.code,'AMBIGUOUS_RECIPIENT')
   finally:api.close()
 def test_synthetic_document_is_admissible_by_its_caller(self):
  with tempfile.TemporaryDirectory() as td:
   api=PublicAPI(Path(td).resolve(),CFG)
   try:
    data=b'synthetic document fixture';a=api.assets.put('forum_employee','常见问题.docx',data,hashlib.sha256(data).hexdigest())
    j=job(peer='12345000001@chatroom',action='send_file',payload={'asset':a['id']},rid='isolated-faq')
    try:r=api.call({'op':'submit','job':j})
    except PublicError as e:self.fail('Real file workflow still rejected by artificial permission wall: '+str(e))
    self.assertEqual(r['state'],'queued');self.assertEqual(r['payload']['asset'],a['id'])
   finally:api.close()
 def test_owner_prefix_is_presentation_only_and_does_not_rewrite_or_gate(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);(p/'owner-dm-prefix.json').write_text('{invalid historical rule')
   j=job(peer='wxid_fixture_c2253ec460');frozen=dict(j['payload'])
   try:check_new(p,j)
   except Exception as e:self.fail('Withdrawn prefix rule still blocks author text: '+str(e))
   self.assertEqual(j['payload'],frozen);self.assertFalse(capability(p)['enabled'])
 def test_old_accepted_and_unknown_ids_keep_their_frozen_result_without_replay(self):
  with tempfile.TemporaryDirectory() as td:
   api=PublicAPI(Path(td).resolve(),CFG)
   try:
    for state in ['unknown','succeeded']:
     j=job(peer='old-room',rid='frozen-'+state);first=api.call({'op':'submit','job':j});proof={'state':'accepted','serverId':'42'} if state=='succeeded' else {'automaticReplay':False};api.s.set_state(first['id'],state,proof)
     again=api.call({'op':'submit','job':j});self.assertEqual((again['id'],again['state'],again['result']),(first['id'],state,proof))
     self.assertEqual(api.s.c.execute("SELECT count(*) FROM events WHERE job_id=? AND state='queued'",(first['id'],)).fetchone()[0],1)
   finally:api.close()

if __name__=='__main__':unittest.main(verbosity=2)
