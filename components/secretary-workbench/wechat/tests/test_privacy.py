import unittest
from privacy import model_text
class PrivacyTests(unittest.TestCase):
    def test_secret_labels_never_leave_transport(self):
        for text in ['备忘：账号 a@example.test 密码：NOT_A_REAL_PASSWORD','token=FAKE_TOKEN_123','我的密码就是FAKE_SECRET','备忘：账号 a@example.test，密码 FAKE_PASS_123','密码FAKE_PASS_123','password FAKE_PASS_123']:
            r=model_text(text)
            self.assertNotIn('FAKE',r);self.assertNotIn('NOT_A_REAL_PASSWORD',r);self.assertNotIn('a@example.test',r)
    def test_token_business_or_password_file_design_not_secret_values(self):
        for text in ['核对Token补助','希望做一个口令文件接口']:
            self.assertEqual(model_text(text),text)
    def test_regular_text_unchanged(self):self.assertEqual(model_text('秘书：你好'),'秘书：你好')
if __name__=='__main__':unittest.main()
