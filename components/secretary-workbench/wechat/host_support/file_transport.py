"""File preview/receipt primitives; no private service or scopes."""
from rsi_runtime_env import display, xauthority
import hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))
COMMON=Path(__file__).resolve().parent
def preview_matches(text,name):
    return bool(re.search(r'(?<![A-Za-z0-9_.-])'+re.escape(name)+r'(?![A-Za-z0-9_.-])',text))

def dependencies():
    sys.path.insert(0,str(COMMON));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def preview(ui,path):
    # Only the editor card is OCR'd, never other conversations or their content.
    box=ui.cfg['header_box'];im=ui.ui.screenshot().crop((box[0],ui.cfg['editor'][1]-50,box[2],ui.cfg['send'][1]-25));im.save(path)
    ocr=Path(os.environ.get('WECHAT_OCR_RUNTIME',str(ROOT/'runtime/ocr')))
    r=subprocess.run([str(ocr/'usr/bin/tesseract'),str(path),'stdout','--tessdata-dir',str(ocr/'usr/share/tesseract-ocr/5/tessdata'),'-l','eng','--psm','6'],capture_output=True,text=True,timeout=10)
    if r.returncode:raise ValueError('file preview OCR unavailable')
    return r.stdout

def require_empty_editor(ui):
    # The header extends beyond the editor frame. Stay inside the editor's right border;
    # otherwise a blinking caret plus that border can look like an existing attachment.
    box=ui.cfg['header_box'];im=ui.ui.screenshot().crop((box[0]+20,ui.cfg['editor'][1]-30,box[2]-40,ui.cfg['send'][1]-30)).convert('RGB')
    # A caret is tiny; text, existing file cards and images are not. OCR alone could miss Chinese or an image.
    if sum(min(pixel)<230 for pixel in im.getdata())>80:raise ValueError('editor is not visibly empty; existing contents retained')

def chooser_present():
    env=dict(os.environ,DISPLAY=display(),XAUTHORITY=xauthority(Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))))
    s=subprocess.run(['xwininfo','-root','-tree'],env=env,capture_output=True,text=True,check=True,timeout=5).stdout
    rows=re.findall(r'0x[0-9a-f]+ "Select File": \("wechat" "wechat"\)\s+(\d+)x(\d+)\+(-?\d+)\+(-?\d+)',s)
    if not rows:return False
    if rows!=[('647','432','0','0')]:raise ValueError('unrecognized file chooser layout; leave untouched')
    return True

def native_receipt(j):
    dependencies();from linux_tool import native,decode,ACCOUNT
    from xml.etree import ElementTree as ET
    table='Msg_'+hashlib.md5(j['peer'].encode()).hexdigest();matches=[]
    with native('message/message_0.db') as (c,r):
        if r.get('consistency')!='committed':return {'state':'unknown','reason':'native snapshot gap'}
        me=c.execute('select rowid from Name2Id where user_name=?',(ACCOUNT,)).fetchone()
        if not me:return {'state':'unknown','reason':'sender identity missing'}
        rows=c.execute('select server_id,local_id,status,local_type,message_content from '+table+' where create_time>=? and real_sender_id=? order by create_time,local_id limit 101',(int(j['startedAt'])-1,me[0])).fetchall()
        if len(rows)>100:return {'state':'unknown','reason':'candidate budget exceeded'}
        for x in rows:
            sid=str(x['server_id']&0xffffffffffffffff)
            if not x['server_id'] or sid in j['beforeIds'] or x['status']!=2 or int(x['local_type'])&0xffffffff!=49:continue
            s=decode(x['message_content'])
            if not s or len(s)>100000 or '<!DOCTYPE' in s.upper() or '<!ENTITY' in s.upper():continue
            if s.startswith(ACCOUNT+':\n'):s=s[len(ACCOUNT)+2:]
            try:doc=ET.fromstring(s)
            except ET.ParseError:continue
            title=doc.findtext('.//appmsg/title') or doc.findtext('.//title')
            kind=doc.findtext('.//appmsg/type') or doc.findtext('.//type')
            length=doc.findtext('.//totallen');md5=doc.findtext('.//filemd5') or doc.findtext('.//md5')
            if title==j['name'] and kind=='6' and length==str(j['size']) and md5==j['md5']:
                matches.append({'serverId':sid,'localId':x['local_id']})
    unique={x['serverId']:x for x in matches}
    if len(unique)!=1:return {'state':'unknown','reason':'no unique exact file receipt'}
    return {'state':'accepted','peer':j['peer'],**next(iter(unique.values())),'nativeFilenameMatch':True,'nativeSizeMatch':True,'nativeMD5Match':True,'phoneReceiptConfirmed':False,'automaticResend':False}
