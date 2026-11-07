import tempfile,unittest,sqlite3,struct,hashlib,hmac,os
from pathlib import Path
from Crypto.Cipher import AES
import snapshot

KEY=b'k'*32;SALT=b's'*16
def checksum(b,seed=(0,0)):
    a,c=seed
    for x,y in zip(struct.unpack('<'+'I'*(len(b)//4),b)[::2],struct.unpack('<'+'I'*(len(b)//4),b)[1::2]):a=(a+x+c)&0xffffffff;c=(c+y+a)&0xffffffff
    return a,c
def encrypted(plain,n):
    start=16 if n==1 else 0;iv=bytes([n%256])*16
    body=AES.new(KEY,AES.MODE_CBC,iv).encrypt(plain[start:4016]);mac=hashlib.pbkdf2_hmac('sha512',KEY,bytes(x^0x3a for x in SALT),2,32)
    enc=body+iv;tag=hmac.new(mac,enc+struct.pack('<I',n),hashlib.sha512).digest()
    return (SALT if n==1 else b'')+enc+tag

class SnapshotTests(unittest.TestCase):
    def empty_page(self,pages=1,counter=1,valid=1):
        raw=bytearray(4096);raw[:16]=b'SQLite format 3\0';raw[16:24]=struct.pack('>H6B',4096,1,1,80,64,32,32)
        raw[24:32]=struct.pack('>II',counter,pages);raw[44:48]=struct.pack('>I',4);raw[56:60]=struct.pack('>I',1);raw[92:100]=struct.pack('>II',valid,3045000)
        raw[100]=13;raw[105:107]=struct.pack('>H',4016)
        return bytes(raw)
    def test_authenticated_logical_size_excludes_only_zero_preallocation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'encrypted.db';src.write_bytes(encrypted(self.empty_page(),1)+bytes(4096*2));before=src.read_bytes()
            with snapshot.database(src,KEY,root) as (c,receipt):
                self.assertEqual(c.execute('select count(*) from sqlite_master').fetchone()[0],0)
                self.assertEqual(receipt['preallocatedZeroPages'],2)
                self.assertEqual(receipt['consistency'],'committed')
            self.assertEqual(src.read_bytes(),before)
    def test_invalid_size_and_zero_active_pages_are_never_skipped(self):
        cases=[self.empty_page(counter=2,valid=1),self.empty_page(pages=0),self.empty_page(pages=2)]
        for head in cases:
            with self.subTest(header=head[24:32]),tempfile.TemporaryDirectory() as td:
                root=Path(td);src=root/'encrypted.db';src.write_bytes(encrypted(head,1)+bytes(4096*2))
                with self.assertRaises(ValueError),snapshot.database(src,KEY,root):pass
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'encrypted.db';src.write_bytes(encrypted(self.empty_page(),1)+encrypted(bytes(4096),2))
            with self.assertRaises(ValueError),snapshot.database(src,KEY,root):pass
    def test_committed_wal_can_grow_into_preallocated_space(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'encrypted.db';src.write_bytes(encrypted(self.empty_page(),1)+bytes(4096*2))
            updated=bytearray(self.empty_page(pages=2));updated[32:40]=struct.pack('>II',2,1)
            head=struct.pack('>6I',0x377f0682,3007000,4096,0,10,20);seed=checksum(head);head+=struct.pack('>2I',*seed);wal=head
            for n,commit,plain in [(1,0,bytes(updated)),(2,2,bytes(4096))]:
                body=encrypted(plain,n);frame=struct.pack('>2I',n,commit);seed=checksum(frame+body,seed);wal+=frame+head[16:24]+struct.pack('>2I',*seed)+body
            Path(str(src)+'-wal').write_bytes(wal)
            with snapshot.database(src,KEY,root) as (c,receipt):
                self.assertEqual(c.execute('pragma page_count').fetchone()[0],2)
                self.assertEqual(receipt['committedFrames'],2)
                self.assertEqual(receipt['integrity'],'ok')
    def test_tampered_encrypted_page_rejected(self):
        p=bytearray(encrypted(b'x'*4096,2));p[12]^=1
        with self.assertRaises(ValueError):snapshot.page(bytes(p),KEY,SALT,2)
    def test_path_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'out').write_bytes(b'x');(p/'link').symlink_to(p/'out')
            with self.assertRaises(ValueError):snapshot.stamp([p/'link'])
    def test_budget_checked_before_copy(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'src').write_bytes(b'x'*4096)
            with self.assertRaises(ValueError):snapshot.copy_stable(p/'src',p/'dest',100)
            self.assertFalse((p/'dest').exists())
    def test_source_change_cleans_partial_files(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'src').write_bytes(b'x'*4096)
            def changed():
                with (p/'src').open('ab') as f:f.write(b'x')
            with self.assertRaises(ValueError):snapshot.copy_stable(p/'src',p/'dest',20000,after_copy=changed)
            self.assertFalse((p/'dest').exists())
    def test_commit_only_and_old_generation_tail_ignored(self):
        head=struct.pack('>6I',0x377f0682,3007000,4096,0,10,20);seed=checksum(head);head+=struct.pack('>2I',*seed)
        def frame(n,commit,data,seed,salts=head[16:24]):
            h=struct.pack('>2I',n,commit);c=checksum(h+data,seed);return h+salts+struct.pack('>2I',*c)+data,c
        f,s=frame(2,2,b'a'*4096,seed);g,t=frame(3,0,b'b'*4096,s)
        old,_=frame(4,4,b'c'*4096,t,b'old-salt')
        r=snapshot.wal_commits(head+f+g+old)
        self.assertEqual(len(r['frames']),1);self.assertEqual(r['pages'],2)
    def test_checksum_failure_never_claims_current(self):
        head=struct.pack('>6I',0x377f0682,3007000,4096,0,10,20);head+=struct.pack('>2I',*checksum(head))
        bad=struct.pack('>2I',1,1)+head[16:24]+b'\0'*8+b'a'*4096
        with self.assertRaises(ValueError):snapshot.wal_commits(head+bad)
    def test_encryption_roundtrip(self):
        plain=b'SQLite format 3\0'+b'x'*4000+b'\0'*80
        self.assertEqual(snapshot.page(encrypted(plain,1),KEY,SALT,1),plain)

