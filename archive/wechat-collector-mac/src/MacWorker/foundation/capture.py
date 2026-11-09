import os
import json
from pathlib import Path
import subprocess
import threading
import time


def capture_env():
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','USER','LOGNAME','TMPDIR','LANG','LC_ALL','SHELL')}
    env.update({'WXKEY_ONESHOT_GUI':'1','WXKEY_SETUP_TIMEOUT':'30s','WXKEY_PBKDF_PROBE_TIMEOUT':'3m'})
    return env


class Jobs:
    def __init__(self,library):
        self.lib=library;self.lock=threading.Lock();self.current={'state':'idle','message':'等待连接本地聊天记录'}

    def consent(self):
        try:
            p=self.lib.state/'capture-consent.json'
            return json.loads(p.read_text()).get('approved') is True
        except (OSError,ValueError):return False

    def set_consent(self,approved):
        if not isinstance(approved,bool):raise ValueError('invalid consent')
        p=self.lib.state/'capture-consent.json';tmp=p.with_suffix('.tmp')
        tmp.write_text(json.dumps({'approved':approved,'scope':'local-wechat-accounts','updated':int(time.time())}));os.chmod(tmp,0o600);os.replace(tmp,p)

    def update(self,message):
        with self.lock:self.current['message']=message

    def start(self,account,action):
        self.lib.account_path(account)
        if action not in ('capture','import'):raise ValueError('unknown action')
        if action=='capture' and not self.consent():raise ValueError('请先在阅读器中授权后续本机读取')
        with self.lock:
            if self.current['state']=='running':raise ValueError('已有读取任务正在进行')
            self.current={'state':'running','message':'准备本地读取','account':account,'started':int(time.time())}
        threading.Thread(target=self.run,args=(account,action),daemon=True).start()

    def run(self,account,action,contacts_only=False):
        try:
            root=self.lib.account_path(account)
            keydir=self.lib.state/'keys';keydir.mkdir(exist_ok=True,mode=0o700)
            config=keydir/f'{account}.keys.json'
            if action=='capture' and not self.lib.keys_cover(account,config):
                raise ValueError('现有密钥不足，请使用应用中的“连接微信”入口完成连接；旧记录和密钥已保留。')
            if not config.exists():raise ValueError('尚未获取该账号的数据库密钥，请先连接微信')
            if contacts_only:self.lib.import_keys(account,config,self.update,contacts_only=True)
            else:self.lib.import_keys(account,config,self.update)
            with self.lock:self.current['state']='done'
        except Exception as e:
            with self.lock:self.current.update(state='error',message=str(e))

    def status(self):
        with self.lock:return dict(self.current)

    def resume_index(self,account):
        self.lib.account_path(account)
        plain=self.lib.state/'accounts'/account/'decrypted'
        if not (plain/'message').is_dir():raise ValueError('没有可恢复的本机已解密记录')
        with self.lock:
            if self.current['state']=='running':raise ValueError('已有读取任务正在进行')
            self.current={'state':'running','message':'继续整理本机记录','account':account,'started':int(time.time())}
        def resume():
            try:
                self.lib.import_plain(account,plain,self.update)
                with self.lock:self.current.update(state='done',message='本机聊天记录已更新')
            except Exception as e:
                with self.lock:self.current.update(state='error',message=str(e))
        threading.Thread(target=resume,daemon=True).start()
