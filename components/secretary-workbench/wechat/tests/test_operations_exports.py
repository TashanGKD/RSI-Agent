import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.exports import file_identity,validate_bytes
class ExportTests(unittest.TestCase):
 def test_identity_from_actual_native_xml(self):
  m=file_identity('<msg><appmsg><title>a.txt</title><type>6</type><appattach><totallen>3</totallen><filemd5>900150983cd24fb0d6963f7d28e17f72</filemd5></appattach></appmsg></msg>')
  validate_bytes(m,b'abc')
  with self.assertRaises(ValueError):validate_bytes(m,b'xyz')
 def test_file_name_traversal(self):
  with self.assertRaises(ValueError):file_identity('<msg><appmsg><title>../a.txt</title><type>6</type><totallen>3</totallen><filemd5>900150983cd24fb0d6963f7d28e17f72</filemd5></appmsg></msg>')
 def test_wrong_type_not_file(self):
  with self.assertRaises(ValueError):file_identity('<msg><appmsg><type>5</type></appmsg></msg>')
