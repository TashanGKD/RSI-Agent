"""Run local adapter checks; optionally run the inherited synthetic Linux suites."""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--linux', action='store_true', help='Also run synthetic Linux WeChat regressions.')
    args = parser.parse_args()
    subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, '-B', '-m', 'rsi_agent', 'mac', 'verify'], cwd=ROOT, check=True)
    if not args.linux:
        return
    if sys.platform != 'linux':
        raise SystemExit('--linux requires Linux; do not count skipped platform tests as passing.')
    with tempfile.TemporaryDirectory(prefix='rsi-agent-tests-') as folder:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                   WECHAT_TOOL_ROOT=str(Path(folder) / 'empty-runtime'),
                   WECHAT_PROFILE=str(Path(folder) / 'empty-profile'),
                   WECHAT_ACCOUNT_ID='wxid_fixture_operator')
        for key in ('DISPLAY', 'XAUTHORITY', 'WECHAT_DISPLAY', 'WECHAT_XAUTHORITY'):
            env.pop(key, None)
        cwd = ROOT / 'components/secretary-workbench/wechat'
        for pattern in ('test_operations*.py', 'test_snapshot.py'):
            subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', pattern], cwd=cwd, env=env, check=True)
        code = "import sys,unittest;sys.path.insert(0,'tests');suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in ['test_linux_tool','test_sender','test_read_metadata','test_receive_source']);result=unittest.TextTestRunner().run(suite);sys.exit(not result.wasSuccessful())"
        subprocess.run([sys.executable, '-B', '-c', code], cwd=cwd, env=env, check=True)
        subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'reader-tests'], cwd=cwd, env=env, check=True)
        # Verify the unified entry really creates and serves the existing notebook.
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        command = [sys.executable, '-B', '-m', 'rsi_agent', 'notebook', '--demo',
                   '--workspace', str(Path(folder) / 'demo'), '--port', str(port)]
        with tempfile.TemporaryFile(mode='w+') as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True)
            try:
                for _ in range(60):
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError('Notebook startup failed: ' + log.read()[-2000:])
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/', timeout=1) as response:
                            page = response.read().decode()
                            assert response.status == 200 and '<html' in page.lower()
                        print('PASS unified notebook: new synthetic workspace -> loopback HTTP 200')
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError('Notebook did not become ready.')
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
