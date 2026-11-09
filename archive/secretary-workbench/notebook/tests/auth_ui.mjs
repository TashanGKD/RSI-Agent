// All credentials below are fictional fixture data. Uses an isolated local server only.
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || '/home/operator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const directory = new URL('../web-access/', import.meta.url);
// Read first, so missing implementation fails before a browser/server is allocated.
const files = Object.fromEntries(await Promise.all(['index.html', 'auth.js', 'auth.css'].map(async name => [name, await readFile(new URL(name, directory))])));
let initialized = false, authenticated = false, statusError = false, requests = [], finishActivation, loginFailure = null;
const server = http.createServer(async (request, response) => {
  const path = new URL(request.url, 'http://127.0.0.1').pathname;
  response.setHeader('Cache-Control', 'no-store');
  if (path === '/api/auth/status') {
    response.setHeader('Content-Type', 'application/json');
    response.statusCode = statusError ? 503 : 200;
    response.end(JSON.stringify({initialized, authenticated})); return;
  }
  if (request.method === 'POST' && path.startsWith('/api/auth/')) {
    let raw = ''; for await (const chunk of request) raw += chunk;
    requests.push({path, body: JSON.parse(raw), contentType: request.headers['content-type'], origin: request.headers.origin});
    response.setHeader('Content-Type', 'application/json');
    if (path === '/api/auth/activate') {
      finishActivation = ok => { response.statusCode = ok ? 200 : 403; response.end(JSON.stringify(ok ? {authenticated: true} : {error: 'fixture-private-detail'})); };
      return;
    }
    if (loginFailure) { response.statusCode = loginFailure.status; response.end(JSON.stringify({error:'fixture-private-detail',code:loginFailure.code})); return; }
    response.end(JSON.stringify({authenticated: true})); return;
  }
  if (path === '/') { response.setHeader('Content-Type', 'text/html'); response.end('<h1>fixture notebook</h1>'); return; }
  const name = {'/login': 'index.html', '/auth.js': 'auth.js', '/auth.css': 'auth.css'}[path];
  if (!name) { response.statusCode = 404; response.end(); return; }
  response.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html');
  response.end(files[name]);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = 'http://127.0.0.1:' + server.address().port;
let browser;
try {
  browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page = await browser.newPage({viewport: {width: 390, height: 844}});
  const messages = []; page.on('console', item => messages.push(item.text()));
  await page.goto(base + '/login');
  await page.getByRole('heading', {name: '启用你的记事本'}).waitFor();
  assert.match(await page.locator('#auth-feedback').innerText(), /激活链接/);
  assert.equal(await page.locator('#auth-submit').isDisabled(), true, 'missing token cannot submit');
  await page.locator('#password').fill('fictional-password');
  await page.locator('#password-confirm').fill('fictional-password');
  await page.locator('#auth-form').dispatchEvent('submit');
  assert.equal(requests.length, 0);
  await page.goto(base + '/login#activate=fictional-activation-token');
  await page.getByRole('heading', {name: '启用你的记事本'}).waitFor();
  await page.locator('#password').fill('fictional-password');
  await page.locator('#password-confirm').fill('different-password');
  await page.locator('#auth-submit').click();
  assert.match(await page.locator('#auth-feedback').innerText(), /两次.*一致/);
  assert.equal(requests.length, 0, 'mismatched confirmation rejected before POST');
  assert.match(page.url(), /#activate=/);
  await page.locator('#password-confirm').fill('fictional-password');
  await page.locator('#auth-form').dispatchEvent('submit');
  await page.waitForFunction(() => document.querySelector('#auth-submit').disabled);
  await page.locator('#auth-form').dispatchEvent('submit');
  await page.waitForTimeout(80);
  assert.equal(requests.length, 1, 'a second submit while pending is ignored');
  assert.equal(await page.locator('#auth-form').getAttribute('aria-busy'), 'true');
  assert.equal(requests[0].path, '/api/auth/activate');
  assert.deepEqual(Object.keys(requests[0].body).sort(), ['password', 'token']);
  assert.equal(requests[0].body.token, 'fictional-activation-token');
  assert.equal(requests[0].origin, base);
  assert.match(requests[0].contentType, /application\/json/);
  finishActivation(false); finishActivation = null;
  await page.waitForFunction(() => !document.querySelector('#auth-submit').disabled);
  assert.match(await page.locator('#auth-feedback').innerText(), /激活未成功/);
  assert.doesNotMatch(await page.locator('#auth-feedback').innerText(), /fixture-private-detail/);
  assert.match(page.url(), /#activate=fictional-activation-token/, 'failed activation preserves private link fragment');
  assert.ok(messages.every(message => !message.includes('fictional-activation-token')), 'token is never logged');
  await page.locator('#auth-submit').click();
  await page.waitForTimeout(80); finishActivation(true); finishActivation = null;
  await page.waitForURL(base + '/#today');
  assert.doesNotMatch(page.url(), /activate/);
  initialized = true; requests = [];
  await page.setViewportSize({width: 1280, height: 900});
  await page.goto(base + '/login');
  await page.getByRole('heading', {name: '欢迎回来'}).waitFor();
  assert.equal(await page.locator('#confirm-field').isVisible(), false);
  assert.equal(await page.locator('#password').getAttribute('autocomplete'), 'current-password');
  await page.locator('#password').fill('short');
  await page.locator('#auth-form').dispatchEvent('submit');
  assert.match(await page.locator('#auth-feedback').innerText(), /至少.*8/);
  assert.equal(requests.length, 0);
  await page.locator('#password').evaluate(element => { element.value = 'x'.repeat(257); });
  await page.locator('#auth-form').dispatchEvent('submit');
  assert.match(await page.locator('#auth-feedback').innerText(), /最多.*256/);
  assert.equal(requests.length, 0, 'oversized password rejected before POST');
  await page.locator('#password').fill('short');
  await page.locator('#auth-form').dispatchEvent('submit');
  for (const width of [360, 390, 430]) {
    await page.setViewportSize({width, height: 780});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, 'no horizontal overflow at ' + width);
    assert.ok(await page.locator('#password').evaluate(element => parseFloat(getComputedStyle(element).fontSize) >= 16));
    assert.ok((await page.locator('#auth-submit').boundingBox()).height >= 44);
  }
  if (process.env.AUTH_UI_SCREENSHOT_DIR) {
    await mkdir(process.env.AUTH_UI_SCREENSHOT_DIR, {recursive: true});
    await page.screenshot({path: process.env.AUTH_UI_SCREENSHOT_DIR + '/login-mobile.png', fullPage: true});
  }
  await page.locator('#password').fill('fictional-login-password');
  loginFailure = {status:403,code:'origin'};
  await page.locator('#auth-submit').click();
  await page.waitForFunction(() => document.querySelector('#auth-feedback').textContent.includes('页面验证'));
  assert.doesNotMatch(await page.locator('#auth-feedback').innerText(), /账号或密码不正确|fixture-private-detail/);
  loginFailure = {status:401,code:'authentication'};
  await page.locator('#auth-submit').click();
  await page.waitForFunction(() => document.querySelector('#auth-feedback').textContent.includes('账号或密码不正确'));
  loginFailure = null; requests = [];
  await page.locator('#auth-submit').click();
  await page.waitForURL(base + '/#today');
  assert.deepEqual(requests[0].body, {password: 'fictional-login-password'});
  statusError = true;
  await page.goto(base + '/login');
  await page.getByRole('button', {name: '重新连接'}).waitFor();
  assert.match(await page.locator('#auth-feedback').innerText(), /暂时无法/);
  statusError = false;
  await page.getByRole('button', {name: '重新连接'}).click();
  await page.getByRole('heading', {name: '欢迎回来'}).waitFor();
  authenticated = true;
  await page.goto(base + '/login#activate=fictional-activation-token');
  await page.waitForURL(base + '/#today');
  assert.equal(await page.locator('#auth-feedback').count(), 0);
  console.log('PASS: mobile activation/login, password min8/max256, missing token, mismatch, duplicate submit, preserved failure fragment, private errors, mobile 360/390/430, status retry, authenticated redirect');
} finally {
  if (finishActivation) finishActivation(false);
  if (browser) await browser.close();
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
}
