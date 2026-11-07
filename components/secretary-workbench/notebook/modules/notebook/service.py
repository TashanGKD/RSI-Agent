"""Additive local notebook over preserved legacy evidence and human history.

Only this module owns ledger tables. External modules use the public service.
Original records are append-only; a task change and its review acknowledgement
share a transaction. No source acquisition or model inference occurs here.
"""
import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
from contracts import STATES, DOMAINS, CLOSED, KINDS, TIMEZONE, state, text, day, actor, today
from .schedule import ScheduleMixin, window
from .journal import JournalMixin
from .reviews import ReviewMixin, followup
from .catalog import CatalogMixin
from .work import WorkMixin
from contracts.work import work_metadata
from contracts.source_refs import source_refs
from .legacy_notebook import Notebook as LegacyNotebook
from .legacy_store import ValidationError, ConflictError, validate_id, stamp

PATCH_FIELDS={'title','kind','domain','state','assignee','counterparty','summary','proposedAt','timeRequirement',
              'recurrence','planDate','eventWindow','reviewDate','followup','deadlineDate','sourceContacts','condition','relatedRecordIds','completionCriterion','recommendation','sources','needsReview'}
COMMON={'actor','requestId','note','confirm','sourceTime','presentationId','presentationVersion','attachments','work'}
MAX_ASSET=8*1024*1024

