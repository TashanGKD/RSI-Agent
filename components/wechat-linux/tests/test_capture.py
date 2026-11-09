import unittest
from pathlib import Path
from capture import validate_offset, decode_passphrase, validate_binary

class CaptureGuards(unittest.TestCase):
    def test_foreign_binary_rejected(self):
        with self.assertRaises(ValueError):validate_binary('/usr/bin/true')
    def test_offset_cannot_inject_debugger(self):
        for value in ['0x1\nshell touch /tmp/bad',-1,True,0,2**64]:
            with self.assertRaises(ValueError):validate_offset(value)
    def test_secret_shape_rejected(self):
        for value in ['a'*63,'g'*64,'a'*64+'\nother','']:
            with self.assertRaises(ValueError):decode_passphrase(value)
    def test_fixed_binary_and_real_shape(self):
        self.assertEqual(validate_offset(0x87b3cf0),0x87b3cf0)
        self.assertEqual(len(decode_passphrase('a'*64)),32)
        self.assertEqual(validate_binary('/var/lib/secretary-wechat/app/opt/wechat/wechat').name,'wechat')

if __name__=='__main__':unittest.main()
