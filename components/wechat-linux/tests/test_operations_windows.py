import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.windows import parse_app_windows
class WindowsTests(unittest.TestCase):
 def test_wechat_appex_and_main(self):
  s='0xa00072 (has no name): ("com.tencent.wechatappex" "WeChatAppEx")  600x800+340+50  +340+50\n0x200011 "Weixin": ("wechat" "wechat")  905x667+181+117  +181+117'
  self.assertEqual(len(parse_app_windows(s)),2)
 def test_foreign_app_excluded(self):self.assertEqual(parse_app_windows('0x1 "Terminal": ("xterm" "XTerm")  600x500+0+0'),[])
