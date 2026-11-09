"""Bounded public-page observations for links supplied by the native owner."""
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import sys
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from rsi_agent.config import ROOT


def address(url):
    parts = urlsplit(url)
    if (parts.scheme == 'http' and parts.hostname == 'mp.weixin.qq.com'
            and not parts.username and not parts.password and parts.port in (None, 80)):
        parts = parts._replace(scheme='https', netloc='mp.weixin.qq.com')
    if (len(url) > 2048 or parts.scheme != 'https' or not parts.hostname
            or parts.username or parts.password or parts.port not in (None, 443)
            or any(c.isspace() for c in url)):
        raise ValueError('Public HTTPS link required.')
    return parts


def urls(text):
    found = []
    for raw in re.findall(r'https?://[^\s<>"\']+', text):
        url = raw.rstrip('。，！？；：、）)]}')
        try:
            url = address(url).geturl()
        except ValueError:
            continue
        if url not in found:
            found.append(url)
        if len(found) == 2:
            break
    return found


def shared_link(raw):
    if (not isinstance(raw, str) or len(raw.encode()) > 100000
            or '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper()):
        return None
    try:
        apps = ET.fromstring(raw).findall('appmsg')
        if len(apps) != 1 or apps[0].findtext('type') != '5' or len(apps[0].findall('url')) != 1:
            return None
        original = apps[0].findtext('url') or ''
        url = address(original).geturl()
    except (ET.ParseError, ValueError):
        return None
    text = '\n'.join(x for x in [apps[0].findtext('title'), apps[0].findtext('des'), original] if x)
    return {'url': url, 'text': text[:3000]}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.body, self.main, self.title = [], [], [], []
        self.wechat = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        selected = attrs.get('id') == 'js_content'
        self.wechat = self.wechat or selected
        self.stack.append((tag, selected or tag in ('main', 'article')))
        if len(self.stack) > 256:
            raise ValueError('HTML nesting limit exceeded.')
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3'):
            self.handle_data('\n')
        if tag in ('br', 'img', 'meta', 'link', 'hr', 'input', 'source', 'wbr'):
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        tags = {item[0] for item in self.stack}
        if 'title' in tags:
            self.title.append(data)
        if tags & {'script', 'style', 'noscript', 'head'}:
            return
        self.body.append(data)
        if any(item[1] for item in self.stack):
            self.main.append(data)


def content(url, raw, charset='utf-8'):
    page = Page()
    page.feed(raw.decode(charset, errors='replace'))
    text = re.sub(r'[ \t\r\f\v]+', ' ', ''.join(page.main or page.body)).strip()
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    if not text or (urlsplit(url).hostname == 'mp.weixin.qq.com' and (not page.wechat or not ''.join(page.main).strip())):
        return {'state': 'unavailable', 'url': url, 'code': 'ARTICLE_BODY_UNAVAILABLE'}
    return {'state': 'ready', 'url': url, 'title': ''.join(page.title).strip()[:200],
            'text': text[:8000], 'truncated': len(text) > 8000,
            'source_sha256': hashlib.sha256(raw).hexdigest()}


def fetch(url):
    connection = None
    try:
        parts = address(url)
        host = parts.hostname.encode('idna').decode()
        resolved = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not resolved or any(not ipaddress.ip_address(row[4][0]).is_global for row in resolved):
            raise ValueError('Public destination required.')
        # Pin the checked address; TLS still verifies the original hostname.
        connection = http.client.HTTPSConnection(host, timeout=10)
        connection.sock = ssl.create_default_context().wrap_socket(
            socket.create_connection((resolved[0][4][0], 443), timeout=10), server_hostname=host)
        target = (parts.path or '/') + ('?' + parts.query if parts.query else '')
        connection.request('GET', target, headers={'User-Agent': 'RSI-Agent-LinkReader/0.1',
            'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status != 200:
            return {'state': 'unavailable', 'url': url, 'code': 'HTTP_' + str(response.status)}
        kind = response.headers.get_content_type()
        if kind not in ('text/html', 'text/plain'):
            return {'state': 'unavailable', 'url': url, 'code': 'UNSUPPORTED_CONTENT'}
        raw = response.read(1000001)
        if len(raw) > 1000000:
            return {'state': 'unavailable', 'url': url, 'code': 'PAGE_TOO_LARGE'}
        if kind == 'text/plain':
            text = raw.decode('utf-8', errors='replace')
            return {'state': 'ready', 'url': url, 'title': '', 'text': text[:8000],
                    'truncated': len(text) > 8000, 'source_sha256': hashlib.sha256(raw).hexdigest()}
        return content(url, raw, response.headers.get_content_charset() or 'utf-8')
    except (OSError, ValueError, LookupError, http.client.HTTPException):
        return {'state': 'unavailable', 'url': url, 'code': 'PUBLIC_PAGE_UNAVAILABLE'}
    finally:
        if connection is not None:
            connection.close()


def linked_pages(db, source, text, explicit=None):
    links = [explicit] if explicit else urls(text)
    if not links:
        return []
    db.execute('CREATE TABLE IF NOT EXISTS link_reads(source TEXT,url TEXT,value TEXT,PRIMARY KEY(source,url))')
    pages = []
    for url in links:
        cached = db.execute('SELECT value FROM link_reads WHERE source=? AND url=?', (source, url)).fetchone()
        if cached:
            pages.append(json.loads(cached[0]))
            continue
        value = {'state': 'unavailable', 'url': url, 'code': 'PUBLIC_PAGE_UNAVAILABLE'}
        try:
            result = subprocess.run([sys.executable, '-B', '-m', 'trigger.link_reader', url], cwd=ROOT,
                                    capture_output=True, text=True, timeout=20)
            if result.returncode == 0 and len(result.stdout.encode()) < 100000:
                value = json.loads(result.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        with db:
            db.execute('INSERT INTO link_reads VALUES(?,?,?)', (source, url, json.dumps(value)))
        pages.append(value)
    return pages


if __name__ == '__main__':
    print(json.dumps(fetch(sys.argv[1]), ensure_ascii=False))
