"""Operation-specific evidence, separate from UI clicking and queue acceptance."""
import re
import hashlib
from xml.etree import ElementTree as ET

def xml(raw):
 if not isinstance(raw,str) or len(raw.encode())>100000 or re.search(r'<!\s*(DOCTYPE|ENTITY)',raw,re.I):raise ValueError('unsafe or over-budget XML')
 return ET.fromstring(raw)
def friend(row):
 return bool(row and row.get('local_type')==1 and row.get('flag',0)&1 and not row.get('delete_flag',0))
def text_mode(expected,actual):
 if actual==expected:return 'exact'
 # Exactly one LF, not CRLF, blank text, or any run of multiple terminal LFs.
 if isinstance(actual,str) and len(expected)>1 and expected.endswith('\n') and expected[-2] not in '\r\n' and actual==expected[:-1]:return 'single_terminal_lf_removed'
 return None
def matches(j,kind,text,source):
 p=j['payload'];a=j['action']
 if a=='send_text':return kind==1 and text_mode(p['text'],text) is not None
 if a=='mention':
  if kind!=1 or text!=p['text']:return False
  try:at=xml(source).findtext('.//atuserlist') or ''
  except (ValueError,ET.ParseError):return False
  return set(filter(None,at.split(',')))==set(p['members'])
 if a=='reply':
  if kind!=49:return False
  try:r=xml(text)
  except (ValueError,ET.ParseError):return False
  return r.findtext('.//appmsg/type')=='57' and r.findtext('.//appmsg/title')==p['text'] and r.findtext('.//refermsg/svrid')==p['source_id']
 if a=='forward':
  original=j.get('nativeSource') or {}
  if kind!=original.get('kind'):return False
  if kind==1:return text==original.get('text')
  try:r=xml(text);s=xml(original['text'])
  except (ValueError,ET.ParseError,KeyError):return False
  if kind==3:
   ri=r.find('.//img');si=s.find('.//img');return ri is not None and si is not None and bool(si.get('md5')) and ri.get('md5')==si.get('md5')
  if kind==49:
   typ=s.findtext('.//appmsg/type')
   if typ=='6':
    expected=s.findtext('.//filemd5') or s.findtext('.//md5');actual=r.findtext('.//filemd5') or r.findtext('.//md5')
    return bool(expected) and actual==expected and r.findtext('.//appmsg/type')==typ and all(s.findtext('.//'+k) and r.findtext('.//'+k)==s.findtext('.//'+k) for k in ['title','totallen'])
   if typ=='5':return r.findtext('.//appmsg/type')==typ and all(s.findtext('.//appmsg/'+k) and r.findtext('.//appmsg/'+k)==s.findtext('.//appmsg/'+k) for k in ['title','url'])
 return False

def native_message(j,attempt):
 from linux_tool import native,ACCOUNT,decode
 if j['action']=='send_text' and (attempt.get('peer')!=j['peer'] or attempt.get('action')!='send_text' or attempt.get('text')!=j['payload']['text'] or attempt.get('clickScheduled') is not True):return {'state':'unknown','reason':'attempt_identity_mismatch','automaticReplay':False}
 table='Msg_'+hashlib.md5(j['peer'].encode()).hexdigest();found=[];text_rows=[]
 with native('message/message_0.db') as (c,r):
  if r.get('consistency')!='committed':return {'state':'unknown','reason':'native_consistency_gap'}
  if not c.execute('select 1 from sqlite_master where name=?',(table,)).fetchone():return {'state':'unknown','reason':'target_messages_absent'}
  me=c.execute('select rowid from Name2Id where user_name=?',(ACCOUNT,)).fetchone()
  if not me:return {'state':'unknown','reason':'sender_unresolved'}
  rows=c.execute('select server_id,status,local_type,message_content,source,create_time from '+table+' where real_sender_id=? and create_time>=? limit 101',(me[0],int(attempt['startedAt'])-1)).fetchall()
  if len(rows)>100:return {'state':'unknown','reason':'candidate_budget'}
  for x in rows:
   sid=str(x['server_id']&0xffffffffffffffff)
   if not x['server_id'] or sid in attempt['beforeIds'] or x['status']!=2:continue
   text=decode(x['message_content']);src=decode(x['source']) or ''
   if j['peer'].endswith('@chatroom') and text.startswith(ACCOUNT+':\n'):text=text[len(ACCOUNT)+2:]
   if matches(dict(j,nativeSource=attempt.get('nativeSource')),int(x['local_type'])&0xffffffff,text,src):
    found.append(sid)
    if j['action']=='send_text':text_rows.append((sid,text,x['create_time']))
 if len(set(found))!=1:return {'state':'unknown','reason':'no_unique_semantic_receipt','automaticReplay':False}
 result={'state':'accepted','peer':j['peer'],'serverId':found[0],'evidence':'native-sender-status-and-operation-semantics','phoneReceiptConfirmed':False,'automaticResend':False}
 if j['action']=='send_text':
  if len(set(text_rows))!=1:return {'state':'unknown','reason':'no_unique_semantic_receipt','automaticReplay':False}
  sid,actual,created=text_rows[0];expected=j['payload']['text'];mode=text_mode(expected,actual)
  result.update(senderId=ACCOUNT,nativeStatus=2,nativeCreateTime=created,uniqueCandidateCount=1,textComparison={'mode':mode,'expectedText':expected,'actualText':actual,'expectedSHA256':hashlib.sha256(expected.encode()).hexdigest(),'actualSHA256':hashlib.sha256(actual.encode()).hexdigest(),'expectedChars':len(expected),'actualChars':len(actual),'removedTerminalLFCount':1 if mode=='single_terminal_lf_removed' else 0})
  if (j.get('result') or {}).get('sendClicks')==1:result['sendClicks']=1
 return result
