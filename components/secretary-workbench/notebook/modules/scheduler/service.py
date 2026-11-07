"""One deliberate local tick. Review requests only; never a daemon or task editor."""
from contextlib import contextmanager
from datetime import datetime, date, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
import hashlib
import json
import os
import sqlite3
import uuid

ACTOR={'name':'本地调度','kind':'ai'}


class Scheduler:
    MAX_ATTEMPTS=3
    MAX_PER_TICK=8
    LEASE_SECONDS=300
    RETRY_SECONDS=60

    def __init__(self, workspace, notebook_port, secretary_port, clock=None):
        self.workspace=Path(workspace).expanduser().resolve(); self.notebook=notebook_port; self.secretary=secretary_port
        self.clock=clock or (lambda:datetime.now(timezone.utc)); self.conditions={}; self.gaps=[]
        self.directory=self.workspace/'scheduler'
        if self.directory.is_symlink(): raise ValueError('scheduler directory must not be symlink')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db_file=self.directory/'runs.sqlite3'; self.lock_file=self.directory/'tick.lock'
        if self.db_file.is_symlink() or self.lock_file.is_symlink(): raise ValueError('scheduler files must not be symlinks')
        with self._connect() as db: db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        os.chmod(self.db_file,0o600)

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.db_file,timeout=10); db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def _now(self):
        value=self.clock()
        if not isinstance(value,datetime) or value.tzinfo is None: raise ValueError('clock must return aware datetime')
        return value

    def register_condition(self,name,resolver):
        if not isinstance(name,str) or not name.strip() or len(name)>2000 or not callable(resolver): raise ValueError('exact condition and explicit resolver required')
        self.conditions[name]=resolver

    def due_checks(self):
        self.gaps=[]; today=self._now().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(); checks=[]
        for task in self.notebook.list_tasks():
            if not task.get('active',True) or task.get('state') in ('已完成','不用管了'): continue
            triggers=[]; schedule={}; condition=task.get('condition') or ''; proof=None
            for field in ('planDate','reviewDate'):
                value=task.get(field)
                if value:
                    try:
                        if not isinstance(value,str) or len(value)!=10: raise ValueError()
                        date.fromisoformat(value)
                    except (TypeError,ValueError):
                        self.gaps.append({'taskId':task['id'],'status':'invalid_date','field':field}); continue
                    schedule[field]=value
                    if value<=today: triggers.append(field)
            if condition:
                resolver=self.conditions.get(condition)
                if resolver is None:
                    self.gaps.append({'taskId':task['id'],'status':'condition_unknown'}); continue
                try:
                    proof=resolver(dict(task))
                    if not isinstance(proof,dict): raise ValueError('condition resolver must return receipt object')
                    if proof.get('error') or proof.get('status') in ('failed','stopped','unavailable'):
                        raise ValueError('condition source reported failure')
                    if proof.get('met') is not True:
                        if proof.get('met') is not False: self.gaps.append({'taskId':task['id'],'status':'condition_unknown'})
                        continue
                    if proof.get('fresh') is not True or not isinstance(proof.get('receipt'),str) or not proof['receipt'].strip():
                        self.gaps.append({'taskId':task['id'],'status':'condition_stale_or_unverified'}); continue
                    if len(proof['receipt'])>4000: raise ValueError('condition receipt too long')
                except Exception as exc:
                    self.gaps.append({'taskId':task['id'],'status':'condition_failed','error':(type(exc).__name__+': '+str(exc))[:1000]}); continue
                if schedule and not triggers: continue
                triggers.append('condition')
            if not triggers: continue
            definition={'taskId':task['id'],'schedule':{k:v for k,v in schedule.items() if k in triggers},'condition':condition}
            key='review-'+hashlib.sha256(json.dumps(definition,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:40]
            check={'id':key,**definition,'triggers':triggers,'conditionReceipt':proof.get('receipt') if proof else None}
            checks.append(check)
        return checks

    def _write(self,run):
        with self._connect() as db: db.execute('INSERT INTO runs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                                             (run['id'],json.dumps(run,ensure_ascii=False,sort_keys=True)))

    def status(self):
        with self._connect() as db: return [json.loads(r[0]) for r in db.execute('SELECT data FROM runs ORDER BY rowid DESC')]

    def _reconcile(self,run):
        if run['status']!='submitted': return run
        try:
            job=self.secretary.get_job(run['jobId']); status=job.get('status')
            if status=='completed': run.update(status='reviewed',jobStatus=status)
            elif status=='failed': run.update(status='failed',jobStatus=status,error=job.get('error') or 'secretary review failed',retryAt=self._now().timestamp()+self.RETRY_SECONDS)
            elif status in ('queued','running') and self._now().timestamp()>run['leaseUntil']:
                run.update(status='failed',jobStatus=status,error='secretary worker stopped or overdue; result unconfirmed',retryAt=self._now().timestamp()+self.RETRY_SECONDS)
            elif status not in ('queued','running'): raise ValueError('secretary job status unavailable')
        except Exception as exc: run.update(status='failed',error=(type(exc).__name__+': '+str(exc))[:1000],retryAt=self._now().timestamp()+self.RETRY_SECONDS)
        self._write(run); return run

    def tick(self,apply=False):
        if type(apply) is not bool: raise ValueError('apply must be explicit boolean')
        checks=self.due_checks(); result={'pending':checks,'gaps':list(self.gaps),'runs':self.status(),'applied':False}
        if not apply: return result
        # One local caller owns a tick; persisted lease survives process interruption.
        with open(self.lock_file,'a+') as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                result['gaps'].append({'status':'tick_busy'}); return result
            saved={r['id']:self._reconcile(r) for r in self.status()}; count=0
            for check in checks:
                run=saved.get(check['id']); now=self._now().timestamp()
                if run and (run['status'] in ('reviewed','submitted') or run['attempts']>=self.MAX_ATTEMPTS or
                            (run['status']=='running' and run['leaseUntil']>now) or run.get('retryAt',0)>now): continue
                if count>=self.MAX_PER_TICK: break
                count+=1
                if run is None:
                    raw={'type':'scheduled_review','instruction':'Request review only. Read relevant current facts before proposing changes. Never infer completion or unchanged sources from a due date. No execution is authorized.',
                         'sourceFreshness':'unknown','check':check}
                    run={**check,'status':'pending','attempts':0,'messageId':None,'raw':json.dumps(raw,ensure_ascii=False,sort_keys=True)}
                run.update(status='running',attempts=run['attempts']+1,leaseUntil=now+self.LEASE_SECONDS,leaseId=uuid.uuid4().hex,error=None)
                self._write(run)
                try:
                    record=self.notebook.append_record({'text':run['raw'],'objectIds':[check['taskId']],'actor':ACTOR,'requestId':check['id']})
                    run['messageId']=record['id']; self._write(run)
                    job=self.secretary.submit(message_id=record['id'],request_id=check['id'],intent='review')
                    if not isinstance(job,dict) or not isinstance(job.get('id'),str): raise ValueError('secretary did not return job receipt')
                    run.update(status='submitted',jobId=job['id'],jobStatus=job.get('status'))
                    if job.get('status')=='failed': raise RuntimeError(job.get('error') or 'secretary review failed')
                except Exception as exc:
                    run.update(status='failed',error=(type(exc).__name__+': '+str(exc))[:2000],retryAt=now+self.RETRY_SECONDS)
                    if run.get('messageId'):
                        try: self.notebook.set_record_processing(run['messageId'],'failed','调度提交失败：'+run['error'])
                        except Exception as receipt_exc: run['receiptError']=(type(receipt_exc).__name__+': '+str(receipt_exc))[:1000]
                self._write(run)
            result.update(applied=True,runs=self.status())
            return result
