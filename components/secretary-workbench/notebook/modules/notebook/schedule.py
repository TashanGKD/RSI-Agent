"""Notebook-owned dated occurrences; no collector, network, UI or timer dependency.
Old objects and changes stay intact. Each schedule occurrence has its own version
and append-only before/after events; never project a later day onto an earlier one.
"""
import hashlib
import json
import re
import uuid
from datetime import date as Date, datetime
from contracts import DOMAINS, STATES, TIMEZONE, actor, day, state, text, today
from .legacy_store import ValidationError, ConflictError, validate_id, stamp

GROUPS=('待办','等对方','暂缓','其他','已完成','不用管了')
LABELS={'待办':'未完成','等对方':'等对方','暂缓':'已暂缓','其他':'其他','已完成':'已完成','不用管了':'无需处理'}

def clock(value):
    if value in (None,''):return None
    if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):raise ValidationError('时刻须为北京时间HH:mm')
    return value

def interval(start,end):
    start,end=clock(start),clock(end)
    if end and (not start or end<=start):raise ValidationError('结束须晚于开始；跨日请分别安排')
    return start,end

def window(value,plan):
    if value is None:return None
    if not isinstance(value,dict) or set(value)-{'start','end','timezone'} or value.get('timezone',TIMEZONE)!=TIMEZONE:raise ValidationError('日程区间无效')
    start=value.get('start');end=value.get('end')
    def parse(v):
        if not isinstance(v,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::00)?\+08:00',v):raise ValidationError('日程区间须带北京时间偏移')
        try:d=datetime.fromisoformat(v)
        except ValueError:raise ValidationError('日程时刻无效') from None
        return d
    d=parse(start);e=parse(end) if end else None
    if (plan and d.date().isoformat()!=plan) or (e and (e.date()!=d.date() or e<=d)):raise ValidationError('日程区间须在计划当天且结束晚于开始')
    return {'start':d.isoformat(),'end':e.isoformat() if e else None,'timezone':TIMEZONE}

def make_window(date,start,end):
    return {'start':f'{date}T{start}:00+08:00','end':f'{date}T{end}:00+08:00' if end else None,'timezone':TIMEZONE} if start else None

def _json(v):return json.dumps(v,ensure_ascii=False,separators=(',',':'))

def _entry_id(rid,date):return 'SCH-'+hashlib.sha256((rid+'|'+date).encode()).hexdigest()[:32]

