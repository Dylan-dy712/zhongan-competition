// Keep all rendered information and temporary user input scoped to one encounter.
function caseCaption(item = careContext.current) {
  return `<p class="case-caption"><strong>${escape(item.title)}</strong><span>${escape(item.dateLabel)} · ${escape(item.hospital)}</span><small>虚构示例</small></p>`;
}
function caseDocuments(kind) {
  const docs = careContext.current.docs.filter(doc => !kind || doc.kind === kind);
  return docs.length ? docs.map(doc => `<section class="card case-document"><h3>${escape(doc.name)}</h3><blockquote class="quote">${escape(doc.quote)}</blockquote><small>虚构示例摘录 · 非真实原件</small></section>`).join('') : '<section class="card"><h3>本次资料待补充</h3><p>这次就医尚无此类资料，补充后再核对。</p></section>';
}
function caseUpload(label = '补充本次就医资料') {
  return `<button class="outline" data-action="upload">＋ ${label}</button><p class="notice">仅在当前页面本地预览，尚未上传或分析。</p>`;
}
function buildCaseMaterials() {
  return `${caseCaption()}${caseDocuments()}<section class="card"><h3>本次补充资料</h3>${files.length?fileList():'<p>后来拿到的报告和单据，可以补充到这次就医。</p>'}${caseUpload()}</section>`;
}

