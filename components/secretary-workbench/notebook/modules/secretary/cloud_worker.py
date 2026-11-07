"""Explicit Mac outbound worker. One claim by default; no source discovery."""
import argparse
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

from contracts.errors import ValidationError
from modules.notebook.http_port import HTTPNotebookPort, RemoteNotebookError, validate_base_url
from .cloud_queue import canonical, identifier, public_result, stamp
from .service import SecretaryService


def _input_hash(record):
    return hashlib.sha256(canonical({key:record.get(key) for key in ('id','text','attachments','actor','at')}).encode()).hexdigest()


class _CloudRunJournal(SecretaryService):
    """Secretary runtime with only IDs/checkpoints persisted in its own job ledger.

    Model plans and source input live in memory. A restarted unfinished run uses
    the existing service's completed-prefix replanning contract. Stable job/step
    request IDs protect writes interrupted before their local receipt was saved.
    """
    def __init__(self,*args,**kwargs):
        self._live={}
        super().__init__(*args,**kwargs)

    @staticmethod
    def _reduced(job):
        saved={key:copy.deepcopy(value) for key,value in job.items()
               if key not in {'input','plan','planArchives'}}
        result=job.get('result',{})
        saved['result']={key:copy.deepcopy(result.get(key,[])) for key in ('created','matched','closed','linked','records')}
        # Keep exactly the already-saved prefix, with no task fields, note or text.
        saved['completedPlanPrefix']=[{key:copy.deepcopy(op[key]) for key in ('action','key','taskId','objectIds') if key in op}
            for op in job.get('plan',{}).get('operations',[])[:len(job.get('steps',[]))]]
        # Exception strings from third-party ports are never journal data.
        if saved.get('error'):
            saved['error']='整理尚未完成；原输入仍保留在云端。'
        return saved

    def prepare(self,message_id=None,request_id=None,*,intent='input'):
        if intent!='input' or not isinstance(message_id,str) or not isinstance(request_id,str):
            raise ValidationError('云设备必须指定已保存留言和云任务编号')
        identifier(message_id);identifier(request_id)
        record=self.notebook.record_detail(message_id)
        if (record.get('actor') or {}).get('kind')!='human':
            raise ValidationError('云设备只能整理本人留言')
        digest=_input_hash(record)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM jobs WHERE input_key=?',('message:'+message_id,)).fetchone()
            if row:
                job=json.loads(row['payload'])
                if job['requestId']!=request_id or job.get('inputHash')!=digest:
                    raise ValidationError('本机运行编号或原输入不一致')
                return self._public(job)
            now=stamp()
            job={'id':'sec-worker-'+hashlib.sha256(request_id.encode()).hexdigest()[:32],
                 'status':'queued','stage':'saved','createdAt':now,'updatedAt':now,
                 'messageId':message_id,'requestId':request_id,'inputHash':digest,'intent':'input','steps':[],
                 'result':{'created':[],'matched':[],'closed':[],'linked':[],'records':[]},
                 'input':{'type':'message','intent':'input','record':record}}
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',
                       (job['id'],'message:'+message_id,request_id,canonical(self._reduced(job)),now))
        self._live[job['id']]=copy.deepcopy(job)
        return self._public(job)

    def _get(self,job_id):
        if job_id in self._live:
            return copy.deepcopy(self._live[job_id])
        job=super()._get(job_id)
        if job['status']=='completed':
            return job
        record=self.notebook.record_detail(job['messageId'])
        if _input_hash(record)!=job.get('inputHash'):
            raise ValidationError('云原输入发生变化，已停止本机恢复')
        job['input']={'type':'message','intent':'input','record':record}
        prefix=job.pop('completedPlanPrefix',[])
        if job.get('steps'):
            if len(prefix)!=len(job['steps']):
                raise ValidationError('本机检查点不完整，不能安全恢复')
            job['plan']={'summary':'','operations':prefix}
            job['needsReplan']=True
        self._live[job_id]=copy.deepcopy(job)
        return job

    def _write(self,job):
        job['updatedAt']=stamp()
        self._live[job['id']]=copy.deepcopy(job)
        super()._write(self._reduced(job))


