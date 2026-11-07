"""Serve only built observer assets on loopback. No source reads or mutations."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, hashlib, json, mimetypes, re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
ROOT = Path(__file__).resolve().parents[1] / 'web/dist'
LIVE = _install.path('monitor_workspace') / 'live'

def resolve_static(url):
    path = unquote(urlsplit(url).path)
    if '\x00' in path or '..' in Path(path).parts or path.startswith(('/private', '/@fs')):
        raise ValueError('not a public observer asset')
    if path in ('/live.json', '/monitor-status.json'):
        target = LIVE / ('live.json' if path == '/live.json' else 'status.json')
        if target.is_file() and (not target.is_symlink()):
            return target
        raise ValueError('not ready')
    if path.startswith('/versions/'):
        if not re.fullmatch('/versions/[0-9]{8}T[0-9]{6}-[a-f0-9]{6}/(snapshot|sources)\\.json', path):
            raise ValueError('invalid data route')
        target = LIVE / path.lstrip('/')
        if any((p.is_symlink() for p in [target] + list(target.parents))):
            raise ValueError('symlink refused')
        if target.is_file():
            return target
        raise ValueError('version expired')
    target = (ROOT / path.lstrip('/')).resolve()
    if path == '/':
        target = ROOT / 'index.html'
    if target != ROOT and ROOT not in target.parents:
        raise ValueError('outside public build')
    if not target.is_file() or target.is_symlink():
        raise ValueError('not found')
    return target

class Handler(BaseHTTPRequestHandler):
    allowed_hosts = ('127.0.0.1', 'localhost')

    def do_GET(self):
        host = self.headers.get('Host', '').split(':')[0]
        if host not in self.allowed_hosts:
            self.send_error(403)
            return
        try:
            path = resolve_static(self.path)
        except ValueError:
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def log_message(self, *args):
        pass
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--port', type=int, default=18974)
    a = p.parse_args()
    if not a.execute:
        p.print_help()
    else:
        server = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
        print('Read-only observer: http://127.0.0.1:' + str(a.port), flush=True)
        server.serve_forever()
