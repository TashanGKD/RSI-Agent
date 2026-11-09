"""Protected upstream's read-only static renderer. Authentication is at HTTPS gateway."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse
from pathlib import Path
from http.server import ThreadingHTTPServer
import serve
BASE = _install.path('monitor.cloud_root')
serve.ROOT = BASE / 'public/web'
serve.LIVE = BASE / 'public/data'

class CloudHandler(serve.Handler):
    allowed_hosts = tuple(_install.setting('monitor.cloud','allowed_hosts',['127.0.0.1','localhost']))
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--port', type=int, default=18974)
    a = p.parse_args()
    if not a.execute:
        p.print_help()
    else:
        ThreadingHTTPServer(('127.0.0.1', a.port), CloudHandler).serve_forever()
