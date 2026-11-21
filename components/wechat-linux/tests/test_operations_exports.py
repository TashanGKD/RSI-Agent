import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.exports import file_identity,validate_bytes,FileTooLarge
class ExportTests(unittest.TestCase):
 def test_identity_from_actual_native_xml(self):
  m=file_identity('<msg><appmsg><title>a.txt</title><type>6</type><appattach><totallen>3</totallen><filemd5>900150983cd24fb0d6963f7d28e17f72</filemd5></appattach></appmsg></msg>')
  validate_bytes(m,b'abc')
  with self.assertRaises(ValueError):validate_bytes(m,b'xyz')
 def test_file_name_traversal(self):
  with self.assertRaises(ValueError):file_identity('<msg><appmsg><title>../a.txt</title><type>6</type><totallen>3</totallen><filemd5>900150983cd24fb0d6963f7d28e17f72</filemd5></appmsg></msg>')
 def test_wrong_type_not_file(self):
  with self.assertRaises(ValueError):file_identity('<msg><appmsg><type>5</type></appmsg></msg>')
 def test_large_file_within_budget_and_oversize_is_distinct(self):
  xml='<msg><appmsg><title>a.pdf</title><type>6</type><appattach><totallen>{}</totallen></appattach><md5>900150983cd24fb0d6963f7d28e17f72</md5></appmsg></msg>'
  self.assertEqual(file_identity(xml.format(12536601))['size'],12536601)
  with self.assertRaises(FileTooLarge):file_identity(xml.format(25000001))
