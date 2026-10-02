// Fictional UI fixtures only. Claim, encounter and condition identities stay separate.
(() => {
  const groups = [
    { id: 'unconfirmed', name: '病情待确认', subtitle: '先保留记录，等资料齐了再归类', icon: 'file', tone: 'sand' },
    { id: 'pneumonia', name: '肺炎', subtitle: '住院与后续复诊，放在一起看', icon: 'care', tone: 'mint' },
    { id: 'fracture', name: '骨折', subtitle: '保留每一步治疗与复查记录', icon: 'hospital', tone: 'blue' },
  ];
  const encounters = [
    { id: 'current', group: 'unconfirmed', title: '本次住院', date: '2026-10-08', dateLabel: '2026.10.08 出院', type: '住院', hospital: '医院待补充', claim: '理赔状态待同步', claimId: '尚未关联', stage: '待核对', focus: '先确认复诊时间与科室', hint: '示例记录提到 10 月 12 日上午复查血常规。', summary: '现有示例只包含出院后的复查安排和费用总额，尚无完整诊断与治疗经过。', cost: '1,200.00', payment: '缺少医保结算与理赔结果，最终自付待核对。', docs: [{ name: '出院记录摘录', quote: '出院后建议 10 月 12 日上午复诊并复查血常规，请携带本次就医材料。' }, { name: '费用单摘录', quote: '费用总额 1200.00 元。各项费用与支付方式请以正式结算资料为准，资料未包含报销信息。' }], question: '具体几点复诊、挂哪个科，是否需要预约？' },
    { id: 'pneumonia-followup', group: 'pneumonia', title: '肺炎 · 门诊复诊', date: '2026-09-18', dateLabel: '2026.09.18', type: '门诊', hospital: '示例医院 A · 呼吸内科', claim: '审核中', claimId: 'DEMO-003', stage: '待补资料', focus: '把这次复诊结果补进来', hint: '目前只有就诊登记，检查结果尚未提供。', summary: '本次为肺炎住院后的门诊复诊。与前次住院分开记录，检查结果和后续医嘱仍待补充。', cost: null, payment: '尚无本次费用资料，不能沿用上次住院金额。', docs: [{ name: '门诊登记摘录', quote: '2026 年 9 月 18 日，肺炎出院后复诊。检查结果及后续医嘱待补充。' }], question: '复诊检查结果是否已出，医生有没有调整后续安排？' },
    { id: 'pneumonia-stay', group: 'pneumonia', title: '肺炎 · 住院治疗', date: '2026-09-10', dateLabel: '2026.09.05 — 09.10', type: '住院', hospital: '示例医院 A · 呼吸内科', claim: '已结案', claimId: 'DEMO-002', stage: '已有后续复诊', focus: '接着查看 9 月 18 日复诊', hint: '这次理赔已结案，后续就医仍单独保留。', summary: '示例出院记录列出肺炎诊断与住院日期。治疗明细和康复医嘱尚未提供，不能据此判断恢复情况。', cost: null, payment: '结案不代表全部报销；赔付金额及个人承担需查看结算资料。', docs: [{ name: '住院记录摘录', quote: '诊断：肺炎。2026 年 9 月 5 日入院，9 月 10 日出院。' }], question: '出院后的用药与观察要求，是否有完整书面医嘱？', next: 'pneumonia-followup' },
    { id: 'fracture-visit', group: 'fracture', title: '骨折 · 门诊就诊', date: '2026-06-12', dateLabel: '2026.06.12', type: '门诊', hospital: '示例医院 B · 骨科', claim: '已结案', claimId: 'DEMO-001', stage: '历史记录', focus: '下次就诊时，方便回看', hint: '保留当次病历；当前恢复情况尚未更新。', summary: '示例门诊病历记录了骨折诊断。部位、治疗方式和后续复查情况未提供，暂不生成具体康复任务。', cost: null, payment: '尚未提供费用及赔付明细，无法计算最终自付。', docs: [{ name: '门诊病历摘录', quote: '2026 年 6 月 12 日，骨科门诊。诊断记录：骨折。' }], question: '能否补齐骨折部位、治疗方式和后续复查记录？' },
  ];
  let filter = 'all', view = 'condition';
  const baseRender = render;
  const route = id => `encounter-${id}`;
  const find = id => encounters.find(item => route(item.id) === id);
  const groupFor = item => groups.find(group => group.id === item.group);
  const action = (text, target, cls = 'records-link') => `<button class="${cls}" data-go="${target}">${text}${icon('arrow', 15)}</button>`;

  function encounterCard(item) {
    return `<article class="records-encounter" data-tone="${groupFor(item).tone}">
      <div class="records-date"><span>${item.dateLabel}</span><span>${item.type}</span></div>
      <button class="records-title-link" data-go="${route(item.id)}"><h3>${item.title}</h3>${icon('arrow', 17)}</button>
      <p class="records-hospital">${item.hospital}</p>
      <div class="records-statuses"><span class="records-care-status">${item.stage}</span><span>理赔 · ${item.claim}</span></div>
      <div class="records-next"><span class="records-next-icon">${icon('leaf', 16)}</span><div><strong>${item.focus}</strong><p>${item.hint}</p></div></div>
      <div class="records-card-bottom"><span>${item.docs.length} 份示例摘录</span>${action('查看这次就医', route(item.id))}</div>
    </article>`;
  }

  function recordsPage() {
    const visible = encounters.filter(item => filter === 'all' || item.group === filter);
    const list = view === 'condition' ? groups.filter(group => visible.some(item => item.group === group.id)).map(group => {
      const items = visible.filter(item => item.group === group.id);
      return `<section class="records-group"><div class="records-group-heading"><span class="records-group-icon ${group.tone}">${icon(group.icon, 21)}</span><div><h2>${group.name}<small>${items.length} 次就医</small></h2><p>${group.subtitle}</p></div></div><div class="records-group-items">${items.map(encounterCard).join('')}</div></section>`;
    }).join('') : `<section class="records-timeline" aria-label="按时间排列的就医记录">${[...visible].sort((a,b) => b.date.localeCompare(a.date)).map(encounterCard).join('')}</section>`;
    return `<div class="records-page">
      <section class="records-profile" aria-label="基本信息"><span class="records-profile-kicker">我的健康档案 <span>虚构示例</span></span><img class="records-profile-art" src="assets/care-archive-v1.webp" width="136" height="136" alt=""><div class="records-profile-top"><span class="records-avatar">${icon('user', 26)}</span><div class="records-person"><h2>小安 <span>本人</span></h2><p>性别未填写<span>·</span>年龄未填写</p></div></div><p class="records-profile-saying">每一次看病，都好好记下。</p><div class="records-profile-bottom"><div class="records-profile-counts"><span><strong>${encounters.length}</strong>次就医</span><span><strong>${groups.length}</strong>个病情分组</span></div><button data-go="privacy" aria-label="查看资料使用说明">${icon('file', 14)}资料说明${icon('arrow', 13)}</button></div></section>
      <div class="records-section-heading"><div><span class="records-section-kicker">CARE JOURNEY</span><h2>你的就医足迹</h2><p>把相关的看病经历，慢慢串起来</p></div><span>${visible.length} 次就医</span></div>
      <div class="records-controls"><div class="records-view" role="group" aria-label="记录排列方式"><button data-records-view="condition" aria-pressed="${view === 'condition'}">按病情</button><button data-records-view="time" aria-pressed="${view === 'time'}">按时间</button></div><span>最近就医优先</span></div>
      <div class="records-filters" role="group" aria-label="按病情筛选">${[{id:'all',name:'全部'}, ...groups.slice(1), groups[0]].map(group => `<button data-records-filter="${group.id}" aria-pressed="${filter === group.id}">${group.name === '病情待确认' ? '待确认' : group.name}${group.id === 'all' ? `<span>${encounters.length}</span>` : ''}</button>`).join('')}</div>
      <div id="records-results">${list}</div>
      <aside class="records-note">${icon('care', 17)}<p>理赔结束，关怀还可以继续。<br><span>这里展示虚构档案与摘录，尚未关联真实理赔。</span></p></aside>
    </div>`;
  }

  function encounterPage(item) {
    const group = groupFor(item);
    return `<div class="records-detail">
      <section class="records-detail-hero"><span class="records-detail-label">${group.name} · 虚构示例</span><h2>${item.title}</h2><p>${item.dateLabel}</p><p>${item.hospital}</p><div class="records-statuses"><span class="records-care-status">${item.stage}</span><span>理赔 · ${item.claim}</span></div></section>
      <section class="records-detail-card"><h3>这次看病，先了解这些</h3><p>${item.summary}</p><details class="records-evidence"><summary>查看本次资料依据 · ${item.docs.length} 份摘录</summary>${item.docs.map(doc => `<div><h4>${doc.name}</h4><blockquote>${doc.quote}</blockquote><small>虚构示例摘录 · 非真实原件</small></div>`).join('')}</details></section>
      <section class="records-detail-card records-care-card"><div class="records-detail-heading">${icon('leaf',20)}<h3>接下来，关心这件事</h3></div><strong>${item.focus}</strong><p>${item.hint}</p><div class="records-question"><small>可以向医院确认</small><p>${item.question}</p></div>${item.next ? action('查看后续复诊', route(item.next), 'records-detail-action') : ''}${item.id === 'current' ? action('查看现有康复指引', 'recovery', 'records-detail-action') : ''}</section>
      <section class="records-detail-card"><div class="records-detail-heading">${icon('cost',20)}<h3>费用与理赔</h3></div><div class="records-detail-money"><span>医疗费用总额</span><strong>${item.cost ? '¥ ' + item.cost : '待补充'}</strong></div><p>${item.payment}</p><dl class="records-claim-meta"><div><dt>关联理赔</dt><dd>${item.claimId}</dd></div><div><dt>理赔状态</dt><dd>${item.claim}</dd></div></dl><small>理赔状态与恢复情况分别记录。</small></section>
      <p class="records-detail-footnote">仅展示本次就医的示例内容；其他就医的费用与资料不会混入这里。</p>
      ${action('返回全部就医记录', 'records', 'records-detail-action')}
    </div>`;
  }

  encounters.forEach(item => { parentPage[route(item.id)] = 'records'; });
  render = function() {
    const id = pageId(), item = find(id);
    if (id === 'records') details.records = ['就医记录', recordsPage()];
    if (item) details[id] = ['这次就医', encounterPage(item)];
    baseRender();
    main.classList.toggle('records-screen', id === 'records');
    main.classList.toggle('records-detail-screen', !!item);
  };
  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.recordsFilter !== undefined) {
      filter = button.dataset.recordsFilter;
      positions.records = main.scrollTop;
      render();
      main.querySelector(`[data-records-filter="${filter}"]`)?.focus({preventScroll: true});
    }
    if (button.dataset.recordsView !== undefined) {
      view = button.dataset.recordsView;
      positions.records = main.scrollTop;
      render();
      main.querySelector(`[data-records-view="${view}"]`)?.focus({preventScroll: true});
    }
  });
  render();
})();
