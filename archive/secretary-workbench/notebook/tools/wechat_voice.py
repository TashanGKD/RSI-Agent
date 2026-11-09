#!/usr/bin/env python3
"""Optional bounded extraction/ASR of at most six explicitly exported voice rows."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
import wechat_read as wr

REPO=Path.home()/'WeChatPilot/wechat-collector-mac'
DOTNET=Path.home()/'WeChatPilot/dev-tools/dotnet/dotnet'
SMOKE=REPO/'tests/VoiceSmoke/bin/Debug/net8.0/VoiceSmoke.dll'
NODE_MODULES=REPO/'build/微信记录.app/Contents/Resources/worker/_internal/node_modules'


@contextmanager
def asr_runner(original=SMOKE.parent,cli=REPO/'build/微信记录.app/Contents/Resources/cli'):
    """Reuse existing dependencies in a tiny isolated runner; no installs/writes to them."""
    with tempfile.TemporaryDirectory(prefix='codex-voice-asr-') as d:
        root=Path(d)
        for name in ('VoiceSmoke.dll','VoiceSmoke.deps.json','VoiceSmoke.runtimeconfig.json'):
            shutil.copyfile(Path(original)/name,root/name)
        for artifact in Path(cli).glob('*.dll'):(root/artifact.name).symlink_to(artifact)
        (root/'WechatUiCollector.dll').unlink(missing_ok=True)
        (root/'WechatUiCollector.dll').symlink_to(Path(original)/'WechatUiCollector.dll')
        (root/'runtimes').symlink_to(Path(cli)/'runtimes',target_is_directory=True)
        yield root/'VoiceSmoke.dll'


def validate_voice(row):
    if row.get('account')!=wr.ACCOUNT or row.get('kind')!=34:raise ValueError('unapproved voice row')
    if not re.fullmatch(r'[1-9][0-9]{0,18}',str(row.get('serverId',''))):raise ValueError('exact nonzero server identity required')
    if not re.fullmatch(r'[A-Za-z0-9_@.\-]{1,256}',row.get('nativeChat','')):raise ValueError('invalid native conversation')
    return row


def execute(input_path,outdir):
    input_path=wr.no_symlinks(Path(input_path).absolute());outdir=wr.no_symlinks(Path(outdir).absolute())
    for protected in (wr.NATIVE,wr.ARCHIVE,wr.FOUNDATION):
        if outdir.is_relative_to(protected):raise ValueError('output inside protected source root')
    if (outdir.parent/'voice-followup.json').exists():raise FileExistsError('voice receipt already exists')
    if input_path.stat().st_size>wr.OUTPUT_CAP:raise ValueError('input exceeds bound')
    rows=[validate_voice(r) for line in input_path.read_text().splitlines() if (r:=json.loads(line)).get('kind')==34]
    if not 1<=len(rows)<=6:raise ValueError('requires one to six voice rows')
    outdir.mkdir(mode=0o700) # exclusive; existing output refuses overwrite
    receipt={'inputSha256':wr.digest(input_path),'startedAt':wr.utc(),'sources':[],'voices':[],'deadlineSeconds':285,'scratchBudgetBytes':wr.BUDGET,'sourceWrites':False,'collectorStarted':False,'asrMethod':'existing VoiceSmoke calling LocalTranscriber in isolated temporary runner with existing dependency links; no source change','status':'partial'}
    items=[]
    for r in rows:
        item={'stableId':r['stableId'],'nativeChat':r['nativeChat'],'serverId':r['serverId'],'time':r['time'],'sender':r['sender'],'conversationName':r['conversationName'],'status':'audio-not-found'}
        items.append((r,item));receipt['voices'].append(item)
    deadline=time.monotonic()+285
    def checkpoint():
        if time.monotonic()>deadline:raise TimeoutError('voice deadline')
    def alarm(*_):raise TimeoutError('voice deadline')
    old=signal.signal(signal.SIGALRM,alarm);signal.alarm(285)
    try:
        cfgpath=wr.no_symlinks(wr.ARCHIVE/'keys'/f'{wr.ACCOUNT}.keys.json')
        if cfgpath.stat().st_mode&0o077:raise ValueError('key permissions')
        cfg=json.loads(cfgpath.read_text());root=wr.NATIVE/wr.ACCOUNT/'db_storage'
        if Path(cfg.get('db_root','')).resolve()!=root.parent.resolve():raise ValueError('account mismatch')
        decrypt,*_=wr.codec()
        from media import voice_from_db
        for name in ('media_1.db','media_0.db'):
            if all('silkPath' in i for _,i in items):break
            checkpoint();source=root/'message'/name
            st=wr.stamp(wr.pair(source));planned=2*st[0]['size']+sum(s['size'] for s in st[1:] if s)+50_000_000
            if planned>wr.BUDGET:raise ValueError('media source exceeds scratch budget')
            info={'source':'message/'+name,'plannedPeakBytes':planned,'status':'failed'};receipt['sources'].append(info)
            with tempfile.TemporaryDirectory(prefix='codex-wechat-voice-') as d:
                snap,st=wr.snapshot(source,Path(d),wr.BUDGET-st[0]['size']-50_000_000,checkpoint)
                with snap.open('rb') as f:salt=f.read(16).hex()
                key=cfg['keys'].get(salt,'')
                if not re.fullmatch(r'[a-fA-F0-9]{64}',key):raise ValueError('media key unavailable')
                plain=Path(d)/'plain.db';decrypt(snap,plain,bytes.fromhex(key),checkpoint=checkpoint)
                info.update({'sourceStamp':st,'encryptedSha256':wr.digest(snap,checkpoint),'plaintextSha256':wr.digest(plain,checkpoint),'snapshotAt':wr.utc()})
                for r,item in items:
                    if 'silkPath' in item:continue
                    checkpoint()
                    blob=voice_from_db(plain,{'server_id':r['serverId'],'time':r['timeUnix']},[r['nativeChat']],allow_time=False)
                    if blob:
                        if len(blob)>16_000_000:raise ValueError('voice payload exceeds cap')
                        tag=wr.hashlib.sha256(r['stableId'].encode()).hexdigest()[:20];silk=outdir/(tag+'.silk')
                        fd=os.open(silk,os.O_CREAT|os.O_WRONLY|os.O_EXCL,0o600)
                        with os.fdopen(fd,'wb') as f:f.write(blob)
                        item.update({'status':'audio-extracted','silkPath':str(silk),'silkBytes':len(blob),'silkSha256':wr.digest(silk),'source':info['source'],'association':'exact nativeChat + serverId; time fallback disabled'})
                info['status']='ok'
        node=shutil.which('node')
        for r,item in items:
            if 'silkPath' not in item:continue
            checkpoint();wav=Path(item['silkPath']).with_suffix('.wav')
            if not node:item['decodeError']='node-unavailable';continue
            env=dict(os.environ);env['NODE_PATH']=str(NODE_MODULES)
            try:
                result=subprocess.run([node,str(wr.FOUNDATION/'decode-voice.cjs'),item['silkPath'],str(wav)],capture_output=True,timeout=min(25,max(1,int(deadline-time.monotonic()))),env=env)
                if result.returncode or not wav.exists():item['decodeError']='existing-decoder-failed';continue
                os.chmod(wav,0o600);item.update({'wavPath':str(wav),'wavSha256':wr.digest(wav),'wavBytes':wav.stat().st_size,'status':'audio-decoded-asr-missing'})
                if DOTNET.exists() and SMOKE.exists():
                    # The inspected existing smoke executable accepts a WAV directly;
                    # it does not open message DBs or write transcript stores.
                    with asr_runner() as runner:
                        result=subprocess.run([str(DOTNET),str(runner),str(wav)],capture_output=True,timeout=min(45,max(1,int(deadline-time.monotonic()))))
                    if result.returncode==0:
                        data=json.loads(result.stdout.decode().strip().splitlines()[-1]);text=data.get('syntheticSpeech','')
                        if text:item.update({'status':'transcribed','asrText':text,'asrModel':data.get('model'),'asrHumanVerified':False})
                    else:item['asrError']='existing-runtime-entrypoint-failed'
            except Exception as exc:item['errorType']=type(exc).__name__
        receipt['status']='complete' if all(i['status']=='transcribed' for _,i in items) else 'partial'
    except Exception as exc:receipt['errorType']=type(exc).__name__
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,old);receipt['finishedAt']=wr.utc();receipt['scratchCleaned']=True
        with wr.exclusive_output(outdir.parent/'voice-followup.json') as f:json.dump(receipt,f,ensure_ascii=False,indent=2)
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');p.add_argument('--input');p.add_argument('--output-directory');a=p.parse_args()
    if not a.execute:p.print_help();return 0
    if not a.input or not a.output_directory:p.error('explicit input and output-directory required')
    r=execute(a.input,a.output_directory);print(json.dumps({'status':r['status'],'voiceCount':len(r['voices']),'statuses':[x['status'] for x in r['voices']]}));return 0 if r['status']=='complete' else 2
if __name__=='__main__':raise SystemExit(main())
