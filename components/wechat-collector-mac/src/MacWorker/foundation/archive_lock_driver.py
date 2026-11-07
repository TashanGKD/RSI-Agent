"""Strict, bounded preparation-only protocol. Never imports legacy worker code."""
import json
import re
import sys
from archive_lock import ArchiveLockError, _Store, _fold_leaf

_LIMIT=8192

def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ArchiveLockError('invalid_request')
        value[key]=item
    return value

def parse_request(raw):
    try:
        if not isinstance(raw,bytes) or not 0<len(raw)<=_LIMIT or b'\0' in raw:raise ValueError()
        # Bound nesting before recursive parsing; strings are scanned separately.
        depth=0;quoted=False;escaped=False
        for c in raw:
            if quoted:
                if escaped:escaped=False
                elif c==92:escaped=True
                elif c==34:quoted=False
            elif c==34:quoted=True
            elif c in (91,123):
                depth+=1
                if depth>4:raise ValueError()
            elif c in (93,125):depth-=1
        value=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=_unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        if isinstance(value,dict) and type(value.get('v')) is int and value['v']==2:
            if set(value)!={'v','op','request','names'} or value['op']!='normalizeNames':raise ValueError()
            if not isinstance(value['request'],str) or not re.fullmatch('[0-9a-f]{32}',value['request']):raise ValueError()
            names=value['names']
            if not isinstance(names,list) or not 1<=len(names)<=2048:raise ValueError()
            for name in names:
                if not isinstance(name,str) or not name or name in ('.','..') or '\0' in name or '/' in name or len(name.encode('utf-8','strict'))>255:raise ValueError()
            return value
        if not isinstance(value,dict) or set(value)!= {'v','request','targets'} or type(value['v']) is not int or value['v']!=1:raise ValueError()
        if not isinstance(value['request'],str) or not re.fullmatch('[0-9a-f]{32}',value['request']):raise ValueError()
        targets=value['targets']
        if not isinstance(targets,list) or not 1<=len(targets)<=2:raise ValueError()
        for target in targets:
            if not isinstance(target,dict) or set(target)!= {'path','mode'}:raise ValueError()
            path=target['path'];mode=target['mode']
            if not isinstance(path,str) or not 1<len(path)<=4096 or '\0' in path or not path.startswith('/') or not isinstance(mode,str) or mode not in ('shared','exclusive'):raise ValueError()
            path.encode('utf-8','strict')
        return value
    except (ValueError,TypeError,UnicodeError,RecursionError,ArchiveLockError):raise ArchiveLockError('invalid_request') from None

def _run(argv,source,sink,store_factory):
    def emit(value):sink.write(json.dumps(value,separators=(',',':'))+'\n');sink.flush()
    if argv!=['--archive-lock']:
        emit({'v':1,'status':'error','code':'invalid_mode'});return 64
    try:
        raw=source.read(_LIMIT+1)
        if len(raw)>_LIMIT or not raw.endswith(b'\n') or raw.count(b'\n')!=1:raise ArchiveLockError('invalid_request')
        request=parse_request(raw)
        if request['v']==2:
            # This branch is names-only: no Store, archive, or coordination I/O.
            try:
                labels={};classes=[]
                for name in request['names']:
                    folded=_fold_leaf(name)
                    if folded not in labels:labels[folded]=len(labels)
                    classes.append(labels[folded])
                value={'v':2,'op':'normalizeNames','status':'normalized','request':request['request'],'classes':classes}
                text=json.dumps(value,separators=(',',':'))+'\n'
                if len(text.encode('utf-8','strict'))>_LIMIT:raise ValueError()
            except Exception:
                emit({'v':2,'op':'normalizeNames','status':'error','request':request['request'],'code':'invalid_request'});return 64
            sink.write(text);sink.flush();return 0
        bindings=store_factory().prepare([(t['path'],t['mode']) for t in request['targets']])
        emit({'v':1,'status':'prepared','request':request['request'],'bindings':bindings});return 0
    except ArchiveLockError as error:
        code=error.code if error.code in ('invalid_request','invalid_user','unsafe_archive','unsafe_coordination','authority_lost') else 'unsafe_archive'
    except Exception:code='unsafe_archive'
    emit({'v':1,'status':'error','code':code});return 64

def main():return _run(sys.argv[1:],sys.stdin.buffer,sys.stdout,_Store)
if __name__=='__main__':raise SystemExit(main())
