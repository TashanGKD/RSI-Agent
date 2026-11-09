import unittest
from test_local_http import LocalHTTPTests

class ScheduleHTTPTests(LocalHTTPTests):
 def test_schedule_contract_and_failures(self):
  _,r=self.req('/api/tasks',{'title':'独立日程','state':'待办','planDate':self.boot['today'],'confirm':True})
  t=r['task'];status,data=self.req('/api/schedule?start='+self.boot['today']+'&end='+self.boot['today'])
  self.assertEqual(status,200);e=data['entries'][0];self.assertEqual(e['objectId'],t['id'])
  body={'expectedRevision':e['revision'],'expectedObjectRevision':t['revision'],'state':'已完成','note':'HTTP保存','requestId':'SCHED-HTTP'}
  path='/api/schedule/'+e['id']+'/record'
  status,result=self.req(path,body);self.assertEqual(status,200);self.assertEqual(result['entry']['state'],'已完成')
  self.assertEqual(self.req(path,body)[1]['entry']['revision'],result['entry']['revision'])
  self.assertEqual(self.req(path,dict(body,requestId='STALE'))[0],409)
  self.assertEqual(self.req('/api/schedule?start=2026-10-01&end=2026-12-01')[0],400)
  self.assertEqual(self.req('/api/schedule?start=2026-10-23&start=2026-10-24&end=2026-10-24')[0],400)
  self.assertEqual(self.req('/api/schedule?start=2026-10-23&end=2026-10-24&secret=1')[0],400)
  self.assertEqual(self.req(path,dict(body,requestId='BAD'),{'Origin':'null'})[0],403)
  self.assertEqual(self.req('/api/tasks/'+t['id'])[1]['task']['state'],'已完成')

if __name__=='__main__':unittest.main()
