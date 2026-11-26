import base64, json, os, sys, time, urllib.request
import websocket

out_dir, minutes = sys.argv[1], float(sys.argv[2])
target = os.path.join(out_dir, 'screen.png')
status = os.path.join(out_dir, 'status.txt')
STATE_JS = """(() => {
  const t = document.body ? document.body.innerText : '';
  return {
    login_form: t.includes('手机号登录') || t.includes('获取验证码'),
    expired: t.includes('已过期') || t.includes('二维码失效'),
    verify: t.includes('安全验证') || t.includes('滑块') || t.includes('拖动'),
  };
})()"""


class Page:
    def __init__(self):
        pages = json.load(urllib.request.urlopen('http://127.0.0.1:9333/json/list', timeout=5))
        page = next(p for p in pages if p['type'] == 'page' and 'xiaohongshu.com' in p['url'])
        self.ws = websocket.create_connection(page['webSocketDebuggerUrl'], suppress_origin=True, timeout=15)
        self.next_id = 0

    def call(self, method, params=None):
        self.next_id += 1
        self.ws.send(json.dumps({'id': self.next_id, 'method': method, 'params': params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get('id') == self.next_id:
                return message.get('result', {})


def write_status(text):
    with open(status, 'w', encoding='utf-8') as f:
        f.write(text)


page = Page()
end, logged_in_checks = time.time() + minutes * 60, 0
while time.time() < end:
    try:
        state = page.call('Runtime.evaluate', {'expression': STATE_JS, 'returnByValue': True})['result']['value']
        if state['expired']:
            page.call('Page.reload')
            time.sleep(4)
            continue
        shot = page.call('Page.captureScreenshot', {'format': 'png'})['data']
        with open(target + '.tmp', 'wb') as f:
            f.write(base64.b64decode(shot))
        os.replace(target + '.tmp', target)
        if state['verify']:
            write_status('needs_verification')
        elif state['login_form']:
            write_status('waiting_for_scan')
            logged_in_checks = 0
        else:
            logged_in_checks += 1
            write_status('logged_in' if logged_in_checks >= 3 else 'checking')
            if logged_in_checks >= 3:
                break
    except Exception as error:
        write_status('error: %s' % error)
        time.sleep(3)
        try:
            page = Page()
        except Exception:
            pass
    time.sleep(2)
else:
    write_status('timed_out')
