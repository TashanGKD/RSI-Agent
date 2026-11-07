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

