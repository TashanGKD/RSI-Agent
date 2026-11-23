import contextlib,hashlib,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.contract import validate_job
from operations import stickers

MD5='0c93feff4655bb72c9bd5890c5e08748'
PEER='12345@chatroom'

def emoji(md5):return '<msg><emoji md5="%s" len="1"/></msg>'%md5

class StickerTests(unittest.TestCase):
 def test_contract_requires_one_exact_lowercase_md5(self):
  job={'client':'rsi-group','request_id':'r1','peer':PEER,'action':'send_sticker','payload':{'md5':MD5}}
  self.assertEqual(validate_job(job)['payload'],{'md5':MD5})
  for payload in ({'md5':MD5.upper()},{'md5':'x'*32},{},{'md5':MD5,'text':'hi'}):
   with self.assertRaises(ValueError):validate_job(dict(job,payload=payload))
  with self.assertRaises(ValueError):validate_job(dict(job,execution_mode='verified_fast'))

 def test_cells_follow_the_measured_panel_grid_on_the_first_page(self):
  panel={'x':139,'y':232}
  self.assertEqual(stickers.cell_box(panel,0),(162,254,230,322))
  self.assertEqual(stickers.cell_box(panel,5),(162,342,230,410))
  with self.assertRaises(ValueError):stickers.cell_box(panel,20)

 def test_panel_must_be_the_one_new_official_popup(self):
  chat={'id':'0x2','width':623,'height':667};panel={'id':'0x3','width':466,'height':466}
  identity=lambda w:{'class':['wechat','wechat'],'pid':7}
  self.assertEqual(stickers.owned_panel([chat],[chat,panel],identity(chat),identity),panel)
  for after in ([chat],[chat,panel,dict(panel,id='0x4')],[chat,dict(panel,width=400)],[panel]):
   with self.assertRaises(ValueError):stickers.owned_panel([chat],after,identity(chat),identity)
  with self.assertRaises(ValueError):stickers.owned_panel([chat],[chat,panel],identity(chat),lambda w:{'class':['wechat','wechat'],'pid':8})

 def receipt(self,rows,before=()):
  db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
  table='Msg_'+hashlib.md5(PEER.encode()).hexdigest()
  db.execute('create table Name2Id(user_name text)');db.execute("insert into Name2Id values('me'),('other')")
  db.execute('create table '+table+'(local_id integer primary key,server_id int,status int,local_type int,message_content text,create_time int,real_sender_id int)')
  db.executemany('insert into '+table+'(server_id,status,local_type,message_content,create_time,real_sender_id) values(?,?,?,?,?,?)',rows)
  @contextlib.contextmanager
  def native(rel):yield db,{'consistency':'committed'}
  with tempfile.TemporaryDirectory() as root:
   j={'id':'a'*32,'peer':PEER,'payload':{'md5':MD5}}
   Path(root,j['id']+'-attempt.json').write_text(json.dumps({'peer':PEER,'action':'send_sticker','md5':MD5,'startedAt':100,'beforeIds':list(before)}))
   with patch('linux_tool.native',native),patch('linux_tool.ACCOUNT','me'),patch('linux_tool.decode',str):
    return stickers.verify(SimpleNamespace(root=Path(root)),j)

 def test_receipt_requires_one_new_sent_self_sticker_with_the_md5(self):
  sent=(11,2,47,'me:\n'+emoji(MD5),101,1)
  self.assertEqual(self.receipt([sent])['serverId'],'11')
  self.assertEqual(self.receipt([sent])['nativeStatus'],2)
  self.assertEqual(self.receipt([sent],before=['11'])['state'],'not_sent') # an older send is never this receipt
  self.assertEqual(self.receipt([(11,1,47,emoji(MD5),101,1)])['reason'],'native_sticker_not_yet_sent')
  self.assertEqual(self.receipt([(0,1,47,emoji(MD5),101,1)])['reason'],'native_sticker_not_yet_sent')
  self.assertEqual(self.receipt([sent,(12,2,47,emoji(MD5),102,1)])['candidates'],2)

 def test_no_local_row_long_after_the_click_proves_no_send(self):
  # Another sender, another sticker, or a text row never count as this send.
  for rows in ([],[(11,2,47,emoji(MD5),101,2)],[(11,2,47,emoji('b'*32),101,1)],[(11,2,1,MD5,101,1)]):
   self.assertEqual(self.receipt(rows)['state'],'not_sent')
  with patch('operations.stickers.time.time',return_value=130):
   self.assertEqual(self.receipt([])['state'],'unknown')

if __name__=='__main__':unittest.main()
