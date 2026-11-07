"""Fixed-account, read-only 163 IMAP adapter. No arguments: usage, no network."""
import argparse
import ctypes as C
import email
import email.policy
import imaplib
import json
import os
from pathlib import Path
import re
import ssl
import sys
from datetime import datetime, timezone

ACCOUNT = os.environ.get('SECRETARY_MAIL_ACCOUNT','operator@example.invalid')
HOST = 'imap.163.com'
SERVICE = os.environ.get('SECRETARY_MAIL_KEYCHAIN_SERVICE','org.example.secretary.mail163.imap')
ROOT = Path('/var/lib/secretary-mail/mail163')

def validate_secret(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9]{16}', value):
        raise ValueError('Expected exactly 16 ASCII letters/digits; credential not displayed')

def keychain(secret=None):
    sec = C.CDLL('/System/Library/Frameworks/Security.framework/Security')
    find = sec.SecKeychainFindGenericPassword
    find.argtypes = [C.c_void_p,C.c_uint32,C.c_char_p,C.c_uint32,C.c_char_p,C.POINTER(C.c_uint32),C.POINTER(C.c_void_p),C.POINTER(C.c_void_p)]
    find.restype = C.c_int32
    free = sec.SecKeychainItemFreeContent
    free.argtypes = [C.c_void_p,C.c_void_p]
    add = sec.SecKeychainAddGenericPassword
    add.argtypes = [C.c_void_p,C.c_uint32,C.c_char_p,C.c_uint32,C.c_char_p,C.c_uint32,C.c_void_p,C.POINTER(C.c_void_p)]
    add.restype = C.c_int32
    modify = sec.SecKeychainItemModifyAttributesAndData
    modify.argtypes = [C.c_void_p,C.c_void_p,C.c_uint32,C.c_void_p]
    modify.restype = C.c_int32
    cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cf.CFRelease.argtypes = [C.c_void_p]
    svc, acct = SERVICE.encode(), ACCOUNT.encode()
    size, data, item = C.c_uint32(), C.c_void_p(), C.c_void_p()
    status = find(None,len(svc),svc,len(acct),acct,C.byref(size),C.byref(data),C.byref(item))
    if secret is None:
        if status: raise RuntimeError(f'Keychain lookup failed: OSStatus {status}')
        try:
            value = C.string_at(data,size.value).decode('ascii')
            validate_secret(value)
            return value
        finally:
            if data.value: free(None,data)
            if item.value: cf.CFRelease(item)
    validate_secret(secret)
    raw = secret.encode('ascii')
    if status == 0:
        if data.value: free(None,data)
        try: status = modify(item,None,len(raw),raw)
        finally:
            if item.value: cf.CFRelease(item)
    elif status == -25300:
        status = add(None,len(svc),svc,len(acct),acct,len(raw),raw,None)
    if status: raise RuntimeError(f'Keychain storage failed: OSStatus {status}')

def private_write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(path.parent,0o700)
    fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f: f.write(data)

def inspect_mail(limit):
    secret = keychain()
    c = None
    result = {'account':ACCOUNT,'host':HOST,'port':993,'at':datetime.now(timezone.utc).isoformat(),'readOnly':True}
    run = ROOT / ('reads/' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    try:
        c = imaplib.IMAP4_SSL(HOST,993,ssl_context=ssl.create_default_context(),timeout=20)
        c.login(ACCOUNT,secret)
        secret = None
        # Native IMAP ID identifies this ordinary client; no security checks disabled.
        imaplib.Commands.setdefault('ID',('AUTH','SELECTED'))
        c._simple_command('ID','("name" "TashanSecretary" "version" "1.0" "vendor" "Tashan" "contact" "operator@example.invalid")')
        typ, folders = c.list()
        if typ != 'OK': raise RuntimeError('Mailbox listing rejected')
        result['folderCount'] = len(folders)
        typ, count = c.select('INBOX',readonly=True)
        if typ != 'OK': raise RuntimeError('Read-only INBOX EXAMINE rejected')
        result['messageCount'] = int(count[0])
        def response(name):
            _, v = c.response(name)
            return v[0].decode() if v and isinstance(v[0],bytes) else None
        result['uidValidity'] = response('UIDVALIDITY')
        result['uidNext'] = response('UIDNEXT')
        typ, data = c.uid('SEARCH',None,'ALL')
        if typ != 'OK': raise RuntimeError('UID search rejected')
        uids = data[0].split()
        result['sampleUids'] = [x.decode() for x in uids[-limit:]]
        result['messages'] = []
        for uid in uids[-limit:]:
            typ, before = c.uid('FETCH',uid,'(FLAGS)')
            if typ != 'OK': raise RuntimeError('Initial FLAGS fetch rejected')
            flags_before = sorted(imaplib.ParseFlags(b' '.join(x for x in before if isinstance(x,bytes))))
            typ, rows = c.uid('FETCH',uid,'(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.131072>)')
            if typ != 'OK': raise RuntimeError('Read-only sample fetch rejected')
            literals = [r for r in rows if isinstance(r,tuple)]
            header = next((r[1] for r in literals if b'BODY[HEADER]' in r[0].upper()),b'')
            body = next((r[1] for r in literals if b'BODY[TEXT]' in r[0].upper()),b'')
            if not header: raise RuntimeError('Server returned no message header')
            msg = email.message_from_bytes(header,policy=email.policy.default)
            meta = {'uid':uid.decode(),'messageId':str(msg.get('Message-ID','')),'date':str(msg.get('Date','')),'from':str(msg.get('From','')),'subject':str(msg.get('Subject','')),'bodyBytesFetched':len(body),'bodyMayBeTruncated':len(body)>=131072}
            # Only local original storage; paths derive exclusively from numeric server UIDs.
            if not re.fullmatch(rb'[0-9]+',uid): raise RuntimeError('Invalid UID')
            private_write(run/(uid.decode()+'.eml'),header+body)
            typ, after = c.uid('FETCH',uid,'(FLAGS)')
            if typ != 'OK': raise RuntimeError('Final FLAGS fetch rejected')
            flags_after = sorted(imaplib.ParseFlags(b' '.join(x for x in after if isinstance(x,bytes))))
            meta['flagsUnchanged'] = flags_before == flags_after
            result['messages'].append(meta)
        result['sampleFlagsUnchanged'] = all(x['flagsUnchanged'] for x in result['messages'])
        result['status'] = 'read_verified'
        result['originalsDirectory'] = str(run)
        private_write(run/'receipt.json',json.dumps(result,ensure_ascii=False,indent=2).encode())
        return result
    finally:
        secret = None
        if c:
            try: c.logout()
            except Exception: pass

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['store','read'],nargs='?')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--limit',type=int,default=3,choices=range(1,6))
    a = p.parse_args()
    if not a.action or not a.execute:
        p.print_help(); return
    try:
        if a.action == 'store':
            keychain(sys.stdin.readline().rstrip('\n'))
            print(json.dumps({'account':ACCOUNT,'stored':'macOS Keychain','secretPrinted':False}))
        else:
            r = inspect_mail(a.limit)
            # Headers and body remain local. Ordinary CLI output contains only acceptance metadata.
            print(json.dumps({k:v for k,v in r.items() if k!='messages'},ensure_ascii=False))
    except Exception as e:
        # Authentication failures can contain credential-bearing protocol text: print type only.
        print(json.dumps({'status':'failed','stage':a.action,'errorType':type(e).__name__},ensure_ascii=False))
        sys.exit(1)

if __name__ == '__main__': main()
