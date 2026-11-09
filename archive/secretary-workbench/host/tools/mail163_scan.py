"""Bounded, explicitly requested all-folder IMAP acquisition. Only EXAMINE/PEEK."""
import argparse,base64,hashlib,html,imaplib,json,os,re,ssl,sys
from datetime import datetime,timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import mail163
W=Path(__file__).resolve().parent

def safe_text(s):
    s=re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b','[认证信息已隔离]',s)
    return '\n'.join('[认证行已隔离]' if re.search(r'密码|口令|授权码|验证码|password|passwd|credential|(?:access|refresh|session)[_-]?token|(?:api|access)[_-]?key|client[_-]?secret',line,re.I) else re.sub(r'(https?://[^\s<>?]+)\?[^\s<>]+',r'\1?[链接参数留原件]',line) for line in s.split('\n'))

class TextHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','head'):self.hidden+=1
        if tag in ('p','br','div','tr','li','h1','h2','h3') and not self.hidden:self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','head') and self.hidden:self.hidden-=1
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)

def html_text(s):
    p=TextHTML();p.feed(s);return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',''.join(p.parts))

def quote_folder(s):
    if any(x in s for x in ('\r','\n','\0')):raise ValueError('Invalid folder name')
    return '"'+s.replace('\\','\\\\').replace('"','\\"')+'"'

def decode_folder(s):
    def sub(m):
        if not m[1]:return '&'
        t=m[1].replace(',','/');return base64.b64decode(t+'='*((-len(t))%4)).decode('utf-16-be')
    return re.sub(r'&([^-]*)-',sub,s)

def write_json(p,x):
    p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(p)

def parse_date(s):
    try:
        d=parsedate_to_datetime(s)
        if d.tzinfo is None:return None
        return d.astimezone(timezone.utc)
    except Exception:return None

