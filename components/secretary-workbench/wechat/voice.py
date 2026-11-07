"""Bounded private native-ID audio retrieval and reuse of existing local ASR."""
import base64,hashlib,json,os,subprocess,sys,time
from pathlib import Path
TOOLS=Path('/opt/secretary-workbench/notebook/tools')
NODE='node'

def ready_to_attempt(event,root):
    sidecar=Path(root)/'voices'/(hashlib.sha256(event['id'].encode()).hexdigest()+'.json')
    if not sidecar.exists():return True
    d=json.loads(sidecar.read_text())
    return bool(d.get('text')) or time.time()-d.get('attempted',0)>=300

def transcribe(event,root,call):
    folder=Path(root)/'voices';folder.mkdir(mode=0o700,exist_ok=True)
    tag=hashlib.sha256(event['id'].encode()).hexdigest()
    sidecar=folder/(tag+'.json')
    if sidecar.exists():
        data=json.loads(sidecar.read_text())
        if data.get('text'):return data['text']
        if time.time()-data.get('attempted',0)<300:return None
    outcome={'attempted':time.time(),'native_id':event['id'],'local_id':event['local_id'],'server_id':str(event['server_id']),'human_verified':False}
    try:
        data=call({'action':'voice','local_id':event['local_id'],'server_id':event['server_id']})
        if data.get('state')!='audio_ready':raise ValueError('native audio not cached')
        if int(data.get('server_id',0))!=event['server_id']:raise ValueError('native audio identity mismatch')
        raw=base64.b64decode(data['audio_base64'],validate=True)
        if len(raw)>2000000 or hashlib.sha256(raw).hexdigest()!=data['sha256']:raise ValueError('audio integrity mismatch')
        silk=folder/(tag+'.silk');wav=silk.with_suffix('.wav')
        if not silk.exists():
            fd=os.open(silk,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as f:f.write(raw)
        elif silk.is_symlink() or hashlib.sha256(silk.read_bytes()).hexdigest()!=data['sha256']:raise ValueError('cached audio conflict')
        sys.path.insert(0,str(TOOLS));import wechat_voice as reuse
        env=dict(os.environ);env['NODE_PATH']=str(reuse.NODE_MODULES)
        if not wav.exists():
            r=subprocess.run([NODE,str(reuse.wr.FOUNDATION/'decode-voice.cjs'),str(silk),str(wav)],env=env,capture_output=True,timeout=25)
            if r.returncode or not wav.exists():raise ValueError('existing SILK decoder failed')
            wav.chmod(0o600)
        if wav.is_symlink() or wav.stat().st_size>16000000:raise ValueError('invalid WAV')
        with reuse.asr_runner() as runner:
            r=subprocess.run([str(reuse.DOTNET),str(runner),str(wav)],capture_output=True,text=True,timeout=45)
        if r.returncode or len(r.stdout.encode())>200000:raise ValueError('existing local ASR failed')
        result=json.loads(r.stdout.strip().splitlines()[-1]);text=result.get('syntheticSpeech','')
        if not isinstance(text,str) or not text.strip() or len(text.encode())>28000:raise ValueError('empty or invalid ASR')
        outcome.update(text=text,model=result.get('model'),audio_sha256=data['sha256'],state='transcribed')
    except Exception as exc:outcome.update(state='attention',error_type=type(exc).__name__)
    temp=sidecar.with_suffix('.tmp');temp.write_text(json.dumps(outcome,ensure_ascii=False));temp.chmod(0o600);temp.replace(sidecar)
    if outcome.get('text'):
        # WAV is a large derived intermediate; original audio remains in native AUP source.
        candidate=folder/(tag+'.wav')
        if candidate.is_file() and not candidate.is_symlink():candidate.unlink()
    return outcome.get('text')
