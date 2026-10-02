// Functional regression checks only: this DOM shim has no layout or CSS engine.
// Every production script is loaded in the order declared by home-proposal.html.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../output_dir/product-design');
const entry = fs.readFileSync(path.join(root, 'home-proposal.html'), 'utf8');
const scriptFiles = [...entry.matchAll(/<script\s+src="([^"?]+)(?:\?[^\"]*)?"/g)].map(match => match[1]);
const decode = value => String(value).replace(/&(amp|lt|gt|quot|#39);/g, token => ({
  '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'",
})[token]);
const clone = value => value == null ? value : JSON.parse(JSON.stringify(value));

function createApp(hash = '#/records') {
  const documentListeners = {}, windowListeners = {}, timers = new Map(), liveUrls = new Set();
  let timerSequence = 0, urlSequence = 0;
  const listen = (registry, name, callback) => (registry[name] ||= []).push(callback);
  const dispatch = (registry, name, event) => [...(registry[name] || [])].forEach(callback => callback(event));
  const style = () => ({setProperty(name, value) { this[name] = value; }});
  let document;

  function matchesSimple(node, selector) {
    const attrs = [...selector.matchAll(/\[([^\]=\s]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\]\s]+)))?\]/g)];
    const bare = selector.replace(/\[[^\]]*\]/g, '');
    const tag = bare.match(/^[\w-]+/)?.[0];
    if (tag && node.tagName !== tag.toUpperCase()) return false;
    for (const [, id] of bare.matchAll(/#([\w-]+)/g)) if (node.id !== id) return false;
    for (const [, cls] of bare.matchAll(/\.([\w-]+)/g)) if (!node.className.split(/\s+/).includes(cls)) return false;
    for (const [, name, quoted, single, unquoted] of attrs) {
      if (!node.hasAttribute(name)) return false;
      const value = quoted ?? single ?? unquoted;
      if (value !== undefined && node.getAttribute(name) !== value) return false;
    }
    return true;
  }

  function matches(node, selector) {
    return selector.split(',').some(part => {
      const chunks = part.trim().match(/(?:\[[^\]]*\]|[^\s])+/g) || [];
      if (!chunks.length || !matchesSimple(node, chunks.pop())) return false;
      let ancestor = node.parentElement;
      while (chunks.length) {
        const expected = chunks.pop();
        while (ancestor && !matchesSimple(ancestor, expected)) ancestor = ancestor.parentElement;
        if (!ancestor) return false;
        ancestor = ancestor.parentElement;
      }
      return true;
    });
  }

  class Element {
    constructor(tagName) {
      this.tagName = tagName.toUpperCase();
      this.attributes = {}; this.dataset = {}; this.children = []; this.parentElement = null;
      this.id = ''; this.className = ''; this.value = ''; this.checked = false; this.disabled = false;
      this.open = false; this.scrollTop = 0; this.style = style(); this.events = {}; this._html = '';
      this.classList = {
        toggle: (name, on) => {
          const values = new Set(this.className.split(/\s+/).filter(Boolean));
          const enabled = on === undefined ? !values.has(name) : on;
          enabled ? values.add(name) : values.delete(name);
          this.className = [...values].join(' ');
          return enabled;
        },
        contains: name => this.className.split(/\s+/).includes(name),
      };
    }
    setAttribute(name, value) {
      value = decode(value); this.attributes[name] = value;
      if (name === 'id') this.id = value;
      if (name === 'class') this.className = value;
      if (name === 'value') this.value = value;
      if (['checked', 'disabled', 'open'].includes(name)) this[name] = true;
      if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = value;
    }
    getAttribute(name) {
      if (name === 'class') return this.className;
      if (name === 'id') return this.id;
      if (name === 'open') return this.open ? '' : null;
      return this.attributes[name] ?? null;
    }
    hasAttribute(name) { return this.getAttribute(name) !== null; }
    set innerHTML(value) {
      this._html = String(value);
      this.children.forEach(child => { child.parentElement = null; });
      this.children = [];
      const stack = [this], voidTags = new Set(['META', 'LINK', 'IMG', 'INPUT', 'BR', 'HR', 'SOURCE']);
      for (const token of this._html.match(/<!--[\s\S]*?-->|<![^>]*>|<\/?[A-Za-z][^>]*>|[^<]+/g) || []) {
        if (token.startsWith('<!')) continue;
        if (token.startsWith('</')) {
          const tag = token.match(/^<\/([^\s>]+)/)[1].toUpperCase();
          for (let index = stack.length - 1; index > 0; index--) {
            if (stack[index].tagName === tag) { stack.length = index; break; }
          }
        } else if (token.startsWith('<')) {
          const tag = token.match(/^<([^\s/>]+)/)[1];
          const node = new Element(tag);
          const attrs = token.slice(tag.length + 1).replace(/\/?\s*>$/, '');
          for (const [, key, quoted, single, bare] of attrs.matchAll(/([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
            node.setAttribute(key, quoted ?? single ?? bare ?? '');
          }
          stack.at(-1).append(node);
          if (!voidTags.has(node.tagName) && !token.endsWith('/>')) stack.push(node);
        } else if (stack.at(-1).tagName === 'TEXTAREA') {
          stack.at(-1).value += decode(token);
        }
      }
    }
    get innerHTML() { return this._html; }
    get isConnected() { for (let node = this; node; node = node.parentElement) if (node === body) return true; return false; }
    set textContent(value) { this._html = String(value); this.children = []; }
    get textContent() { return decode(this._html.replace(/<[^>]*>/g, '')); }
    append(node) { node.parentElement = this; this.children.push(node); }
    querySelectorAll(selector) {
      const found = [];
      const visit = node => node.children.forEach(child => { if (matches(child, selector)) found.push(child); visit(child); });
      visit(this); return found;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    closest(selector) { for (let node = this; node; node = node.parentElement) if (matches(node, selector)) return node; return null; }
    addEventListener(name, callback) { listen(this.events, name, callback); }
    focus() { document.activeElement = this; }
    scrollIntoView(options) { this.scrolledIntoView = options; }
    showModal() { this.open = true; }
    close() { const wasOpen = this.open; this.open = false; if (wasOpen) dispatch(this.events, 'close', {target: this}); }
    replaceWith(node) {
      const index = this.parentElement.children.indexOf(this);
      node.parentElement = this.parentElement; this.parentElement.children[index] = node; this.parentElement = null;
    }
    insertAdjacentHTML(_, html) {
      const fragment = new Element('fragment'); fragment.innerHTML = html;
      fragment.children.forEach(node => this.parentElement.append(node));
    }
    click() { emit('click', this); }
  }

  const body = new Element('body');
  body.innerHTML = entry.match(/<body>([\s\S]*)<\/body>/)[1];
  document = {
    body, activeElement: null, documentElement: {style: style()},
    createElement: tag => new Element(tag),
    getElementById: id => body.querySelector('#' + id),
    querySelector: selector => body.querySelector(selector),
    querySelectorAll: selector => body.querySelectorAll(selector),
    addEventListener: (name, callback) => listen(documentListeners, name, callback),
  };
  function emit(name, target) {
    const event = {target, currentTarget: target, prevented: false, stopped: false,
      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }};
    if (name === 'click' && target.onclick) target.onclick(event);
    dispatch(target.events, name, event);
    if (!event.stopped) dispatch(documentListeners, name, event);
    return event;
  }

  const location = {hash};
  const stack = [{hash, state: null}];
  let historyIndex = 0;
  const history = {
    get state() { return stack[historyIndex].state; },
    pushState(state, _, nextHash) {
      stack.splice(historyIndex + 1); stack.push({state: clone(state), hash: nextHash}); historyIndex++;
      location.hash = nextHash;
    },
    replaceState(state, _, nextHash) {
      stack[historyIndex] = {state: clone(state), hash: nextHash}; location.hash = nextHash;
    },
    back() { this.go(-1); }, forward() { this.go(1); },
    go(offset) {
      const next = historyIndex + offset;
      if (next < 0 || next >= stack.length) return;
      historyIndex = next; location.hash = stack[historyIndex].hash;
      dispatch(windowListeners, 'popstate', {state: clone(this.state)});
    },
  };
  const window = {visualViewport: {height: 844, addEventListener() {}}};
  const context = vm.createContext({
    document, location, history, window, innerHeight: 844, console,
    addEventListener: (name, callback) => listen(windowListeners, name, callback),
    setTimeout: callback => { timers.set(++timerSequence, callback); return timerSequence; },
    clearTimeout: id => timers.delete(id),
    matchMedia: () => ({matches: true}),
    URL: {
      createObjectURL() { const url = `blob:test/${++urlSequence}`; liveUrls.add(url); return url; },
      revokeObjectURL: url => liveUrls.delete(url),
    },
    FormData: class {
      constructor(form) { this.form = form; }
      get(name) { return this.form.querySelectorAll(`[name="${name}"]`).find(node => node.checked)?.value ?? null; }
    },
  });
  const evaluate = code => vm.runInContext(code, context);
  for (const file of scriptFiles) vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context, {filename: file});
  const find = selector => {
    const node = document.querySelector(selector);
    assert(node, `Expected rendered element ${selector} at ${location.hash}`);
    return node;
  };
  return {
    evaluate, document, history, location, liveUrls,
    main: document.getElementById('main'),
    html: () => document.getElementById('main').innerHTML,
    find, click: selector => emit('click', find(selector)),
    emit,
    input(selector, value) { const node = find(selector); node.value = value; emit('input', node); },
    submit: selector => emit('submit', find(selector)),
    toggle(selector, open) { const node = find(selector); node.open = open; emit('toggle', node); },
    upload(name) {
      const node = find('#upload-files');
      node.files = [{name, type: 'application/pdf', size: 2048, lastModified: 1}];
      emit('change', node);
    },
  };
}

const app = createApp();
const selected = () => app.evaluate('careContext.activeId');
const navigate = id => app.evaluate(`go(${JSON.stringify(id)})`);
const snapshot = () => JSON.parse(app.evaluate('JSON.stringify({messages, draft, files, reminder, feedback, consent, imported})'));

// The same selected encounter supplies the home, summary, chat, cost and source views.
app.click('[data-go="encounter-current"]');
assert.equal(selected(), 'current');
navigate('home');
assert.match(app.html(), /总费用 ¥ 1,200\.00/);
navigate('chat');
assert.match(app.html(), /1,200\.00/);
assert.match(app.html(), /AI 问答尚未接通/);
assert(app.find('.nuan-welcome'));
navigate('evidence');
assert.match(app.html(), /1,200\.00/);
assert.match(app.html(), /最终自付/);
assert.doesNotMatch(app.html(), /尚未读取到金额/);
app.click('[data-go="raw-cost"]');
assert.match(app.html(), /费用总额 1200\.00 元/);

for (const id of ['pneumonia-stay', 'pneumonia-followup', 'fracture-visit']) {
  navigate('records');
  app.click(`[data-go="encounter-${id}"]`);
  assert.equal(selected(), id);
  const title = app.evaluate('careContext.current.title');
  for (const route of ['home', 'chat', 'summary', 'materials', 'evidence', 'raw-cost', 'discharge', 'recovery', 'recovery-daily', 'recovery-signals', 'recovery-visits', 'appointment', 'visit', 'care-report', 'claim-record']) {
    navigate(route);
    assert(app.html().includes(title), `${id} title missing from ${route}`);
    assert.doesNotMatch(app.html(), /1,200\.00|1200\.00|10 月 12 日|血常规/, `${id} leaked current encounter into ${route}`);
    if (id !== 'fracture-visit') assert.doesNotMatch(app.html(), /诊断记录：骨折|示例医院 B/);
    if (id === 'fracture-visit') assert.doesNotMatch(app.html(), /诊断：肺炎|示例医院 A/);
  }
  navigate('chat');
  app.click('[data-explain="cost"]');
  assert(app.find('#nuan-explanation').open);
  assert.match(app.find('#nuan-explanation').innerHTML, /费用资料待补充/);
  assert.doesNotMatch(app.find('#nuan-explanation').innerHTML, /1200|1,200|10 月 12 日/);
  app.click('[data-explain-close]');
}

// Keep user input per encounter by exercising the production DOM event handlers.
navigate('encounter-current');
navigate('appointment');
app.click('[data-action="remind"]');
assert(app.find('#reminder').open);
const radios = app.document.querySelectorAll('#reminder input[name=time]');
radios.forEach(radio => { radio.checked = radio.value === '10 月 12 日 08:00'; });
assert(app.submit('#reminder-form').prevented);
assert.equal(snapshot().reminder, '10 月 12 日 08:00');
navigate('chat');
app.input('#question', 'current question');
assert(app.submit('#chat-form').prevented);
assert.equal(snapshot().messages.length, 2);
assert(!app.document.querySelector('.nuan-welcome'), 'Welcome should be removed after a conversation starts');
app.input('#question', 'current draft & followup');
app.upload('current-record.pdf');
app.find('.chat-thread').scrollTop = 127;
navigate('consent');
const consentBox = app.find('#consent-check');
consentBox.checked = true;
// Consent is UI state here; the example still does not analyze selected files.
app.emit('change', consentBox);
app.click('[data-action="accept"]');
navigate('feedback');
app.input('#correction', 'current correction');
app.click('[data-action="feedback"]');
const currentState = snapshot();
const currentUrl = currentState.files[0].url;

navigate('records');
app.click('[data-go="encounter-pneumonia-followup"]');
assert.deepEqual(snapshot(), {messages: [], draft: '', files: [], reminder: '', feedback: '', consent: false, imported: false});
navigate('chat');
assert(app.document.querySelector('.nuan-welcome'));
assert.equal(app.find('#question').value, '');
assert.equal(app.find('.chat-thread').scrollTop, 0);
app.input('#question', 'pneumonia question');
app.submit('#chat-form');
app.input('#question', 'pneumonia draft');
app.upload('pneumonia-record.pdf');
app.find('.chat-thread').scrollTop = 241;
const pneumoniaState = snapshot();
const pneumoniaUrl = pneumoniaState.files[0].url;
navigate('materials');
assert.match(app.html(), /pneumonia-record\.pdf/);
assert.doesNotMatch(app.html(), /current-record\.pdf/);
const pneumoniaFileId = pneumoniaState.files[0].id;

navigate('encounter-current');
assert.deepEqual(snapshot(), currentState, 'Current encounter state should be restored in full');
navigate('chat');
assert.equal(app.find('#question').value, 'current draft & followup');
assert.equal(app.find('.chat-thread').scrollTop, 127);
assert.match(app.html(), /current question/);
assert.doesNotMatch(app.html(), /pneumonia question|pneumonia draft/);
navigate(`file-${pneumoniaFileId}`);
assert.match(app.html(), /这份资料已移除/);
assert(!app.html().includes(pneumoniaUrl), 'An unrelated file ID must not expose another encounter file');
navigate('materials');
assert.match(app.html(), /current-record\.pdf/);
assert.doesNotMatch(app.html(), /pneumonia-record\.pdf/);
navigate('appointment');
assert.match(app.html(), /10 月 12 日 08:00/);

navigate('encounter-pneumonia-followup');
assert.deepEqual(snapshot(), pneumoniaState, 'Pneumonia encounter state should be restored in full');
navigate('chat');
assert.equal(app.find('.chat-thread').scrollTop, 241);
assert.equal(app.find('#question').value, 'pneumonia draft');
navigate('materials');
app.click(`[data-remove="${pneumoniaFileId}"]`);
assert(!app.liveUrls.has(pneumoniaUrl), 'Removing a local file should release its own preview URL');
assert(app.liveUrls.has(currentUrl), 'Removing one encounter file must preserve another encounter preview');

// Quick actions open existing reading, retain drafts, and do not submit a question.
navigate('chat');
app.input('#question', 'keep this unsent');
const beforeQuick = snapshot().messages;
app.click('[data-chat-topic="cost"]');
assert(app.find('#chat-topic-cost').open);
assert.equal(app.document.activeElement, app.find('#chat-topic-cost summary'));
assert.equal(app.find('#chat-topic-cost').scrolledIntoView.block, 'nearest');
assert.equal(app.find('#question').value, 'keep this unsent');
assert.deepEqual(snapshot().messages, beforeQuick);
navigate('materials'); navigate('chat');
assert(app.find('#chat-topic-cost').open, 'The expanded reading should survive navigation');
app.toggle('#chat-topic-cost', false);
navigate('materials'); navigate('chat');
assert(!app.find('#chat-topic-cost').open, 'A manually collapsed reading should stay collapsed');
app.click('[data-chat-topic="action"]');
assert.equal(app.document.activeElement, app.find('#chat-topic-action'));
assert.deepEqual(snapshot().messages, beforeQuick);
const detachedTopic = app.find('#chat-topic-cost');
const expansionBefore = app.evaluate('JSON.stringify(careContext.expanded)');
navigate('encounter-current');
assert(!detachedTopic.isConnected);
detachedTopic.open = true;
app.emit('toggle', detachedTopic);
assert.equal(app.evaluate('JSON.stringify(careContext.expanded)'), expansionBefore, 'A delayed toggle from removed markup must not change either encounter');

// Browser history uses the encounter stored on each entry, even on shared routes.
const historyApp = createApp('#/encounter-current');
historyApp.evaluate("go('chat')");
historyApp.input('#question', 'current history draft');
historyApp.evaluate("go('records'); go('encounter-pneumonia-stay'); go('chat')");
historyApp.input('#question', 'pneumonia history draft');
historyApp.history.back();
assert.equal(historyApp.location.hash, '#/encounter-pneumonia-stay');
assert.equal(historyApp.evaluate('careContext.activeId'), 'pneumonia-stay');
historyApp.history.back();
assert.equal(historyApp.location.hash, '#/records');
assert.equal(historyApp.evaluate('careContext.activeId'), 'current');
historyApp.history.back();
assert.equal(historyApp.location.hash, '#/chat');
assert.equal(historyApp.evaluate('careContext.activeId'), 'current');
assert.equal(historyApp.find('#question').value, 'current history draft');
historyApp.history.forward(); historyApp.history.forward(); historyApp.history.forward();
assert.equal(historyApp.location.hash, '#/chat');
assert.equal(historyApp.evaluate('careContext.activeId'), 'pneumonia-stay');
assert.equal(historyApp.find('#question').value, 'pneumonia history draft');
historyApp.click('[data-action="back"]');
assert.equal(historyApp.location.hash, '#/encounter-pneumonia-stay');

// A directly opened encounter URL chooses that case without preceding navigation.
for (const id of ['pneumonia-followup', 'fracture-visit']) {
  const deepApp = createApp(`#/encounter-${id}`);
  assert.equal(deepApp.evaluate('careContext.activeId'), id);
  assert.equal(deepApp.history.state.encounterId, id);
  deepApp.click('[data-go="chat"]');
  assert.equal(deepApp.evaluate('careContext.activeId'), id);
  assert.doesNotMatch(deepApp.html(), /1,200\.00|10 月 12 日/);
  deepApp.click('[data-action="back"]');
  assert.equal(deepApp.location.hash, `#/encounter-${id}`);
  deepApp.click('[data-action="back"]');
  assert.equal(deepApp.location.hash, '#/records');
}

console.log(`PASS: ${scriptFiles.length} production scripts; cross-page encounter/expense/source isolation; conversation, draft, local-file, reminder and scroll restoration; history back/forward/deep routes; quick actions and source dialogs. Non-visual checks only.`);