def extract(raw,record,root):
    msg=BytesParser(policy=policy.default).parsebytes(raw)
    plain=[];rich=[];assets=[]
    for i,part in enumerate(msg.walk()):
        if part.is_multipart():continue
        payload=part.get_payload(decode=True) or b''
        ct=part.get_content_type();disp=part.get_content_disposition();name=part.get_filename()
        if ct in ('text/plain','text/html') and disp!='attachment' and not name:
            char=part.get_content_charset() or 'utf-8'
            try:text=payload.decode(char,errors='replace')
            except LookupError:text=payload.decode('utf-8',errors='replace')
            (plain if ct=='text/plain' else rich).append(text)
        else:
            h=hashlib.sha256(payload).hexdigest();p=root/'assets'/h
            if not p.exists():
                p.parent.mkdir(mode=0o700,exist_ok=True);p.write_bytes(payload);p.chmod(0o600)
            assets.append({'part':i,'name':safe_text(str(name or '')),'contentType':ct,'size':len(payload),'sha256':h,'path':str(p),'disposition':disp,'read':False})
    text='\n'.join(plain) if plain else '\n'.join(html_text(x) for x in rich)
    record.update(text=safe_text(text),attachments=assets,mimeDefects=[type(x).__name__ for x in msg.defects],headerDefects=[type(x).__name__ for x in msg.defects],rawSha256=hashlib.sha256(raw).hexdigest(),textSha256=hashlib.sha256(text.encode()).hexdigest())
    return record

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--execute',action='store_true');ap.add_argument('--run-config',type=Path);a=ap.parse_args()
    if not a.execute:ap.print_help();return
    if a.run_config is None:ap.error('--execute requires an explicit --run-config with fresh time boundaries')
    cfg=json.loads(a.run_config.read_text());R=Path(cfg['runDir']);start=datetime.fromisoformat(cfg['startInclusive']).astimezone(timezone.utc);end=datetime.fromisoformat(cfg['endExclusive']).astimezone(timezone.utc)
    if start>=end:raise ValueError('Invalid time window')
    R.mkdir(mode=0o700,parents=True,exist_ok=True)
    if R.is_symlink() or R.stat().st_uid!=os.getuid():raise ValueError('Invalid private run directory')
    os.chmod(R,0o700)
    out={'window':{'startInclusive':start.isoformat(),'endExclusive':end.isoformat()},'account':mail163.ACCOUNT,'folders':[],'messages':[],'errors':[],'allFlagsUnchanged':True,'status':'running'}
    c=imaplib.IMAP4_SSL(mail163.HOST,993,ssl_context=ssl.create_default_context(),timeout=25)
    try:
        c.login(mail163.ACCOUNT,mail163.keychain());imaplib.Commands.setdefault('ID',('AUTH','SELECTED'));c._simple_command('ID','("name" "TashanSecretary" "version" "1.0")')
        typ,folders=c.list()
        if typ!='OK':raise RuntimeError('LIST rejected')
        for entry in folders:
            if not isinstance(entry,bytes):raise RuntimeError('Unexpected LIST literal; preserve gap')
            match=re.match(rb'\((.*?)\)\s+(?:"[^"]*"|NIL)\s+(.*)',entry)
            if not match:raise RuntimeError('Unparsed folder')
            flags,name=match.groups()
            if b'\\Noselect' in flags:continue
            s=name.decode('ascii');s=s[1:-1].replace('\\"','"').replace('\\\\','\\') if s.startswith('"') and s.endswith('"') else s
            label=decode_folder(s);folder={'nativeName':s,'displayName':label,'records':[]}
            out['folders'].append(folder)
            try:
                typ,counts=c.select(quote_folder(s),readonly=True)
                if typ!='OK':raise RuntimeError('EXAMINE rejected')
                folder['messageCount']=int(counts[0]);folder['uidValidity']=(c.response('UIDVALIDITY')[1][0] or b'').decode()
                typ,data=c.uid('SEARCH',None,'ALL')
                if typ!='OK':raise RuntimeError('UID search rejected')
                uids=data[0].split();folder['allUids']=[x.decode() for x in uids]
                for offset in range(0,len(uids),40):
                    typ,rows=c.uid('FETCH',b','.join(uids[offset:offset+40]),'(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER])')
                    if typ!='OK':raise RuntimeError('Header batch rejected')
                    for row in rows:
                        if not isinstance(row,tuple):continue
                        envelope,rawheader=row
                        uid=re.search(rb'\bUID (\d+)',envelope).group(1).decode()
                        size=int(re.search(rb'RFC822.SIZE (\d+)',envelope).group(1))
                        internal=imaplib.Internaldate2tuple(envelope)
                        import time
                        internal_dt=datetime.fromtimestamp(time.mktime(internal),timezone.utc) if internal else None
                        msg=BytesParser(policy=policy.default).parsebytes(rawheader)
                        sent=parse_date(str(msg.get('Date','')))
                        # Read a union of original message date and server arrival window; retain both.
                        selected=any(start<=t<end for t in (sent,internal_dt) if t)
                        m={'folder':label,'folderNative':s,'uidValidity':folder['uidValidity'],'uid':uid,'nativeId':s+':'+folder['uidValidity']+':'+uid,'messageId':str(msg.get('Message-ID','')),'inReplyTo':str(msg.get('In-Reply-To','')),'references':str(msg.get('References','')),'subject':safe_text(str(msg.get('Subject',''))),'from':safe_text(str(msg.get('From',''))),'to':safe_text(str(msg.get('To',''))),'cc':safe_text(str(msg.get('Cc',''))),'dateHeader':str(msg.get('Date','')),'sentAt':sent.isoformat() if sent else None,'internalAt':internal_dt.isoformat() if internal_dt else None,'size':size,'selected':selected,'flagsBefore':[x.decode() for x in imaplib.ParseFlags(envelope)]}
                        folder['records'].append(m)
                        if not selected:continue
                        if size>32*1024*1024:
                            m['gap']='over_32MiB_full_fetch_limit';out['messages'].append(m);continue
                        typ,bodyrows=c.uid('FETCH',uid,'(UID BODY.PEEK[])')
                        if typ!='OK':raise RuntimeError('Message body rejected')
                        raw=next((x[1] for x in bodyrows if isinstance(x,tuple)),None)
                        if raw is None:raise RuntimeError('No body literal')
                        if len(raw)>32*1024*1024:raise RuntimeError('Server body exceeded limit')
                        rawdir=R/'mail-originals'/hashlib.sha256(s.encode()).hexdigest()[:12];rawdir.mkdir(mode=0o700,parents=True,exist_ok=True);rp=rawdir/(uid+'.eml');rp.write_bytes(raw);rp.chmod(0o600)
                        m['rawPath']=str(rp)
                        extract(raw,m,R)
                        typ,fr=c.uid('FETCH',uid,'(FLAGS)')
                        if typ!='OK':raise RuntimeError('FLAGS verification failed')
                        after=[x.decode() for x in imaplib.ParseFlags(b' '.join(x for x in fr if isinstance(x,bytes)))]
                        m['flagsUnchanged']=sorted(after)==sorted(m['flagsBefore']);out['allFlagsUnchanged'] &=m['flagsUnchanged'];out['messages'].append(m)
                folder['status']='retrieved';folder['selectedCount']=sum(x['selected'] for x in folder['records'])
                write_json(R/'mail-inventory.json',out)
                print(json.dumps({'folder':label,'total':folder['messageCount'],'selected':folder['selectedCount']},ensure_ascii=False),flush=True)
            except Exception as e:
                folder['status']='failed';out['errors'].append({'folder':label,'errorType':type(e).__name__});write_json(R/'mail-inventory.json',out)
        out['status']='retrieved-with-gaps' if out['errors'] else 'retrieved';write_json(R/'mail-inventory.json',out)
        view=[]
        for i,m in enumerate(sorted(out['messages'],key=lambda x:(x['sentAt'] or x['internalAt'] or '',x['nativeId']))):
            m['readIndex']=i+1
            view.append({'index':i+1,**{k:m.get(k) for k in ['nativeId','folder','sentAt','internalAt','subject','from','to','text','attachments','gap']}})
        write_json(R/'mail-inventory.json',out);write_json(R/'reading-safe.json',view)
        print(json.dumps({'status':out['status'],'folders':len(out['folders']),'selectedRecords':len(out['messages']),'allFlagsUnchanged':out['allFlagsUnchanged']},ensure_ascii=False))
    finally:
        try:c.logout()
        except Exception:pass

if __name__=='__main__':main()
