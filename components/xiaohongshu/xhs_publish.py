"""Prepare and publish Xiaohongshu image notes through a logged-in Chrome.

The browser runs elsewhere (for example in WSL) with a remote debugging port.
Publishing is split into two commands so a person can review the filled form:

    prepare  fills a dedicated creator-center tab and records a job
    publish  clicks the publish button for that job, once, after confirmation

Every job keeps its state in a private directory. A job whose publish click
has happened is never clicked again, even when the outcome is unclear.
"""
import argparse
import base64
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import random
import re
import sys
import time
import urllib.parse
import urllib.request

DEFAULT_CDP = 'http://127.0.0.1:9333'
DEFAULT_STATE = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'RSI-Xiaohongshu'
PUBLISH_URL = 'https://creator.xiaohongshu.com/publish/publish?source=official'

TITLE_LIMIT = 20
BODY_LIMIT = 1000
IMAGE_LIMIT = 18
IMAGE_BYTES_LIMIT = 32 * 1024 * 1024
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}
VISIBILITY = ('公开可见', '仅自己可见', '仅互关好友可见')
DECLARATIONS = ('虚构演绎，仅供娱乐', '笔记含AI合成内容', '内容包含营销广告')

# Creator-center page structure observed on 2026-11-26. Update here when the page changes.
SELECTORS = {
    'image_tab': '.creator-tab',
    'upload_input': 'input.upload-input, input[type=file]',
    'title': 'input.d-text[placeholder*="标题"]',
    'editor': 'div.tiptap.ProseMirror',
    'topic_list': '#creator-editor-topic-container',
    'topic_item': '#creator-editor-topic-container .item',
    'bound_topic': 'a.tiptap-topic',
    'select_value': '.d-select-description',
    'select_placeholder': '.d-select-placeholder',
    'option': '.d-options-wrapper .d-grid-item',
    'publish_host': 'xhs-publish-btn',
}
PHONE_BLOCK_TEXT = '绑定手机号后才可发布笔记'
STATES_BEFORE_CLICK = {'prepared'}


class PublishError(RuntimeError):
    def __init__(self, code, detail=''):
        super().__init__(code + (': ' + detail if detail else ''))
        self.code = code


# ---------------------------------------------------------------- drafts

def browser_path(path, style):
    """Return the path the browser host sees for a local file."""
    if style == 'native':
        return str(path)
    windows = PureWindowsPath(str(path))
    if not windows.drive:
        return str(path).replace('\\', '/')
    drive = windows.drive.rstrip(':').lower()
    return '/mnt/' + drive + '/' + '/'.join(windows.parts[1:])


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def load_draft(path):
    """Validate a draft file and return it with absolute image paths and digests."""
    path = Path(path)
    draft = json.loads(path.read_text(encoding='utf-8'))
    unknown = set(draft) - {'title', 'body', 'images', 'topics', 'visibility', 'declaration'}
    if unknown:
        raise PublishError('DRAFT_UNKNOWN_FIELDS', ', '.join(sorted(unknown)))
    title = draft.get('title', '')
    body = draft.get('body', '')
    topics = draft.get('topics', [])
    images = draft.get('images', [])
    if not isinstance(title, str) or not title.strip() or len(title) > TITLE_LIMIT:
        raise PublishError('DRAFT_TITLE', 'title must have 1-%d characters' % TITLE_LIMIT)
    if not isinstance(body, str) or not body.strip():
        raise PublishError('DRAFT_BODY', 'body is required')
    if '#' in body or '@' in body:
        raise PublishError('DRAFT_BODY', 'put topics in "topics"; "#" and "@" open suggestion lists in the editor')
    if not isinstance(topics, list) or not all(isinstance(t, str) and t.strip() and '#' not in t for t in topics):
        raise PublishError('DRAFT_TOPICS', 'topics are names without "#"')
    if len(body) + sum(len(t) + 2 for t in topics) > BODY_LIMIT:
        raise PublishError('DRAFT_BODY', 'body and topics exceed %d characters' % BODY_LIMIT)
    if draft.get('visibility') not in VISIBILITY:
        raise PublishError('DRAFT_VISIBILITY', 'choose one of ' + ' / '.join(VISIBILITY))
    if draft.get('declaration') not in (None,) + DECLARATIONS:
        raise PublishError('DRAFT_DECLARATION', 'use null or one of ' + ' / '.join(DECLARATIONS))
    if not isinstance(images, list) or not 1 <= len(images) <= IMAGE_LIMIT:
        raise PublishError('DRAFT_IMAGES', 'add 1-%d images' % IMAGE_LIMIT)
    resolved = []
    for item in images:
        image = (path.parent / item).resolve()
        if image.suffix.lower() not in IMAGE_SUFFIXES:
            raise PublishError('DRAFT_IMAGE_TYPE', str(image))
        if not image.is_file():
            raise PublishError('DRAFT_IMAGE_MISSING', str(image))
        if image.stat().st_size > IMAGE_BYTES_LIMIT:
            raise PublishError('DRAFT_IMAGE_SIZE', str(image))
        resolved.append({'path': str(image), 'sha256': file_sha256(image)})
    return {'title': title, 'body': body.strip(), 'topics': [t.strip() for t in topics],
            'visibility': draft['visibility'], 'declaration': draft.get('declaration'),
            'images': resolved}


