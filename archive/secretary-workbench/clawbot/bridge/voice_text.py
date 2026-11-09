"""Current-item voice text, never inferred from latest inbound or quoted items."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from .child_exec import run_limited


def platform_text(item):
    if type(item.get('type')) is not int or item['type'] != 3:return None
    obj=item.get('voice_item')
    text=obj.get('text') if isinstance(obj,dict) else None
    return text if isinstance(text,str) and text.strip() else None


def prompt(raw,items,transcripts=(),*,compact=False):
    """Preserve typed-only input exactly; label ordered voice/mixed input.

    No truncation, recursive reference promotion, prefix stripping or summaries.
    """
    if not isinstance(items,list) or len(items)>20:raise ValueError('invalid current input items')
    if not all(isinstance(i,dict) for i in items):raise ValueError('invalid current item')
    voices=any(type(i.get('type')) is int and i['type']==3 for i in items)
    if not voices:return raw
    typed=''.join(i.get('text_item',{}).get('text','') for i in items if type(i.get('type')) is int and i['type']==1)
    if typed!=raw:raise ValueError('current text differs from immutable input')
    local={t['index']:t for t in transcripts if t.get('provenance')=='local'}
    blocks=[]
    for n,item in enumerate(items):
        kind=item.get('type');text=None
        if type(kind) is int and kind==1:
            text=item.get('text_item',{}).get('text','');label='文字'
        elif type(kind) is int and kind==3:
            text=platform_text(item);label='语音转写（微信自动识别）'
            if text is None:
                text=local.get(n,{}).get('text');label='语音转写（本地自动识别，待核）'
            if text is None:text='未取得可用转写；音频读取状态见附件收据。';label='语音（未识别）'
        else:label='附件';text='见本条附件收据。'
        if not isinstance(text,str):raise ValueError('invalid current item text')
        blocks.append(label+'\n'+text if compact and len(items)==1 else '[第%d项 · %s]\n%s\n[/第%d项]'%(n+1,label,text,n+1))
        ref=item.get('ref_msg')
        if isinstance(ref,dict):
            # Never expose CDN locators/keys, or recursively promote a forwarded
            # envelope into current sender speech. Full source stays in intake.
            quoted=ref.get('message_item',{})
            evidence={k:ref[k] for k in ('title','svr_id') if isinstance(ref.get(k),str)}
            if isinstance(quoted,dict):
                evidence['type']=quoted.get('type')
                for name in ('text_item','voice_item'):
                    obj=quoted.get(name)
                    if isinstance(obj,dict) and isinstance(obj.get('text'),str):evidence[name]=obj['text']
            blocks.append('[引用资料（非本人当前输入）]\n'+json.dumps(evidence,ensure_ascii=False,sort_keys=True)+'\n[/引用资料]')
    result='\n'.join(blocks)
    if len(result.encode())>65536 or '\0' in result:raise ValueError('voice input exceeds native text limits')
    return result


def local_asr(wav,timeout=45):
    """Reuse installed read-only VoiceSmoke/LocalTranscriber, at most 45s.

    Only private regular WAV files; no shell, installs, source DBs or service.
    Nonempty ASR is recognition evidence, not human verification.
    """
    wav=Path(wav)
    if not wav.is_absolute():raise ValueError('ASR requires absolute managed WAV')
    for p in (wav,*wav.parents):
        if p.is_symlink():raise ValueError('ASR symlink refused')
    st=wav.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_size>16777216:
        raise ValueError('unsafe ASR WAV')
    with wav.open('rb') as f:header=f.read(12)
    if header[:4]!=b'RIFF' or header[8:12]!=b'WAVE':raise ValueError('invalid ASR WAV')
    tool=Path('/opt/secretary-workbench/notebook/tools/wechat_voice.py')
    spec=importlib.util.spec_from_file_location('clawbot_existing_voice',tool)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if not module.DOTNET.is_file() or not module.SMOKE.is_file():raise ValueError('existing local ASR unavailable')
    with module.asr_runner() as runner,tempfile.TemporaryFile() as out:
        result=run_limited([str(module.DOTNET),str(runner),str(wav)],1024*1024,stdout=out,stderr=subprocess.DEVNULL,
                           timeout=max(.1,min(45,timeout)))
        if result.returncode or out.tell()>1024*1024:raise ValueError('existing local ASR failed')
        out.seek(0);data=json.loads(out.read(1024*1024).decode().splitlines()[-1])
    text=data.get('syntheticSpeech')
    if not isinstance(text,str) or not text.strip() or len(text.encode())>32000 or '\0' in text:raise ValueError('local ASR text unavailable')
    return {'text':text,'model':data.get('model'),'human_verified':False}
