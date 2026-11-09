"""Explicit in-process execution port. No shell, plugin loading, timers, or task mutation."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import copy
import json
import os
import re
import sqlite3

ACTOR = {'name':'本地执行接入','kind':'ai'}
ID = re.compile(r'^[A-Za-z0-9_.:-]{1,120}$')


def identifier(value):
    if not isinstance(value,str) or not ID.fullmatch(value): raise ValueError('invalid executor/request/object identifier')
    return value


def bounded_json(value, limit=16384):
    def check(node, depth=0):
        if depth > 8: raise ValueError('payload nesting exceeds budget')
        if isinstance(node,dict):
            if any(not isinstance(k,str) for k in node): raise ValueError('payload keys must be strings')
            for v in node.values(): check(v,depth+1)
        elif isinstance(node,list):
            for v in node: check(v,depth+1)
        elif node is not None and type(node) not in (str,bool,int,float): raise ValueError('payload must be plain JSON')
    check(value)
    try: result=json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)
    except (TypeError,ValueError,RecursionError) as exc: raise ValueError('payload must be finite JSON') from exc
    if len(result.encode()) > limit or '\x00' in result: raise ValueError('payload exceeds budget')
    return result


class ExecutorRegistry:
    """Callables must return an observed status and nonempty summary.

    An accepted/running request is never automatically rerun after a crash: the
    side effect could already have happened. Its result remains unconfirmed.
    Notebook processing receipts describe this execution, never business state.
    """
    def __init__(self, workspace, notebook_port, clock=None):
        self.workspace=Path(workspace).expanduser().resolve(); self.notebook=notebook_port
        self.clock=clock or (lambda:datetime.now(timezone.utc)); self.handlers={}
        directory=self.workspace/'executors'
        if directory.is_symlink(): raise ValueError('executor directory must not be symlink')
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db_file=directory/'requests.sqlite3'
        if self.db_file.is_symlink(): raise ValueError('executor database must not be symlink')
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, canonical TEXT NOT NULL, data TEXT NOT NULL)')
        os.chmod(self.db_file,0o600)

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.db_file,timeout=10); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def register(self,name,handler):
        identifier(name)
        if not callable(handler): raise ValueError('explicit callable required')
        self.handlers[name]=handler

    def _now(self):
        value=self.clock()
        if not isinstance(value,datetime) or value.tzinfo is None: raise ValueError('clock must return aware datetime')
        return value.timestamp()

    def _save(self,request):
        with self._connect() as db: db.execute('UPDATE requests SET data=? WHERE id=?',(bounded_json(request,65536),request['requestId']))

    def get_request(self,request_id):
        identifier(request_id)
        with self._connect() as db: row=db.execute('SELECT data FROM requests WHERE id=?',(request_id,)).fetchone()
        if not row: raise KeyError(request_id)
        request=json.loads(row['data'])
        if request['status']=='running' and request['leaseUntil'] <= self._now():
            # Read-only detection, never infer whether the callable succeeded.
            request.update(status='unconfirmed',error='executor lease expired; actual result unknown; automatic retry disabled')
        return request

    def list_requests(self):
        with self._connect() as db: keys=[r[0] for r in db.execute('SELECT id FROM requests ORDER BY rowid DESC LIMIT 500')]
        return [self.get_request(key) for key in keys]

    def _receipt(self,request):
        text=bounded_json({k:request[k] for k in ('requestId','executor','status','summary','result','error')},24000)
        status='completed' if request['status']=='completed' else 'failed'
        self.notebook.set_record_processing(request['messageId'],status,text,object_ids=[request['taskId']])

    def dispatch(self,executor_name,task_id,request_id,payload=None):
        for value in (executor_name,task_id,request_id): identifier(value)
        if executor_name not in self.handlers: raise ValueError('executor is not explicitly registered')
        payload={} if payload is None else payload
        if not isinstance(payload,dict): raise ValueError('payload must be an object')
        canonical=bounded_json({'executor':executor_name,'taskId':task_id,'payload':payload})
        self.notebook.get_task(task_id)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE'); row=db.execute('SELECT canonical FROM requests WHERE id=?',(request_id,)).fetchone()
            if row:
                if row['canonical']!=canonical: raise ValueError('requestId reused for different execution')
                previous=True
            else:
                previous=False
                request={'requestId':request_id,'executor':executor_name,'taskId':task_id,'payload':copy.deepcopy(payload),
                         'status':'running','summary':'','result':None,'error':None,'messageId':None,
                         'createdAt':self._now(),'leaseUntil':self._now()+120}
                db.execute('INSERT INTO requests VALUES(?,?,?)',(request_id,canonical,bounded_json(request)))
        if previous:
            request=self.get_request(request_id)
            if request['status'] in ('completed','failed') and request.get('messageId'): self._receipt(request)
            return request
        try:
            record=self.notebook.append_record({'text':bounded_json({'type':'execution_request',**json.loads(canonical),'requestId':request_id}),
                   'objectIds':[task_id],'actor':ACTOR,'requestId':'executor-input-'+request_id})
            request['messageId']=record['id']; self._save(request)
            self.notebook.set_record_processing(record['id'],'running','已由显式注册执行者接单；尚无完成结果',object_ids=[task_id])
            result=self.handlers[executor_name](copy.deepcopy(request))
            if not isinstance(result,dict) or set(result)-{'status','summary','result'}: raise ValueError('executor result has unknown fields')
            if result.get('status') not in ('completed','failed') or not isinstance(result.get('summary'),str) or not result['summary'].strip():
                raise ValueError('executor must return observed status and nonempty result summary')
            bounded_json(result,8000)
            request.update(status=result['status'],summary=result['summary'],result=result.get('result'))
            if request['status']=='failed': request['error']=request['summary']
        except Exception as exc:
            request.update(status='failed',error=(type(exc).__name__+': '+str(exc))[:2000],summary='执行失败，未确认完成')
        request['finishedAt']=self._now(); self._save(request)
        if request.get('messageId'):
            try: self._receipt(request)
            except Exception as exc:
                request['receiptError']=(type(exc).__name__+': '+str(exc))[:2000]; self._save(request)
        return request
