"""Local WCDB SQLCipher-4 page decoding. Never publishes partial output."""
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
from Crypto.Cipher import AES
from playback import noop_checkpoint

PAGE = 4096


def _page(page, key, mac_key, number):
    if len(page) != PAGE: raise ValueError('truncated database page')
    start = 16 if number == 1 else 0
    wanted = hmac.new(mac_key, page[start:4032] + struct.pack('<I', number), hashlib.sha512).digest()
    if not hmac.compare_digest(wanted, page[4032:]): raise ValueError(f'page {number}: wrong key or damaged content')
    body = AES.new(key, AES.MODE_CBC, page[4016:4032]).decrypt(page[start:4016])
    return (b'SQLite format 3\0' if number == 1 else b'') + body + bytes(80)


def _checksum(data, endian, previous=(0, 0)):
    if len(data) % 8: raise ValueError('invalid WAL checksum input')
    words = struct.unpack(endian + str(len(data)//4) + 'I', data)
    a,b = previous
    for i in range(0, len(words), 2):
        a=(a+words[i]+b)&0xffffffff; b=(b+words[i+1]+a)&0xffffffff
    return a,b


def _shm_header(path):
    if path is None or not Path(path).exists():return None
    with Path(path).open('rb') as f:data=f.read(96)
    if len(data)!=96 or data[:48]!=data[48:96]:raise ValueError('unstable WAL index header')
    h=data[:48]
    if struct.unpack('<I',h[:4])[0]!=3007000 or h[12]!=1:raise ValueError('unsupported WAL index')
    mxframe=struct.unpack('<I',h[16:20])[0]
    page_size=struct.unpack('<H',h[14:16])[0]
    if page_size!=PAGE and not (mxframe==0 and page_size==0):raise ValueError('WAL index page size mismatch')
    if _checksum(h[:40],'<')!=struct.unpack('<II',h[40:48]):raise ValueError('invalid WAL index checksum')
    return {'frames':struct.unpack('<I',h[16:20])[0],'pages':struct.unpack('<I',h[20:24])[0],'salt':h[32:40],'checksum':struct.unpack('<II',h[24:32]),'big_endian':h[13]}


def wal_frames(path,shm=None,checkpoint=noop_checkpoint):
    """Returns only valid committed frames; rejects truncation/corruption."""
    path=Path(path)
    index=_shm_header(shm)
    if not path.exists() or path.stat().st_size == 0:
        if index and index['frames']:raise ValueError('WAL index references missing log')
        return [], 0
    frames=[]; committed=0; dbsize=0
    with path.open('rb') as f:
        header=f.read(32)
        if len(header)!=32: raise ValueError('truncated WAL header')
        magic,version,size=struct.unpack('>III',header[:12])
        if magic not in (0x377f0682,0x377f0683) or version!=3007000 or size!=PAGE: raise ValueError('unsupported WAL format')
        endian='<' if magic==0x377f0682 else '>'
        checksum=_checksum(header[:24],endian)
        if checksum!=struct.unpack('>II',header[24:32]): raise ValueError('invalid WAL header checksum')
        if index:
            if index['salt']!=header[16:24] or index['big_endian']!=(magic&1):raise ValueError('WAL and index generation differ')
            if path.stat().st_size<32+index['frames']*(24+PAGE):raise ValueError('truncated active WAL range')
            if not index['frames']:return [],0
        while True:
            if len(frames)%256==0:checkpoint()
            if index and len(frames)==index['frames']:break
            fh=f.read(24)
            if not fh: break
            page=f.read(PAGE)
            if len(fh)!=24 or len(page)!=PAGE: raise ValueError('truncated WAL frame')
            pn,commit=struct.unpack('>II',fh[:8])
            if fh[8:16]!=header[16:24] or pn<1: raise ValueError('invalid WAL frame salt or page')
            checksum=_checksum(fh[:8]+page,endian,checksum)
            if checksum!=struct.unpack('>II',fh[16:24]): raise ValueError('invalid WAL frame checksum')
            frames.append((pn,page))
            if commit:
                committed=len(frames);dbsize=commit
        if index and (committed!=index['frames'] or dbsize!=index['pages'] or checksum!=index['checksum']):raise ValueError('WAL index does not match final commit')
    return frames[:committed],dbsize


def decrypt_file(source, output, key, wal=None,shm=None,checkpoint=noop_checkpoint):
    source,output=Path(source),Path(output)
    if len(key)!=32 or source.stat().st_size%PAGE or source.stat().st_size<PAGE: raise ValueError('invalid key or database size')
    with source.open('rb') as f: salt=f.read(16)
    mac_key=hashlib.pbkdf2_hmac('sha512',key,bytes(x^0x3a for x in salt),2,32)
    output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix='.decrypt-',dir=output.parent)
    try:
        with os.fdopen(fd,'w+b') as out, source.open('rb') as src:
            number=1
            while True:
                if (number-1)%256==0:checkpoint()
                page=src.read(PAGE)
                if not page:break
                out.write(_page(page,key,mac_key,number)); number+=1
            frames,dbsize=wal_frames(wal or str(source)+'-wal',shm or str(source)+'-shm',checkpoint=checkpoint)
            for index,(number,page) in enumerate(frames):
                if index%256==0:checkpoint()
                if number>dbsize: continue
                out.seek((number-1)*PAGE);out.write(_page(page,key,mac_key,number))
            if dbsize: out.truncate(dbsize*PAGE)
            # Materialized WAL commits are now in a standalone rollback-mode file.
            out.seek(18);out.write(b'\x01\x01');out.flush();os.fsync(out.fileno())
        checkpoint()
        con=sqlite3.connect(Path(tmp).as_uri()+'?mode=ro&immutable=1',uri=True)
        try:
            result=con.execute('PRAGMA integrity_check').fetchall()
            if result != [('ok',)]: raise ValueError('decrypted database integrity check failed')
        finally: con.close()
        checkpoint()
        os.replace(tmp,output);os.chmod(output,0o600)
    except (sqlite3.Error,ValueError) as exc:
        raise ValueError(str(exc)) from exc
    finally:
        Path(tmp).unlink(missing_ok=True)