class CloudWorker:
    def __init__(self,notebook_port,workspace,worker_id,*,model_runner=None):
        identifier(worker_id)
        self.notebook=notebook_port
        self.workspace=Path(workspace).expanduser().resolve()
        if self.workspace.is_symlink():
            raise ValidationError('设备工作区无效')
        self.workspace.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.worker_id=worker_id
        self.service=_CloudRunJournal(notebook_port,self.workspace,model_runner=model_runner)
        self._claim=None
        self._last_heartbeat=0
        self._renewing=False

    @contextmanager
    def _owner_lock(self):
        path=self.service.directory/'cloud-worker.lock'
        descriptor=os.open(path,os.O_CREAT|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(descriptor,'a') as stream:
            try:
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValidationError('这个设备工作区已有执行器运行') from None
            yield

    def _lease_guard(self):
        if self._renewing or self._claim is None or time.monotonic()-self._last_heartbeat<60:
            return
        self._renewing=True
        try:
            self.notebook.worker_report(self._claim['job']['id'],self.worker_id,self._claim['leaseToken'],'running')
            self._last_heartbeat=time.monotonic()
        finally:
            self._renewing=False

    def run_once(self):
        with self._owner_lock():
            claim=self.notebook.worker_claim(self.worker_id)
            if claim is None:
                return None
            if not isinstance(claim,dict) or set(claim)!={'job','leaseToken'}:
                raise RemoteNotebookError('云任务租约格式无效')
            job=claim['job']
            identifier(job.get('id'));identifier(job.get('messageId'))
            token=claim['leaseToken']
            if not isinstance(token,str) or not 20<=len(token)<=160:
                raise RemoteNotebookError('云任务租约格式无效')
            self._claim=claim
            self._last_heartbeat=time.monotonic()
            self.notebook.before_write=self._lease_guard
            try:
                local=self.service.prepare(job['messageId'],request_id=job['id'])
                done=self.service.run(local['id'])
                status=done.get('status')
                if status not in {'completed','failed'}:
                    raise RemoteNotebookError('本机整理没有产生结束回执')
                result={key:value for key,value in done.get('result',{}).items()
                        if key in {'summary','created','matched','closed','linked','records'}}
                if status=='completed':
                    result.setdefault('summary','已恢复并确认此前保存的整理结果。')
                result=public_result(result)
                self._lease_guard()
                return self.notebook.worker_report(job['id'],self.worker_id,token,status,result=result,
                    error='本机整理未完成；原留言和已保存步骤仍保留。' if status=='failed' else None)
            except Exception:
                # A rejected/stale lease stops notebook writes through the guard. Report
                # failure best-effort; never turn an unacknowledged save into completion.
                self.notebook.before_write=None
                try:
                    return self.notebook.worker_report(job['id'],self.worker_id,token,'failed',
                        error='执行设备操作失败；请检查设备状态后重试。')
                except Exception:
                    raise RemoteNotebookError('设备回执未获云端确认；云端租约到期后可恢复') from None
            finally:
                self.notebook.before_write=None
                self._claim=None
                self.service._live.clear()


def load_config(path):
    """Read a private regular JSON file without following symlinks or logging data."""
    try:
        descriptor=os.open(Path(path).expanduser(),os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(descriptor,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_uid!=os.getuid() or info.st_size>16384:
                raise ValueError()
            data=json.loads(stream.read(16385))
        if not isinstance(data,dict) or set(data)!={'baseUrl','deviceToken','workspace','workerId'}:
            raise ValueError()
        validate_base_url(data['baseUrl'])
        identifier(data['workerId'])
        if not isinstance(data['workspace'],str) or not Path(data['workspace']).is_absolute():
            raise ValueError()
        token=data['deviceToken']
        if not isinstance(token,str) or not 1<=len(token)<=4096 or not token.isascii() or any(c.isspace() or ord(c)<33 for c in token):
            raise ValueError()
        return data
    except (OSError,ValueError,TypeError,UnicodeError,RecursionError):
        raise ValidationError('配置必须是本人拥有的600权限普通JSON文件，并包含有效的四个必填字段') from None


def main(argv=None):
    parser=argparse.ArgumentParser(description='Mac出站秘书设备；无默认站点或原始信源扫描。')
    parser.add_argument('--config',help='显式600权限私有JSON配置')
    parser.add_argument('--loop',action='store_true',help='显式持续轮询，每8秒检查一次')
    args=parser.parse_args(argv)
    if not args.config:
        parser.print_help()
        return 0
    try:
        config=load_config(args.config)
        port=HTTPNotebookPort(config['baseUrl'],config['deviceToken'],config['workspace'])
        worker=CloudWorker(port,config['workspace'],config['workerId'])
    except (ValidationError,OSError):
        print('设备配置无效；请检查私有配置文件和工作区。',file=sys.stderr)
        return 1
    try:
        while True:
            try:
                result=worker.run_once()
                print('秘书设备：'+('暂无待整理输入。' if result is None else '云端状态 '+result['status']))
                health=Path(config['workspace'])/'device-health.json'
                health.write_text(json.dumps({'at':stamp(),'status':'online','lastResult':result['status'] if result else 'idle'}))
                health.chmod(0o600)
                if not args.loop:
                    return 1 if result and result['status']=='failed' else 0
            except Exception:
                print('秘书设备未能完成本轮连接或确认回执。',file=sys.stderr)
                health=Path(config['workspace'])/'device-health.json'
                health.write_text(json.dumps({'at':stamp(),'status':'connection_error'}))
                health.chmod(0o600)
                if not args.loop:
                    return 1
            time.sleep(8)
    except KeyboardInterrupt:
        return 0


if __name__=='__main__':
    raise SystemExit(main())
