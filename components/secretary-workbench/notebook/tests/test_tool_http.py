import unittest
from test_local_http import LocalHTTPTests
class ToolHTTPTests(LocalHTTPTests):
 def test_public_foundations_roundtrip(self):
  self.assertEqual(self.req('/api/notebook/capabilities')[1]['version'],'4.4')
  status,r=self.req('/api/tasks',{'title':'HTTP工具测试','deadlineDate':'2026-10-28'})
  self.assertEqual(status,200,r);t=r['task']
  status,r=self.req('/api/notebook/objects?kind=action&limit=1');self.assertEqual(status,200,r);self.assertEqual(r['objects'][0]['id'],t['id'])
  seq=self.req('/api/notebook/changes')[1]['cursor']
  self.req('/api/tasks/'+t['id']+'/record',{'expectedRevision':t['revision'],'summary':'新摘要'})
  self.assertEqual(self.req('/api/notebook/as-of?sequence='+str(seq))[1]['objects'][0]['summary'],'')
  status,r=self.req('/api/tasks/'+t['id']+'/restore-preview',{'sequence':seq,'fields':['summary']});self.assertEqual(status,200,r)
  status,r=self.req('/api/tasks/'+t['id']+'/restore',{'sequence':seq,'fields':['summary'],'expectedRevision':r['expectedRevision'],'requestId':'REST-http'})
  self.assertEqual(status,200,r);self.assertEqual(r['task']['summary'],'')
  self.assertEqual(self.req('/api/notebook/changes?cursor=0&cursor=1')[0],400)
  self.assertEqual(self.req('/api/notebook/as-of?at=2000-01-01T00%3A00%3A00%2B08%3A00')[0],400)
 def test_metadata_source_ref_online_boundary_contract(self):
  from contracts.source_refs import source_refs
  self.assertTrue(source_refs([{'sourceId':'wechat:mine','nativeId':'real','conversation':'组名','sender':'昵称'}]))
  with self.assertRaises(Exception):source_refs([{'sourceId':'wechat:mine','nativeId':'real','xml':'raw'}])
 def test_source_local_http_versions_assets_receipts_checkpoint(self):
  import base64
  sid='wechat:fixture';root='/api/sources/'+sid
  status,r=self.req(root+'/imports',{'records':[{'nativeId':'msg-1','text':'旧原文','at':'2026-10-24T09:00:00+08:00'}]})
  self.assertEqual(status,200,r);snapshot=r['receipt']['snapshot']
  record=self.req(root+'/records')[1]['records'][0];rid=record['id']
  self.assertEqual(self.req(root+'/snapshots')[1]['snapshots'][0]['snapshot'],snapshot)
  self.assertEqual(self.req(root+'/read-version?recordId='+rid+'&snapshot='+snapshot)[1]['record']['text'],'旧原文')
  status,r=self.req(root+'/receipts',{'snapshot':snapshot,'recordIds':[rid]});self.assertEqual(status,200,r);receipt=r['receipt']
  self.assertEqual(self.req(root+'/receipts/'+receipt['id'])[0],200)
  status,r=self.req(root+'/checkpoints',{'consumerId':'notebook','stage':'retrieved','snapshot':snapshot,'recordIds':[rid],'expectedRevision':0});self.assertEqual(status,200,r)
  self.assertEqual(self.req(root+'/checkpoints',{'consumerId':'notebook','stage':'read','snapshot':snapshot,'recordIds':[rid],'receiptIds':[receipt['id']],'expectedRevision':0})[0],409)
  status,r=self.req(root+'/assets',{'data':base64.b64encode(b'fixture bytes').decode(),'name':'说明.txt','mime':'text/plain'});self.assertEqual(status,200,r)
  self.assertEqual(self.req(root+'/assets/'+r['asset']['assetRef'])[1],b'fixture bytes')
  self.assertEqual(self.req(root+'/records?limit=1&limit=2')[0],400)
 def test_source_catalog_metadata_only(self):
  status,r=self.req('/api/source-catalog',{'sourceId':'wechat:fixture','displayName':'微信保存目录','recordCount':5,'status':'cached_only','expectedRevision':0,'requestId':'CAT-one'})
  self.assertEqual(status,200,r);self.assertFalse(r['source']['coverage']['upstreamComplete'])
  self.assertEqual(self.req('/api/source-catalog',{'sourceId':'wechat:fixture','text':'原始记录','expectedRevision':1})[0],400)
  self.assertEqual(self.req('/api/source-catalog',{'sourceId':'wechat:fixture','recordCount':6,'expectedRevision':0})[0],409)
