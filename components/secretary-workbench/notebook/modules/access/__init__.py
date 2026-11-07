"""Private single-owner access; credentials are independent of notebook data."""
import hashlib
import hmac
import secrets
import sqlite3
import time
import re
from http.cookies import SimpleCookie, CookieError
from pathlib import Path
from urllib.parse import urlsplit


class AccessError(ValueError):
    def __init__(self,message='验证未通过，请检查后重试',status=401):
        super().__init__(message);self.status=status


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


class AccessService:
    COOKIE='tashan_session'
    def __init__(self,workspace,public_origin,activation_token=None,device_token=None,clock=time.time):
        u=urlsplit(public_origin)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.path or u.query or u.fragment:
            raise ValueError('在线入口必须是明确的HTTPS Origin')
        self.origin=public_origin;self.host=u.netloc;self.clock=clock
        root=Path(workspace).resolve();folder=root/'access'
        if folder.is_symlink() or not folder.resolve().is_relative_to(root):raise ValueError('访问工作区路径越界')
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db_file=folder/'access.sqlite3'
        if self.db_file.is_symlink():raise ValueError('访问数据库不能使用链接')
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS failures(ip TEXT NOT NULL,at REAL NOT NULL);''')
            if activation_token is not None:
                if len(activation_token)<32:raise ValueError('激活凭证长度不足')
                db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('activation',digest(activation_token)))
                db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('activationExpires',str(clock()+7*86400)))
            if device_token is not None:
                if len(device_token)<32:raise ValueError('设备凭证长度不足')
                db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('device',digest(device_token)))
        self.db_file.chmod(0o600)
    def connect(self):return sqlite3.connect(str(self.db_file),timeout=20)
    def setting(self,db,key):
        r=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone();return r[0] if r else None
    def initialized(self):
        with self.connect() as db:return bool(self.setting(db,'password'))
    def requires_username(self):
        with self.connect() as db:return bool(self.setting(db,'username')) or not self.setting(db,'password')
    def _username(self,username):
        if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_]{3,64}',username):raise AccessError('账号应为3至64位字母、数字或下划线',400)
    def _password(self,password):
        if not isinstance(password,str) or not 8<=len(password)<=256:raise AccessError('密码应为8至256个字符',400)
    def _limit(self,db,ip):
        now=self.clock();db.execute('DELETE FROM failures WHERE at<?',(now-900,))
        if db.execute('SELECT count(*) FROM failures WHERE ip=?',(ip,)).fetchone()[0]>=10:
            raise AccessError('尝试次数较多，请15分钟后重试',429)
    def _session(self,db):
        token=secrets.token_urlsafe(40)
        db.execute('INSERT INTO sessions VALUES(?,?)',(digest(token),self.clock()+14*86400))
        return f'{self.COOKIE}={token}; Path=/; Max-Age={14*86400}; Secure; HttpOnly; SameSite=Strict'
    def activate(self,token,password,ip,username=None):
        self._password(password)
        if username is not None:self._username(username)
        failed=False;cookie=None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._limit(db,ip)
            valid=isinstance(token,str) and len(token)<=256 and hmac.compare_digest(digest(token),self.setting(db,'activation') or '')
            if self.setting(db,'password') or not valid or float(self.setting(db,'activationExpires') or 0)<self.clock():
                db.execute('INSERT INTO failures VALUES(?,?)',(ip,self.clock()));failed=True
            else:
                salt=secrets.token_hex(16)
                hashed=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
                db.execute('INSERT INTO settings VALUES(?,?)',('password',salt+':'+hashed))
                if username is not None:db.execute('INSERT INTO settings VALUES(?,?)',('username',username))
                db.execute("DELETE FROM settings WHERE key IN ('activation','activationExpires')")
                cookie=self._session(db)
        if failed:raise AccessError('激活链接无效、已使用或已过期')
        return cookie
    def login(self,password,ip,username=None):
        self._password(password);failed=False;cookie=None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._limit(db,ip)
            stored=self.setting(db,'password');salt,hashed=stored.split(':') if stored else ('0'*32,'0'*64)
            owner=self.setting(db,'username')
            valid_username=not owner or (isinstance(username,str) and len(username)<=64 and hmac.compare_digest(owner.encode(),username.encode()))
            candidate=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
            if not stored or not valid_username or not hmac.compare_digest(candidate,hashed):
                db.execute('INSERT INTO failures VALUES(?,?)',(ip,self.clock()));failed=True
            else:
                db.execute('DELETE FROM failures WHERE ip=?',(ip,));cookie=self._session(db)
        if failed:raise AccessError('账号或密码不正确，请重新输入')
        return cookie
    def _cookie_token(self,cookie):
        try:
            jar=SimpleCookie();jar.load(cookie or '');m=jar.get(self.COOKIE)
            return m.value if m and 20<=len(m.value)<=256 else None
        except CookieError:return None
    def authenticate(self,cookie,bearer):
        with self.connect() as db:
            if bearer:
                if not bearer.startswith('Bearer ') or not 32<=len(bearer[7:])<=256:return None
                stored=self.setting(db,'device')
                return 'device' if stored and hmac.compare_digest(digest(bearer[7:]),stored) else None
            token=self._cookie_token(cookie)
            if not token:return None
            r=db.execute('SELECT expires FROM sessions WHERE hash=?',(digest(token),)).fetchone()
            return 'human' if r and r[0]>self.clock() else None
    def logout(self,cookie):
        token=self._cookie_token(cookie)
        if token:
            with self.connect() as db:db.execute('DELETE FROM sessions WHERE hash=?',(digest(token),))
        return f'{self.COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict'
