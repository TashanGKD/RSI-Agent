"""Bounded WCDB snapshots. Original DB/WAL/SHM are opened as byte streams only.

AES/HMAC layout follows the already audited Mac foundation/crypto.py. WAL
checksum/commit rules follow SQLite walformat and Tencent WCDB Repair/Wal.cpp.
No connection to a live encrypted database is ever opened by this module.
"""
import hashlib,hmac,os,sqlite3,stat,struct,tempfile,shutil
from contextlib import contextmanager
from pathlib import Path

PAGE=4096
CAP=64*1024*1024

def private_regular(p):
    p=Path(p).absolute()
    for part in [p,*p.parents]:
        if part.is_symlink():raise ValueError('symlink database component refused')
    if not stat.S_ISREG(p.stat().st_mode):raise ValueError('regular database component required')
    return p

def stamp(paths):
    result=[]
    for p in paths:
        p=Path(p)
        if p.is_symlink():raise ValueError('symlink database component refused')
        if not p.exists():result.append(None);continue
        private_regular(p);s=p.stat()
        result.append([s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns])
    return result

def copy_stable(source,target,budget=CAP,after_copy=lambda:None):
    source,target=Path(source),Path(target)
    src=[source,Path(str(source)+'-wal'),Path(str(source)+'-shm')]
    before=stamp(src);total=sum(x[1] for x in before if x)
    if total>budget:raise ValueError('snapshot budget exceeded')
    target.mkdir(mode=0o700)
    try:
        remaining=budget
        for p in src:
            if not p.exists():continue
            dest=target/p.name
            fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with p.open('rb') as i,os.fdopen(fd,'wb') as out:
                while True:
                    b=i.read(min(1024*1024,remaining+1))
                    if not b:break
                    remaining-=len(b)
                    if remaining<0:raise ValueError('snapshot exceeded budget')
                    out.write(b)
        after_copy()
        if before!=stamp(src):raise ValueError('database changed during snapshot; retry needed')
        return target/source.name,before,total
    except BaseException:shutil.rmtree(target);raise

def page(raw,key,salt,number):
    from Crypto.Cipher import AES
    if len(raw)!=PAGE or len(key)!=32 or number<1:raise ValueError('invalid encrypted page')
    start=16 if number==1 else 0
    mac=hashlib.pbkdf2_hmac('sha512',key,bytes(x^0x3a for x in salt),2,32)
    wanted=hmac.new(mac,raw[start:4032]+struct.pack('<I',number),hashlib.sha512).digest()
    if not hmac.compare_digest(wanted,raw[4032:]):raise ValueError('encrypted page authentication failed')
    body=AES.new(key,AES.MODE_CBC,raw[4016:4032]).decrypt(raw[start:4016])
    return (b'SQLite format 3\0' if number==1 else b'')+body+bytes(80)

def checksum(data,endian,seed=(0,0)):
    if len(data)%8:raise ValueError('invalid checksum input')
    words=struct.unpack(endian+str(len(data)//4)+'I',data);a,b=seed
    for i in range(0,len(words),2):a=(a+words[i]+b)&0xffffffff;b=(b+words[i+1]+a)&0xffffffff
    return a,b

def wal_commits(data):
    if not data:return {'frames':[],'pages':0,'committedFrames':0,'tail':'none'}
    if len(data)<32:raise ValueError('truncated WAL header')
    magic,ver,size=struct.unpack('>III',data[:12])
    if magic not in (0x377f0682,0x377f0683) or ver!=3007000 or size!=PAGE:raise ValueError('unsupported WAL header')
    endian='<' if magic==0x377f0682 else '>';seed=checksum(data[:24],endian)
    if seed!=struct.unpack('>II',data[24:32]):raise ValueError('WAL header checksum mismatch')
    frames=[];committed=0;pages=0;tail='none'
    for pos in range(32,len(data),PAGE+24):
        fh=data[pos:pos+24];body=data[pos+24:pos+24+PAGE]
        if len(fh)!=24 or len(body)!=PAGE:raise ValueError('truncated WAL frame')
        # Old generation tails are normal after WAL reuse, never applied.
        if fh[8:16]!=data[16:24]:tail='old_generation';break
        number,end=struct.unpack('>II',fh[:8])
        if number<1 or number>CAP//PAGE or end>CAP//PAGE:raise ValueError('WAL page budget exceeded')
        seed=checksum(fh[:8]+body,endian,seed)
        if seed!=struct.unpack('>II',fh[16:24]):raise ValueError('WAL frame checksum mismatch')
        frames.append((number,body))
        if end:committed=len(frames);pages=end
    if len(frames)>committed:tail='uncommitted'
    return {'frames':frames[:committed],'pages':pages,'committedFrames':committed,'tail':tail}

@contextmanager
def database(source,key,scratch,allow_baseline=False):
    """A consistency receipt always accompanies the connection, including degradation."""
    source=private_regular(source);scratch=Path(scratch)
    if scratch.is_symlink() or scratch.stat().st_mode&0o077:raise ValueError('private scratch root required')
    with tempfile.TemporaryDirectory(prefix='snapshot-',dir=scratch) as tmp:
        tmp=Path(tmp);copied,signature,total=copy_stable(source,tmp/'raw')
        raw=copied.read_bytes()
        if len(raw)<PAGE or len(raw)%PAGE:raise ValueError('invalid database size')
        salt=raw[:16];wp=Path(str(copied)+'-wal');wal=wp.read_bytes() if wp.exists() else b''
        receipt={'bytesCopied':total,'signature':signature,'consistency':'committed','source':source.name,'gap':None}
        # SQLite fileformat 1.3.7: trust the authenticated size only when the
        # change counter matches version-valid-for. WCDB may preallocate zeros.
        head=page(raw[:PAGE],key,salt,1);physical_pages=len(raw)//PAGE
        logical_pages=struct.unpack('>I',head[28:32])[0]
        if 0<logical_pages<physical_pages and head[24:28]==head[92:96]:
            if any(raw[logical_pages*PAGE:]):raise ValueError('nonzero tail beyond authenticated database size')
            raw=raw[:logical_pages*PAGE]
        receipt['preallocatedZeroPages']=physical_pages-len(raw)//PAGE
        try:w=wal_commits(wal)
        except ValueError as e:
            if not allow_baseline:raise
            w={'frames':[],'pages':0,'committedFrames':0,'tail':'invalid'}
            receipt.update(consistency='baseline_only',gap=str(e))
        out=tmp/'plain.db'
        fd=os.open(out,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w+b') as f:
            for n,pos in enumerate(range(0,len(raw),PAGE),1):f.write(page(raw[pos:pos+PAGE],key,salt,n))
            for n,b in w['frames']:
                if n>w['pages']:continue
                f.seek((n-1)*PAGE);f.write(page(b,key,salt,n))
            if w['pages']:f.truncate(w['pages']*PAGE)
            f.seek(18);f.write(b'\1\1')
        c=sqlite3.connect(out.as_uri()+'?mode=ro&immutable=1',uri=True);c.row_factory=sqlite3.Row
        try:
            if [r[0] for r in c.execute('pragma integrity_check')]!=['ok']:raise ValueError('snapshot integrity failed')
            receipt.update(committedFrames=w['committedFrames'],walTail=w['tail'],integrity='ok')
            yield c,receipt
        finally:c.close()
