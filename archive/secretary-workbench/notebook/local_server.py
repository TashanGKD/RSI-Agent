#!/usr/bin/env python3
"""Thin, explicit-workspace local HTTP host for the independently usable modules.
No remote deployment, collector, timer, or implicit choice of the user's live DB.
"""
import argparse
import base64
import binascii
import hmac
import json
import mimetypes
import secrets
import re
import socket
import sys
import traceback
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,unquote,quote,parse_qs
from contracts import STATES,DOMAINS,TIMEZONE,today
from modules.notebook import NotebookService
from modules.secretary import SecretaryService,SecretaryValidationError
from modules.sources import SourceRegistry
from modules.access import AccessError
from store import ValidationError,ConflictError,strict_json

APP=Path(__file__).resolve().parent
VERSION='4.4.unified.20261031'
ASSETS={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/style.css':'style.css','/schedule.js':'schedule.js','/schedule.css':'schedule.css','/tool-details.js':'tool-details.js','/work-view.js':'work-view.js'}
FONTS={'HarmonyOS_Sans_SC_Regular.ttf','HarmonyOS_Sans_SC_Medium.ttf','google-sans-flex-latin.woff2'}
MAX_BODY=12*1024*1024

def make_server(workspace,db_file=None,source_file=None,port=0,model_runner=None,access=None,secretary_factory=None):
    workspace=Path(workspace).expanduser().resolve();workspace.mkdir(parents=True,exist_ok=True,mode=0o700)
    db_file=Path(db_file) if db_file else workspace/'notebook'/'notebook.sqlite3'
    source_file=Path(source_file) if source_file else workspace/'source.json'
    if not source_file.exists():source_file.write_text('{"records":[]}\n',encoding='utf-8');source_file.chmod(0o600)
    notebook=NotebookService(db_file,source_file,workspace)
    sources=SourceRegistry(workspace)
    secretary=secretary_factory(notebook,workspace) if secretary_factory else SecretaryService(notebook,workspace,model_runner=model_runner,source_port=sources)

    class Handler(BaseHTTPRequestHandler):
        server_version='TashanLocal/4';protocol_version='HTTP/1.0'
        def setup(self):super().setup();self.connection.settimeout(15)
        def log_message(self,*_):pass
        def send(self,status,content,kind='application/json; charset=utf-8',extra=None):
            raw=json.dumps(content,ensure_ascii=False).encode() if isinstance(content,(dict,list)) else content
            self.send_response(status)
            headers={'Content-Type':kind,'Content-Length':str(len(raw)),'Cache-Control':'no-store',
                'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
                'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
                'Permissions-Policy':'microphone=(), geolocation=()'}
            headers.update(extra or {})
            for k,v in headers.items():self.send_header(k,v)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
        def error(self,status,message,code='request_error'):return self.send(status,{'error':message,'code':code})
        def valid_host(self):
            return self.headers.get('Host')==access.host if access else self.headers.get('Host') in ('127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port))
        def identity(self):return access.authenticate(self.headers.get('Cookie'),self.headers.get('Authorization')) if access else 'local'
        def online_fields(self,body):
            if body.get('sources'):raise ValidationError('原始信源仅保留Mac，线上请保存必要摘要')
            from contracts.source_refs import source_refs
            for key in ('sourceRefs','sourceContacts'):
                if key in body:source_refs(body[key])
            if self.identity()=='device' and (body.get('confirm') or body.get('needsReview') is False):raise ValidationError('批阅确认只能由本人操作')
        def bootstrap(self):
            return {'version':VERSION,'csrfToken':self.server.csrf,'states':list(STATES),'domains':list(DOMAINS),
                'today':today(),'tasks':notebook.list_tasks(),'records':notebook.list_records(),'dueFollowups':notebook.due_followups()['items'],
                'sources':notebook.source_catalog() if access else sources.list_sources(),'meta':{'count':len(notebook.list_tasks()),'timezone':TIMEZONE,
                    'coverageText':('云端记事本；微信原文与附件保留Mac。AI整理需Mac在线。' if access else '读取已有本地记事本；页面重载不扫描微信、飞书或会议。'),'workspaceMode':'online' if access else 'local','timersEnabled':False}}
        def guarded(self,fn):
            try:return fn()
            except AccessError as e:return self.error(e.status,str(e),'authentication')
            except ConflictError as e:return self.error(409,str(e),'conflict')
            except (ValidationError,SecretaryValidationError,ValueError,TypeError,UnicodeDecodeError,binascii.Error) as e:return self.error(400,str(e)[:240],'validation')
            except (KeyError,FileNotFoundError):return self.error(404,'未找到记录或资料','not_found')
            except (BrokenPipeError,ConnectionResetError,socket.timeout):return
            except Exception as e:
                print('HTTP internal '+type(e).__name__+' '+','.join(f.name+':'+str(f.lineno) for f in traceback.extract_tb(e.__traceback__)),file=sys.stderr,flush=True)
                return self.error(500,'操作未完成，已保存的原记录保留，请重试','internal')
        def do_HEAD(self):self.do_GET()
        def do_GET(self):
            if not self.valid_host():return self.error(403,'仅允许本机访问','host')
            return self.guarded(self.get)
        def get(self):
            parsed=urlsplit(self.path);path=unquote(parsed.path);parts=path.strip('/').split('/')
            if path=='/api/health':return self.send(200,{'ok':True,'version':VERSION,'collectors':False,'timers':False})
            if access:
                if path=='/api/auth/status':return self.send(200,{'authenticated':self.identity()=='human','initialized':access.initialized(),'usernameRequired':access.requires_username()})
                public={'/login':'index.html','/auth.js':'auth.js','/auth.css':'auth.css'}
                if path in public:
                    mime={'/login':'text/html','/auth.js':'text/javascript','/auth.css':'text/css'}[path]
                    return self.send(200,(APP/'web-access'/public[path]).read_bytes(),mime+'; charset=utf-8')
                if not self.identity():
                    if path in ('/','/index.html'):return self.send(303,b'','text/plain',{'Location':'/login'})
                    return self.error(401,'请先登录私人记事本','authentication')
            if path=='/api/bootstrap':return self.send(200,self.bootstrap())
            if path.startswith('/api/notebook/'):
                q=parse_qs(parsed.query,keep_blank_values=True)
                if any(len(v)!=1 for v in q.values()):raise ValidationError('查询条件不能重复')
                kw={k:v[0] for k,v in q.items()}
                numeric={'limit','sequence'}|({'cursor'} if path=='/api/notebook/changes' else set())
                for k in numeric & set(kw):
                    if not kw[k].isdigit():raise ValidationError('序号/页大小无效')
                    kw[k]=int(kw[k])
                if path=='/api/notebook/capabilities':
                    if kw:raise ValidationError('能力查询不接受参数')
                    from modules.notebook.public_api import capabilities
                    return self.send(200,capabilities())
                if path=='/api/notebook/work':
                    if set(kw)-{'start','end','person','organization','keyword','cursor','limit','snapshot'}:raise ValidationError('工作查询条件无效')
                    if 'cursor' in kw:
                        if not kw['cursor'].isdigit():raise ValidationError('游标无效')
                        kw['cursor']=int(kw['cursor'])
                    return self.send(200,notebook.query_work(**kw))
                if path=='/api/notebook/objects':return self.send(200,notebook.query_objects(**kw))
                if path=='/api/notebook/changes':
                    if set(kw)-{'cursor','limit','object_id','author','start','end'}:raise ValidationError('变更查询参数无效')
                    return self.send(200,notebook.changes(**kw))
                if path=='/api/notebook/as-of':
                    if set(kw)-{'sequence','at'}:raise ValidationError('历史查询参数无效')
                    return self.send(200,notebook.as_of(**kw))
                if path=='/api/notebook/followups':
                    if set(kw)-{'date','at'}:raise ValidationError('复看查询参数无效')
                    return self.send(200,notebook.due_followups(**kw))

            if path=='/api/schedule':
                q=parse_qs(parsed.query,keep_blank_values=True)
                if set(q)-{'start','end','assignee','domain'} or any(len(v)!=1 for v in q.values()):raise ValidationError('日程查询条件无效或重复')
                return self.send(200,notebook.query_schedule(q.get('start',[None])[0],q.get('end',[None])[0],q.get('assignee',['我'])[0],q.get('domain',[''])[0]))
            if len(parts)==3 and parts[:2]==['api','schedule']:return self.send(200,{'entry':notebook.get_schedule(parts[2]),'history':notebook.schedule_history(parts[2])})
            if path=='/api/messages':return self.send(200,{'records':notebook.list_records()})
            if len(parts)==3 and parts[:2]==['api','messages']:return self.send(200,{'record':notebook.record_detail(parts[2])})
            if path=='/api/jobs':return self.send(200,{'jobs':secretary.list_jobs()})
            if path=='/api/sources':return self.send(200,{'sources':notebook.source_catalog() if access else sources.list_sources()})
            if len(parts)==3 and parts[:2]==['api','jobs']:return self.send(200,{'job':secretary.get_job(parts[2])})
            if len(parts)==3 and parts[:2]==['api','tasks']:return self.send(200,notebook.detail(parts[2]))
            if len(parts)==5 and parts[:2]==['api','tasks'] and parts[3]=='sources' and parts[4].isdigit():
                file=notebook.source(parts[2],int(parts[4]));return self.send(200,file.read_bytes(),'text/plain; charset=utf-8')
            if len(parts)==3 and parts[:2]==['api','assets']:
                a=notebook.asset(parts[2]);kind=a['mime'];safe_inline=kind.startswith('image/') and kind in ('image/png','image/jpeg','image/webp','image/gif')
                return self.send(200,Path(a['path']).read_bytes(),kind,{'Content-Disposition':('inline' if safe_inline else 'attachment')+"; filename*=UTF-8''"+quote(a['name'])})
            if len(parts)>=4 and parts[:2]==['api','sources'] and parts[3]!='records':
                if access:return self.error(404,'信源原件与读取工具仅在本机使用','local_only')
                sid=parts[2];op=parts[3]
                q=parse_qs(parsed.query,keep_blank_values=True)
                if any(len(v)!=1 for v in q.values()):raise ValidationError('信源参数重复')
                kw={k:v[0] for k,v in q.items()}
                if len(parts)==4 and op=='snapshots' and not kw:return self.send(200,{'snapshots':sources.list_snapshots(sid)})
                if len(parts)==4 and op=='versions' and set(kw)=={'recordId'}:return self.send(200,{'versions':sources.list_record_versions(sid,kw['recordId'])})
                if len(parts)==4 and op=='read-version' and set(kw)=={'recordId','snapshot'}:return self.send(200,sources.read_record_version(sid,kw['recordId'],kw['snapshot']))
                if len(parts)==4 and op=='receipts' and not kw:return self.send(200,{'receipts':sources.list_read_receipts(sid)})
                if len(parts)==5 and op=='receipts' and not kw:return self.send(200,{'receipt':sources.read_read_receipt(sid,parts[4])})
                if len(parts)==4 and op=='checkpoints' and set(kw)=={'consumerId'}:return self.send(200,sources.get_checkpoints(sid,kw['consumerId']))
                if len(parts)==4 and op=='assets' and not kw:return self.send(200,{'assets':sources.list_assets(sid)})
                if len(parts)==5 and op=='assets' and not kw:
                    asset=sources.get_asset(sid,parts[4]);meta=asset['metadata'];return self.send(200,asset['content'],meta['mime'],{'Content-Disposition':"attachment; filename*=UTF-8''"+quote(meta.get('name') or 'source-asset')})
                raise ValidationError('信源读取参数无效')
            if len(parts)==4 and parts[:2]==['api','sources'] and parts[3]=='records':
                if access:return self.error(404,'原始信源保留Mac，线上仅提供工作记事本','local_only')
                q=parse_qs(parsed.query,keep_blank_values=True);allowed={'start','end','keyword','conversation','sender','content_type','limit','cursor'}
                if set(q)-allowed or any(len(v)!=1 for v in q.values()):raise ValidationError('查询条件无效')
                kw={k:v[0] for k,v in q.items()};kw['limit']=int(kw.get('limit',100));return self.send(200,sources.query(parts[2],**kw))
            if path in ASSETS:
                f=APP/'web-local'/ASSETS[path]
            elif len(parts)==2 and parts[0]=='fonts' and parts[1] in FONTS:f=APP/'web'/'fonts'/parts[1]
            else:return self.error(404,'未找到页面或资料','not_found')
            mime=mimetypes.guess_type(f.name)[0] or 'application/octet-stream'
            if f.suffix=='.js':mime='text/javascript'
            if mime.startswith('text/'):mime+='; charset=utf-8'
            raw=f.read_bytes()
            return self.send(200,raw,mime,{'Cache-Control':'private, max-age=86400'} if f.name in FONTS else None)
        def do_POST(self):
            expected={access.origin} if access else {'http://127.0.0.1:'+str(self.server.server_port),'http://localhost:'+str(self.server.server_port)}
            token=self.headers.get('X-CSRF-Token','')
            if not self.valid_host() or self.headers.get('Origin') not in expected:return self.error(403,'请求来源未获验证','origin')
            path=unquote(urlsplit(self.path).path)
            bootstrap_auth=access and path in ('/api/auth/login','/api/auth/activate')
            if access and not bootstrap_auth and not self.identity():return self.error(401,'请先登录私人记事本','authentication')
            if not bootstrap_auth and not hmac.compare_digest(token.encode(),self.server.csrf.encode()):return self.error(403,'页面验证已失效，请重新载入后重试','origin')
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':return self.error(400,'只接受JSON请求','content_type')
            return self.guarded(self.post)
        def post(self):
            try:size=int(self.headers.get('Content-Length','0'))
            except ValueError:raise ValidationError('长度无效')
            if size<1 or size>MAX_BODY:return self.error(413,'请求过大或为空','too_large')
            raw=self.rfile.read(size)
            if len(raw)!=size:raise ValidationError('请求尚未完整到达')
            body=strict_json(raw.decode())
            if not isinstance(body,dict):raise ValidationError('请求须为对象')
            path=unquote(urlsplit(self.path).path);parts=path.strip('/').split('/')
            if access:
                identity=self.identity()
                ip=self.headers.get('X-Real-IP',self.client_address[0])[:100]
                if path in ('/api/auth/login','/api/auth/activate'):
                    allowed={'password'}|({'token'} if path.endswith('activate') else set())
                    if set(body)-{'username'}!=allowed:raise ValidationError('登录字段无效')
                    cookie=access.activate(body['token'],body['password'],ip,username=body.get('username')) if path.endswith('activate') else access.login(body['password'],ip,username=body.get('username'))
                    return self.send(200,{'ok':True},extra={'Set-Cookie':cookie})
                if path=='/api/auth/logout':
                    if body or identity!='human':raise ValidationError('退出请求无效')
                    return self.send(200,{'ok':True},extra={'Set-Cookie':access.logout(self.headers.get('Cookie'))})
                worker_only=path=='/api/validate' or path.startswith('/api/worker/') or (len(parts)==4 and parts[:2]==['api','messages'] and parts[3]=='processing')
                if worker_only and identity!='device':return self.error(403,'此接口仅供已授权设备使用','device_required')
                if path=='/api/validate':
                    if set(body)-{'body','creating'} or not isinstance(body.get('body'),dict) or type(body.get('creating',False)) is not bool:raise ValidationError('预检字段无效')
                    check=dict(body['body'],actor={'name':'秘书','kind':'ai'})
                    self.online_fields(check)
                    notebook.validate_fields(check,creating=body.get('creating',False))
                    return self.send(200,{'valid':True})
                if path=='/api/worker/claim':
                    if set(body)!={'workerId'}:raise ValidationError('设备字段无效')
                    return self.send(200,{'claim':secretary.claim(body['workerId'])})
                if len(parts)==5 and parts[:3]==['api','worker','jobs'] and parts[4]=='report':
                    if set(body)-{'workerId','leaseToken','status','result','error'}:raise ValidationError('回执字段无效')
                    return self.send(200,{'job':secretary.report(parts[3],body.get('workerId'),body.get('leaseToken'),body.get('status'),body.get('result'),body.get('error'))})
                if len(parts)==4 and parts[:2]==['api','messages'] and parts[3]=='processing':
                    if set(body)-{'status','receipt','objectIds'}:raise ValidationError('处理字段无效')
                    return self.send(200,{'record':notebook.set_record_processing(parts[2],body.get('status'),body.get('receipt',''),body.get('objectIds'))})
                if path=='/api/schedule' or (len(parts)==4 and parts[:2]==['api','schedule']):
                    self.online_fields(body)
                    body=dict(body,actor={'name':'我','kind':'human'} if identity=='human' else {'name':'秘书','kind':'ai'})
                if path in ('/api/messages','/api/tasks') or (len(parts)==4 and parts[:2]==['api','tasks']):
                    self.online_fields(body)
                    if identity=='device' and len(parts)==4 and parts[3]=='confirm':return self.error(403,'批阅确认只能由本人操作','human_required')
                    body=dict(body,actor={'name':'我','kind':'human'} if identity=='human' else {'name':'秘书','kind':'ai'})
            if len(parts)==4 and parts[:2]==['api','messages'] and parts[3]=='integrate-work':
                if access:
                    if identity!='device':return self.error(403,'历史并入仅由授权设备操作','device_required')
                    self.online_fields(body)
                    if 'task' in body:self.online_fields(body['task'])
                return self.send(200,notebook.integrate_work_record(parts[2],dict(body,actor={'name':'秘书','kind':'ai'})))
            if path=='/api/source-catalog':
                if access and identity!='device':return self.error(403,'目录仅由授权本机工具同步','device_required')
                return self.send(200,{'source':notebook.update_source_catalog(dict(body,actor={'name':'信源工具','kind':'ai'}))})
            if len(parts)==4 and parts[:2]==['api','sources']:
                if access:return self.error(404,'原始信源仅保留本机','local_only')
                sid=parts[2];op=parts[3]
                if op=='imports':
                    if set(body)-{'records','displayName','coverage','gaps'}:raise ValidationError('导入字段无效')
                    from modules.sources.registry import _source_id
                    platform,account=_source_id(sid)
                    return self.send(200,{'receipt':sources.import_records(platform,account,body.get('records'),display_name=body.get('displayName'),coverage=body.get('coverage'),gaps=body.get('gaps'))})
                if op=='receipts':
                    if set(body)-{'snapshot','recordIds','mediaReads'}:raise ValidationError('读取回执字段无效')
                    return self.send(200,{'receipt':sources.persist_read_receipt(sid,body.get('snapshot'),body.get('recordIds'),media_reads=body.get('mediaReads'))})
                if op=='checkpoints':
                    if set(body)-{'consumerId','stage','expectedRevision','snapshot','recordIds','receiptIds','acknowledgment'}:raise ValidationError('检查点字段无效')
                    from modules.sources import CheckpointConflictError
                    try:r=sources.advance_checkpoint(sid,body.get('consumerId'),body.get('stage'),expected_revision=body.get('expectedRevision'),snapshot=body.get('snapshot'),record_ids=body.get('recordIds'),receipt_ids=body.get('receiptIds'),acknowledgment=body.get('acknowledgment'))
                    except CheckpointConflictError as exc:raise ConflictError(str(exc)) from None
                    return self.send(200,r)
                if op=='assets':
                    if set(body)-{'name','data','mime','expectedSha256'}:raise ValidationError('信源附件字段无效')
                    return self.send(200,{'asset':sources.put_asset(sid,base64.b64decode(body.get('data',''),validate=True),mime=body.get('mime'),name=body.get('name'),expected_sha256=body.get('expectedSha256'))})
                raise ValidationError('信源操作无效')
            if len(parts)==4 and parts[:2]==['api','tasks'] and parts[3] in ('present','restore-preview','restore','followup-ack'):
                if parts[3]=='present':return self.send(200,{'presentation':notebook.present(parts[2],body)})
                if parts[3]=='restore-preview':
                    if set(body)-{'sequence','fields','actor'}:raise ValidationError('恢复预览字段无效')
                    return self.send(200,notebook.restore_preview(parts[2],sequence=body.get('sequence'),fields=body.get('fields')))
                if parts[3]=='restore':return self.send(200,{'task':notebook.restore(parts[2],body)})
                return self.send(200,{'receipt':notebook.acknowledge_followup(parts[2],body)})
            if path=='/api/schedule':return self.send(200,{'entry':notebook.create_schedule(body)})
            if len(parts)==4 and parts[:2]==['api','schedule'] and parts[3]=='record':return self.send(200,{'entry':notebook.schedule_record(parts[2],body)})
            if path=='/api/messages':return self.send(200,{'record':notebook.append_record(body)})
            if path=='/api/tasks':return self.send(200,{'task':notebook.create_task(body)})
            if path=='/api/uploads':
                if set(body)-{'name','data','mime'} or not isinstance(body.get('data'),str):raise ValidationError('附件字段无效')
                data=base64.b64decode(body['data'],validate=True)
                return self.send(200,{'asset':notebook.attach_asset(body.get('name'),data,body.get('mime'))})
            if path=='/api/secretary/run':
                if set(body)-{'messageId','requestId'}:raise ValidationError('整理字段无效')
                return self.send(200,{'job':secretary.submit(message_id=body.get('messageId'),request_id=body.get('requestId'))})
            if path=='/api/refresh':
                if body:raise ValidationError('重载不接受额外字段')
                result=self.bootstrap();result['changes']={'reloaded':True,'sourcesScanned':False};return self.send(200,result)
            if len(parts)==4 and parts[:2]==['api','tasks'] and parts[3] in ('record','confirm'):
                if parts[3]=='confirm':body=dict(body,confirm=True)
                return self.send(200,{'task':notebook.record(parts[2],body)})
            return self.error(404,'未找到操作','not_found')
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True;server.csrf=secrets.token_urlsafe(32)
    server.notebook=notebook;server.sources=sources;server.secretary=secretary
    return server

def disabled_model_runner(context):
    raise SecretaryValidationError('Source package demo requires explicit --enable-codex-exec and operator configuration.')

def main():
    p=argparse.ArgumentParser(description='他山本地秘书：显式工作区、仅本机，不自动采集或开定时')
    p.add_argument('--enable-codex-exec',action='store_true')
    p.add_argument('--workspace',type=Path,required=True);p.add_argument('--db',type=Path);p.add_argument('--source',type=Path);p.add_argument('--port',type=int,default=8876)
    args=p.parse_args()
    if not 1024<=args.port<=65535:p.error('端口应在1024—65535')
    server=make_server(args.workspace,args.db,args.source,args.port,model_runner=None if args.enable_codex_exec else disabled_model_runner)
    print('本地秘书已启动：http://127.0.0.1:'+str(server.server_port),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
