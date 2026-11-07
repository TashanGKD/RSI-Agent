(() => {
  'use strict';
  const form = document.querySelector('#auth-form');
  const password = document.querySelector('#password');
  const username = document.querySelector('#username');
  const usernameField = document.querySelector('#username-field');
  let usernameRequired = false;
  const confirmation = document.querySelector('#password-confirm');
  const confirmField = document.querySelector('#confirm-field');
  const submit = document.querySelector('#auth-submit');
  const submitLabel = document.querySelector('#submit-label');
  const feedback = document.querySelector('#auth-feedback');
  const retry = document.querySelector('#auth-retry');
  const title = document.querySelector('#auth-title');
  const description = document.querySelector('#auth-description');
  const passwordLabel = document.querySelector('#password-label');
  let ready = false;
  let pending = false;
  let checking = false;
  let activation = false;
  // Fragments never enter the URL of a request. Do not store or log this token.
  function activationFromURL() {
    const token = new URLSearchParams(window.location.hash.slice(1)).get('activate') || '';
    return token.length > 0 && token.length <= 512 ? token : '';
  }

  function notify(message, error = false) {
    feedback.textContent = message;
    feedback.classList.toggle('is-error', error);
  }
  function availability() {
    password.disabled = !ready || pending;
    username.disabled = !ready || pending || !usernameRequired;
    confirmation.disabled = !ready || pending || !activation;
    submit.disabled = !ready || pending || (activation && !activationFromURL());
    retry.disabled = checking;
    form.setAttribute('aria-busy', pending ? 'true' : 'false');
    submitLabel.textContent = pending ? (activation ? '正在设置密码…' : '正在登录…') : (activation ? '设置密码并进入' : '进入记事本');
  }
  function enterNotebook() {
    // Only success removes the private fragment. A failed activation remains retryable.
    if (window.location.hash) window.history.replaceState(null, '', window.location.pathname + window.location.search);
    window.location.replace('/#today');
  }
  async function requestJSON(path, body) {
    if (!['/api/auth/status', '/api/auth/login', '/api/auth/activate'].includes(path)) throw new Error('invalid auth endpoint');
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    try {
      // no-referrer + same-origin fetch serializes Origin as "null" in WebKit.
      // Fixed relative endpoints + CORS-mode preserve the real Origin without
      // leaking referrers. The server still rejects null/foreign origins.
      const options = {credentials: 'same-origin', mode: 'cors', redirect: 'error', cache: 'no-store', signal: controller.signal};
      if (body !== undefined) {
        options.method = 'POST';
        options.headers = {'Content-Type': 'application/json'};
        options.body = JSON.stringify(body);
      }
      const response = await window.fetch(path, options);
      if (!response.ok) {
        const failure = new Error('request rejected');
        failure.status = response.status;
        try { const data = await response.json(); failure.code = typeof data.code === 'string' ? data.code : ''; } catch { failure.code = ''; }
        throw failure;
      }
      return await response.json();
    } finally {
      window.clearTimeout(timer);
    }
  }
  async function loadStatus() {
    if (checking || pending) return;
    checking = true;
    ready = false;
    retry.hidden = true;
    notify('正在连接，请稍候。');
    availability();
    try {
      const status = await requestJSON('/api/auth/status');
      if (typeof status.authenticated !== 'boolean' || typeof status.initialized !== 'boolean') throw new Error('invalid status');
      if (status.authenticated) { enterNotebook(); return; }
      activation = !status.initialized;
      if (!activation && activationFromURL()) window.history.replaceState(null, '', window.location.pathname + window.location.search);
      usernameRequired = status.usernameRequired === true;
      usernameField.hidden = !usernameRequired;
      username.required = usernameRequired;
      ready = true;
      form.hidden = false;
      confirmField.hidden = !activation;
      confirmation.required = activation;
      password.autocomplete = activation ? 'new-password' : 'current-password';
      title.textContent = activation ? '启用你的记事本' : '欢迎回来';
      description.textContent = activation ? '设置登录账号和密码，以后在手机或电脑上继续记录。' : (usernameRequired ? '输入账号和密码，继续你的记录。' : '输入密码，继续你的记录。');
      passwordLabel.textContent = activation ? '设置密码' : '登录密码';
      document.title = (activation ? '启用' : '登录') + ' · 他山共同记事本';
      notify(activation && !activationFromURL() ? '激活链接不完整，请使用完整的私人激活链接。' : '', activation && !activationFromURL());
    } catch {
      title.textContent = '暂时无法连接';
      description.textContent = '连接恢复后，即可继续登录。';
      notify('暂时无法连接记事本，请稍后重试。', true);
      retry.hidden = false;
    } finally {
      checking = false;
      availability();
    }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pending || !ready) return;
    password.removeAttribute('aria-invalid');
    confirmation.removeAttribute('aria-invalid');
    const activationToken = activationFromURL();
    if (activation && !activationToken) { notify('激活链接不完整，请使用完整的私人激活链接。', true); return; }
    const value = password.value;
    const account = username.value.trim();
    if (usernameRequired && !/^[A-Za-z0-9_]{3,64}$/.test(account)) {
      notify('请输入账号（3至64位字母、数字或下划线）。', true);
      username.focus(); return;
    }
    const count = [...value].length;
    if (count < 8 || count > 256 || value.includes('\0')) {
      notify(count < 8 ? '密码至少需要 8 个字符。' : '密码最多 256 个字符，且不能包含空字符。', true);
      password.setAttribute('aria-invalid', 'true');
      password.focus(); return;
    }
    if (activation && value !== confirmation.value) {
      notify('两次输入的密码不一致，请重新确认。', true);
      confirmation.setAttribute('aria-invalid', 'true');
      confirmation.focus(); return;
    }
    pending = true;
    notify(activation ? '正在设置密码，请稍候。' : '正在登录，请稍候。');
    availability();
    try {
      const body = activation ? {token: activationToken, password: value} : {password: value};
      if (usernameRequired) body.username = account;
      await requestJSON(activation ? '/api/auth/activate' : '/api/auth/login', body);
      password.value = '';
      confirmation.value = '';
      enterNotebook();
    } catch (error) {
      const message = error.status === 429 ? '尝试次数较多，请稍后再试。'
        : error.status === 403 && error.code === 'origin' ? '登录页面验证未通过，请重新打开登录页后重试。'
        : error.status === 401 && !activation ? '账号或密码不正确，请检查后重试。'
        : error.status >= 500 ? '记事本暂时无法响应，请稍后重试。'
        : error.status ? (activation ? '激活未成功，请检查私人激活链接后重试。' : '暂时无法登录，请检查账号和密码后重试。')
        : '网络连接不稳定，请稍后重试。';
      notify(message, true);
    } finally {
      pending = false;
      availability();
    }
  });
  window.addEventListener('hashchange', () => {
    if (!pending) loadStatus();
  });
  retry.addEventListener('click', loadStatus);
  loadStatus();
})();
