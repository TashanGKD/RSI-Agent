"""Cached-key import requests use fake jobs and generated contact copies only."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import sys
import unittest
from unittest.mock import patch

WORKER=Path(__file__).resolve().parents[2]/'src/MacWorker/mac_worker.py'
spec=importlib.util.spec_from_file_location('cached_import_fixture',WORKER)
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

class CachedImport(unittest.TestCase):
    def setUp(self):
        checkpoint=patch.object(worker,'_playback_checkpoint_factory',return_value=lambda:None)
        checkpoint.start();self.addCleanup(checkpoint.stop)
    def test_missing_cached_keys_never_bootstraps_or_requests_ui(self):
        with tempfile.TemporaryDirectory(prefix='cached-key-missing-') as folder:
            state=Path(folder);source=state/'sources';(source/'fixture/db_storage').mkdir(parents=True)
            output=io.StringIO()
            with patch.object(sys.modules[worker.Jobs.__module__].subprocess,'run') as external,contextlib.redirect_stdout(output):
                worker.main({'action':'import','archive':str(state/'archive'),'sourceRoot':str(source),'account':'fixture'})
            self.assertEqual(json.loads(output.getvalue())['state'],'error')
            external.assert_not_called()
    def test_source_links_and_relative_paths_are_rejected_before_library(self):
        with tempfile.TemporaryDirectory(prefix='cached-source-boundary-') as folder:
            source=Path(folder)/'sources';source.mkdir();(source/'fixture/db_storage').mkdir(parents=True)
            linked=Path(folder)/'linked';linked.symlink_to(source,target_is_directory=True)
            for path in ('relative',str(linked)):
                with self.subTest(path=path),patch.object(worker,'Library') as library,self.assertRaises(ValueError):
                    worker.main({'action':'import','archive':folder,'sourceRoot':path,'account':'fixture'})
                library.assert_not_called()
    def test_contact_scope_does_not_reindex_or_read_message_databases(self):
        with tempfile.TemporaryDirectory(prefix='contact-scope-') as folder:
            state=Path(folder);plain=state/'plain';(plain/'contact').mkdir(parents=True);(plain/'message').mkdir()
            with sqlite3.connect(plain/'contact/contact.db') as db: db.execute('CREATE TABLE contact(username TEXT)');db.execute("INSERT INTO contact VALUES('fixture')")
            message=plain/'message/message_0.db';message.write_bytes(b'not sqlite; contacts must not open this')
            library=worker.Library(state/'archive',source=state/'sources')
            library.import_plain('fixture',plain,contacts_only=True)
            with library.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],0)
                self.assertEqual(db.execute("SELECT status FROM coverage WHERE account='fixture' AND path='contact/contact.db'").fetchone()[0],'ready')
            self.assertEqual(message.read_bytes(),b'not sqlite; contacts must not open this')
    def test_contacts_import_uses_saved_keys_and_returns_contact_manifest_only(self):
        with tempfile.TemporaryDirectory(prefix='cached-import-') as folder:
            state=Path(folder);source=state/'source';account='fixture';(source/account/'db_storage').mkdir(parents=True)
            contact=state/'accounts'/account/'decrypted/contact/contact.db';contact.parent.mkdir(parents=True)
            with sqlite3.connect(contact) as db: db.execute('CREATE TABLE fixture(value TEXT)')
            calls=[]
            class Library:
                def __init__(self,archive,source=None): self.state=state;calls.append(('source',source))
                def coverage(self,account): return [{'path':'contact/contact.db','status':'ready'},{'path':'message/message_0.db','status':'locked'}]
            class Jobs:
                def __init__(self,library): pass
                def consent(self): return True
                def run(self,account,action,contacts_only=False): calls.append((account,action));calls.append(('contacts_only',contacts_only))
                def status(self): return {'state':'done'}
            output=io.StringIO()
            with patch.object(worker,'Library',Library),patch.object(worker,'Jobs',Jobs),contextlib.redirect_stdout(output):
                worker.main({'action':'import','archive':str(state),'account':account,'sourceRoot':str(source),'scope':'contacts'})
            response=json.loads(output.getvalue())
            self.assertIn((account,'import'),calls,'cached import must never request capture/bootstrap')
            self.assertIn(('contacts_only',True),calls)
            self.assertEqual(response['sourceScope'],'contacts')
            self.assertEqual([entry['path'] for entry in response['sourceManifest']],['contact/contact.db'])
            self.assertTrue(response['sourceVerified'])

if __name__=='__main__':unittest.main()