class ScheduleMixin:
    def _init_schedule(self):
        with self._connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS schedule_entries(
              id TEXT PRIMARY KEY,object_id TEXT NOT NULL,date TEXT NOT NULL,
              start_time TEXT,end_time TEXT,state TEXT NOT NULL,revision INTEGER NOT NULL,
              assignee TEXT NOT NULL,domain TEXT NOT NULL,payload TEXT NOT NULL,
              UNIQUE(object_id,date));
            CREATE INDEX IF NOT EXISTS schedule_date_owner ON schedule_entries(date,assignee,domain,state);
            CREATE TABLE IF NOT EXISTS schedule_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id TEXT UNIQUE NOT NULL,entry_id TEXT NOT NULL,at TEXT NOT NULL,actor TEXT NOT NULL,
              before_value TEXT NOT NULL,after_value TEXT NOT NULL,note TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS schedule_event_entry ON schedule_events(entry_id,seq);
            CREATE TABLE IF NOT EXISTS schedule_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')
        if self.db_file.with_name(self.db_file.name+'.online.json').exists():return
        with self._connect() as db:
            if db.execute("SELECT 1 FROM schedule_meta WHERE key='import_v1'").fetchone():return
        tasks=self.list_tasks()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM schedule_meta WHERE key='import_v1'").fetchone():return
            at=stamp();count=0
            for t in tasks:
                if t.get('kind')=='action' and t.get('active',True) and t.get('planDate'):
                    e=self._entry_from_task(t,t['planDate']);e['importedAt']=at
                    if not self._entry(db,e['id'],required=False):self._put_entry(db,e,{'name':'迁移','kind':'ai'},'从现有明确计划导入；此前每日状态未知');count+=1
            db.execute('INSERT INTO schedule_meta VALUES(?,?)',('import_v1',_json({'version':1,'at':at,'count':count,'coverage':'此前每日状态未知；原事项历史保留'})))

    def _entry_from_task(self,t,date):
        w=t.get('eventWindow') or {};start=end=None
        if w.get('start') and w['start'][:10]==date:
            start=w['start'][11:16];end=w.get('end')[11:16] if w.get('end') else None
        return dict(id=_entry_id(t['id'],date),objectId=t['id'],date=date,startTime=start,endTime=end,
            state=t['state'],revision=0,title=t['title'],summary=t.get('summary',''),domain=t.get('domain',''),assignee=t.get('assignee',''),
            previousEntryId=None,nextEntryId=None,createdAt=stamp(),updatedAt=stamp(),definitionId=t['id'] if t.get('recurrence') else None,occurrenceKey=date if t.get('recurrence') else None)

    def _entry(self,db,eid,required=True):
        validate_id(eid);r=db.execute('SELECT payload FROM schedule_entries WHERE id=?',(eid,)).fetchone()
        if not r and required:raise KeyError(eid)
        return json.loads(r[0]) if r else None

    def _put_entry(self,db,e,a,note='',before=None):
        before=self._entry(db,e['id'],required=False) if before is None else before
        e=dict(e,revision=(before['revision'] if before else 0)+1,updatedAt=stamp())
        db.execute('INSERT INTO schedule_entries VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
            'date=excluded.date,start_time=excluded.start_time,end_time=excluded.end_time,state=excluded.state,'
            'revision=excluded.revision,assignee=excluded.assignee,domain=excluded.domain,payload=excluded.payload',
            (e['id'],e['objectId'],e['date'],e.get('startTime'),e.get('endTime'),e['state'],e['revision'],e['assignee'],e['domain'],_json(e)))
        event_id='SEV-'+uuid.uuid4().hex
        db.execute('INSERT INTO schedule_events(event_id,entry_id,at,actor,before_value,after_value,note) VALUES(?,?,?,?,?,?,?)',
            (event_id,e['id'],e['updatedAt'],_json(a),_json(before),_json(e),note or ''))
        self._audit(db,'schedule',e['id'],before,e)
        self._link_operation(db,'schedule_events',event_id)
        return e

    def _sync_schedule(self,db,t,previous,a,note='',explicit=None):
        """Compatibility write adapter: only this object's current planned occurrence."""
        if t.get('kind')!='action' or not t.get('active',True):return
        if t.get('recurrence'):
            for row in db.execute('SELECT payload FROM schedule_entries WHERE object_id=? AND date>=?',(t['id'],today())).fetchall():
                entry=json.loads(row[0])
                if not entry.get('definitionId'):
                    self._put_entry(db,dict(entry,definitionId=t['id'],occurrenceKey=entry['date']),a,'关联循环定义；原安排与历史保留')
            return
        if previous.get('recurrence') and not t.get('recurrence'):
            for row in db.execute('SELECT payload FROM schedule_entries WHERE object_id=? AND date>=?',(t['id'],today())).fetchall():
                entry=json.loads(row[0])
                if entry.get('definitionId'):self._put_entry(db,dict(entry,definitionId=None,occurrenceKey=None),a,'取消后续循环关联；历史保留')
        plan=t.get('planDate');old_plan=previous.get('planDate') if previous else None
        prior=self._entry(db,_entry_id(t['id'],old_plan),required=False) if old_plan else None
        if prior and old_plan!=plan and prior['state'] not in ('已完成','不用管了'):
            moved=dict(prior,state='暂缓' if plan else '不用管了',nextEntryId=_entry_id(t['id'],plan) if plan else None)
            self._put_entry(db,moved,a,'计划改期' if plan else '撤销本次安排')
        if not plan:return
        candidate=self._entry_from_task(t,plan)
        if t['state']=='暂缓' and plan>today():candidate['state']='待办'
        existing=self._entry(db,candidate['id'],required=False)
        if existing:
            updated=dict(existing,**{k:candidate[k] for k in ('title','summary','domain','assignee','state','startTime','endTime')})
            explicit=explicit if explicit is not None else {k for k in t if t.get(k)!=previous.get(k)}
            if 'state' not in explicit and old_plan==plan:updated['state']=existing['state']
            if not ({'eventWindow','planDate'} & explicit) and old_plan==plan:
                updated['startTime']=existing.get('startTime');updated['endTime']=existing.get('endTime')
            # An unchanged object note must not create a fake schedule-state change.
            if updated==existing:return
        else:updated=candidate
        if prior and old_plan!=plan:updated['previousEntryId']=prior['id']
        self._put_entry(db,updated,a,note)

    def get_schedule(self,eid):
        with self._connect() as db:
            e=self._entry(db,eid);t=self._current(e['objectId'],db);e['lastOperationId']=t.get('lastOperationId');e['lastSequence']=t.get('lastSequence');e['objectRevision']=t['revision'];e['followup']=t.get('followup');e['warnings']=['计划晚于明确截止 '+t['deadlineDate']] if t.get('deadlineDate') and e['date']>t['deadlineDate'] and e['state'] not in ('已完成','不用管了') else [];e.setdefault('summary',t.get('summary',''));return e

    def schedule_history(self,eid):
        with self._connect() as db:
            self._entry(db,eid)
            return [dict(id=r['event_id'],sequence=r['seq'],at=r['at'],actor=json.loads(r['actor']),
                before=json.loads(r['before_value']),after=json.loads(r['after_value']),note=r['note'])
                for r in db.execute('SELECT * FROM schedule_events WHERE entry_id=? ORDER BY seq DESC',(eid,))]

    def query_schedule(self,start,end,assignee='我',domain=''):
        start,end=day(start),day(end)
        if not start or not end or not 0<=(Date.fromisoformat(end)-Date.fromisoformat(start)).days<42:raise ValidationError('查询日期范围须为1至42天')
        text(assignee,'负责人筛选',120,empty=True)
        if domain and domain not in DOMAINS:raise ValidationError('领域无效')
        with self._connect() as db:
            tasks={t['id']:t for t in self.list_tasks()}
            entries=[];overdue=[]
            for row in db.execute('SELECT payload FROM schedule_entries WHERE date<=? ORDER BY date,id',(end,)):
                e=json.loads(row[0]);t=tasks.get(e['objectId'])
                if not t or not t.get('active',True):continue
                if assignee and assignee!='全部' and e['assignee']!=assignee:continue
                if domain and e['domain']!=domain:continue
                e['lastOperationId']=t.get('lastOperationId');e['lastSequence']=t.get('lastSequence');e['objectRevision']=t['revision'];e['followup']=t.get('followup');e['warnings']=['计划晚于明确截止 '+t['deadlineDate']] if t.get('deadlineDate') and e['date']>t['deadlineDate'] and e['state'] not in ('已完成','不用管了') else [];e.setdefault('summary',t.get('summary',''))
                if start<=e['date']<=end:entries.append(e)
                elif start<=today()<=end and e['date']<today() and e['state']=='待办':
                    newer=db.execute("SELECT 1 FROM schedule_entries WHERE object_id=? AND date>? LIMIT 1",(e['objectId'],e['date'])).fetchone()
                    if not newer and (e.get('definitionId') or t['state']=='待办'):overdue.append(e)
            unscheduled=[]
            if start<=today()<=end:
                for t in tasks.values():
                    if not(t.get('active',True) and t['kind']=='action' and t['state']=='待办' and not t.get('planDate') and not t.get('planDateExplicit') and not t.get('needsReview') and (t.get('legacy') or t.get('importedLegacyPlanning'))):continue
                    if t.get('reviewDate') and t['reviewDate']>today():continue
                    if assignee and assignee!='全部' and t.get('assignee')!=assignee:continue
                    if domain and t.get('domain')!=domain:continue
                    if db.execute('SELECT 1 FROM schedule_entries WHERE object_id=?',(t['id'],)).fetchone():continue
                    unscheduled.append(t)
            def sort_key(e):return (e['date'],GROUPS.index(e['state']),DOMAINS.index(e['domain']) if e['domain'] in DOMAINS else len(DOMAINS),e.get('startTime') or '99:99',e['createdAt'],e['id'])
            entries.sort(key=sort_key);overdue.sort(key=sort_key)
            receipt=db.execute("SELECT value FROM schedule_meta WHERE key='import_v1'").fetchone()
        groups=[{'state':s,'label':LABELS[s],'entries':[e for e in entries if e['state']==s]} for s in GROUPS]
        conflicts=[]
        for i,left in enumerate(entries):
            if not left.get('startTime') or not left.get('endTime') or left['state'] in ('已完成','不用管了','暂缓'):continue
            for right in entries[i+1:]:
                if right['date']!=left['date'] or right['assignee']!=left['assignee'] or right['state'] in ('已完成','不用管了','暂缓') or not right.get('startTime') or not right.get('endTime'):continue
                if max(left['startTime'],right['startTime'])<min(left['endTime'],right['endTime']):conflicts.append(dict(entryIds=[left['id'],right['id']],date=left['date'],kind='known_time_overlap'))
        return dict(conflicts=conflicts,entries=entries,groups=groups,overdue=overdue,unscheduled=unscheduled,timezone=TIMEZONE,
            range={'start':start,'end':end},coverage=json.loads(receipt[0]) if receipt else None)

    def create_schedule(self,body):
        self._assert_writable()
        if not isinstance(body,dict) or set(body)-{'objectId','date','startTime','endTime','expectedObjectRevision','actor','requestId','note'}:raise ValidationError('安排字段无效')
        rid=validate_id(body.get('objectId'));date=day(body.get('date'))
        if not date:raise ValidationError('请选择安排日期')
        start,end=interval(body.get('startTime'),body.get('endTime'));a=actor(body.get('actor'))
        note=text(body.get('note',''),'备注',12000,empty=True);v=body.get('expectedObjectRevision')
        if type(v) is not int or v<0:raise ValidationError('缺少事项版本')
        key=body.get('requestId');canon=self._canonical('schedule-create',rid,body)
        with self._transaction(a,key) as db:
            r=self._retry(db,key,canon)
            if r:
                result=self._entry(db,r['result_id']);t=self._current(result['objectId'],db);result['lastOperationId']=t.get('lastOperationId');result['objectRevision']=t['revision'];result['followup']=t.get('followup');result.setdefault('summary',t.get('summary',''));return result
            t=self._current(rid,db)
            if t['revision']!=v:raise ConflictError('事项已变化，请核对最新内容')
            if t['kind']!='action':raise ValidationError('请先将其明确为事项再安排')
            if t.get('recurrence'):
                from .recurrence import includes
                if not includes(t['recurrence'],date):raise ValidationError('日期不在启用的循环定义范围内')
                if 'startTime' not in body:start=t['recurrence'].get('startTime')
                if 'endTime' not in body:end=t['recurrence'].get('endTime')
                start,end=interval(start,end)
            eid=_entry_id(rid,date)
            if self._entry(db,eid,required=False):raise ConflictError('当天已有这件事的安排，请编辑原次')
            patch={'planDate':date,'eventWindow':make_window(date,start,end),'state':'待办','updatedAt':stamp(),'updatedBy':a}
            if t.get('recurrence'):
                patch={'updatedAt':stamp(),'updatedBy':a}
                entry=self._entry_from_task(t,date);entry.update(state='待办',startTime=start,endTime=end)
                self._put_entry(db,entry,a,note)
            self._append(db,rid,a,patch,note,[],{k:t.get(k) for k in patch})
            self._sync_schedule(db,dict(t,**patch),t,a,note)
            self._remember(db,key,canon,'schedule',eid)
        return self.get_schedule(eid)

    def schedule_record(self,eid,body):
        self._assert_writable();validate_id(eid)
        if not isinstance(body,dict) or set(body)-{'expectedRevision','expectedObjectRevision','state','startTime','endTime','postponeTo','followup','note','requestId','actor'}:raise ValidationError('安排操作字段无效')
        a=actor(body.get('actor'));v=body.get('expectedRevision');ov=body.get('expectedObjectRevision')
        if type(v) is not int or v<0 or type(ov) is not int or ov<0:raise ValidationError('缺少有效安排与事项版本')
        st=state(body['state']) if 'state' in body else None
        note=text(body['note'],'备注',12000,empty=True) if 'note' in body else None
        if not any(k in body for k in ('state','startTime','endTime','postponeTo','followup','note')):raise ValidationError('没有要保存的变更')
        from .reviews import followup
        f=followup(body['followup']) if 'followup' in body else None
        target=body.get('postponeTo')
        if target is not None:
            if not isinstance(target,dict) or set(target)-{'date','startTime','endTime'}:raise ValidationError('暂缓安排字段无效')
            date=day(target.get('date'))
            if not date:raise ValidationError('请选择暂缓日期')
            ts,te=interval(target.get('startTime'),target.get('endTime'))
            if st!='暂缓':raise ValidationError('暂缓日期必须与暂缓状态同时提交')
        key=body.get('requestId');canon=self._canonical('schedule-record',eid,body)
        with self._transaction(a,key) as db:
            retry=self._retry(db,key,canon)
            if retry:
                result=self._entry(db,eid);t=self._current(result['objectId'],db);result['lastOperationId']=t.get('lastOperationId');result['objectRevision']=t['revision'];result['followup']=t.get('followup');result.setdefault('summary',t.get('summary',''));return result
            e=self._entry(db,eid);t=self._current(e['objectId'],db)
            if e['revision']!=v or t['revision']!=ov:raise ConflictError('事项或本次安排已变化，草稿保留，请核对后重试')
            start,end=interval(body.get('startTime',e.get('startTime')),body.get('endTime',e.get('endTime')))
            updated=dict(e,startTime=start,endTime=end,state=st or e['state'])
            patch={};future=db.execute('SELECT 1 FROM schedule_entries WHERE object_id=? AND date>? LIMIT 1',(e['objectId'],e['date'])).fetchone()
            if target:
                if future:raise ConflictError('已有后续安排，请改最新一次安排；历史更正不能覆盖后续计划')
                if date<=e['date'] or date<today():raise ValidationError('暂缓日期须晚于本次且不早于今天')
                next_id=_entry_id(e['objectId'],date);existing=self._entry(db,next_id,required=False)
                if existing and existing['state'] in ('已完成','不用管了'):raise ConflictError('目标日期安排已闭环，请另选日期')
                ne=existing or self._entry_from_task(t,date)
                ne=dict(ne,state='待办',startTime=ts,endTime=te,previousEntryId=eid)
                updated['nextEntryId']=next_id;self._put_entry(db,ne,a,note or '')
                if not e.get('definitionId') and not t.get('recurrence'):patch.update(state='暂缓',planDate=date,eventWindow=make_window(date,ts,te))
            elif not future and not e.get('definitionId') and not t.get('recurrence'):
                if st:patch['state']=st
                if 'startTime' in body or 'endTime' in body:patch['eventWindow']=make_window(e['date'],start,end)
                if st in ('已完成','不用管了'):patch.update(needsReview=False,reviewDate=None,followup=None)
            if 'followup' in body:
                if e.get('definitionId'):raise ValidationError('循环实例复看请新增明确备忘；不能覆盖整个定义的复看')
                patch.update(followup=f,reviewDate=(f or {}).get('date'),followupSetAt=stamp())
            if updated!=e or note is not None:self._put_entry(db,updated,a,note or '')
            # Notes are the same shared notebook information, not a second progress log.
            patch.update(updatedAt=stamp(),updatedBy=a)
            self._append(db,t['id'],a,patch,note,[],{k:t.get(k) for k in patch})
            self._remember(db,key,canon,'schedule',eid)
        return self.get_schedule(eid)