(() => {
  const baseRender = render;
  const temporary = new Map();
  const originalRecovery = Object.fromEntries(Object.entries(details).filter(([key]) => key === 'recovery' || key.startsWith('recovery-')).map(([key, value]) => [key, [...value]]));
  function switchEncounter(id) {
    if (id === careContext.activeId || !careContext.find(id)) return;
    saveDraft();
    temporary.set(careContext.activeId, {messages, files, draft, chatScroll, reminder, feedback, consent, imported, positions:{...positions}});
    const saved = temporary.get(id) || {messages:[], files:[], draft:'', chatScroll:0, reminder:'', feedback:'', consent:false, imported:false, positions:{}};
    const recordsPosition = positions.records;
    Object.keys(positions).forEach(key => delete positions[key]);
    Object.assign(positions, saved.positions);
    if (recordsPosition !== undefined) positions.records = recordsPosition;
    messages=saved.messages; files=saved.files; draft=saved.draft; chatScroll=saved.chatScroll;
    reminder=saved.reminder; feedback=saved.feedback; consent=saved.consent; imported=saved.imported;
    careContext.activeId=id;
    explainDialog.close(); dialog.close(); uploadSheet.close();
  }

  home = function() {
    const item = careContext.current, followup = item.followup;
    const focus = followup
      ? `<button class="replica-appointment" data-go="appointment"><span class="replica-date"><small>${followup.month} 月</small><strong>${followup.day}</strong></span><span><strong>${followup.title}</strong><small>${followup.period} · 具体时间和科室待确认</small></span>${icon('arrow',19)}</button>`
      : `<button class="replica-appointment" data-go="recovery"><span>${icon('leaf',25)}</span><span><strong>${escape(item.focus)}</strong><small>${escape(item.hint)}</small></span>${icon('arrow',19)}</button>`;
    return `<div class="home replica-home"><div class="replica-top"><img class="replica-scene" src="assets/reference-scene.webp?img=20261002c" alt=""><header class="brand"><img src="assets/home-brand.webp?img=20261002c" alt="暖愈智护"></header><div class="replica-hero"><h1>看病之后，<br><em>安心一点</em></h1><p>暖暖陪你看懂资料，记好安排。</p><button class="replica-episode" data-go="records" aria-label="选择其他就医记录">${escape(item.title)} <span>切换</span></button></div><img class="replica-mascot" src="assets/reference-mascot.webp?img=20261002c" alt=""><img class="replica-chat" src="assets/reference-chat.webp?img=20261002c" alt=""></div><section class="replica-guide"><img class="replica-guide-art" src="assets/reference-guide.webp?img=20261002c" alt=""><div class="replica-guide-label">${icon('leaf',19)}康复指引</div><h2>下一步，一起理清楚</h2><p>${escape(item.dateLabel)} · 示例</p>${focus}${btn('查看本次关怀 '+icon('arrow',20),'recovery','replica-primary')}</section><h2 class="replica-section-title">这次看病</h2><div class="replica-secondary"><button data-go="summary"><img src="assets/reference-summary.webp?img=20261002c" alt=""><strong>看病总结</strong><p>诊断和治疗经过</p></button><button data-go="evidence"><img src="assets/reference-cost.webp?img=20261002c" alt=""><strong>费用说明</strong><p>${item.cost?'总费用 ¥ '+item.cost:'费用资料待补充'}</p></button></div><p class="footnote"></p></div>`;
  };

  appointment = function() {
    const item = careContext.current;
    if (!item.followup) return `${caseCaption()}<section class="card"><h2>复诊安排待确认</h2><p>${escape(item.question)}</p>${btn('查看本次资料','materials','outline')}</section>`;
    return `${caseCaption()}<section class="card"><span class="eyebrow">${item.followup.month} 月 ${item.followup.day} 日 · ${item.followup.period}</span><h2>${item.followup.title}</h2><p>具体时间、科室和预约方式需要向医院核对。</p>${btn('查看出院记录依据','home-discharge-source','link')}${reminder?`<p class="inline-note">已记下：${escape(reminder)}</p>`:''}<button class="primary" data-action="remind">${reminder?'修改提醒时间':'记下提醒时间'}</button>${reminder?'<button class="outline" data-action="cancel-reminder">取消提醒</button>':''}</section><p class="notice">时间仅保存在当前页面，尚不能发送通知。</p>`;
  };

  function updateDetails() {
    const item = careContext.current, caption = caseCaption(item);
    details.summary = ['看病总结',`${caption}<section class="card"><h2>这次看病的经过</h2><p>${escape(item.summary)}</p></section>${caseDocuments('record')}<section class="card"><h3>还有什么要问清楚</h3><p>${escape(item.question)}</p><button class="outline" data-document-question="${escape(item.question)}">带着这个问题问暖暖</button></section>`];
    details.guide = details.summary;
    details.discharge = ['病历资料',`${caption}${caseDocuments('record')}${caseUpload()}`];
    details['raw-record'] = details.discharge;
    details.materials = ['看病资料',buildCaseMaterials()];
    details.evidence = ['这次看病的费用',`${caption}<section class="card document-focus"><img class="expense-total-art" src="assets/expense-total.webp?img=20261002c" alt=""><div class="document-label">医疗费用合计</div><div class="bill-total">${item.cost?`<span>¥</span>${item.cost}`:'待补充'}</div><p>${escape(item.payment)}</p><div class="cost-facts"><div><span>最终自付</span><strong>待核对</strong></div><div><span>商业保险赔付金额</span><strong>待核对</strong></div></div></section><section class="card"><h3>费用依据</h3>${item.cost?'<p>当前总额来自本次示例费用单，不能代替最终自付。</p>':'<p>本次尚无费用摘录，不使用其他就医的金额。</p>'}${btn('查看本次费用资料','raw-cost','link')}${caseUpload('补充费用资料')}</section><section class="card"><h3>关联理赔</h3><p>${escape(item.claimId)} · ${escape(item.claim)}</p><p>理赔状态与赔付金额分别核对，结案不表示全部报销。</p>${btn('查看理赔说明','claim-record','link')}</section><button class="expense-chat-link" data-document-question="帮我解释这次就医的费用。">${icon('chat',18)}费用还有没看懂的？问问暖暖 ${icon('arrow',14)}</button>`];
    details['raw-cost'] = ['费用资料',`${caption}${caseDocuments('cost')}${caseUpload('补充费用资料')}`];
    details['claim-record'] = ['理赔资料',`${caption}<section class="card"><h2>这次理赔</h2><p>关联编号：${escape(item.claimId)}</p><p>状态：${escape(item.claim)}</p><p>尚未提供核定金额和到账记录，不能据此计算个人承担。</p>${caseUpload('补充理赔资料')}</section>`];
    for (const [id,title] of [['raw-test','检查报告'],['raw-treatment','用药与治疗'],['raw-other','其他资料']]) details[id] = [title,`${caption}<section class="card"><h2>${title}待补充</h2><p>当前本次就医的示例摘录未包含这部分内容。</p>${caseUpload()}</section>`];
    details.test = details['raw-test'];
    details['home-discharge-source'] = details.discharge;
    details['home-cost-source'] = details['raw-cost'];
    if (item.followup) {
      for (const [id,value] of Object.entries(originalRecovery)) details[id] = [...value];
    } else {
      const care = `${caption}<section class="card"><h2>${escape(item.focus)}</h2><p>${escape(item.hint)}</p><p>${escape(item.question)}</p>${item.next?btn('查看后续复诊',`encounter-${item.next}`,'outline'):''}${btn('核对本次资料','materials','outline')}</section><section class="card"><h3>康复要求待补充</h3><p>本次缺少完整康复医嘱，暂不生成用药、活动或饮食任务。</p>${caseUpload()}</section>`;
      for (const id of Object.keys(originalRecovery)) details[id] = ['本次就医关怀',care];
    }
    details['care-report'] = ['本次就医解读',`${caption}<section class="card"><h2>看病经过</h2><p>${escape(item.summary)}</p></section><section class="card"><h2>下一步安排</h2><p>${escape(item.hint)}</p>${btn('查看本次关怀','recovery','outline')}${btn('查看本次费用','evidence','outline')}</section>`];
    details.visit = ['下次就医准备',`${caption}<section class="card"><h2>先把这个问题问清楚</h2><p>${escape(item.question)}</p>${btn('带上本次就医资料','materials','outline')}</section><section class="card"><h3>医院与医生推荐待补充</h3><p>当前没有足够的医疗机构比较数据，暂不能给出推荐名单。</p></section>`];
  }

  render = function() {
    const id = pageId();
    const fromRoute = id.startsWith('encounter-') ? careContext.find(id.slice('encounter-'.length)) : null;
    const fromHistory = history.state?.navKey === navKey ? careContext.find(history.state.encounterId) : null;
    switchEncounter((fromRoute || fromHistory || careContext.current).id);
    if (history.state?.encounterId !== careContext.activeId) history.replaceState({...history.state,encounterId:careContext.activeId},'',location.hash);
    updateDetails();
    baseRender();
  };
  render();
})();
