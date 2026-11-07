"""Authenticated HTTPS notebook adapter for an explicitly configured outbound device.

No cookie/password/Codex credentials are copied. Redirects are never followed,
remote errors never become log text, and attachment names never become paths.
"""
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from contracts.errors import ConflictError, ValidationError

MAX_JSON = 16 * 1024 * 1024
MAX_ASSET = 8 * 1024 * 1024
MAX_CACHE = 32 * 1024 * 1024
_IDENTIFIER = re.compile(r'^[\w.:-]{1,160}$', re.UNICODE)
AI_ACTOR = {'name':'AI秘书','kind':'ai'}


class RemoteNotebookError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _identifier(value):
    if not isinstance(value,str) or not _IDENTIFIER.fullmatch(value):
        raise ValidationError('编号格式无效')
    return urllib.parse.quote(value,safe='')


def validate_base_url(value, *, allow_loopback_http=False):
    if not isinstance(value,str) or len(value)>2048 or any(ord(c)<=32 for c in value):
        raise ValidationError('服务地址格式无效')
    try:
        parsed=urllib.parse.urlsplit(value)
        port=parsed.port
        valid=(parsed.scheme=='https' or (allow_loopback_http and parsed.scheme=='http'
               and parsed.hostname in {'127.0.0.1','localhost','::1'}))
        if (not valid or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ('','/') or '\\' in value):
            raise ValueError()
        if port is not None and not 1<=port<=65535:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError('服务地址必须是无认证参数的HTTPS站点根地址') from None
    return urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,'','',''))


def _encode(value):
    try:
        return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    except (TypeError,ValueError,RecursionError):
        raise ValidationError('JSON资料无效') from None


