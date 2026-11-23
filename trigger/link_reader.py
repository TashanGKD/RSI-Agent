"""Bounded public observations for admitted article and video links."""
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
from urllib.parse import parse_qs, urljoin, urlsplit
from xml.etree import ElementTree as ET

from rsi_agent.config import ROOT


WECHAT_HOST = 'mp.weixin.qq.com'
BILIBILI_HOSTS = {'bilibili.com', 'www.bilibili.com', 'm.bilibili.com'}
BILIBILI_SHORT = 'b23.tv'
BILIBILI_ID = r'(?:BV[0-9A-Za-z]{10}|av[1-9][0-9]{0,19})'
BILIBILI_HEADERS = {'User-Agent': 'RSI-Agent-LinkReader/0.1', 'Accept-Encoding': 'identity'}
XIAOHONGSHU_HOSTS = {'xiaohongshu.com', 'www.xiaohongshu.com'}
XIAOHONGSHU_SHORT = 'xhslink.com'
# A local fake-IP resolver (for example Clash) answers every public name from
# the RFC 2544 benchmark range and maps it back inside its own proxy.
FAKE_IP = ipaddress.ip_network('198.18.0.0/15')
PROXY_ENV = 'RSI_LINK_PROXY'
# Public article request headers as used by wechat-article-reader.
# https://github.com/Rudy-114/wechat-article-reader
WECHAT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def address(url):
    parts = urlsplit(url)
    if (parts.scheme == 'http' and parts.hostname in
            (BILIBILI_HOSTS | {WECHAT_HOST, BILIBILI_SHORT, XIAOHONGSHU_SHORT})
            and not parts.username and not parts.password and parts.port in (None, 80)):
        parts = parts._replace(scheme='https', netloc=parts.hostname)
    if (len(url) > 2048 or parts.scheme != 'https' or not parts.hostname
            or parts.username or parts.password or parts.port not in (None, 443)
            or any(c.isspace() for c in url)):
        raise ValueError('Public HTTPS link required.')
    return parts


def bilibili_video(url):
    try:
        parts = address(url)
    except ValueError:
        return False
    if parts.hostname in BILIBILI_HOSTS:
        return re.fullmatch('/video/' + BILIBILI_ID + '/?', parts.path) is not None
    return parts.hostname == BILIBILI_SHORT and re.fullmatch(r'/[0-9A-Za-z]{1,24}/?', parts.path) is not None


def xiaohongshu_note_id(parts):
    if parts.hostname in XIAOHONGSHU_HOSTS:
        match = re.fullmatch(r'/(?:explore|discovery/item)/([a-f0-9]{24})/?', parts.path)
        if match:
            return match[1]


def xiaohongshu_link(parts):
    return xiaohongshu_note_id(parts) is not None or (
        parts.hostname == XIAOHONGSHU_SHORT
        and re.fullmatch(r'/(?:a|o)/[0-9A-Za-z]{1,32}/?', parts.path) is not None)


def urls(text, *, video_only=False):
    found = []
    for raw in re.findall(r'https?://[^\s<>"\']+', text):
        url = raw.rstrip('。，！？；：、）)]}')
        try:
            url = address(url).geturl()
        except ValueError:
            continue
        if (not video_only or bilibili_video(url)) and url not in found:
            found.append(url)
        if len(found) == 2:
            break
    return found


def video_link(text, explicit):
    if explicit:
        return explicit if bilibili_video(explicit) else None
    return next(iter(urls(text, video_only=True)), None)


