import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.ocr import find_line,parse_tsv
class OcrTests(unittest.TestCase):
 def test_unique_phrase(self):
  self.assertEqual(find_line([{'text':'磐石科学智能实训营线下2群 (100)','point':[100,20]}],'磐石科学智能实训营线下2群'),[100,20])
 def test_duplicate_is_not_guessed(self):
  with self.assertRaises(ValueError):find_line([{'text':'Join group','point':[1,1]},{'text':'Join group','point':[2,2]}],'Join group')
 def test_wrong_group_rejected(self):
  with self.assertRaises(ValueError):find_line([{'text':'线下群','point':[1,1]}],'线下2群')
 def test_missing_ocr_not_success(self):
  with self.assertRaises(ValueError):find_line([], 'Join group')
 def test_ocr_quotes_are_literal_not_csv_record_delimiters(self):
  s='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t10\t20\t10\t90\t"邀请\n5\t1\t1\t1\t2\t1\t10\t40\t50\t10\t95\t学智能实训营线下2群\n'
  rows=parse_tsv(s);self.assertEqual(len(rows),2);self.assertEqual(rows[1]['point'],[35,45])