class NotebookService(WorkMixin,CatalogMixin,ReviewMixin,JournalMixin,ScheduleMixin):
    linked_record_revisions=True
    def __init__(self,db_file,source_file,workspace):
        workspace_input=Path(workspace).expanduser().absolute()
        self.workspace=workspace_input.resolve()
        db_input=Path(db_file).expanduser().absolute()
        # Reject managed symlink escapes BEFORE LegacyNotebook can create a DB/WAL.
        for managed in (self.workspace/'notebook',self.workspace/'notebook'/'attachments'):
            if not managed.resolve().is_relative_to(self.workspace):raise ValidationError('受管工作区路径越界')
        for base in (workspace_input,self.workspace):
            if db_input.is_relative_to(base) and not db_input.resolve().is_relative_to(self.workspace):
                raise ValidationError('数据库路径通过链接越界')
        self.db_file=db_input.resolve()
        self.source_file=Path(source_file).expanduser().resolve()
        self.workspace.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.legacy=LegacyNotebook(self.db_file,self.source_file)
        with self.legacy.connect() as db:
            empty=db.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
            has_objects=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_objects'").fetchone()
            preserved=has_objects and db.execute('SELECT 1 FROM local_objects LIMIT 1').fetchone()
        if empty and not preserved and self.source_file.exists():self.legacy.refresh()
        with self.legacy.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS local_objects(id TEXT PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS local_changes(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT UNIQUE NOT NULL,
              id TEXT NOT NULL,at TEXT NOT NULL,actor TEXT NOT NULL,payload TEXT NOT NULL,previous TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS local_changes_object ON local_changes(id,seq);
            CREATE TABLE IF NOT EXISTS local_records(id TEXT PRIMARY KEY,text TEXT NOT NULL,object_ids TEXT NOT NULL,
              attachments TEXT NOT NULL,actor TEXT NOT NULL,at TEXT NOT NULL,processing TEXT NOT NULL,receipts TEXT NOT NULL,source_refs TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS local_requests(id TEXT PRIMARY KEY,canonical TEXT NOT NULL,result_kind TEXT NOT NULL,result_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS local_assets(id TEXT PRIMARY KEY,name TEXT NOT NULL,mime TEXT NOT NULL,
              size INTEGER NOT NULL,hash TEXT NOT NULL,path TEXT NOT NULL);
            ''')
        with self.legacy.connect() as db:
            if 'source_refs' not in [r[1] for r in db.execute('PRAGMA table_info(local_records)')]:
                db.execute("ALTER TABLE local_records ADD COLUMN source_refs TEXT NOT NULL DEFAULT '[]'")
        with self.legacy.connect() as db:
            if 'work' not in [r[1] for r in db.execute('PRAGMA table_info(local_records)')]:
                db.execute('ALTER TABLE local_records ADD COLUMN work TEXT')
        self.assets_dir=self.workspace/'notebook'/'attachments'
        self.assets_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        if not self.assets_dir.resolve().is_relative_to(self.workspace):raise ValidationError('附件目录越界')
        self._init_schedule()
        self._init_reviews()
        self._init_journal()
        self._init_catalog()

    def _connect(self):return self.legacy.connect()

    def _assert_writable(self):
        if self.db_file.with_name(self.db_file.name+'.online.json').exists():
            raise ValidationError('本机库已保留为切换前存档；请在在线记事本保存，避免产生两份主库')

    def _raw(self,rid,db):
        row=db.execute('SELECT payload FROM tasks WHERE id=?',(rid,)).fetchone()
        if row is None:row=db.execute('SELECT payload FROM local_items WHERE id=?',(rid,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _base(self,rid,db):
        row=db.execute('SELECT payload FROM local_objects WHERE id=?',(rid,)).fetchone()
        if row:return json.loads(row[0])
        old=self.legacy.task(rid)
        raw=self._raw(rid,db)
        contacts=old.get('sourceContacts') or []
        ev=[]
        for c in (raw.get('evidence') or [])[:4]:
            if not isinstance(c,dict):continue
            ev.append({'label':c.get('sender') or '已存原文','quote':str(c.get('text') or c.get('quote') or '')[:12000]})
        if contacts:
            names=[]
            for c in contacts[:3]:
                label=' · '.join(str(c.get(k) or '') for k in ['channel','conversationName','senderName'] if c.get(k))
                if label:names.append(label)
            if names and ev:ev[0]['label']='／'.join(names)
        reminder=old.get('reminder') or {}
        review_date=None;review_at=None
        if reminder.get('at'):
            try:
                original=datetime.fromisoformat(reminder['at'].replace('Z','+00:00'))
                if original.tzinfo is not None:
                    original=original.astimezone(ZoneInfo(TIMEZONE));review_date=original.date().isoformat();review_at=original.isoformat()
            except (ValueError,TypeError):pass
        proposed=old.get('proposedAt')
        if isinstance(proposed,dict):proposed=proposed.get('earliestExplicitMessage')
        if not isinstance(proposed,str) or not proposed:proposed=old.get('proposedDisplayAt')
        st=state(old.get('selectedState','其他'))
        return {'id':rid,'title':old.get('title','未命名'),'kind':old.get('kind','action'),'domain':old.get('domain',''),
            'assignee':old.get('assignee','我'),'counterparty':old.get('counterparty',''),
            'proposedAt':proposed,
            'timeRequirement':old.get('timeRequirement','时间待定'),'deadlineDate':old.get('deadlineDate'),
            'summary':old.get('lastKnownState',''),'state':st,'selectedState':st,'planDate':None,'planDateExplicit':False,
            'reviewDate':review_date,'followup':{'date':review_date,'at':review_at,'condition':'','remindEvenUnchanged':True} if review_at else None,'condition':'','needsReview':not old.get('reviewedByHuman',False) and st not in CLOSED,
            'revision':old['revision'],'active':old.get('active',True),'recommendation':old.get('recommendation'),
            'relatedRecordIds':old.get('relatedRecordIds',[]),'completionCriterion':old.get('completionCriterion',''),
            'sourceContacts':contacts,'evidence':ev,'legacy':True}

    def _current(self,rid,db):
        validate_id(rid);t=self._base(rid,db)
        for e in db.execute('SELECT payload FROM local_changes WHERE id=? ORDER BY seq',(rid,)):
            p=json.loads(e[0]);t.update(p.get('patch',{}));t['revision']+=1
            if 'planDate' in p.get('patch',{}):t['planDateExplicit']=True
            if p.get('sources'):t['evidence']=p['sources']+t.get('evidence',[])
        t['state']=state(t['state']);t['selectedState']=t['state']
        r=t.get('recommendation')
        if r:
            try:t['recommendation']=dict(r,state=state(r['state']))
            except (KeyError,TypeError,ValidationError):t['recommendation']=None
        if t['state'] in CLOSED:t['needsReview']=False;t['reviewDate']=None
        if t.get('kind')!='action':t['needsReview']=False
        source_evidence,contacts=self._linked_source_evidence(rid,db)
        if source_evidence:
            t['evidence']=source_evidence+t.get('evidence',[])
            current=t.get('sourceContacts',[])
            t['sourceContacts']=current+[c for c in contacts if c not in current]
        t['evidence']=t.get('evidence',[])[:5]
        if not t['evidence']:t['evidence']=self._fallback_evidence(rid,db)
        if hasattr(self,'_journal_ready') and self._journal_ready:
            self._decorate_review(t,db)
            latest=db.execute("SELECT o.id,o.seq FROM notebook_operations o JOIN notebook_effects e ON e.operation_id=o.id WHERE e.kind='object' AND e.id=? ORDER BY o.seq DESC LIMIT 1",(rid,)).fetchone()
            if latest:t['lastOperationId']=latest['id'];t['lastSequence']=latest['seq']
        return t

    def _linked_source_evidence(self,rid,db):
        evidence=[];contacts=[]
        for r in db.execute("SELECT text,source_refs,object_ids,actor FROM local_records WHERE source_refs<>'[]' AND object_ids LIKE ? ORDER BY at DESC",('%"'+rid+'"%',)):
            if rid not in json.loads(r['object_ids']):continue
            for ref in json.loads(r['source_refs']):
                channel=ref['sourceId'].split(':',1)[0]
                label=' · '.join(str(v) for v in (channel,ref.get('conversation'),ref.get('sender')) if v)
                evidence.append(dict(ref,label=label,quote=r['text'][:12000],evidenceKind='summary' if json.loads(r['actor']).get('kind')=='ai' else 'input'))
                contacts.append(dict(ref,channel=channel,conversationName=ref.get('conversation',''),senderName=ref.get('sender','')))
                if len(evidence)>=5:return evidence,contacts
        return evidence,contacts

    def _fallback_evidence(self,rid,db):
        for table in ('local_changes','notebook_events'):
            for r in db.execute('SELECT payload,actor,at FROM '+table+' WHERE id=? ORDER BY seq DESC',(rid,)):
                p=json.loads(r['payload']);a=json.loads(r['actor'])
                if p.get('sources'):
                    return [{'label':v.get('label') or '已存原文','quote':str(v.get('quote') or '')[:12000]} for v in p['sources'] if v.get('quote')][:3]
                if p.get('note','').strip():
                    label=('本人批注' if a.get('kind')=='human' else 'AI记录')+' · '+a.get('name','')
                    return [{'label':label,'quote':p['note'][:12000],'at':r['at'],'sender':a.get('name',''),'evidenceKind':'summary' if a.get('kind')=='ai' else 'input'}]
        for r in db.execute("SELECT text,actor,at,object_ids FROM local_records WHERE object_ids LIKE ? AND text<>'' ORDER BY at DESC",('%"'+rid+'"%',)):
            if rid in json.loads(r['object_ids']):
                a=json.loads(r['actor'])
                return [{'label':('本人留言' if a.get('kind')=='human' else 'AI记录')+' · '+a.get('name',''),'quote':r['text'][:12000],'at':r['at'],'sender':a.get('name',''),'evidenceKind':'summary' if a.get('kind')=='ai' else 'input'}]
        return []

    def get_task(self,rid):
        with self._connect() as db:return self._current(rid,db)

    def list_tasks(self):
        with self._connect() as db:
            ids=[r[0] for r in db.execute('SELECT id FROM tasks ORDER BY position,id')]
            ids += [r[0] for r in db.execute('SELECT id FROM local_items ORDER BY created_at,id')]
            ids += [r[0] for r in db.execute('SELECT id FROM local_objects ORDER BY created_at,id')]
            return [self._current(rid,db) for rid in dict.fromkeys(ids)]

    def query(self,view='today',domain='',assignee='我',date=None):
        if view not in ('today','review','all'):raise ValidationError('视图无效')
        if domain and domain not in DOMAINS:raise ValidationError('领域无效')
        requested_date=date
        date=day(date) or today();res=[]
        for t in self.list_tasks():
            if not t.get('active',True):continue
            if domain and t.get('domain')!=domain:continue
            if assignee and assignee!='全部' and t['assignee']!=assignee:continue
            due_plan=t.get('planDate') and t['planDate']<=date
            legacy_pending=(t.get('legacy') or t.get('importedLegacyPlanning')) and not t.get('planDateExplicit') and not t['needsReview'] and not t.get('planDate') and (not t.get('reviewDate') or t['reviewDate']<=date)
            if view=='today' and not(t['kind']=='action' and t['state']=='待办' and (due_plan or legacy_pending)):continue
            future_review=t.get('reviewDate') and t['reviewDate']>date
            due_plan=t.get('planDate') and t['planDate']<=date and t['state']!='暂缓'
            if view=='review':
                due_followup=any(x['objectId']==t['id'] for x in self.due_followups(date=requested_date)['items'])
                if not ((t['needsReview'] and not(future_review and not due_plan)) or due_followup):continue
            res.append(t)
        return sorted(res,key=lambda t:(t.get('planDate') or '9999',t.get('deadlineDate') or '9999',str(t.get('proposedAt') or '9999'),t['id']))

    def _canonical(self,op,rid,body):return json.dumps([op,rid,body],sort_keys=True,ensure_ascii=False,separators=(',',':'))

    def _retry(self,db,request_id,canonical):
        if request_id is None:return None
        validate_id(request_id)
        r=db.execute('SELECT * FROM local_requests WHERE id=?',(request_id,)).fetchone()
        if r and r['canonical']!=canonical:raise ValidationError('请求编号已用于另一份内容')
        return dict(r) if r else None

    def _remember(self,db,key,canon,kind,rid):
        if key:db.execute('INSERT INTO local_requests VALUES(?,?,?,?)',(key,canon,kind,rid))

    def _validate(self,body,creating=False):
        allowed=PATCH_FIELDS|COMMON|({'expectedRevision'} if not creating else set())
        if not isinstance(body,dict) or set(body)-allowed:raise ValidationError('未知字段')
        a=actor(body.get('actor'));p={};sources=[]
        if creating and 'title' not in body:raise ValidationError('请填写事项名称')
        for f,limit in [('title',1000),('assignee',120),('counterparty',500),('summary',12000),('timeRequirement',1000),('condition',2000),('completionCriterion',2000)]:
            if f in body:p[f]=text('' if f=='condition' and body[f] is None else body[f],f,limit,empty=f not in ('title','assignee'))
        if 'state' in body:p['state']=state(body['state'])
        if 'domain' in body:
            if body['domain'] not in (*DOMAINS,'',None):raise ValidationError('领域无效')
            p['domain']=body['domain'] or ''
        if 'kind' in body:
            if body['kind'] not in KINDS:raise ValidationError('性质无效')
            p['kind']=body['kind']
        for f in ('planDate','reviewDate','deadlineDate'):
            if f in body:p[f]=day(body[f],f)
        if 'recurrence' in body:
            from .recurrence import recurrence
            p['recurrence']=recurrence(body['recurrence'])
        if 'sourceContacts' in body:p['sourceContacts']=source_refs(body['sourceContacts'])
        if 'followup' in body:p['followup']=followup(body['followup'])
        if 'attachments' in body:
            if not isinstance(body['attachments'],list) or len(body['attachments'])>10:raise ValidationError('附件引用无效')
            for aid in body['attachments']:self.asset(validate_id(aid))
        if 'presentationId' in body:validate_id(body['presentationId'])
        if 'presentationVersion' in body and (type(body['presentationVersion']) is not int or body['presentationVersion']<1):raise ValidationError('呈报版本无效')
        if 'eventWindow' in body:p['eventWindow']=window(body['eventWindow'],p.get('planDate'))
        if 'proposedAt' in body:
            v=body['proposedAt']
            if v is not None:
                if not isinstance(v,str) or len(v)>60:raise ValidationError('提出时间无效')
                try:
                    d=datetime.fromisoformat(v.replace('Z','+00:00'))
                    if len(v)!=10 and d.tzinfo is None:raise ValueError()
                except ValueError:raise ValidationError('提出时间无效')
            p['proposedAt']=v
        if 'recommendation' in body:
            r=body['recommendation']
            if r is None:p['recommendation']=None
            else:
                if not isinstance(r,dict) or set(r)!={'state','reason'}:raise ValidationError('建议无效')
                p['recommendation']={'state':state(r['state']),'reason':text(r['reason'],'建议依据',4000,empty=True)}
        if 'needsReview' in body:
            if type(body['needsReview']) is not bool:raise ValidationError('批阅标志无效')
            p['needsReview']=body['needsReview']
        if 'relatedRecordIds' in body:
            r=body['relatedRecordIds']
            if not isinstance(r,list) or len(r)>100:raise ValidationError('关联无效')
            p['relatedRecordIds']=[validate_id(x) for x in r]
            if len(set(r))!=len(r):raise ValidationError('重复关联')
        if 'sources' in body:
            if not isinstance(body['sources'],list) or len(body['sources'])>20:raise ValidationError('依据无效')
            for r in body['sources']:
                if not isinstance(r,dict) or set(r)-{'label','quote','at','sender','sourceId','nativeId'}:raise ValidationError('依据字段无效')
                if not r.get('quote'):raise ValidationError('依据缺少原文')
                sources.append({k:text(v,'依据',32000 if k=='quote' else 500,empty=True) for k,v in r.items()})
        note=None if 'note' not in body else text(body['note'],'备注',12000,empty=True)
        if 'sourceTime' in body:text(body['sourceTime'],'原时间',100,empty=True)
        if 'confirm' in body and type(body['confirm']) is not bool:raise ValidationError('确认字段无效')
        if 'work' in body:
            work_metadata(body['work'])
            if not note or not note.strip():raise ValidationError('实际工作须附进展备注')
        if 'requestId' in body:validate_id(body['requestId'])
        return a,p,note,sources

    def _append(self,db,rid,a,patch,note,sources,previous,extras=None):
        before=self._current(rid,db) if previous else None
        payload={'patch':patch}
        for k in ('sourceTime','attachments','work'):
            if extras and k in extras:payload[k]=work_metadata(extras[k]) if k=='work' else extras[k]
        if note is not None:payload['note']=note
        if sources:payload['sources']=sources
        event_id='EV-'+uuid.uuid4().hex
        db.execute('INSERT INTO local_changes(event_id,id,at,actor,payload,previous) VALUES(?,?,?,?,?,?)',
                   (event_id,rid,stamp(),json.dumps(a,ensure_ascii=False),json.dumps(payload,ensure_ascii=False),json.dumps(previous,ensure_ascii=False)))
        self._audit(db,'object',rid,before,self._current(rid,db))
        self._link_operation(db,'local_changes',event_id)

    def validate_fields(self,body,creating=False):
        """Pure public preflight. No writes, no ID allocation or schema mutation."""
        self._validate(body,creating)
        return True

    def _apply_semantics(self,patch,body,current,a):
        if 'followup' in patch:
            patch['reviewDate']=(patch['followup'] or {}).get('date');patch['followupSetAt']=stamp()
        elif 'reviewDate' in patch:
            patch['followup']=followup({'date':patch['reviewDate']});patch['followupSetAt']=stamp()
        if body.get('confirm'):
            if a['kind']!='human':raise ValidationError('本人确认不能由AI代写')
            patch['needsReview']=False
            if patch.get('state',current.get('state'))=='待办' and 'planDate' not in body and not current.get('planDate'):patch['planDate']=today()
        st=patch.get('state',current.get('state','其他'))
        if st in CLOSED:patch['needsReview']=False;patch['reviewDate']=None;patch['followup']=None
        patch['updatedAt']=stamp();patch['updatedBy']=a

    def create_task(self,body):
        self._assert_writable()
        a,p,note,sources=self._validate(body,True);canon=self._canonical('create',None,body);key=body.get('requestId')
        with self._transaction(a,key) as db:
            retry=self._retry(db,key,canon)
            if retry:return self._current(retry['result_id'],db)
            t=self._create_task(db,body,a,p,note,sources);rid=t['id']
            self._remember(db,key,canon,'task',rid)
        return self.get_task(rid)

    def _create_task(self,db,body,a,p,note,sources):
        rid='LOCAL-'+uuid.uuid4().hex
        for ref in p.get('relatedRecordIds',[]):self._current(ref,db)
        t={'id':rid,'kind':'action','title':p['title'],'domain':'','state':'其他','selectedState':'其他',
           'assignee':'我','counterparty':'为自己','summary':'','proposedAt':stamp(),'timeRequirement':'时间待定',
           'deadlineDate':None,'planDate':None,'reviewDate':None,'condition':'','needsReview':True,'revision':0,
           'active':True,'recommendation':None,'relatedRecordIds':[],'completionCriterion':'','evidence':[], 'sourceContacts':[],'legacy':False}
        self._apply_semantics(p,body,t,a);t.update(p)
        db.execute('INSERT INTO local_objects VALUES(?,?,?)',(rid,json.dumps(t,ensure_ascii=False),stamp()))
        if t['needsReview']:self._new_presentation(db,rid,a,note or '')
        self._append(db,rid,a,{},note,sources,{},body)
        self._sync_schedule(db,t,{},a,note or '')
        return t

    def record(self,rid,body,*,_canonical_override=None):
        self._assert_writable()
        validate_id(rid);a,p,note,sources=self._validate(body);v=body.get('expectedRevision')
        if type(v) is not int or v<0:raise ValidationError('缺少有效版本')
        if not p and note is None and not sources and not body.get('confirm'):raise ValidationError('没有要保存的变更')
        key=body.get('requestId');canon=_canonical_override or self._canonical('record',rid,body)
        with self._transaction(a,key) as db:
            retry=self._retry(db,key,canon)
            if retry:return self._current(rid,db)
            t=self._current(rid,db)
            if t['revision']!=v:raise ConflictError('这条事项已被修改，草稿已保留，请核对最新内容')
            for ref in p.get('relatedRecordIds',[]):
                if ref==rid:raise ValidationError('不能关联自身')
                self._current(ref,db)
            self._apply_semantics(p,body,t,a)
            if 'planDate' in p and p['planDate']!=t.get('planDate') and 'eventWindow' not in p:p['eventWindow']=None
            if 'eventWindow' in p:window(p['eventWindow'],p.get('planDate',t.get('planDate')))
            previous={k:t.get(k) for k in p}
            self._audit(db,'object',rid,t,t)
            self._confirm_presentation(db,rid,body,a)
            if p.get('needsReview') is True and not body.get('confirm'):self._new_presentation(db,rid,a,note or '')
            self._append(db,rid,a,p,note,sources,previous,body)
            self._sync_schedule(db,dict(t,**p),t,a,note or '',explicit=set(body))
            self._remember(db,key,canon,'task',rid)
        return self.get_task(rid)

    def detail(self,rid):
        task=self.get_task(rid)
        if task.get('legacy'):
            d=self.legacy.detail(rid)
        else:d={'timeline':list(task.get('cloudProjectionTimeline',[])),'sourceLinks':[],'history':list(task.get('cloudProjectionHistory',[]))}
        with self._connect() as db:
            for e in db.execute('SELECT * FROM local_changes WHERE id=? ORDER BY seq DESC',(rid,)):
                p=json.loads(e['payload']);a=json.loads(e['actor'])
                if p.get('note') is None and not p.get('sources') and not p.get('attachments') and not (set(p.get('patch',{}))-{'updatedAt','updatedBy'}):continue
                d['timeline'].append(dict(id=e['event_id'],at=e['at'],actor=a,author=a['name'],body=p.get('note',''),
                    note=p.get('note',''),changes=p.get('patch',{}),previous=json.loads(e['previous']),sources=p.get('sources',[]),sourceTime=p.get('sourceTime'),work=p.get('work'),attachments=[self.asset(x,public=True) for x in p.get('attachments',[])]))
            for r in self.list_records():
                if rid in r['objectIds']:d['timeline'].append({'id':r['id'],'at':r['at'],'actor':r['actor'],'author':r['actor']['name'],'body':r['text'],'attachments':r['attachments'],'work':r.get('work'),'sourceRefs':r['sourceRefs']})
        ops=self.changes(object_id=rid,limit=500)['operations']
        links={l['id']:(op['id'],op['sequence']) for op in ops for l in op['records']}
        for entry in d['timeline']:
            if entry['id'] in links:entry.update(operationId=links[entry['id']][0],sequence=links[entry['id']][1])
        d['timeline'].sort(key=lambda e:str(e.get('at','')),reverse=True)
        linked=set(task['relatedRecordIds'])
        for info in self.list_records():
            if rid in info['objectIds']:linked.update(info['objectIds'])
        linked.discard(rid)
        all_tasks=self.list_tasks();linked.update(t['id'] for t in all_tasks if rid in t.get('relatedRecordIds',[]))
        with self._connect() as db:
            d['schedules']=[json.loads(r[0]) for r in db.execute('SELECT payload FROM schedule_entries WHERE object_id=? ORDER BY date DESC',(rid,))]
        d.update(task=task,evidence=task['evidence'],relatedTasks=[t for t in all_tasks if t['id'] in linked],operations=ops)
        return d

    def append_record(self,body):
        self._assert_writable()
        if not isinstance(body,dict) or set(body)-{'text','objectIds','attachments','actor','requestId','sourceRefs','work'}:raise ValidationError('信息字段无效')
        value=text(body.get('text',''),'留言',64000,empty=True);a=actor(body.get('actor'));refs=body.get('objectIds',[]);assets=body.get('attachments',[])
        if not isinstance(refs,list) or len(refs)>100 or not isinstance(assets,list) or len(assets)>10:raise ValidationError('信息引用无效')
        if not value.strip() and not assets:raise ValidationError('请写一句话或添加附件')
        refs=[validate_id(x) for x in refs];assets=[validate_id(x) for x in assets]
        if len(set(refs))!=len(refs):raise ValidationError('关联重复')
        work=work_metadata(body['work']) if 'work' in body else None
        if work is not None and not refs:raise ValidationError('实际工作必须关联事项；独立结果请直接建立已完成事项')
        source_refs_value=source_refs(body.get('sourceRefs',[]))
        canon=self._canonical('append_record',None,body);key=body.get('requestId')
        with self._transaction(a,key) as db:
            r=self._retry(db,key,canon)
            if r:return self._record_row(db.execute('SELECT * FROM local_records WHERE id=?',(r['result_id'],)).fetchone())
            linked_before={rid:self._current(rid,db) for rid in refs}
            for aid in assets:self.asset(aid)
            rid='MSG-'+uuid.uuid4().hex
            db.execute('INSERT INTO local_records(id,text,object_ids,attachments,actor,at,processing,receipts,source_refs) VALUES(?,?,?,?,?,?,?,?,?)',(rid,value,json.dumps(refs),json.dumps(assets),json.dumps(a,ensure_ascii=False),stamp(),'pending','[]',json.dumps(source_refs_value,ensure_ascii=False)))
            if work is not None:db.execute('UPDATE local_records SET work=? WHERE id=?',(json.dumps(work,ensure_ascii=False),rid))
            self._audit(db,'record',rid,None,self._record_row(db.execute('SELECT * FROM local_records WHERE id=?',(rid,)).fetchone()))
            self._link_operation(db,'local_records',rid)
            for object_id,old in linked_before.items():
                self._audit(db,'object',object_id,old,old)
                self._append(db,object_id,a,{'updatedAt':stamp(),'updatedBy':a},None,[],{'updatedAt':old.get('updatedAt'),'updatedBy':old.get('updatedBy')})
            self._remember(db,key,canon,'message',rid)
        return self.record_detail(rid)

    def _record_row(self,row):
        if not row:raise KeyError('record')
        result={'id':row['id'],'text':row['text'],'objectIds':json.loads(row['object_ids']),
            'attachments':[self.asset(x,public=True) for x in json.loads(row['attachments'])],
            'actor':json.loads(row['actor']),'at':row['at'],'processing':row['processing'],'receipts':json.loads(row['receipts']),'sourceRefs':json.loads(row['source_refs'])}
        if row['work'] is not None:result['work']=json.loads(row['work'])
        return result

    def list_records(self):
        with self._connect() as db:return [self._record_row(r) for r in db.execute('SELECT * FROM local_records ORDER BY at DESC,id')]

    def record_detail(self,rid):
        validate_id(rid)
        with self._connect() as db:return self._record_row(db.execute('SELECT * FROM local_records WHERE id=?',(rid,)).fetchone())

    def set_record_processing(self,rid,status,receipt='',object_ids=None):
        self._assert_writable()
        validate_id(rid)
        if status not in ('pending','running','completed','failed'):raise ValidationError('整理状态无效')
        text(receipt,'整理回执',12000,empty=True)
        with self._transaction({'name':'处理回执','kind':'ai'}) as db:
            r=self._record_row(db.execute('SELECT * FROM local_records WHERE id=?',(rid,)).fetchone())
            refs=r['objectIds'] if object_ids is None else object_ids
            if not isinstance(refs,list) or len(refs)>100:raise ValidationError('回执关联无效')
            for ref in refs:self._current(validate_id(ref),db)
            affected={oid:self._current(oid,db) for oid in set(r['objectIds']) ^ set(refs)}
            receipts=r['receipts']
            if receipt and not (receipts and receipts[-1].get('text')==receipt and receipts[-1]['status']==status):
                receipts.append({'at':stamp(),'status':status,'text':receipt,'objectIds':refs})
            db.execute('UPDATE local_records SET processing=?,receipts=?,object_ids=? WHERE id=?',(status,json.dumps(receipts,ensure_ascii=False),json.dumps(list(dict.fromkeys(refs))),rid))
            self._audit(db,'record',rid,r,self._record_row(db.execute('SELECT * FROM local_records WHERE id=?',(rid,)).fetchone()))
            for object_id,old in affected.items():
                self._audit(db,'object',object_id,old,old)
                self._append(db,object_id,{'name':'处理回执','kind':'ai'},{'updatedAt':stamp()},None,[],{'updatedAt':old.get('updatedAt')})
        return self.record_detail(rid)

    def source(self,rid,index):
        return self.legacy.source(rid,index)

    def attach_asset(self,name,data,mime=None):
        self._assert_writable()
        text(name,'文件名',200)
        if '/' in name or '\\' in name or name in ('.','..'):raise ValidationError('文件名含路径')
        if not isinstance(data,bytes) or not data or len(data)>MAX_ASSET:raise ValidationError('文件过大或为空（上限8MB）')
        ext=Path(name).suffix.lower();allowed={'.png','.jpg','.jpeg','.webp','.gif','.pdf','.txt','.md','.csv','.json','.docx','.xlsx','.pptx','.mp3','.m4a','.wav'}
        if ext not in allowed:raise ValidationError('不支持这种附件类型')
        signs={'.png':b'\x89PNG\r\n\x1a\n','.jpg':b'\xff\xd8\xff','.jpeg':b'\xff\xd8\xff','.gif':b'GIF','.pdf':b'%PDF-','.docx':b'PK','.xlsx':b'PK','.pptx':b'PK'}
        if ext in signs and not data.startswith(signs[ext]):raise ValidationError('附件类型与内容不符')
        if ext=='.webp' and not(data.startswith(b'RIFF') and data[8:12]==b'WEBP'):raise ValidationError('图片格式无效')
        if not self.assets_dir.resolve().is_relative_to(self.workspace):raise ValidationError('附件目录越界')
        digest=hashlib.sha256(data).hexdigest();aid='ASSET-'+digest[:32];path=self.assets_dir/(aid+ext)
        wrote=False
        try:
            with self._connect() as db:
                db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT id FROM local_assets WHERE id=?',(aid,)).fetchone()
                if r:return self.asset(aid,public=True)
                actual_mime=mimetypes.guess_type(name)[0] or 'application/octet-stream'
                if ext in ('.md','.txt','.csv','.json'):actual_mime='text/plain'
                with path.open('xb') as out:
                    wrote=True
                    out.write(data);out.flush();os.fsync(out.fileno())
                path.chmod(0o600)
                db.execute('INSERT INTO local_assets VALUES(?,?,?,?,?,?)',(aid,name,actual_mime,len(data),digest,str(path.relative_to(self.workspace))))
        except Exception:
            if wrote:path.unlink(missing_ok=True)
            raise
        return self.asset(aid,public=True)

    def asset(self,aid,public=False):
        validate_id(aid)
        with self._connect() as db:r=db.execute('SELECT * FROM local_assets WHERE id=?',(aid,)).fetchone()
        if not r:raise KeyError(aid)
        path=(self.workspace/r['path']).resolve(strict=True)
        if not path.is_relative_to(self.assets_dir.resolve()) or not path.is_relative_to(self.workspace) or not path.is_file():raise ValidationError('附件位置失效')
        result={'id':r['id'],'name':r['name'],'mime':r['mime'],'size':r['size'],'url':'/api/assets/'+quote(aid)}
        if not public:result['path']=str(path)
        return result
