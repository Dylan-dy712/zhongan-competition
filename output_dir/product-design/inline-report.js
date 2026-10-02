// All explanations use the selected fictional encounter; no local file is analysed.
const phrase = (id, label) => `<button class="nuan-key" data-explain="${id}" aria-haspopup="dialog">${escape(label)}<span aria-hidden="true">ⓘ</span></button>`;
const nuanMessage = (content, cls = '') => `<div class="nuan-message ${cls}"><img class="nuan-avatar" src="assets/home-chat.webp?img=20261002c" alt="暖暖"><div class="nuan-message-body">${content}</div></div>`;
careContext.expanded = {};

function caseExplanations() {
  const item = careContext.current;
  const record = item.docs.find(doc => doc.kind === 'record');
  const cost = item.docs.find(doc => doc.kind === 'cost');
  return {
    action: { title:item.focus, kind:'就医安排', body:item.hint, quote:record?.quote, source:record?.name, question:item.question },
    summary: { title:'这次看病怎么回事', kind:'看病经过', body:item.summary, quote:record?.quote, source:record?.name, question:'帮我整理这次看病还有哪些需要向医生确认。' },
    cost: { title:item.cost ? '总费用不等于最终自付' : '这次费用资料待补充', kind:'费用解读', body:item.payment, quote:cost?.quote, source:cost?.name, question:'要核对这次就医的个人承担，还需要哪些资料？' },
  };
}

chat = function() {
  const item = careContext.current, expanded = careContext.expanded[item.id] || {};
  const welcome = !messages.length ? `<section class="nuan-welcome" aria-label="暖暖陪你看懂资料"><div class="nuan-welcome-copy"><span class="nuan-welcome-kicker">暖暖，陪你一起</span><h2>看懂一点，安心一点。</h2><p>看病后的疑问，一件一件聊。</p></div><img src="assets/nuan-reading-v1.webp" width="100" height="110" alt="捧着笔记本的暖暖"></section>` : '';
  return `<div class="chat-thread inline-report-thread" aria-label="暖暖的解读与聊天记录">
    ${welcome}<p class="nuan-conversation-caption">${escape(item.title)} · ${escape(item.dateLabel)}<small>虚构示例解读</small></p>
    <div id="chat-topic-action" tabindex="-1">${nuanMessage(`<div class="nuan-message-label">${icon('hospital',18)}接下来，先关心这件事</div>${item.followup ? `<div class="nuan-date-card"><div class="nuan-calendar"><small>${item.followup.month} 月</small><strong>${item.followup.day}</strong><span>${item.followup.period}</span></div><div><h3>${item.followup.title}</h3><span class="nuan-status">具体时间与科室待确认</span></div></div>` : ''}<p>${phrase('action',item.focus)}</p><p>${escape(item.hint)}</p><small class="nuan-hint">点划线文字，查看记录依据</small>`)}</div>
    <details class="nuan-topic-details" id="chat-topic-summary" data-chat-section="summary" data-encounter-id="${item.id}" ${expanded.summary?'open':''}><summary>${icon('file',18)}看病经过<span>展开了解</span></summary>${nuanMessage(`<p>${escape(item.summary)}</p><p>${phrase('summary','这段说明的依据')}</p>`)}</details>
    <details class="nuan-topic-details" id="chat-topic-cost" data-chat-section="cost" data-encounter-id="${item.id}" ${expanded.cost?'open':''}><summary>${icon('cost',18)}费用解读<span>${item.cost?'¥ '+item.cost:'资料待补充'}</span></summary>${nuanMessage(`<div class="nuan-money"><div><small>医疗费用总额</small><strong>${item.cost?'<span>¥</span> '+item.cost:'待补充'}</strong></div><div class="nuan-money-unknown"><small>最终自付</small><b>待核对</b></div></div><p>${escape(item.payment)}</p><p>${phrase('cost',item.cost?'总费用不等于最终自付':'需要哪些费用资料？')}</p>${btn('查看费用说明','evidence','link')}`)}</details>
    ${files.length?nuanMessage(`<p>本次就医已选 ${files.length} 份补充文件，尚未分析。</p>${btn('查看所选资料','materials','link')}`):''}
    <div class="nuan-end">以上为本次就医的示例解读</div>
    ${messages.map(message => message.me ? `<div class="bubble me">${escape(message.text)}</div>` : nuanMessage(`<p>${escape(message.text)}</p>`)).join('')}
  </div><div class="chat-dock"><div class="nuan-quick-actions" aria-label="查看已有解读"><button data-chat-topic="summary">看病经过</button><button data-chat-topic="cost">费用解读</button><button data-chat-topic="action">下一步安排</button></div><form class="composer" id="chat-form"><button class="attach" type="button" data-action="upload" aria-label="补充本次就医资料">＋</button><textarea id="question" aria-label="想问暖暖的问题" placeholder="哪一句没看懂？接着问暖暖" rows="1">${escape(draft)}</textarea><button type="submit" aria-label="发送">${icon('send',20)}</button></form><p class="notice">示例解读 · AI 问答尚未接通</p></div>`;
};

const explainDialog = document.createElement('dialog');
explainDialog.id = 'nuan-explanation';
explainDialog.setAttribute('aria-labelledby','nuan-explanation-title');
document.body.append(explainDialog);
document.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.chatTopic) {
    const target = document.getElementById(`chat-topic-${button.dataset.chatTopic}`);
    if (!target) return;
    if (target.tagName === 'DETAILS') {
      target.open = true;
      (careContext.expanded[careContext.activeId] ||= {})[button.dataset.chatTopic] = true;
    }
    target.scrollIntoView({block:'nearest'});
    (target.querySelector('summary') || target).focus({preventScroll:true});
  }
  if (button.dataset.explain) {
    const data = caseExplanations()[button.dataset.explain];
    if (!data) return;
    explainDialog.innerHTML = `<div class="dialog-head"><span class="explain-type">${escape(data.kind)}</span><button data-explain-close aria-label="关闭详细说明">×</button></div><h2 id="nuan-explanation-title">${escape(data.title)}</h2><p class="explain-body">${escape(data.body)}</p>${data.quote?`<section class="explain-evidence"><h3>资料依据</h3><blockquote>${escape(data.quote)}</blockquote><small>虚构示例 · ${escape(data.source)}</small></section>`:'<section class="explain-evidence"><h3>费用资料待补充</h3><p>本次尚无费用原件或摘录，不能计算个人承担。</p></section>'}<button class="primary" data-explain-ask="${escape(data.question)}">记下想问的问题 ${icon('chat',17)}</button>`;
    explainDialog.showModal();
  }
  if (button.hasAttribute('data-explain-close')) explainDialog.close();
  if (button.dataset.explainAsk) {
    draft = button.dataset.explainAsk; explainDialog.close(); render();
    document.getElementById('question').focus();
  }
});
document.addEventListener('toggle', event => {
  const section = event.target.dataset?.chatSection;
  const encounterId = event.target.dataset?.encounterId;
  if (section && careContext.find(encounterId) && event.target.isConnected) (careContext.expanded[encounterId] ||= {})[section] = event.target.open;
}, true);
explainDialog.addEventListener('click', event => {
  if (event.target !== explainDialog) return;
  const rect = explainDialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) explainDialog.close();
});
addEventListener('popstate', () => explainDialog.close());
send = function(text) {
  text = text.trim(); if (!text) return;
  messages.push({me:true,text},{me:false,text:'问题已记在本次就医的对话里。AI 问答尚未接通，可以先查看已有解读或点划线文字核对依据。'});
  draft = ''; chatScroll = 1e9; render();
};
render();
