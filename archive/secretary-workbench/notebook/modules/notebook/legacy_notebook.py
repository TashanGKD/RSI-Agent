"""Additive shared notebook operations over the immutable legacy decision history."""
import json
import uuid
import re
from datetime import datetime, timezone
from .legacy_store import Store, STATES as LEGACY_STATES, BLOCKED_SOURCE_SUFFIXES, ValidationError, ConflictError, validate_id, stamp, utcnow
from pathlib import Path

STATES = ['待判断', '待办', '等对方', '暂缓', '已完成', '不用管了']
CLOSED = {'已完成', '不用管了'}
ROUND_FIELDS = {'kind','completionCriterion','recommendation','reviewRound','sourceContacts','proposedAt'}


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def mapped(state):
    return {'交给AI处理':'待办','稍后提醒':'待办','待处理':'待办','进行中':'待办','已结束':'不用管了'}.get(state,state)


class Notebook(Store):
    def __init__(self, db_file, source_file):
        super().__init__(db_file, source_file)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS local_items (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notebook_events (
                    seq INTEGER PRIMARY KEY, id TEXT NOT NULL, at TEXT NOT NULL, actor TEXT NOT NULL,
                    payload TEXT NOT NULL, request_id TEXT UNIQUE, canonical TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS notebook_task ON notebook_events(id, seq);
            ''')

    def _find(self, db, rid):
        row = db.execute(self.SELECT + ' WHERE t.id=?', (rid,)).fetchone()
        if row is not None:
            return row, False
        row = db.execute('SELECT * FROM local_items WHERE id=?', (rid,)).fetchone()
        if row is None:
            raise KeyError(rid)
        return row, True

    def _events(self, db, rid, row, local):
        events = []
        if not local:
            history = list(db.execute('SELECT * FROM history WHERE id=? ORDER BY seq', (rid,)))
            for h in history:
                payload = dict(state=h['state'], note=h['note'], reminder=json.loads(h['reminder']) if h['reminder'] else None)
                # Legacy responsibility was encoded in the state itself.
                payload['assignee'] = 'AI' if h['state'] == '交给AI处理' else '我'
                events.append((h['at'], 0, h['seq'], payload, {'name':'我','kind':'human'}))
            if row['confirmed_at'] and not any(h['at'] == row['confirmed_at'] for h in history):
                reminder = None
                if row['reminder_at']:
                    reminder = dict(kind=row['reminder_kind'], at=row['reminder_at'], timezone=row['reminder_timezone'], firedAt=row['fired_at'])
                events.append((row['confirmed_at'],0,0,dict(state=row['state'],note=row['note'],reminder=reminder,
                               assignee='AI' if row['state']=='交给AI处理' else '我'), {'name':'我','kind':'human'}))
            for p in db.execute('SELECT rowid,payload FROM progress_updates WHERE id=? ORDER BY rowid', (rid,)):
                event = json.loads(p['payload'])
                if 'state' in event:
                    change = dict(state=event['state'])
                    if event['state']=='交给AI处理':
                        change['assignee']='AI'
                    events.append((event['at'],1,p['rowid'],change,{'name':'AI','kind':'ai'}))
        for e in db.execute('SELECT * FROM notebook_events WHERE id=? ORDER BY seq', (rid,)):
            events.append((e['at'],2,e['seq'],json.loads(e['payload']),json.loads(e['actor'])))
        events.sort(key=lambda e:(instant(e[0]), e[1], e[2]))
        return events

    def _compose(self, db, row, local):
        raw = json.loads(row['payload'])
        if local:
            task = dict(raw, active=True, sourceChanged=False, confirmed=False, confirmedAt=None,
                        progressCount=0,lastProgressAt=None,revision=row['revision'])
        else:
            task = super()._task(row)
        task.pop('evidence',None); task.pop('links',None); task.pop('progressUpdates',None)
        task['selectedState'] = mapped(raw['suggestedState'])
        task['assignee'] = 'AI' if raw['suggestedState']=='交给AI处理' else '我'
        task['note'] = ''
        task['reminder'] = None
        task['stateUpdatedBy'] = None
        task['stateUpdatedAt'] = None
        task['reviewedByHuman'] = False
        task['lastHumanReviewAt'] = None
        task.setdefault('kind','action')
        task.setdefault('reviewRound',None)
        task.setdefault('recommendation',None)
        task.setdefault('completionCriterion','')
        task.setdefault('sourceContacts',[])
        for at, _, _, change, actor in self._events(db,raw['id'],row,local):
            if 'reviewRound' in change and change['reviewRound'] != task.get('reviewRound'):
                task['reviewedByHuman'] = False
            for field in ('title','counterparty','timeRequirement','relatedRecordIds',*ROUND_FIELDS):
                if field in change:
                    task[field] = change[field]
            if actor['kind']=='human' and 'kind' in change:
                task['reviewedByHuman']=True
                task['lastHumanReviewAt']=at
            if 'proposedAt' in change:
                task['proposedDisplayAt']=change['proposedAt'][:10]
            if 'counterparty' in change:
                task['people'] = list(dict.fromkeys(x.strip() for x in re.split(r'[／/、，]',change['counterparty']) if x.strip()))
            if 'timeRequirement' in change:
                task['deadlineDate'] = self.normalized(dict(recordId=raw['id'],timeRequirement=change['timeRequirement'],proposedAt=task.get('proposedAt')))['deadlineDate']
            if 'summary' in change:
                task['lastKnownState'] = change['summary']
                task['lastKnownStateSourceTime'] = change.get('sourceTime')
                task['lastKnownStateUpdatedAt'] = at
                task['lastKnownStateUpdatedBy'] = actor['name']
            if 'state' in change:
                task['selectedState'] = mapped(change['state'])
                task['stateUpdatedAt'] = at
                task['stateUpdatedBy'] = actor['name']
                task['confirmed'] = True
                if actor['kind'] == 'human':
                    task['reviewedByHuman'] = True
                    task['lastHumanReviewAt']=at
            if 'assignee' in change:
                task['assignee'] = change['assignee']
            if 'note' in change:
                task['note'] = change['note']
            if 'reminder' in change:
                task['reminder'] = change['reminder']
            if task['selectedState'] in CLOSED:
                task['reminder'] = None
        if not local and task['reminder'] and row['fired_at'] and row['reminder_at']==task['reminder']['at']:
            task['reminder'] = dict(task['reminder'], firedAt=row['fired_at'])
        due_pause=task['selectedState']=='暂缓' and task.get('reminder') and instant(task['reminder']['at'])<=utcnow() and (not task['lastHumanReviewAt'] or instant(task['lastHumanReviewAt'])<instant(task['reminder']['at']))
        task['needsReview'] = bool((not task['reviewedByHuman'] or due_pause) and task['selectedState'] not in CLOSED)
        task.setdefault('relatedRecordIds', [])
        counts=db.execute('SELECT count(*),max(at) FROM notebook_events WHERE id=?',(raw['id'],)).fetchone()
        task['progressCount'] += counts[0]
        if counts[1] and (not task['lastProgressAt'] or instant(counts[1])>instant(task['lastProgressAt'])):
            task['lastProgressAt']=counts[1]
        return task

    def meta(self):
        meta=super().meta()
        with self.connect() as db:
            row=db.execute("SELECT value FROM metadata WHERE key='notebook_coverage'").fetchone()
            if row:
                extra=json.loads(row['value'])
                meta.update({k:v for k,v in extra.items() if k in {'asOf','scope','coverageText','purpose'}})
            meta['count']=db.execute('SELECT (SELECT count(*) FROM tasks WHERE active=1)+(SELECT count(*) FROM local_items)').fetchone()[0]
        return meta

    def _task(self, row):
        with self.connect() as db:
            return self._compose(db,row,False)

    def tasks(self):
        with self.connect() as db:
            result = [self._compose(db,r,False) for r in db.execute(self.SELECT+' ORDER BY t.position,t.id')]
            result.extend(self._compose(db,r,True) for r in db.execute('SELECT * FROM local_items ORDER BY created_at,id'))
            return result

    def task(self, rid):
        validate_id(rid)
        with self.connect() as db:
            row,local = self._find(db,rid)
            return self._compose(db,row,local)

    def _source_links(self, db, rid, raw):
        links = super()._source_links(db,rid,raw)
        for row in db.execute('SELECT payload FROM notebook_events WHERE id=? ORDER BY seq',(rid,)):
            for source in json.loads(row['payload']).get('sources',[]):
                if source.get('path') and not any(link['path']==source['path'] for link in links):
                    links.append(dict(label=source['label'],path=source['path']))
        return links

    def source(self,rid,index):
        validate_id(rid)
        with self.connect() as db:
            row,_=self._find(db,rid)
            raw=json.loads(row['payload'])
            raw.setdefault('links',[])
            links=self._source_links(db,rid,raw)
        if type(index) is not int or index<0 or index>=len(links):
            raise KeyError('source')
        path=self.safe_path(links[index]['path'])
        if path is None or path.suffix.lower() in BLOCKED_SOURCE_SUFFIXES:
            raise KeyError('source')
        return path

    def detail(self, rid):
        validate_id(rid)
        with self.connect() as db:
            row,local = self._find(db,rid)
            events = list(db.execute('SELECT * FROM notebook_events WHERE id=? ORDER BY seq', (rid,)))
            raw=json.loads(row['payload']);raw.setdefault('links',[])
            links=self._source_links(db,rid,raw)
        detail = dict(task=self.task(rid), evidence=[], relatedTasks=[],sourceLinks=[],history=[],timeline=[]) if local else super().detail(rid)
        for e in events:
            change = json.loads(e['payload'])
            actor = json.loads(e['actor'])
            sources=[]
            for source in change.pop('sources',[]):
                source=dict(source)
                path=source.pop('path',None)
                if path:
                    index=next(i for i,link in enumerate(links) if link['path']==path)
                    source['url']='/api/tasks/'+rid+'/sources/'+str(index)
                sources.append(source)
            source_time=change.pop('sourceTime',None)
            detail['timeline'].append(dict(change,id='notebook-'+str(e['seq']),at=e['at'],actor=actor,
                author=actor['name'],body=change.get('note',''),sourceTime=source_time,suggestedState=None,sources=sources,requestId=e['request_id']))
        detail['sourceLinks']=[dict(label=link['label'],url='/api/tasks/'+rid+'/sources/'+str(i)) for i,link in enumerate(links)]
        for event in detail['timeline']:
            event.setdefault('actor',dict(name=event.get('author','我'),kind='ai' if event.get('author')=='AI' else 'human'))
        detail['timeline'].sort(key=lambda e:instant(e['at']),reverse=True)
        related = set(detail['task'].get('relatedRecordIds',[]))
        all_tasks = self.tasks()
        related.update(t['id'] for t in all_tasks if rid in t.get('relatedRecordIds',[]))
        detail['relatedTasks'] = [{k:t[k] for k in ('id','title','selectedState','assignee','active')} for t in all_tasks if t['id'] in related]
        return detail

    @staticmethod
    def _text(value, field, limit, empty=False):
        if not isinstance(value,str) or len(value)>limit or '\x00' in value or (not empty and not value.strip()):
            raise ValidationError(field+'无效或超过长度上限')
        return value.strip() if field != '备注' else value

    def _validate_common(self, obj):
        actor = obj.get('actor', {'name':'我','kind':'human'})
        if not isinstance(actor,dict) or set(actor)!={'name','kind'} or actor['kind'] not in ('human','ai'):
            raise ValidationError('操作者字段无效')
        actor = dict(name=self._text(actor['name'],'操作者',120),kind=actor['kind'])
        request_id = obj.get('requestId')
        if 'requestId' in obj:
            validate_id(request_id)
        changes = {}
        for field,label,limit in [('title','事项名称',1000),('counterparty','对象',500),
                                  ('timeRequirement','期限',1000),('summary','当前进展',4000),
                                  ('completionCriterion','闭环结果',2000),('reviewRound','整理轮次',120)]:
            if field in obj:
                changes[field]=self._text(obj[field],label,limit)
        if 'kind' in obj:
            if obj['kind'] not in ('action','project','goal','memo'):
                raise ValidationError('事项分类无效')
            changes['kind']=obj['kind']
        if 'recommendation' in obj:
            r=obj['recommendation']
            if not isinstance(r,dict) or set(r)!={'state','reason'} or not isinstance(r['state'],str) or mapped(r['state']) not in STATES:
                raise ValidationError('推荐状态无效')
            changes['recommendation']=dict(state=mapped(r['state']),reason=self._text(r['reason'],'推荐依据',4000))
        if 'sourceContacts' in obj:
            contacts=obj['sourceContacts']
            fields={'channel','conversationName','senderName','replyToName','at','conversationId','messageId'}
            if not isinstance(contacts,list) or len(contacts)>50:
                raise ValidationError('来源联系人无效')
            cleaned=[]
            for c in contacts:
                if not isinstance(c,dict) or set(c)-fields or not c.get('channel'):
                    raise ValidationError('来源联系人字段无效')
                clean={k:self._text(v,'来源联系人',500,empty=True) for k,v in c.items()}
                if clean.get('at'):
                    try:
                        d=datetime.fromisoformat(clean['at'].replace('Z','+00:00'))
                        if d.tzinfo is None and len(clean['at'])!=10: raise ValueError()
                    except (ValueError,OverflowError): raise ValidationError('来源时间无效')
                cleaned.append(clean)
            changes['sourceContacts']=cleaned
        if 'proposedAt' in obj:
            v=obj['proposedAt']
            try:
                if not isinstance(v,str) or len(v)>60: raise ValueError()
                d=datetime.fromisoformat(v.replace('Z','+00:00'))
                if d.tzinfo is None and len(v)!=10: raise ValueError()
            except (ValueError,OverflowError): raise ValidationError('提出时间无效')
            changes['proposedAt']=v
        if 'relatedRecordIds' in obj:
            related=obj['relatedRecordIds']
            if not isinstance(related,list) or len(related)>100:
                raise ValidationError('关联事项无效')
            related=[validate_id(r) for r in related]
            if len(set(related))!=len(related):
                raise ValidationError('关联事项不能重复')
            changes['relatedRecordIds']=related
        for field in ['state','assignee','note']:
            if field not in obj:
                continue
            value = obj[field]
            if field=='state':
                if not isinstance(value,str) or mapped(value) not in STATES:
                    raise ValidationError('处理选项无效')
                changes[field] = mapped(value)
            else:
                changes[field] = self._text(value,'备注' if field=='note' else '负责人',4000 if field=='note' else 120)
        if 'sourceTime' in obj:
            value=obj['sourceTime']
            if not isinstance(value,str) or len(value)>60:
                raise ValidationError('原信息时间无效')
            try:
                when=datetime.fromisoformat(value.replace('Z','+00:00'))
                if when.tzinfo is None and len(value)!=10:
                    raise ValueError('timezone required')
            except (ValueError,OverflowError):
                raise ValidationError('原信息时间无效')
            changes['sourceTime']=value
        if 'sources' in obj:
            sources=obj['sources']
            if not isinstance(sources,list) or len(sources)>100:
                raise ValidationError('依据结构无效')
            cleaned=[]
            for source in sources:
                if not isinstance(source,dict) or set(source)-{'label','quote','path'}:
                    raise ValidationError('依据字段无效')
                label=self._text(source.get('label'),'依据标题',500)
                quote=self._text(source.get('quote',''),'依据引文',32000,empty=True)
                clean=dict(label=label,quote=quote)
                if 'path' in source:
                    value=self._text(source['path'],'依据路径',4096)
                    path=Path(value)
                    resolved=self.safe_path(path if path.is_absolute() else self.root/path)
                    if resolved is None or resolved.suffix.lower() in BLOCKED_SOURCE_SUFFIXES:
                        raise ValidationError('依据必须是资料目录内的安全文件')
                    clean['path']=str(resolved)
                elif not quote.strip():
                    raise ValidationError('无依据文件时需提供引文')
                cleaned.append(clean)
            changes['sources']=cleaned
        return actor, request_id, changes

    @staticmethod
    def _canonical(operation,rid,obj,actor):
        canonical = dict(obj)
        canonical.pop('requestId',None)
        canonical['actor']=actor
        return json.dumps([operation,rid,canonical],sort_keys=True,ensure_ascii=False,separators=(',',':'))

    def _retry(self, db, request_id, canonical):
        if request_id is None:
            return None
        old = db.execute('SELECT id,canonical FROM notebook_events WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old['canonical'] != canonical:
                raise ConflictError('请求编号已用于不同内容，请核对后重新提交')
            row,local = self._find(db,old['id'])
            return self._compose(db,row,local)
        return None

    @staticmethod
    def _append(db,rid,when,actor,changes,request_id,canonical):
        db.execute('INSERT INTO notebook_events(id,at,actor,payload,request_id,canonical) VALUES(?,?,?,?,?,?)',
            (rid,when,json.dumps(actor,ensure_ascii=False),json.dumps(changes,ensure_ascii=False),request_id,canonical))

    def create_task(self,obj):
        allowed={'title','counterparty','proposedAt','timeRequirement','summary','state','assignee','note','relatedRecordIds','requestId','actor','sourceTime','sources'} | ROUND_FIELDS
        if not isinstance(obj,dict) or 'title' not in obj or set(obj)-allowed:
            raise ValidationError('新增事项字段无效')
        actor,request_id,changes = self._validate_common(obj)
        title=self._text(obj['title'],'事项名称',1000)
        party=self._text(obj.get('counterparty','为自己'),'对象',500)
        requirement=self._text(obj.get('timeRequirement','时间待定'),'期限',1000)
        proposed=obj.get('proposedAt')
        if proposed is not None:
            if not isinstance(proposed,str) or len(proposed)>60:
                raise ValidationError('提出时间无效')
            try:
                value=datetime.fromisoformat(proposed.replace('Z','+00:00'))
                # A calendar date is also an explicit original information time.
                if value.tzinfo is None and len(proposed)!=10:
                    raise ValueError('timezone required')
            except (ValueError,OverflowError):
                raise ValidationError('提出时间无效')
        related=obj.get('relatedRecordIds',[])
        if not isinstance(related,list) or len(related)>100:
            raise ValidationError('关联事项无效')
        related=[validate_id(r) for r in related]
        if len(set(related))!=len(related):
            raise ValidationError('关联事项不能重复')
        canonical=self._canonical('create',None,obj,actor)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            retry=self._retry(db,request_id,canonical)
            if retry is not None:
                return retry
            for rid in related:
                self._find(db,rid)
            rid='LOCAL-'+uuid.uuid4().hex
            when=stamp()
            raw=dict(id=rid,title=title,counterparty=party,people=[party],proposedAt=proposed or when,
                proposedDisplayAt=(proposed or when)[:10],timeRequirement=requirement,deadlineDate=None,
                sourceStatus='本地新增',lastKnownState='本地新增事项',suggestedState='待判断',category='本地新增',relatedRecordIds=related)
            import re
            deadline=re.match(r'^(\d{4})年(\d{1,2})月(\d{1,2})日',requirement)
            if deadline:
                from datetime import date
                try: raw['deadlineDate']=date(*map(int,deadline.groups())).isoformat()
                except ValueError: pass
            db.execute('INSERT INTO local_items(id,payload,created_at) VALUES(?,?,?)',(rid,json.dumps(raw,ensure_ascii=False),when))
            changes.setdefault('state','待判断');changes.setdefault('assignee','我')
            self._append(db,rid,when,actor,changes,request_id,canonical)
            row,local=self._find(db,rid)
            return self._compose(db,row,local)

    def record(self,rid,obj):
        validate_id(rid)
        allowed={'expectedRevision','requestId','actor','note','state','assignee','reminder','sourceTime','sources',
                 'title','counterparty','timeRequirement','summary','relatedRecordIds'} | ROUND_FIELDS
        if not isinstance(obj,dict) or 'expectedRevision' not in obj or set(obj)-allowed:
            raise ValidationError('记录字段无效')
        if type(obj['expectedRevision']) is not int or obj['expectedRevision']<0:
            raise ValidationError('事项版本无效')
        actor,request_id,changes=self._validate_common(obj)
        if not changes and 'reminder' not in obj:
            raise ValidationError('请填写备注或选择要更改的字段')
        canonical=self._canonical('record',rid,obj,actor)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            retry=self._retry(db,request_id,canonical)
            if retry is not None:
                return retry
            row,local=self._find(db,rid)
            task=self._compose(db,row,local)
            if task['revision']!=obj['expectedRevision']:
                raise ConflictError('这条事项已更新；请先核对最新记录再保存')
            if not task['active']:
                raise ValidationError('该事项已不在当前批次，可查看保留的历史记录')
            for related in changes.get('relatedRecordIds',[]):
                if related==rid:
                    raise ValidationError('关联事项不能指向自己')
                self._find(db,related)
            previous={}
            for field in ('title','counterparty','timeRequirement','summary','relatedRecordIds','state','assignee','reminder',*ROUND_FIELDS):
                if field in changes or field=='reminder' and 'reminder' in obj:
                    key={'summary':'lastKnownState','state':'selectedState'}.get(field,field)
                    previous[field]=task.get(key)
            if 'reminder' in obj:
                changes['reminder']=self.validate_reminder(obj['reminder'],task) if obj['reminder'] is not None else None
            if changes.get('state',task['selectedState']) in CLOSED:
                if changes.get('reminder') is not None:
                    raise ValidationError('已闭合事项不能启用提醒')
                if 'state' in changes and task['reminder']:
                    changes['reminder']=None
            when=stamp()
            if previous:
                changes['previous']=previous
            self._append(db,rid,when,actor,changes,request_id,canonical)
            table='local_items' if local else 'tasks'
            db.execute('UPDATE '+table+' SET revision=revision+1 WHERE id=?',(rid,))
            row,local=self._find(db,rid)
            return self._compose(db,row,local)

    def confirm(self,rid,obj):
        if not isinstance(obj,dict) or set(obj)!={'state','note','expectedRevision','reminder'}:
            raise ValidationError('提交字段不完整或包含未知字段')
        state=obj['state']
        if not isinstance(state,str) or state not in LEGACY_STATES:
            raise ValidationError('处理选项无效')
        self._text(obj['note'],'备注',4000,empty=True)
        change=dict(expectedRevision=obj['expectedRevision'],state=mapped(state))
        if obj['note'].strip(): change['note']=obj['note']
        if state=='交给AI处理': change['assignee']='AI'
        if state=='稍后提醒':
            if obj['reminder'] is None: raise ValidationError('请选择提醒时间')
            change['reminder']=obj['reminder']
        elif obj['reminder'] is not None:
            raise ValidationError('只有稍后提醒选项能提交提醒')
        return self.record(rid,change)

    def due_reminders(self):
        return [t for t in self.tasks() if t['active'] and t['selectedState'] not in CLOSED and t['reminder'] and
                not t['reminder'].get('firedAt') and instant(t['reminder']['at'])<=utcnow()]

    def ack_reminder(self,rid):
        validate_id(rid)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row,local=self._find(db,rid)
            task=self._compose(db,row,local)
            reminder=task['reminder']
            if not reminder or task['selectedState'] in CLOSED or instant(reminder['at'])>utcnow():
                raise ValidationError('提醒尚未到时')
            if not reminder.get('firedAt'):
                when=stamp()
                self._append(db,rid,when,{'name':'记事本','kind':'ai'},dict(reminder=dict(reminder,firedAt=when)),None,'reminder-ack')
                db.execute('UPDATE '+('local_items' if local else 'tasks')+' SET revision=revision+1 WHERE id=?',(rid,))
            row,local=self._find(db,rid)
            return self._compose(db,row,local)