class HTTPNotebookPort:
    linked_record_revisions=True
    def __init__(self, base_url, device_token, workspace, *, allow_loopback_http=False, timeout=30):
        self.base_url=validate_base_url(base_url,allow_loopback_http=allow_loopback_http)
        self.origin=self.base_url
        if (not isinstance(device_token,str) or not 1<=len(device_token)<=4096
            or not device_token.isascii() or any(c.isspace() or ord(c)<33 for c in device_token)):
            raise ValidationError('设备凭据格式无效')
        self._device_token=device_token
        self.workspace=Path(workspace).expanduser().resolve()
        self.assets_dir=self.workspace/'notebook'/'attachments'
        if (self.workspace/'notebook').is_symlink() or self.assets_dir.is_symlink():
            raise ValidationError('附件缓存目录不能是链接')
        self.assets_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        if not self.assets_dir.resolve().is_relative_to(self.workspace):
            raise ValidationError('附件缓存目录越界')
        self._opener=urllib.request.build_opener(_NoRedirect())
        self._csrf=None
        self._asset_metadata={}
        self.timeout=min(max(int(timeout),1),30)
        self.before_write=None

    def __repr__(self):
        return '<HTTPNotebookPort authenticated-device>'

    def _read(self, method, path, body=None, *, binary=False, limit=MAX_JSON):
        if not isinstance(path,str) or not path.startswith('/api/') or '#' in path or ('?' in path and path.split('?',1)[0] not in ('/api/schedule','/api/notebook/objects','/api/notebook/work','/api/notebook/changes','/api/notebook/as-of','/api/notebook/followups')):
            raise ValidationError('接口路径无效')
        if callable(self.before_write):
            self.before_write()
        deadline=time.monotonic()+self.timeout
        data=_encode(body) if body is not None else None
        if data is not None and len(data)>12*1024*1024:
            raise ValidationError('请求超出大小限制')
        headers={'Authorization':'Bearer '+self._device_token,'Accept':'application/json', 'Origin':self.origin}
        if data is not None:
            headers.update({'Content-Type':'application/json','X-CSRF-Token':self._csrf or ''})
        request=urllib.request.Request(self.base_url+path,data=data,headers=headers,method=method)
        try:
            with self._opener.open(request,timeout=self.timeout) as response:
                size=response.headers.get('Content-Length')
                if size and (not size.isdigit() or int(size)>limit):
                    raise RemoteNotebookError('服务响应超出大小限制')
                chunks=[];received=0
                while True:
                    if time.monotonic()>deadline:
                        raise RemoteNotebookError('服务响应超出时间限制')
                    chunk=response.read1(min(65536,limit+1-received))
                    if not chunk:
                        break
                    received+=len(chunk)
                    if received>limit:
                        raise RemoteNotebookError('服务响应超出大小限制')
                    chunks.append(chunk)
                payload=b''.join(chunks)
                if binary:
                    return payload,response.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            code=exc.code
            exc.close()
            if code==401:
                raise RemoteNotebookError('设备认证已失效，请更新本机私有配置') from None
            if code==403:
                raise PermissionError('设备写入校验失效') from None
            if code==409:
                raise ConflictError('事项版本已变化，请重新读取') from None
            if code==404:
                raise KeyError('远端对象不存在') from None
            if code==400:
                raise ValidationError('远端未接受这份资料') from None
            raise RemoteNotebookError('服务请求失败（HTTP %s）'%code) from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise RemoteNotebookError('无法连接私人记事本服务') from None
        try:
            result=json.loads(payload,parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(result,dict):
                raise ValueError()
            return result
        except (ValueError,UnicodeError,RecursionError):
            raise RemoteNotebookError('服务未返回有效JSON') from None

    def _bootstrap(self):
        data=self._read('GET','/api/bootstrap')
        csrf=data.get('csrfToken')
        if not isinstance(csrf,str) or not 1<=len(csrf)<=512 or not csrf.isascii() or any(c.isspace() for c in csrf):
            raise RemoteNotebookError('服务写入校验信息缺失')
        self._csrf=csrf
        for record in data.get('records',[]):
            self._remember_assets(record)
        return data

    def _request(self, method, path, body=None):
        if method=='POST':
            if callable(self.before_write):
                self.before_write()
            if self._csrf is None:
                self._bootstrap()
        try:
            return self._read(method,path,body)
        except PermissionError:
            if method!='POST':
                raise RemoteNotebookError('设备无权访问这项资料') from None
            # The server rejected before mutation. Reuse exactly the same JSON/requestId.
            self._bootstrap()
            try:
                return self._read(method,path,body)
            except PermissionError:
                raise RemoteNotebookError('设备写入校验失败') from None

    def _remember_assets(self, record):
        if isinstance(record,dict):
            for asset in record.get('attachments',[]):
                if isinstance(asset,dict) and isinstance(asset.get('id'),str):
                    self._asset_metadata[asset['id']]={key:asset[key] for key in ('id','name','mime','size') if key in asset}
        return record

    def _ai(self,body):
        if not isinstance(body,dict):
            raise ValidationError('写入资料必须是JSON对象')
        return dict(body,actor=AI_ACTOR.copy())

    def list_tasks(self):
        return self._bootstrap()['tasks']

    def get_task(self,rid):
        return self.detail(rid)['task']

    def detail(self,rid):
        return self._request('GET','/api/tasks/'+_identifier(rid))

    def create_task(self,body):
        return self._request('POST','/api/tasks',self._ai(body))['task']

    def record(self,rid,body):
        return self._request('POST','/api/tasks/'+_identifier(rid)+'/record',self._ai(body))['task']

    def append_record(self,body):
        return self._remember_assets(self._request('POST','/api/messages',self._ai(body))['record'])

    def list_records(self):
        records=self._request('GET','/api/messages')['records']
        for record in records:
            self._remember_assets(record)
        return records

    def record_detail(self,rid):
        return self._remember_assets(self._request('GET','/api/messages/'+_identifier(rid))['record'])

    def set_record_processing(self,rid,status,receipt='',object_ids=None):
        return self._remember_assets(self._request('POST','/api/messages/'+_identifier(rid)+'/processing',
            {'status':status,'receipt':receipt,'objectIds':object_ids})['record'])

    def validate_fields(self,body,creating=False):
        data=self._request('POST','/api/validate',{'body':self._ai(body),'creating':bool(creating)})
        if data.get('valid') is not True:
            raise ValidationError('远端字段校验失败')
        return True

    def attach_asset(self,name,data,mime=None):
        if not isinstance(data,bytes) or not 0<len(data)<=MAX_ASSET:
            raise ValidationError('附件必须在8MiB以内且不为空')
        if not isinstance(name,str) or not 1<=len(name)<=200 or '/' in name or '\\' in name or '\x00' in name:
            raise ValidationError('附件名称无效')
        asset=self._request('POST','/api/uploads',{'name':name,'data':base64.b64encode(data).decode('ascii'),'mime':mime})['asset']
        self._asset_metadata[asset['id']]=asset
        return {key:value for key,value in asset.items() if key!='path'}

    def asset(self,aid):
        encoded=_identifier(aid)
        data,mime=self._read('GET','/api/assets/'+encoded,binary=True,limit=MAX_ASSET)
        if not data:
            raise RemoteNotebookError('附件为空')
        metadata=self._asset_metadata.get(aid,{})
        suffix=Path(str(metadata.get('name',''))).suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,12}',suffix):
            suffix=mimetypes.guess_extension(mime) or '.bin'
        name='remote-'+hashlib.sha256(aid.encode()).hexdigest()+suffix
        path=self.assets_dir/name
        if self.assets_dir.is_symlink() or not self.assets_dir.resolve().is_relative_to(self.workspace):
            raise ValidationError('附件缓存目录越界')
        files=[p for p in self.assets_dir.glob('remote-*') if p.is_file() and not p.is_symlink()]
        total=sum(p.stat().st_size for p in files)
        for old in sorted(files,key=lambda p:p.stat().st_mtime):
            if total+len(data)<=MAX_CACHE and len(files)<64:
                break
            total-=old.stat().st_size;old.unlink();files.remove(old)
        temp=self.assets_dir/('remote-tmp-'+uuid.uuid4().hex)
        try:
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(fd,'wb') as out:
                out.write(data)
            os.replace(temp,path)
        finally:
            temp.unlink(missing_ok=True)
        return {'id':aid,'name':metadata.get('name',name),'mime':mime,'size':len(data),
                'url':'/api/assets/'+encoded,'path':str(path)}

    def worker_claim(self,worker_id):
        data=self._request('POST','/api/worker/claim',{'workerId':worker_id})
        # Support the direct lease object and the explicit {claim: ...} envelope.
        return data['claim'] if 'claim' in data else (data if data.get('job') else None)

    def worker_report(self,job_id,worker_id,lease_token,status,result=None,error=None):
        return self._request('POST','/api/worker/jobs/'+_identifier(job_id)+'/report',
            {'workerId':worker_id,'leaseToken':lease_token,'status':status,'result':result,'error':error})['job']

    def query_schedule(self,start,end,assignee='我',domain=''):
        query=urllib.parse.urlencode(dict(start=start,end=end,assignee=assignee,domain=domain))
        return self._request('GET','/api/schedule?'+query)

    def get_schedule(self,eid):
        return self._request('GET','/api/schedule/'+_identifier(eid))['entry']

    def create_schedule(self,body):
        return self._request('POST','/api/schedule',self._ai(body))['entry']

    def schedule_record(self,eid,body):
        return self._request('POST','/api/schedule/'+_identifier(eid)+'/record',self._ai(body))['entry']

    def capabilities(self):return self._request('GET','/api/notebook/capabilities')

    def query_objects(self,**filters):
        return self._request('GET','/api/notebook/objects?'+urllib.parse.urlencode(filters))

    def changes(self,cursor=0,limit=100,**filters):
        return self._request('GET','/api/notebook/changes?'+urllib.parse.urlencode(dict(filters,cursor=cursor,limit=limit)))

    def as_of(self,**selector):
        return self._request('GET','/api/notebook/as-of?'+urllib.parse.urlencode(selector))

    def present(self,rid,body):
        return self._request('POST','/api/tasks/'+_identifier(rid)+'/present',self._ai(body))['presentation']

    def restore_preview(self,rid,**selector):
        return self._request('POST','/api/tasks/'+_identifier(rid)+'/restore-preview',selector)

    def restore(self,rid,body):
        return self._request('POST','/api/tasks/'+_identifier(rid)+'/restore',self._ai(body))['task']

    def due_followups(self,**selector):
        return self._request('GET','/api/notebook/followups?'+urllib.parse.urlencode(selector))

    def acknowledge_followup(self,rid,body):
        return self._request('POST','/api/tasks/'+_identifier(rid)+'/followup-ack',self._ai(body))['receipt']

    def update_source_catalog(self,body):
        return self._request('POST','/api/source-catalog',self._ai(body))['source']

    def query_work(self,**filters):
        return self._request('GET','/api/notebook/work?'+urllib.parse.urlencode(filters))

    def integrate_work_record(self,rid,body):
        return self._request('POST','/api/messages/'+_identifier(rid)+'/integrate-work',self._ai(body))

    @staticmethod
    def work_record_hash(record):
        from .work import WorkMixin
        return WorkMixin.work_record_hash(record)
