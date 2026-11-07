"""Fake library/jobs only: never touches accounts, keys, WeChat or a worker child."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

WORKER=Path(__file__).resolve().parents[2]/'src/MacWorker/mac_worker.py'
spec=importlib.util.spec_from_file_location('reparse_worker_fixture',WORKER)
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

class ReparseProtocol(unittest.TestCase):
    def setUp(self):
        checkpoint=patch.object(worker,'_playback_checkpoint_factory',return_value=lambda:None)
        checkpoint.start();self.addCleanup(checkpoint.stop)
    @contextlib.contextmanager
    def copies(self):
        with tempfile.TemporaryDirectory(prefix='reparse-manifest-') as folder:
            self.make_copies(Path(folder))
            yield Path(folder)
    def make_copies(self, state):
        for relative in ('contact/contact.db','message/message_0.db'):
            path=state/'accounts/wxid_fixture_a/decrypted'/relative;path.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(path) as db: db.execute('CREATE TABLE fixture(value TEXT)')
    def invoke(self, full, coverage, state=None):
        calls=[]
        class FakeLibrary:
            def __init__(self, archive):
                calls.append(('archive',archive))
                if state is not None: self.state=state
            def coverage(self, account): calls.append(('coverage',account));return coverage
        class FakeJobs:
            def __init__(self, library): pass
            def consent(self): return True
            def run(self, account, action): calls.append((action,account))
            def status(self): return {'state':'done'}
        output=io.StringIO()
        with patch.object(worker,'Library',FakeLibrary),patch.object(worker,'Jobs',FakeJobs),contextlib.redirect_stdout(output):
            worker.main({'action':'capture','archive':'fixture-only','account':'wxid_fixture_a','full':full})
        return json.loads(output.getvalue()),calls
    def test_full_refresh_verifies_selected_source_before_success(self):
        with self.copies() as state:
            result,calls=self.invoke(True,[{'path':'contact/contact.db','status':'ready'},{'path':'message/message_0.db','status':'ready'},{'path':'message/media_0.db','status':'decrypted'},{'path':'message/message_fts.db','status':'error'},{'path':'migrate/unspportmsg.db','status':'locked'}],state)
        self.assertEqual({entry['path'] for entry in result['fullSourceManifest']},{'contact/contact.db','message/message_0.db'})
        self.assertTrue(all(len(entry['sha256'])==64 and entry['bytes']>0 for entry in result['fullSourceManifest']))
        self.assertTrue(result.get('full') and result.get('fullSourceVerified'),'full protocol has no verified whole-source result')
        self.assertEqual(result['fullSourceScope'],'supported_message_databases')
        self.assertEqual(result['fullMessageDatabaseCount'],1)
        self.assertEqual(result['excludedNonMessageDatabaseCount'],3)
        self.assertIn(('capture','wxid_fixture_a'),calls)
        self.assertIn(('coverage','wxid_fixture_a'),calls)
    def test_failed_or_missing_message_source_is_not_full_success(self):
        for coverage in ([],[{'path':'message/message_0.db','status':'ready'}],[{'path':'message/message_0.db','status':'error'}],[{'path':'message/message_0.db','status':'locked'}],[{'path':'message/message_0.db','status':'ready'},{'path':'message/message_1.db','status':'error'}],[{'path':'contact/contact.db','status':'error'},{'path':'message/message_0.db','status':'ready'}],[{'path':'contact/contact.db','status':'ready'},{'path':'message/message_0.db','status':'ready'},{'path':'message/unknown.db','status':'decrypted'}]):
            with self.subTest(coverage=coverage),self.assertRaises(ValueError): self.invoke(True,coverage)
    def test_incremental_semantics_and_archived_history_are_retained(self):
        result,calls=self.invoke(False,[{'path':'message/message_0.db','status':'error'}])
        self.assertEqual(result['state'],'done')
        self.assertEqual(result.get('failedMessageDatabaseCount'),1,'ordinary source failure is silently treated as success')
        self.assertEqual(result.get('messageSourceCount'),1)
        self.assertTrue(result.get('messageCoverageChecked'))
        self.assertIn(('coverage','wxid_fixture_a'),calls)
        with self.copies() as state:
            result,_=self.invoke(True,[{'path':'contact/contact.db','status':'archived'},{'path':'message/message_0.db','status':'archived'}],state)
        self.assertTrue(result.get('fullSourceVerified'))
    def test_ordinary_refresh_reports_locked_mixed_and_empty_message_coverage(self):
        for coverage,count,failed in (([],0,0),([{'path':'message/message_0.db','status':'locked'}],1,1),([{'path':'message/message_0.db','status':'ready'},{'path':'message/biz_message_0.db','status':'error'},{'path':'message/message_fts.db','status':'error'}],2,1)):
            with self.subTest(coverage=coverage):
                result,_=self.invoke(False,coverage)
                self.assertEqual(result.get('messageSourceCount'),count)
                self.assertEqual(result.get('failedMessageDatabaseCount'),failed)
                self.assertEqual(result.get('messageSourceScope'),'supported_message_databases')

    def test_full_flag_is_a_boolean(self):
        with self.assertRaises(ValueError): self.invoke('true',[])
    def test_coverage_labels_do_not_verify_missing_or_corrupt_copies(self):
        coverage=[{'path':'contact/contact.db','status':'archived'},{'path':'message/message_0.db','status':'ready'},{'path':'message/message_1.db','status':'archived'}]
        with tempfile.TemporaryDirectory(prefix='reparse-required-copies-') as folder:
            plain=Path(folder)/'accounts/wxid_fixture_a/decrypted'
            for relative in ('contact/contact.db','message/message_0.db'):
                path=plain/relative;path.parent.mkdir(parents=True,exist_ok=True)
                with sqlite3.connect(path) as db: db.execute('CREATE TABLE fixture(value TEXT)')
            for status in ('ready','archived'):
                coverage[-1]['status']=status
                with self.assertRaises(ValueError): self.invoke(True,coverage,Path(folder))
            missing=plain/'message/message_1.db';missing.write_bytes(b'corrupt fixture')
            with self.assertRaises(ValueError): self.invoke(True,coverage,Path(folder))
            missing.unlink();missing.symlink_to(plain/'message/message_0.db')
            with self.assertRaises(ValueError): self.invoke(True,coverage,Path(folder))
    def test_replaced_file_during_verification_is_rejected(self):
        with self.copies() as state:
            class FakeLibrary: pass
            library=FakeLibrary();library.state=state
            source=state/'accounts/wxid_fixture_a/decrypted/message/message_0.db'
            replacement=source.with_suffix('.replacement')
            shutil.copyfile(source,replacement)
            original_connect=sqlite3.connect
            def replace_on_open(*args,**kwargs):
                db=original_connect(*args,**kwargs)
                os.replace(replacement,source)
                return db
            with patch.object(worker.sqlite3,'connect',replace_on_open),self.assertRaises(ValueError):
                worker.verified_source_database(library,'wxid_fixture_a','message/message_0.db')
    def test_unknown_message_provider_is_only_excluded_after_empty_schema_check(self):
        check=getattr(worker,'empty_non_message_database',None)
        self.assertIsNotNone(check,'unknown provider cannot be classified by a fresh read-only empty-schema integrity check')
        with tempfile.TemporaryDirectory(prefix='reparse-empty-schema-') as folder:
            self.make_copies(Path(folder))
            class FakeLibrary: state=Path(folder)
            path=Path(folder)/'accounts/wxid_fixture_a/decrypted/message/new_provider.db'
            path.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(path) as db: db.execute('VACUUM')
            original=path.read_bytes()
            self.assertTrue(check(FakeLibrary(),'wxid_fixture_a','message/new_provider.db'))
            coverage=[{'path':'contact/contact.db','status':'ready'},{'path':'message/message_0.db','status':'ready'},{'path':'message/new_provider.db','status':'decrypted'}]
            result,_=self.invoke(True,coverage,Path(folder))
            self.assertEqual(result['emptyNonMessageDatabaseCount'],1)
            self.assertEqual(result['excludedNonMessageDatabaseCount'],1)
            self.assertEqual(path.read_bytes(),original,'empty provider classification wrote to its source')
            with sqlite3.connect(path) as db: db.execute('CREATE TABLE unknown_message_kind(value TEXT)')
            self.assertFalse(check(FakeLibrary(),'wxid_fixture_a','message/new_provider.db'),'new unknown tables were permanently allowlisted')
            with self.assertRaises(ValueError): self.invoke(True,coverage,Path(folder))
            path.write_bytes(b'corrupt fixture')
            self.assertFalse(check(FakeLibrary(),'wxid_fixture_a','message/new_provider.db'))
            self.assertFalse(check(FakeLibrary(),'wxid_fixture_a','../outside.db'))

if __name__=='__main__': unittest.main()
