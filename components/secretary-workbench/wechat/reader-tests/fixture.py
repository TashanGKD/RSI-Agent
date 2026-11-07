"""Synthetic in-memory native-schema fixture; no private data or native opener."""
import hashlib
import sqlite3
from contextlib import contextmanager


PEER = 'fixture@chatroom'
SENDER = 'fixture_sender'
TABLE = 'Msg_' + hashlib.md5(PEER.encode()).hexdigest()
QUOTE = ('<msg><appmsg><type>57</type><title>同意这个方案</title>'
         '<refermsg><type>1</type><svrid>18446744073709551615</svrid>'
         '<fromusr>original_sender</fromusr><chatusr>fixture@chatroom</chatusr>'
         '<displayname>原发言者</displayname><content>先做隔离测试</content>'
         '</refermsg></appmsg></msg>')


class Fixture:
    def __init__(self):
        self.connections = {}
        self.opened = []
        for rel in ('contact/contact.db', 'message/message_0.db',
                    'session/session.db', 'message/media_0.db'):
            c = sqlite3.connect(':memory:')
            c.row_factory = sqlite3.Row
            self.connections[rel] = c
        self.connections['contact/contact.db'].executescript('''
            create table contact(username text, remark text, nick_name text, alias text);
            insert into contact values('fixture@chatroom', 'Fixture', '', '');
            insert into contact values('other@chatroom', 'Other', '', '');
        ''')
        self.msg = self.connections['message/message_0.db']
        self.msg.executescript('''
            create table Name2Id(user_name text);
            insert into Name2Id values('fixture_sender');
            create table ''' + TABLE + '''(
                local_id int, server_id int, local_type int, real_sender_id int,
                create_time int, sort_seq int, message_content blob);
        ''')
        self.connections['session/session.db'].executescript('''
            create table Name2Id(user_name text);
            create table SessionUnreadListTable_1(
                server_id int, local_id int, create_time int, username_id int);
            create table SessionTable(username text, last_timestamp int);
        ''')
        self.connections['message/media_0.db'].executescript('''
            create table Name2Id(user_name text);
            create table VoiceInfo(svr_id int, local_id int, create_time int,
                voice_data blob, chat_name_id int);
        ''')

    def add(self, content=QUOTE, kind=(57 << 32) | 49, server=101, at=100):
        self.msg.execute('insert into ' + TABLE + ' values(?,?,?,?,?,?,?)',
                         (server, server, kind, 1, at, server, content))

    @contextmanager
    def open(self, rel):
        self.opened.append(rel)
        yield self.connections[rel], {'consistency': 'committed', 'source': rel}

    def read(self, module, **args):
        return module.Tool(opened=self.open, account='fixture_account').handle({
            'action': 'messages', 'peer': PEER, 'start': 99, 'end': 102, **args})

    def close(self):
        for c in self.connections.values():
            c.close()
