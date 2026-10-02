// Fictional encounter fixtures shared by home, records, chat and expense views.
const careContext = (() => {
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

  encounters[0].followup = { month:'10', day:'12', period:'上午', title:'复诊并复查血常规' };
  encounters.forEach(item => item.docs.forEach(doc => { doc.kind = doc.name.includes('费用') ? 'cost' : 'record'; }));
  return {
    groups, encounters, activeId:'current',
    find(id) { return encounters.find(item => item.id === id); },
    get current() { return this.find(this.activeId); }
  };
})();