def shared_link(raw):
    if (not isinstance(raw, str) or len(raw.encode()) > 100000
            or '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper()):
        return None
    try:
        apps = ET.fromstring(raw).findall('appmsg')
        if len(apps) != 1 or len(apps[0].findall('url')) != 1:
            return None
        original = apps[0].findtext('url') or ''
        url = address(original).geturl()
        kind = apps[0].findtext('type')
        if kind != '5' and (kind != '4' or not (bilibili_video(url) or xiaohongshu_link(address(url)))):
            return None
    except (ET.ParseError, ValueError):
        return None
    text = '\n'.join(x for x in [apps[0].findtext('title'), apps[0].findtext('des'), original] if x)
    return {'url': url, 'text': text[:3000]}


class Page(HTMLParser):
    def __init__(self, wechat):
        super().__init__(convert_charrefs=True)
        self.stack, self.body, self.main, self.title = [], [], [], []
        self.wechat = wechat
        self.article_title = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.wechat and tag == 'meta' and attrs.get('property') == 'og:title':
            self.article_title = attrs.get('content') or ''
        classes = set((attrs.get('class') or '').split())
        wechat_body = {'js_content', 'rich_media_content', 'rich_media_content_full'}
        selected = (self.wechat and
                    (attrs.get('id') in {'js_content', 'page-content'}
                     or bool(classes & wechat_body)))
        selected = selected or (not self.wechat and tag in ('main', 'article'))
        self.stack.append((tag, selected))
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
        if not self.wechat:
            self.body.append(data)
        if any(item[1] for item in self.stack):
            self.main.append(data)


def content(url, raw, charset='utf-8'):
    page = Page(wechat=urlsplit(url).hostname == WECHAT_HOST)
    page.feed(raw.decode(charset, errors='replace'))
    text = re.sub(r'[ \t\r\f\v]+', ' ', ''.join(page.main or page.body)).strip()
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    if not text:
        return {'state': 'unavailable', 'url': url, 'code': 'ARTICLE_BODY_UNAVAILABLE'}
    title = page.article_title or ''.join(page.title)
    return {'state': 'ready', 'url': url, 'title': title.strip()[:200],
            'text': text[:8000], 'truncated': len(text) > 8000,
            'source_sha256': hashlib.sha256(raw).hexdigest()}


def loopback_proxy():
    value = os.environ.get(PROXY_ENV)
    if not value:
        return None
    parts = urlsplit(value)
    if (parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', '::1', 'localhost') or not parts.port
            or parts.username or parts.password or parts.path not in ('', '/')):
        raise ValueError('Loopback HTTP link proxy required.')
    return parts.hostname, parts.port


def public_connection(parts, timeout):
    host = parts.hostname.encode('idna').decode()
    resolved = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = [ipaddress.ip_address(row[4][0]) for row in resolved]
    if addresses and not all(address.is_global for address in addresses):
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        proxy = loopback_proxy()
        fake = [address for address in addresses if address.version == 4 and address in FAKE_IP]
        # The same resolver also answers with real IPv6 records that have no egress here,
        # so tunnel when every address is either fake or global.
        if (proxy and literal is None and fake
                and all(address in fake or address.is_global for address in addresses)):
            # The real address is only known to the local proxy; tunnel by name.
            # Private, loopback and literal destinations are still refused.
            connection = http.client.HTTPSConnection(*proxy, timeout=timeout,
                                                     context=ssl.create_default_context())
            connection.set_tunnel(host, 443)
            return connection
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('Public destination required.')
    # Pin the checked address; TLS still verifies the original hostname.
    connection = http.client.HTTPSConnection(host, timeout=timeout)
    connection.sock = ssl.create_default_context().wrap_socket(
        socket.create_connection((resolved[0][4][0], 443), timeout=timeout), server_hostname=host)
    return connection


def bilibili_request(parts, *, redirect=False):
    connection = public_connection(parts, 4)
    try:
        target = parts.path + ('?' + parts.query if parts.query else '')
        connection.request('GET', target, headers=BILIBILI_HEADERS)
        response = connection.getresponse()
        if redirect:
            if response.status in (301, 302, 303, 307, 308):
                return address(response.getheader('Location', ''))
            raise ValueError('BILIBILI_SHORT_UNRESOLVED')
        if response.status != 200 or response.headers.get_content_type() != 'application/json':
            raise ValueError('BILIBILI_HTTP_' + str(response.status))
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('BILIBILI_RESPONSE_TOO_LARGE')
        return json.loads(raw), hashlib.sha256(raw).hexdigest()
    finally:
        connection.close()


def fetch_bilibili(url):
    base = {'url': url, 'kind': 'bilibili_video'}
    try:
        parts = address(url)
        part_override = parse_qs(parts.query, keep_blank_values=True).get('p')
        if parts.hostname == BILIBILI_SHORT:
            token = parts.path.strip('/')
            if re.fullmatch(BILIBILI_ID, token):
                parts = parts._replace(netloc='www.bilibili.com', path='/video/' + token)
            else:
                # Follow at most one short redirect, only to a Bilibili video.
                parts = bilibili_request(parts._replace(query='', fragment=''), redirect=True)
        if parts.hostname not in BILIBILI_HOSTS or not bilibili_video(parts.geturl()):
            raise ValueError('BILIBILI_SHORT_TARGET_UNSUPPORTED')
        video = parts.path.split('/')[2]
        requested_part = part_override or parse_qs(parts.query, keep_blank_values=True).get('p', ['1'])
        if len(requested_part) != 1 or not re.fullmatch('[1-9][0-9]{0,3}', requested_part[0]):
            raise ValueError('BILIBILI_PART_UNAVAILABLE')
        part = int(requested_part[0])
        query = 'bvid=' + video if video.startswith('BV') else 'aid=' + video[2:]
        response, proof = bilibili_request(address('https://api.bilibili.com/x/web-interface/view?' + query))
        data = response['data']
        bvid = data['bvid']
        if (response['code'] != 0 or not re.fullmatch(r'BV[0-9A-Za-z]{10}', bvid)
                or video not in (bvid, 'av' + str(data.get('aid'))) or not data['title'].strip()):
            raise ValueError('BILIBILI_VIDEO_UNVERIFIED')
        selected = [page for page in data['pages'] if page.get('page') == part]
        if len(selected) != 1 or type(selected[0]['cid']) is not int or selected[0]['cid'] <= 0:
            raise ValueError('BILIBILI_PART_UNAVAILABLE')
        return dict(base, state='ready', canonical_url=f'https://www.bilibili.com/video/{bvid}/?p={part}',
                    title=data['title'][:200], description=(data.get('desc') or '')[:8000], part=part,
                    part_title=(selected[0].get('part') or '')[:200], source_sha256=proof,
                    content_scope='metadata')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException) as error:
        code = str(error)
        return dict(base, state='unavailable', code=code if re.fullmatch('BILIBILI_[A-Z0-9_]+', code)
                    else 'BILIBILI_METADATA_UNAVAILABLE')


class NoteMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            attrs = dict(attrs)
            field = attrs.get('property')
            if field in ('og:url', 'og:title', 'og:description') and attrs.get('content'):
                self.values.setdefault(field, attrs['content'].strip())


def xiaohongshu_response(parts):
    connection = public_connection(parts, 4)
    try:
        target = parts.path + ('?' + parts.query if parts.query else '')
        connection.request('GET', target, headers={
            'User-Agent': 'RSI-Agent-LinkReader/0.1',
            'Accept': 'text/html', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status in (301, 302, 303, 307, 308):
            return response.getheader('Location', ''), None, None
        if response.status != 200:
            raise ValueError('XIAOHONGSHU_HTTP_' + str(response.status))
        if response.headers.get_content_type() != 'text/html':
            raise ValueError('XIAOHONGSHU_METADATA_UNAVAILABLE')
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('XIAOHONGSHU_PAGE_TOO_LARGE')
        return None, raw, response.headers.get_content_charset() or 'utf-8'
    finally:
        connection.close()


def fetch_xiaohongshu(url, parts):
    base = {'url': url, 'kind': 'xiaohongshu_note'}
    note_id = xiaohongshu_note_id(parts)
    try:
        for hop in range(3):
            location, raw, charset = xiaohongshu_response(parts)
            if location is None:
                page = NoteMetadata()
                page.feed(raw.decode(charset, errors='replace'))
                fields = page.values
                canonical = address(fields.get('og:url', '')) if fields.get('og:url') else None
                if not note_id or canonical is None or xiaohongshu_note_id(canonical) != note_id or not fields.get('og:title'):
                    raise ValueError('XIAOHONGSHU_METADATA_UNAVAILABLE')
                return dict(base, state='ready', content_scope='metadata',
                            canonical_url=f'https://www.xiaohongshu.com/explore/{note_id}',
                            title=fields['og:title'][:200], description=fields.get('og:description', '')[:8000],
                            source_sha256=hashlib.sha256(raw).hexdigest())
            if not location:
                raise ValueError('XIAOHONGSHU_REDIRECT_UNSUPPORTED')
            redirected = address(urljoin(parts.geturl(), location))
            if redirected.hostname in XIAOHONGSHU_HOSTS:
                if redirected.path.rstrip('/') == '/login':
                    raise ValueError('XIAOHONGSHU_LOGIN_REQUIRED')
                if redirected.path == '/404' or redirected.path.startswith('/404/'):
                    raise ValueError('XIAOHONGSHU_NOTE_UNAVAILABLE')
            redirected_id = xiaohongshu_note_id(redirected)
            if not redirected_id or (note_id and note_id != redirected_id):
                raise ValueError('XIAOHONGSHU_REDIRECT_UNSUPPORTED')
            if hop == 2 or redirected == parts:
                raise ValueError('XIAOHONGSHU_REDIRECT_LIMIT')
            parts, note_id = redirected, redirected_id
    except (OSError, ValueError, LookupError, http.client.HTTPException) as error:
        code = str(error)
        return dict(base, state='unavailable', code=code if re.fullmatch('XIAOHONGSHU_[A-Z0-9_]+', code)
                    else 'XIAOHONGSHU_METADATA_UNAVAILABLE')


def fetch(url):
    if bilibili_video(url):
        return fetch_bilibili(url)
    connection = None
    try:
        parts = address(url)
        if xiaohongshu_link(parts):
            return fetch_xiaohongshu(url, parts)
        wechat = parts.hostname == WECHAT_HOST
        connection = public_connection(parts, 10)
        target = (parts.path or '/') + ('?' + parts.query if parts.query else '')
        headers = {'User-Agent': 'RSI-Agent-LinkReader/0.1', 'Accept': 'text/html,text/plain',
                   'Accept-Encoding': 'identity'}
        if wechat:
            headers.update(WECHAT_HEADERS)
        connection.request('GET', target, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            code = 'HTTP_' + str(response.status)
            if wechat and 300 <= response.status < 400:
                location = urlsplit(response.getheader('Location', ''))
                if location.hostname in (None, WECHAT_HOST) and location.path == '/mp/wappoc_appmsgcaptcha':
                    code = 'WECHAT_VERIFICATION_REQUIRED'
            return {'state': 'unavailable', 'url': url, 'code': code}
        kind = response.headers.get_content_type()
        if kind != 'text/html' and (wechat or kind != 'text/plain'):
            return {'state': 'unavailable', 'url': url, 'code': 'UNSUPPORTED_CONTENT'}
        # WeChat HTML includes several MB of scripts even for a short article.
        limit = 8_000_000 if wechat else 1_000_000
        raw = response.read(limit + 1)
        if len(raw) > limit:
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
        if bilibili_video(url):
            value['kind'] = 'bilibili_video'
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
