import json,tempfile,unittest
from pathlib import Path
from modules.notebook import NotebookService,ValidationError

class CutoverTests(unittest.TestCase):
    def test_archived_local_database_remains_readable_but_refuses_all_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);src=p/'source.json';src.write_text('{"records":[]}');db=p/'db.sqlite3'
            n=NotebookService(db,src,p/'workspace');t=n.create_task({'title':'fixture'})
            db.with_name(db.name+'.online.json').write_text(json.dumps({'url':'https://notes.example.test'}))
            for fn in [lambda:n.create_task({'title':'wrong'}),lambda:n.record(t['id'],{'expectedRevision':t['revision'],'note':'wrong'}),lambda:n.append_record({'text':'wrong'}),lambda:n.attach_asset('a.txt',b'wrong'),lambda:n.set_record_processing('fake','completed')]:
                with self.assertRaises(ValidationError):fn()
            self.assertEqual(len(n.list_tasks()),1)

if __name__=='__main__':unittest.main()
