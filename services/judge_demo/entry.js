(function () {
  'use strict';
  const status = document.getElementById('status');
  const retry = document.getElementById('retry');
  const visitorKey = 'zhongan_judge_visitor_v1';
  const entryKey = 'zhongan_judge_entry_v1';
  let secret = '';
  let visitor = '';
  let busy = false;
  function showError(message, canRetry = true) {
    status.textContent = message;
    status.setAttribute('role', 'alert');
    retry.hidden = !canRetry;
    retry.disabled = false;
  }
  try {
    const fragment = location.hash.slice(1);
    // Remove the invitation from the visible URL before any request or redirect.
    if (fragment) history.replaceState(null, '', location.pathname);
    if (fragment && !/^[A-Za-z0-9_-]{43,128}$/.test(fragment)) {
      throw new Error('体验链接不完整，请重新扫描现场二维码。');
    }
    secret = fragment || sessionStorage.getItem(entryKey) || '';
    if (!secret) throw new Error('请使用现场提供的完整体验链接或二维码。');
    sessionStorage.setItem(entryKey, secret);
    visitor = localStorage.getItem(visitorKey) || '';
    if (!/^[0-9a-f]{64}$/.test(visitor)) {
      visitor = Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, '0')).join('');
      localStorage.setItem(visitorKey, visitor);
    }
    // Reading it back ensures reloads will retain this visitor before allocating a slot.
    if (localStorage.getItem(visitorKey) !== visitor) throw new Error('无法保存体验账号，请在系统浏览器中重新打开链接。');
  } catch (error) {
    showError(error instanceof Error && !/storage|denied|security/i.test(error.message)
      ? error.message : '浏览器禁止保存账号，请在系统浏览器中重新打开链接。', false);
    return;
  }
  async function enter() {
    if (busy) return;
    busy = true;
    retry.hidden = true;
    retry.disabled = true;
    status.setAttribute('role', 'status');
    status.textContent = '正在分配专属体验账号…';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch('/judge/session', {
        method: 'POST', cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json', Authorization: 'Demo ' + secret},
        body: JSON.stringify({visitor_id: visitor})
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        const message = result && (result.detail || result.message);
        showError(typeof message === 'string' ? message : '体验服务暂时不可用，请稍后重试。', ![403,409].includes(response.status));
        return;
      }
      if (!result || typeof result.access_token !== 'string' || !result.user || typeof result.user.display_name !== 'string') {
        throw new Error('体验服务返回异常，请重新连接。');
      }
      sessionStorage.setItem('zhongan_chat_token', result.access_token);
      sessionStorage.setItem('zhongan_account_name', result.user.display_name);
      localStorage.removeItem('zhongan_last_conversation');
      status.textContent = result.user.display_name + ' 已准备好，正在进入首页…';
      location.replace('/#/home');
    } catch (error) {
      showError(error && error.name === 'AbortError' ? '连接超时，请重新连接。' : '连接暂时中断，请重新连接。');
    } finally {
      clearTimeout(timeout);
      busy = false;
    }
  }
  retry.addEventListener('click', enter);
  void enter();
}());