def content_sha256(draft):
    canonical = dict(draft, images=[image['sha256'] for image in draft['images']])
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def readback_matches(draft, readback):
    """List the fields where the filled page differs from the draft."""
    problems = []
    if readback.get('title') != draft['title']:
        problems.append('title')
    if normalize_text(readback.get('body_text', '')) != normalize_text(expected_body_text(draft)):
        problems.append('body')
    if readback.get('topics') != draft['topics']:
        problems.append('topics')
    if readback.get('image_count') != len(draft['images']):
        problems.append('images')
    if readback.get('visibility') != draft['visibility']:
        problems.append('visibility')
    if readback.get('declaration') != draft['declaration']:
        problems.append('declaration')
    return problems


def expected_body_text(draft):
    tail = ' '.join('#' + topic for topic in draft['topics'])
    return draft['body'] + ('\n' + tail if tail else '')


def normalize_text(text):
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.replace('\xa0', ' ').splitlines()]
    return '\n'.join(line for line in lines if line)


# ---------------------------------------------------------------- jobs

class Jobs:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / 'jobs').mkdir(parents=True, exist_ok=True)

    def path(self, job_id):
        if not re.fullmatch(r'[0-9a-f]{16}', job_id):
            raise PublishError('JOB_ID', job_id)
        return self.root / 'jobs' / job_id

    def load(self, job_id):
        record = self.path(job_id) / 'job.json'
        if not record.is_file():
            raise PublishError('JOB_NOT_FOUND', job_id)
        return json.loads(record.read_text(encoding='utf-8'))

    def save(self, job):
        folder = self.path(job['id'])
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / 'job.json.tmp'
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, folder / 'job.json')

    def all(self):
        for record in sorted((self.root / 'jobs').glob('*/job.json')):
            yield json.loads(record.read_text(encoding='utf-8'))

    def transition(self, job, state, **detail):
        job['state'] = state
        job.setdefault('history', []).append({'at': now(), 'state': state, **detail})
        self.save(job)

    @contextlib.contextmanager
    def lock(self):
        """Allow one browser operation at a time across processes."""
        lock = self.root / 'browser.lock'
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise PublishError('BROWSER_BUSY', 'another operation holds %s; remove it only if no publisher is running' % lock)
        try:
            os.write(handle, ('%d %s' % (os.getpid(), now())).encode())
            os.close(handle)
            yield
        finally:
            lock.unlink(missing_ok=True)


def now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec='seconds')


def require_state(job, allowed, action):
    if job['state'] not in allowed:
        raise PublishError('JOB_STATE', '%s needs %s, job %s is %s' % (action, '/'.join(sorted(allowed)), job['id'], job['state']))


# ---------------------------------------------------------------- browser

