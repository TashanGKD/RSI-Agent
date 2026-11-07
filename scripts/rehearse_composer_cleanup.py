"""Exercise cancellation in a disposable Qt/Openbox desktop, without WeChat or sending."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
EDITOR = '''
import json,sys
from PyQt5.QtWidgets import QApplication,QTextEdit
from PyQt5.QtCore import QSocketNotifier,QTimer,Qt
app=QApplication([])
class Editor(QTextEdit):
 returns=0;events=[]
 def mousePressEvent(self,event):
  super().mousePressEvent(event);self.events.append(['click',len(self.textCursor().selectedText())])
 def keyPressEvent(self,event):
  if event.key() in (Qt.Key_Return,Qt.Key_Enter):self.returns+=1
  super().keyPressEvent(event);self.events.append([event.key(),len(self.textCursor().selectedText())])
editor=Editor();editor.resize(600,300);editor.move(100,100);editor.show();editor.setFocus()
def request(fd):
 line=sys.stdin.readline()
 if not line:app.quit();return
 command=json.loads(line)
 if command['op']=='set':editor.setPlainText(command['text']);editor.setFocus()
 print(json.dumps({'text':editor.toPlainText(),'returns':editor.returns,'events':editor.events[-20:]}),flush=True)
watch=QSocketNotifier(sys.stdin.fileno(),QSocketNotifier.Read);watch.activated.connect(request)
QTimer.singleShot(200,lambda:print(json.dumps({'window':int(editor.winId()),'x':editor.pos().x(),'y':editor.pos().y()}),flush=True))
app.exec()
'''


def read(child):
    if not select.select([child.stdout], [], [], 5)[0]:
        raise ValueError('Fixture editor timed out')
    line = child.stdout.readline()
    if not line:
        raise ValueError('Fixture editor exited; check Qt/X11 dependencies')
    return json.loads(line)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--source', type=Path, default=ROOT, help='Baseline or candidate checkout; evaluator stays unchanged.')
    args = parser.parse_args()
    if not args.execute:
        parser.print_help()
        return 0
    if sys.platform != 'linux':
        parser.error('Linux with X/VNC, Openbox, GTK3 and PyQt5 is required.')
    source = args.source.resolve()
    wx = source / 'components/secretary-workbench/wechat'
    sys.path[:0] = [str(wx), str(wx / 'host_support')]
    spec = importlib.util.spec_from_file_location('bootstrap', ROOT / 'deploy/wechat-gui/prepare_runtime.py')
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    processes = []
    report = {'source': str(source), 'scope': 'owned Qt editor; fixture identity adapter; no WeChat/profile/sender'}
    with tempfile.TemporaryDirectory(prefix='rsi-cancel-') as folder, tempfile.TemporaryFile() as logs:
        root = Path(folder)
        number = next(n for n in range(193, 250) if not Path(f'/tmp/.X{n}-lock').exists() and not Path(f'/tmp/.X11-unix/X{n}').exists())
        display = ':' + str(number)
        bootstrap.prepare(root, display)
        env = dict(os.environ, DISPLAY=display, XAUTHORITY=str(root / 'Xauthority'),
                   WECHAT_DISPLAY=display, WECHAT_XAUTHORITY=str(root / 'Xauthority'),
                   WECHAT_TOOL_ROOT=folder, WECHAT_PROFILE=str(root / 'absent-profile'), WECHAT_ACCOUNT_ID='wxid_fixture_only',
                   WECHAT_NATIVE_CODE=str(wx), WECHAT_HOST_SUPPORT_CODE=str(wx / 'host_support'),
                   HOME=folder, XDG_CONFIG_HOME=str(root / 'config'), XDG_CACHE_HOME=str(root / 'cache'),
                   XDG_RUNTIME_DIR=folder, GDK_BACKEND='x11', QT_QPA_PLATFORM='xcb')
        os.environ.update(env)
        try:
            processes.append(subprocess.Popen(['Xtigervnc', display, '-geometry', '905x667', '-depth', '24',
                '-rfbport', '-1', '-rfbunixpath', str(root / 'vnc.sock'), '-rfbunixmode', '0600',
                '-SecurityTypes', 'None', '-localhost', '-nolisten', 'tcp', '-auth', str(root / 'Xauthority')], stdout=logs, stderr=logs))
            bootstrap.wait_ready(root, display, 8)
            processes.append(subprocess.Popen(['openbox', '--sm-disable'], stdout=logs, stderr=logs))
            time.sleep(.3)
            child = subprocess.Popen([sys.executable, '-B', '-u', '-c', EDITOR], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=logs, text=True, bufsize=1)
            processes.append(child)
            window = read(child)
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk, Gdk, GLib
            from image_client import Controls
            from native_text import Desktop
            from operations import composer, sending
            cfg = {'header_box': [window['x'], window['y'], window['x'] + 600, window['y'] + 40],
                   'editor': [window['x'] + 450, window['y'] + 150], 'send': [window['x'] + 540, window['y'] + 270]}

            def rpc(op, text=None):
                child.stdin.write(json.dumps({'op': op, 'text': text}) + '\n')
                child.stdin.flush()
                return read(child)

            def guard(*_):
                if display == ':92' or child.poll() is not None:
                    raise ValueError('Owned fixture changed')

            def ui():
                control = Controls(root)
                control.x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
                control.x.XSetInputFocus(control.d, window['window'], 2, 0)
                control.x.XFlush(control.d)
                # Replace account/window binding only; use the actual input/clipboard primitives.
                view = Desktop.__new__(Desktop)
                view.cfg = cfg; view.check = guard; view.target = {'username': 'wxid_fixture_only'}
                view.GLib = GLib; view.clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                view.x = control.x; view.xt = control.t; view.d = control.d
                return view

            def empty(_):
                if rpc('get')['text']:
                    raise ValueError('Editor still contains text')

            driver = SimpleNamespace(root=root, session_bindings={}, ui=lambda _: ui(),
                                     app_windows=lambda: [window], _file_helper=lambda: SimpleNamespace(require_empty_editor=empty))
            cases = []
            for index, prior in enumerate(('', 'Prior memo 中文\nKeep this')):
                payload = '[RSI fixture] unsent 中文 🧪\nSecond line'
                job = {'id': format(index, '032x'), 'peer': 'wxid_fixture_only', 'action': 'send_text', 'payload': {'text': payload}, 'preview': {}}
                composer.save(root, job, {'priorText': prior, 'priorSHA': hashlib.sha256(prior.encode()).hexdigest(),
                                         'state': 'staged', 'binding': cfg, 'window': window})
                rpc('set', payload)
                with patch('operations.sending.scene', side_effect=guard):
                    cleaned = sending.cleanup(driver, job)
                observed = rpc('get')
                cases.append({'case': 'owned-prior' if prior else 'owned-empty', 'cleanup': cleaned,
                              'restored': observed['text'] == prior, 'journal': composer.load(root, job)['state'],
                              'return_keys': observed['returns'], 'remaining_chars': len(observed['text'])})
                if not cleaned:
                    cases[-1]['input_events'] = observed['events']
            for index, attempted in enumerate((False, True), 2):
                job = {'id': format(index, '032x'), 'peer': 'wxid_fixture_only', 'action': 'send_text', 'payload': {'text': 'Owned payload'}, 'preview': {}}
                composer.save(root, job, {'priorText': 'Saved prior', 'state': 'staged', 'binding': cfg, 'window': window})
                text = 'Owned payload' if attempted else 'Foreign memo 中文'
                rpc('set', text)
                attempt = root / (job['id'] + '-attempt.json')
                if attempted:
                    attempt.write_text('original-checkpoint')
                    attempt.chmod(0o600)
                with patch('operations.sending.scene', side_effect=guard):
                    cleaned = sending.cleanup(driver, job)
                observed = rpc('get')
                cases.append({'case': 'attempted' if attempted else 'foreign', 'protected': not cleaned and observed['text'] == text,
                              'prior_preserved': composer.load(root, job)['priorText'] == 'Saved prior',
                              'checkpoint_preserved': not attempted or attempt.read_text() == 'original-checkpoint',
                              'return_keys': observed['returns']})
            report['cases'] = cases
            passed = all(c['cleanup'] and c['restored'] and c['journal'] == 'restored' for c in cases[:2])
            passed &= all(c['protected'] and c['prior_preserved'] and c['checkpoint_preserved'] for c in cases[2:])
            passed &= all(c['return_keys'] == 0 for c in cases)
            report['passed'] = passed
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
