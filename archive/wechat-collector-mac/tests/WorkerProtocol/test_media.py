"""Generated index, account files and PNG only; no real media, keys or processes."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

WORKER=Path(__file__).resolve().parents[2]/'src/MacWorker/mac_worker.py'
spec=importlib.util.spec_from_file_location('media_worker_fixture',WORKER)
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
PNG=bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082')

class MediaBinding(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='media-worker-');self.root=Path(self.folder.name)
        self.archive=self.root/'archive';self.archive.mkdir();self.sources=self.root/'sources';self.account='fixture';(self.sources/self.account/'db_storage').mkdir(parents=True)
        self.chat=hashlib.md5(b'friend').hexdigest();self.source='message/message_0.db'
        cache=self.archive/'media';cache.mkdir();self.image=cache/'fixture.png';self.image.write_bytes(PNG)
        with sqlite3.connect(self.archive/'index.db') as db:
            db.executescript('CREATE TABLE conversations(account TEXT,id TEXT,username TEXT);CREATE TABLE messages(account TEXT,chat TEXT,source TEXT,local_id TEXT,server_id TEXT,time INTEGER,raw TEXT,kind INTEGER);CREATE INDEX message_time ON messages(account,chat,time,local_id);')
            db.execute('INSERT INTO conversations VALUES(?,?,?)',(self.account,self.chat,'friend'))
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)',(self.account,self.chat,self.source,'1','100',1700000000,'raw fixture',3))
    def tearDown(self):self.folder.cleanup()
    def request(self,**changes):
        value=dict(action='attachment',archive=str(self.archive),sourceRoot=str(self.sources),account=self.account,chat='friend',serverId='100',source=self.source,localId=1,createTime=1700000000)
        value.update(changes);return value
    def invoke(self,value,fake=True):
        calls=[]
        class Media:
            def __init__(inner,lib):pass
            def attachment(inner,mid):calls.append(mid);return self.image,'image/png'
        output=io.StringIO()
        with contextlib.ExitStack() as stack:
            if fake:stack.enter_context(patch.object(worker,'Media',Media))
            stack.enter_context(contextlib.redirect_stdout(output));worker.main(value)
        return json.loads(output.getvalue()),calls
    def test_complete_message_identity_is_verified_before_media(self):
        for change in ({'localId':2},{'source':'message/message_9.db'},{'createTime':1700000001},{'account':'another'},{'chat':'other'}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.invoke(self.request(**change))
        response,calls=self.invoke(self.request());self.assertEqual(len(calls),1)
        self.assertEqual(response['messageIdentity'],dict(account=self.account,chat='friend',serverId='100',source=self.source,localId=1,createTime=1700000000))
    def test_negative_synthetic_id_and_ambiguity(self):
        with sqlite3.connect(self.archive/'index.db') as db:db.execute("UPDATE messages SET server_id='0'")
        negative=worker.local_identity(self.source,self.chat,'1')
        response,calls=self.invoke(self.request(serverId=str(negative)));self.assertEqual(len(calls),1)
        self.assertEqual(response['messageIdentity']['serverId'],str(negative))
        with sqlite3.connect(self.archive/'index.db') as db:
            db.execute("UPDATE messages SET server_id='100'")
            db.execute('INSERT INTO messages SELECT account,chat,source,local_id,server_id,time,raw,kind FROM messages')
        with self.assertRaises(ValueError):self.invoke(self.request())
    def test_debug_decode_uses_only_declared_account_file(self):
        source=self.sources/self.account/'msg/attach'/self.chat/'2023-11/Img/fixture.dat';source.parent.mkdir(parents=True);source.write_bytes(PNG)
        response,_=self.invoke(self.request(action='debugImageDecode',relativeFile=str(source.relative_to(self.sources/self.account))),fake=False)
        self.assertEqual(response['mime'],'image/png');self.assertEqual(Path(response['path']).read_bytes(),PNG)
        for relative in ('../outside.dat',str(source)):
            with self.subTest(relative=relative),self.assertRaises(ValueError):self.invoke(self.request(action='debugImageDecode',relativeFile=relative),fake=False)
        outside=self.root/'outside.dat';outside.write_bytes(PNG);source.unlink();source.symlink_to(outside)
        with self.assertRaises(ValueError):self.invoke(self.request(action='debugImageDecode',relativeFile=str(source.relative_to(self.sources/self.account))),fake=False)
    def test_diagnostic_rejects_other_source_cached_key_and_redacts_error(self):
        source=self.sources/self.account/'msg/fixture.dat';source.parent.mkdir();source.write_bytes(PNG)
        keys=self.archive/'keys';keys.mkdir();config=keys/f'{self.account}.keys.json';config.write_text(json.dumps({'db_root':'/fixture/another-account','image_key':'secret-fixture-key'}));config.chmod(0o600)
        request=self.request(action='debugImageDecode',relativeFile='msg/fixture.dat')
        with self.assertRaises(ValueError):self.invoke(request,fake=False)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):worker.respond(request)
        response=json.loads(output.getvalue());self.assertEqual(response['status'],'missing');self.assertNotIn('secret-fixture',response['error']);self.assertNotIn(str(self.root),response['error'])

    def test_only_confirmed_attachment_absence_has_structured_reason(self):
        with sqlite3.connect(self.archive/'index.db') as db:
            db.execute("ALTER TABLE messages ADD COLUMN metadata TEXT DEFAULT '{}'")
            db.execute('UPDATE messages SET kind=43,metadata=?',(json.dumps({'md5':'a'*32}),))
        def response(request):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):worker.respond(request)
            return json.loads(output.getvalue())
        missing=response(self.request())
        self.assertEqual(missing.get('errorCode'),'attachment_not_local')
        self.assertEqual(missing['status'],'missing')
        self.assertNotIn('path',missing)
        for arguments in ([],['--serve']):
            result=subprocess.run([sys.executable,str(WORKER),*arguments],input=json.dumps(self.request())+'\n',text=True,capture_output=True,timeout=10)
            self.assertEqual(json.loads(result.stdout).get('errorCode'),'attachment_not_local')
        # A stale identity must fail before looking up media or assigning a reason.
        self.assertNotIn('errorCode',response(self.request(localId=2)))
        with sqlite3.connect(self.archive/'index.db') as db:db.execute("UPDATE messages SET metadata='{}'")
        self.assertEqual(response(self.request()).get('errorCode'),'attachment_identity_unavailable')
        with patch.object(worker.Media,'attachment',side_effect=PermissionError('/private/fixture-denied')):
            self.assertNotIn('errorCode',response(self.request()))
        with patch.object(worker.Media,'voice',side_effect=ValueError('fixture voice unavailable')):
            self.assertNotIn('errorCode',response(self.request(action='voice')))

if __name__=='__main__':unittest.main()
