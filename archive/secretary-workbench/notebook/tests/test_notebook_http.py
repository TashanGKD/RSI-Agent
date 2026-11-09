import json
import unittest
from test_http import HTTPTests


class NotebookHTTPTests(HTTPTests):
    def headers(self):
        boot=json.loads(self.request('/api/bootstrap')[1])
        return {'Origin':self.base,'Content-Type':'application/json','X-CSRF-Token':boot['csrfToken']}

    def test_new_contract_create_record_refresh(self):
        boot=json.loads(self.request('/api/bootstrap')[1])
        self.assertEqual(boot['states'],['待判断','待办','等对方','暂缓','已完成','不用管了'])
        status,raw=self.request('/api/tasks',dict(title='创建事项',requestId='http-create'),self.headers())
        self.assertEqual(status,200,raw)
        task=json.loads(raw)['task']
        payload=dict(expectedRevision=task['revision'],note='补充说明',state='等对方',assignee='AI',actor={'name':'AI','kind':'ai'},requestId='http-record')
        status,raw=self.request('/api/tasks/'+task['id']+'/record',payload,self.headers())
        self.assertEqual(status,200,raw)
        self.assertEqual(json.loads(raw)['task']['assignee'],'AI')
        self.assertEqual(self.request('/api/tasks/'+task['id']+'/record',payload,self.headers())[0],200)
        self.assertEqual(self.request('/api/refresh',{},self.headers())[0],200)
        detail=json.loads(self.request('/api/tasks/'+task['id'])[1])
        self.assertEqual(detail['task']['selectedState'],'等对方')
        self.assertEqual(detail['timeline'][0]['body'],'补充说明')

    def test_new_writes_keep_same_origin_guard_and_rejections(self):
        self.assertEqual(self.request('/api/tasks',{'title':'denied'})[0],403)
        self.assertEqual(self.request('/api/tasks',{'title':'bad','path':'/tmp/secret'},self.headers())[0],400)
        self.assertEqual(self.request('/api/tasks/T-1/record',{'expectedRevision':0,'state':[]},self.headers())[0],400)
        self.assertIn(self.request('/api/tasks/%2e%2e%2fsecret/record',{'expectedRevision':0,'note':'bad'},self.headers())[0],(400,404))
        self.assertEqual(self.request('/api/tasks/T-1/record',{'expectedRevision':99,'note':'conflict'},self.headers())[0],409)
        self.assertEqual(len(json.loads(self.request('/api/bootstrap')[1])['tasks']),1)

if __name__=='__main__': unittest.main()