class Browser:
    def __init__(self, endpoint):
        self.endpoint = endpoint.rstrip('/')

    def request(self, path, method='GET'):
        request = urllib.request.Request(self.endpoint + path, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as response:
            body = response.read().decode('utf-8')
        return json.loads(body) if body.startswith(('{', '[')) else body

    def tabs(self):
        return [tab for tab in self.request('/json/list') if tab.get('type') == 'page']

    def open(self, url):
        return Page(self.request('/json/new?' + urllib.parse.quote(url, safe=':/?&=%'), method='PUT'))

    def attach(self, tab_id):
        for tab in self.tabs():
            if tab['id'] == tab_id:
                return Page(tab)
        raise PublishError('TAB_GONE', 'the prepared tab %s was closed' % tab_id)

    def close(self, tab_id):
        with contextlib.suppress(Exception):
            self.request('/json/close/' + tab_id)


class Page:
    def __init__(self, tab):
        import websocket  # websocket-client; imported here so tests do not need it
        self.id = tab['id']
        self.socket = websocket.create_connection(tab['webSocketDebuggerUrl'], suppress_origin=True, timeout=30)
        self.next_id = 0
        self.mouse = (random.uniform(200, 900), random.uniform(150, 600))
        self.call('Page.enable')

    def call(self, method, **params):
        self.next_id += 1
        self.socket.send(json.dumps({'id': self.next_id, 'method': method, 'params': params}))
        while True:
            message = json.loads(self.socket.recv())
            if message.get('method') == 'Page.javascriptDialogOpening':
                self.socket.send(json.dumps({'id': 0, 'method': 'Page.handleJavaScriptDialog', 'params': {'accept': True}}))
            if message.get('id') == self.next_id:
                if 'error' in message:
                    raise PublishError('CDP_' + method, message['error'].get('message', ''))
                return message.get('result', {})

    def eval(self, expression):
        result = self.call('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        if 'exceptionDetails' in result:
            details = result['exceptionDetails']
            raise PublishError('PAGE_SCRIPT', details.get('exception', {}).get('description', details.get('text', '')))
        return result['result'].get('value')

    def wait(self, expression, timeout, interval=0.5):
        deadline = time.monotonic() + timeout
        while True:
            value = self.eval(expression)
            if value:
                return value
            if time.monotonic() > deadline:
                return value
            time.sleep(interval)

    def move_to(self, x, y):
        """Move the pointer along a curved, eased path, as a hand would."""
        start_x, start_y = self.mouse
        bend_x = (start_x + x) / 2 + random.uniform(-90, 90)
        bend_y = (start_y + y) / 2 + random.uniform(-70, 70)
        steps = random.randint(14, 26)
        for step in range(1, steps + 1):
            t = step / steps
            t = t * t * (3 - 2 * t)
            px = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * bend_x + t * t * x
            py = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * bend_y + t * t * y
            self.call('Input.dispatchMouseEvent', type='mouseMoved', x=px, y=py)
            time.sleep(random.uniform(0.006, 0.022))
        self.mouse = (x, y)

    def click_point(self, x, y):
        self.move_to(x, y)
        time.sleep(random.uniform(0.06, 0.22))
        self.call('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y, button='left', clickCount=1)
        time.sleep(random.uniform(0.05, 0.13))
        self.call('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y, button='left', clickCount=1)

    def click(self, element_js):
        """Scroll the element to the middle of the view and click its centre with real mouse events.

        The click is refused when another element (such as the sticky publish bar) covers that point.
        """
        found = self.eval('(() => { const e = %s; if (!e) return false; e.scrollIntoView({block: "center"}); return true; })()'
                          % element_js)
        if not found:
            return False
        time.sleep(0.3)
        # Aim somewhere inside the middle of the element rather than at its exact centre.
        point = self.eval('(() => { const e = %s; if (!e) return null; const r = e.getBoundingClientRect();'
                          ' const x = r.x + r.width * %.3f, y = r.y + r.height * %.3f; const top = document.elementFromPoint(x, y);'
                          ' return top && (e === top || e.contains(top) || top.contains(e)) ? [x, y] : "covered"; })()'
                          % (element_js, random.uniform(0.32, 0.68), random.uniform(0.35, 0.65)))
        if point == 'covered':
            raise PublishError('CLICK_COVERED', element_js[:80])
        if not point:
            return False
        self.click_point(*point)
        return True

    def key(self, key, code, keycode, modifiers=0, commands=()):
        for kind in ('keyDown', 'keyUp'):
            extra = {'commands': list(commands)} if commands and kind == 'keyDown' else {}
            self.call('Input.dispatchKeyEvent', type=kind, key=key, code=code,
                      windowsVirtualKeyCode=keycode, modifiers=modifiers, **extra)
            time.sleep(random.uniform(0.04, 0.11))

    def type_text(self, text):
        """Type one character at a time with uneven gaps and longer pauses after punctuation."""
        for character in text:
            self.call('Input.insertText', text=character)
            time.sleep(random.uniform(0.05, 0.19))
            if character in '，。！？；、,.!?;':
                time.sleep(random.uniform(0.2, 0.7))
            elif random.random() < 0.03:
                time.sleep(random.uniform(0.5, 1.4))

    def screenshot(self, path):
        data = self.call('Page.captureScreenshot', format='png')['data']
        Path(path).write_bytes(base64.b64decode(data))

    def publish_buttons(self):
        """Return {button text: centre} for buttons inside the closed shadow root."""
        root = self.call('DOM.getDocument', depth=-1, pierce=True)['root']
        buttons = {}

        def walk(node, inside):
            inside = inside or node.get('localName') == SELECTORS['publish_host']
            if inside and node.get('nodeName') == 'BUTTON':
                text = ''.join(child.get('nodeValue', '') for child in node.get('children', [])).strip()
                self.call('DOM.scrollIntoViewIfNeeded', nodeId=node['nodeId'])
                quad = self.call('DOM.getBoxModel', nodeId=node['nodeId'])['model']['content']
                buttons[text] = ((quad[0] + quad[4]) / 2, (quad[1] + quad[5]) / 2)
            for child in node.get('children', []) + node.get('shadowRoots', []):
                walk(child, inside)

        walk(root, False)
        return buttons

    def close_socket(self):
        with contextlib.suppress(Exception):
            self.socket.close()


def js(value):
    return json.dumps(value, ensure_ascii=False)


# Some controls have off-page copies (one "上传图文" tab sits at about -9700, -9900),
# so a match must have a size and a non-negative position in the document.
VISIBLE = ('e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0'
           ' && r.left + scrollX >= 0 && r.top + scrollY >= 0; }')


def find_by_text(selector, text):
    """Pick the visible match that receives clicks; some controls are rendered twice on top of each other."""
    return ('(() => { const all = [...document.querySelectorAll(%s)].filter(e => (%s)(e) && e.innerText.trim() === %s);'
            ' return all.find(%s) || all[0]; })()' % (js(selector), VISIBLE, js(text), HITTABLE))


HITTABLE = ('e => { const r = e.getBoundingClientRect(); const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);'
            ' return !!t && (e === t || e.contains(t)); }')


def pause(low=0.6, high=1.8):
    """Leave a person-like gap between steps."""
    time.sleep(random.uniform(low, high))


def page_state(page):
    return page.eval('''(() => ({
        url: location.href,
        login: location.hostname.startsWith('login') || location.pathname.includes('login'),
        phoneBlocked: document.body.innerText.includes(%s),
        publishHost: !!document.querySelector(%s),
        hostAttrs: (h => h ? Object.fromEntries([...h.attributes].map(a => [a.name, a.value])) : null)(document.querySelector(%s)),
    }))()''' % (js(PHONE_BLOCK_TEXT), js(SELECTORS['publish_host']), js(SELECTORS['publish_host'])))


def read_form(page):
    """Read back what the creator form currently holds."""
    return page.eval('''(() => {
        const visible = %s;
        const editor = document.querySelector(%s);
        const title = document.querySelector(%s);
        const count = (document.body.innerText.match(/图片编辑\\s*(\\d+)\\s*\\/\\s*%d/) || [])[1];
        const values = [...document.querySelectorAll(%s)].filter(visible).map(e => e.innerText.trim());
        let bodyText = '';
        if (editor) {
            const copy = editor.cloneNode(true);
            copy.querySelectorAll('.content-hide').forEach(e => e.remove());
            bodyText = [...copy.querySelectorAll('p')].map(p => p.textContent).join('\\n');
        }
        return {
            title: title ? title.value : null,
            body_text: bodyText,
            topics: editor ? [...editor.querySelectorAll(%s)].map(a => JSON.parse(a.dataset.topic).name) : [],
            image_count: count ? Number(count) : 0,
            visibility: values.find(v => %s.includes(v)) || null,
            declaration: values.find(v => %s.includes(v)) || null,
        };
    })()''' % (VISIBLE, js(SELECTORS['editor']), js(SELECTORS['title']), IMAGE_LIMIT, js(SELECTORS['select_value']),
               js(SELECTORS['bound_topic']), js(list(VISIBILITY)), js(list(DECLARATIONS))))


# ---------------------------------------------------------------- steps

def open_image_form(page):
    """Switch to the image-note form; return the landing view's account blocker and draft count."""
    if not page.wait('document.readyState === "complete" && !!document.querySelector(%s)' % js(SELECTORS['image_tab']), 30):
        state = page_state(page)
        raise PublishError('NOT_LOGGED_IN' if state['login'] else 'CREATOR_PAGE', state['url'])
    pause(0.8, 1.6)
    blocker = account_blocker(page_state(page))
    drafts = page.eval(DRAFT_COUNT)
    if not page.click(find_by_text(SELECTORS['image_tab'], '上传图文')):
        raise PublishError('IMAGE_TAB_MISSING')
    ready = page.wait('[...document.querySelectorAll(%s)].some(e => e.accept.includes(".jpg"))' % js(SELECTORS['upload_input']), 15)
    if not ready:
        raise PublishError('IMAGE_INPUT_MISSING')
    return blocker, drafts


def account_blocker(state):
    if state['login']:
        return 'NOT_LOGGED_IN'
    return 'PHONE_NOT_BOUND' if state['phoneBlocked'] else None


def upload_images(page, paths):
    root = page.call('DOM.getDocument', depth=0)['root']['nodeId']
    for node in page.call('DOM.querySelectorAll', nodeId=root, selector=SELECTORS['upload_input'])['nodeIds']:
        attributes = page.call('DOM.getAttributes', nodeId=node)['attributes']
        accept = dict(zip(attributes[::2], attributes[1::2])).get('accept', '')
        if '.jpg' in accept:
            page.call('DOM.setFileInputFiles', nodeId=node, files=paths)
            break
    else:
        raise PublishError('IMAGE_INPUT_MISSING')
    loaded = page.wait('(() => { const m = document.body.innerText.match(/图片编辑\\s*(\\d+)\\s*\\/\\s*%d/);'
                       ' return m && Number(m[1]) === %d && !!document.querySelector(%s) && !/上传中/.test(document.body.innerText); })()'
                       % (IMAGE_LIMIT, len(paths), js(SELECTORS['title'])), 120, interval=1)
    if not loaded:
        raise PublishError('IMAGE_UPLOAD', 'the page did not show %d uploaded images' % len(paths))


def select_all_and_delete(page):
    page.key('a', 'KeyA', 65, modifiers=2, commands=('selectAll',))
    page.key('Backspace', 'Backspace', 8)


def fill_title(page, title):
    page.click('document.querySelector(%s)' % js(SELECTORS['title']))
    select_all_and_delete(page)
    page.type_text(title)


def fill_body(page, body, topics):
    page.click('document.querySelector(%s)' % js(SELECTORS['editor']))
    select_all_and_delete(page)
    for index, line in enumerate(body.splitlines()):
        if index:
            page.key('Enter', 'Enter', 13)
        if line:
            page.type_text(line)
    if topics:
        page.key('Enter', 'Enter', 13)
    for index, topic in enumerate(topics):
        page.type_text(('' if index == 0 else ' ') + '#' + topic)
        wanted = '#' + topic
        item = ('[...document.querySelectorAll(%s)].find(e => e.innerText.trim().split("\\n")[0].trim() === %s)'
                % (js(SELECTORS['topic_item']), js(wanted)))
        if not page.wait('!!(%s)' % item, 8):
            raise PublishError('TOPIC_NOT_FOUND', '%s has no exact suggestion' % wanted)
        page.click(item)
        bound = page.wait('[...document.querySelectorAll(%s)].some(a => JSON.parse(a.dataset.topic).name === %s)'
                          % (js(SELECTORS['bound_topic']), js(topic)), 5)
        if not bound:
            raise PublishError('TOPIC_NOT_BOUND', wanted)


def choose_option(page, current_js, option):
    if not page.click(current_js):
        raise PublishError('SELECT_MISSING', option)
    target = find_by_text(SELECTORS['option'], option)
    if not page.wait('!!(%s)' % target, 5):
        raise PublishError('OPTION_MISSING', option)
    page.click(target)
    time.sleep(0.5)


def set_visibility(page, visibility):
    current = '[...document.querySelectorAll(%s)].find(e => (%s)(e) && %s.includes(e.innerText.trim()))' % (
        js(SELECTORS['select_value']), VISIBLE, js(list(VISIBILITY)))
    choose_option(page, current, visibility)


def set_declaration(page, declaration):
    if declaration is None:
        return
    current = find_by_text(SELECTORS['select_placeholder'], '添加内容类型声明')
    choose_option(page, current, declaration)


def capture_preview(page, folder):
    shots = []
    for index, anchor in enumerate(('document.querySelector(%s)' % js(SELECTORS['title']),
                                    '[...document.querySelectorAll(%s)].find(e => %s.includes(e.innerText.trim()))'
                                    % (js(SELECTORS['select_value']), js(list(VISIBILITY))))):
        page.eval('(() => { const e = %s; if (e) e.scrollIntoView({block: "center"}); })()' % anchor)
        time.sleep(0.6)
        shot = Path(folder) / ('preview-%d.png' % (index + 1))
        page.screenshot(shot)
        shots.append(str(shot))
    return shots


# ---------------------------------------------------------------- commands

def probe_account(browser):
    """Open the creator landing view in a throwaway tab; its banner shows account blockers."""
    page = browser.open(PUBLISH_URL)
    try:
        page.wait('document.readyState === "complete" && !!document.querySelector(%s)' % js(SELECTORS['image_tab']), 30)
        pause(0.8, 1.6)
        return account_blocker(page_state(page))
    finally:
        page.close_socket()
        browser.close(page.id)


def command_status(args, jobs):
    browser = Browser(args.cdp)
    version = browser.request('/json/version')
    blocker = probe_account(browser)
    open_jobs = [{'id': job['id'], 'state': job['state'], 'title': job['draft']['title']}
                 for job in jobs.all() if job['state'] not in ('published', 'discarded', 'draft_saved')]
    return {'browser': version.get('Browser'), 'logged_in': blocker != 'NOT_LOGGED_IN',
            'can_publish': blocker is None, 'blocker': blocker, 'open_jobs': open_jobs}


def command_prepare(args, jobs):
    draft = load_draft(args.draft)
    digest = content_sha256(draft)
    job_id = digest[:16]
    history = []
    if (jobs.path(job_id) / 'job.json').is_file():
        previous = jobs.load(job_id)
        if previous['state'] not in ('discarded', 'failed', 'not_published'):
            raise PublishError('DUPLICATE_CONTENT', 'job %s already holds this content in state %s' % (job_id, previous['state']))
        history = previous.get('history', [])
    folder = jobs.path(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    job = {'id': job_id, 'content_sha256': digest, 'draft': draft, 'created_at': now(), 'history': history}
    jobs.transition(job, 'preparing')
    browser = Browser(args.cdp)
    page = browser.open(PUBLISH_URL)
    job['tab_id'] = page.id
    jobs.save(job)
    try:
        job['blocker'], job['drafts_before'] = open_image_form(page)
        pause()
        upload_images(page, [browser_path(image['path'], args.path_style) for image in draft['images']])
        pause(1.5, 3.5)
        fill_title(page, draft['title'])
        pause()
        fill_body(page, draft['body'], draft['topics'])
        pause()
        set_visibility(page, draft['visibility'])
        if draft['declaration']:
            pause()
            set_declaration(page, draft['declaration'])
        pause(1, 2.5)
        readback = read_form(page)
        problems = readback_matches(draft, readback)
        job['readback'] = readback
        job['previews'] = capture_preview(page, folder)
        if problems:
            raise PublishError('READBACK_MISMATCH', ', '.join(problems))
    except Exception as error:
        job['error'] = str(error)
        jobs.transition(job, 'failed', error=str(error))
        with contextlib.suppress(Exception):
            page.screenshot(folder / 'failure.png')
        page.close_socket()
        browser.close(page.id)
        raise
    finally:
        page.close_socket()
    jobs.transition(job, 'prepared')
    return {'job': job_id, 'confirm': digest[:8], 'previews': job['previews'], 'blocker': job['blocker'],
            'readback': readback}


def verified_page(browser, job):
    page = browser.attach(job['tab_id'])
    problems = readback_matches(job['draft'], read_form(page))
    if problems:
        page.close_socket()
        raise PublishError('FORM_CHANGED', ', '.join(problems))
    return page


def click_publish_bar(page, label):
    """Click a button in the publish bar after scrolling through the form once."""
    buttons = page.publish_buttons()
    if label not in buttons:
        raise PublishError('PUBLISH_BUTTON_MISSING', '%s not in %s' % (label, sorted(buttons)))
    attrs = page_state(page)['hostAttrs'] or {}
    if attrs.get('submit-disabled') == 'true' or attrs.get('submit-loading') == 'true':
        raise PublishError('PUBLISH_BUTTON_BUSY', json.dumps(attrs, ensure_ascii=False))
    page.eval('window.scrollTo({top: 0, behavior: "smooth"})')
    pause(1.2, 2.5)
    page.eval('window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"})')
    pause(1, 2)
    buttons = page.publish_buttons()
    x, y = buttons[label]
    page.click_point(x + random.uniform(-18, 18), y + random.uniform(-5, 5))


def visible_messages(page):
    return page.eval('[...document.querySelectorAll("[class*=toast], [class*=message], [class*=notice]")]'
                     '.filter(e => e.getClientRects().length).map(e => e.innerText.trim()).filter(Boolean).join(" | ")')


DRAFT_COUNT = '(Number((document.body.innerText.match(/草稿箱\\((\\d+)\\)/) || [])[1]) || 0)'


def leave_with(page, label, timeout):
    """Publish: success means the page left the form, as the mature projects check."""
    click_publish_bar(page, label)
    left = page.wait('!location.pathname.startsWith("/publish/publish")', timeout, interval=1)
    return bool(left), page.eval('location.href'), visible_messages(page)


def command_publish(args, jobs):
    job = jobs.load(args.job)
    require_state(job, STATES_BEFORE_CLICK, 'publish')
    if args.confirm != job['content_sha256'][:8]:
        raise PublishError('CONFIRM_MISMATCH', 'pass --confirm %s after reviewing the previews' % job['content_sha256'][:8])
    browser = Browser(args.cdp)
    page = verified_page(browser, job)
    try:
        blocker = probe_account(browser)
        if blocker:
            raise PublishError(blocker, 'bind a phone number in the Xiaohongshu app first' if blocker == 'PHONE_NOT_BOUND' else '')
        jobs.transition(job, 'publishing')
        try:
            left, url, toast = leave_with(page, '发布', args.timeout)
        except Exception as error:
            jobs.transition(job, 'unknown', error=str(error))
            raise
        with contextlib.suppress(Exception):
            page.screenshot(jobs.path(job['id']) / 'after-publish.png')
        if left:
            jobs.transition(job, 'published', url=url, toast=toast)
            return {'job': job['id'], 'state': 'published', 'url': url, 'toast': toast}
        jobs.transition(job, 'unknown', url=url, toast=toast)
        raise PublishError('PUBLISH_UNCONFIRMED', 'the page stayed on the form; check 笔记管理 before doing anything else. toast: ' + toast)
    finally:
        page.close_socket()


def command_save_draft(args, jobs):
    job = jobs.load(args.job)
    require_state(job, STATES_BEFORE_CLICK, 'save-draft')
    browser = Browser(args.cdp)
    page = verified_page(browser, job)
    try:
        jobs.transition(job, 'saving_draft')
        try:
            # Saved drafts live in this browser's storage; the page stays on the same URL and
            # returns to the landing view, where the 草稿箱 count includes the new draft.
            before = job.get('drafts_before', 0)
            click_publish_bar(page, '暂存离开')
            saved = page.wait('!document.querySelector(%s) && %s > %d' % (js(SELECTORS['title']), DRAFT_COUNT, before),
                              args.timeout, interval=1)
            toast = visible_messages(page)
        except Exception as error:
            jobs.transition(job, 'unknown', error=str(error))
            raise
        state = 'draft_saved' if saved else 'unknown'
        jobs.transition(job, state, toast=toast)
        return {'job': job['id'], 'state': state, 'toast': toast}
    finally:
        page.close_socket()


def command_resolve(args, jobs):
    """Record the outcome a person verified for a job left in "unknown"."""
    job = jobs.load(args.job)
    require_state(job, {'unknown', 'publishing', 'saving_draft'}, 'resolve')
    jobs.transition(job, args.outcome, evidence=args.evidence, resolved_by='person')
    return {'job': job['id'], 'state': args.outcome}


def command_discard(args, jobs):
    job = jobs.load(args.job)
    require_state(job, STATES_BEFORE_CLICK | {'failed', 'preparing'}, 'discard')
    if job.get('tab_id'):
        Browser(args.cdp).close(job['tab_id'])
    jobs.transition(job, 'discarded')
    return {'job': job['id'], 'state': 'discarded'}


def command_show(args, jobs):
    job = jobs.load(args.job)
    return {key: job.get(key) for key in ('id', 'state', 'content_sha256', 'draft', 'readback', 'previews', 'blocker', 'history')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cdp', default=os.environ.get('RSI_XHS_CDP', DEFAULT_CDP))
    parser.add_argument('--state-dir', default=os.environ.get('RSI_XHS_STATE', str(DEFAULT_STATE)))
    parser.add_argument('--path-style', choices=('wsl', 'native'), default='wsl',
                        help='how the browser host reads local image paths')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    prepare = commands.add_parser('prepare')
    prepare.add_argument('draft')
    for name in ('publish', 'save-draft'):
        sub = commands.add_parser(name)
        sub.add_argument('job')
        sub.add_argument('--timeout', type=float, default=30)
        if name == 'publish':
            sub.add_argument('--confirm', required=True)
    for name in ('discard', 'show'):
        commands.add_parser(name).add_argument('job')
    resolve = commands.add_parser('resolve', help='record an outcome checked in 笔记管理 or 草稿箱')
    resolve.add_argument('job')
    resolve.add_argument('outcome', choices=('published', 'draft_saved', 'not_published'))
    resolve.add_argument('--evidence', required=True)
    args = parser.parse_args(argv)
    jobs = Jobs(args.state_dir)
    handler = {'status': command_status, 'prepare': command_prepare, 'publish': command_publish,
               'save-draft': command_save_draft, 'discard': command_discard, 'show': command_show,
               'resolve': command_resolve}[args.command]
    try:
        if args.command == 'show':
            result = handler(args, jobs)
        else:
            with jobs.lock():
                result = handler(args, jobs)
    except PublishError as error:
        print(json.dumps({'ok': False, 'error': error.code, 'detail': str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(dict(ok=True, **result), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())

