// Only fictional source excerpts are displayed in this prototype.
const documentHero=(kind,title,subtitle)=>`<div class="document-hero"><span class="document-kind">本次就医 · 已列出的资料</span><h2>${title}</h2><p>${subtitle}</p><img src="assets/${kind==='test'?'onboard-materials':'onboard-document'}.webp" alt=""></div>`;
const sourceExcerpt=(title,page,text)=>`<section class="source-paper"><div class="source-heading"><span>${icon('file',17)} ${title}</span><small>${page}</small></div><blockquote>${text}</blockquote><div class="paper-bottom">资料原文<span></span></div></section>`;
const warmNote=text=>`<aside class="warm-note"><img src="assets/home-chat.webp?img=20261002c" alt="暖暖"><div><strong>暖暖帮你理一理</strong><p>${text}</p></div></aside>`;
const askDocument=(question,label='这份资料，问问暖暖')=>`<button class="primary document-ask" data-document-question="${question}">${icon('chat',20)}${label}${icon('arrow',16)}</button>`;
details.discharge=['出院记录',`${documentHero('discharge','回家后的安排，先看这里','10 月 8 日出院 · 医院名称待补充')}
<section class="card document-focus"><div class="document-label">这份记录里写了</div><div class="followup-summary"><div class="document-date"><small>10 月</small><b>12</b></div><div><h3>上午复诊</h3><p>并复查血常规</p><span class="soft-tag">具体几点还需核对</span></div></div><div class="bring-line">${icon('file',18)}记得带上本次就医材料</div></section>
${sourceExcerpt('出院记录','第 2 页','出院后建议 10 月 12 日上午复诊并复查血常规，请携带本次就医材料。')}
<section class="card document-check"><h3>去之前，再问清楚这两件事</h3><div class="check-line"><span>01</span><div><strong>几点去、去哪里？</strong><p>记录只写了“上午”，没有具体时间和地点。</p></div></div><div class="check-line"><span>02</span><div><strong>挂哪个科室，需要预约吗？</strong><p>这些信息没有写在这段记录里，可以向医院确认。</p></div></div>${btn('查看复查安排','appointment','outline')}</section>
${warmNote('不用一次记住所有事。先把复诊时间和地点问清楚，再把资料带齐。')}${askDocument('这份出院记录里的复诊安排，我还需要确认什么？')}<p class="document-footnote">这里只展示记录中已有的安排。</p>`];
details.evidence=['费用单',`${documentHero('cost','这笔费用，先分清楚','费用单 · 第 1 页')}
<section class="card document-focus cost-focus"><div class="document-label">费用单总额</div><div class="bill-total"><span>¥</span>1,200<span>.00</span></div><p>这次费用的合计，不等于最后自己付的钱。</p><div class="cost-facts"><div><span>报销金额</span><strong>暂未提供</strong></div><div><span>最终自付</span><strong>还不能确定</strong></div></div></section>
${sourceExcerpt('费用单','第 1 页','费用总额 1200.00 元。各项费用与支付方式请以正式结算资料为准，资料未包含报销信息。')}
<section class="card document-check"><h3>想知道最后自付多少？</h3><p>可以补充写有支付、报销明细的结算资料，才能进一步核对。</p><button class="upload-document" data-action="upload"><span class="upload-document-icon">＋</span><span><strong>补充结算资料</strong><small>拍照或选择手机里的文件</small></span>${icon('arrow',17)}</button><p class="document-local">文件尚未上传，暂时不能更新金额。</p></section>
${warmNote('看到总额先别着急。这份资料还没有报销信息，不能把 1,200 元都算成你的负担。')}${askDocument('这份费用单的总额和自付有什么区别？')}<p class="document-footnote">实际支付金额以结算资料为准</p>`];
details.test=['检查单',`${documentHero('test','检查结果，要结合报告看','本次就医 · 检查资料')}
<section class="card document-focus"><div class="document-label">这份已列出的资料的情况</div><h3>还没有具体检查结果</h3><p class="result-description">目前只有一段说明，没有检查项目、数值或参考范围，暂时不能判断结果是否正常。</p><div class="result-fields"><span>检查项目<b>未提供</b></span><span>检查数值<b>未提供</b></span><span>参考范围<b>未提供</b></span></div></section>
${sourceExcerpt('检查单','资料摘录','本次检查已记录于就医材料。尚未提供具体检查结果。')}
<section class="card document-check"><h3>拿到完整报告后，可以补在这里</h3><p>尽量拍清楚整页，保留检查日期、项目名称、结果和参考范围。</p><button class="upload-document" data-action="upload"><span class="upload-document-icon">＋</span><span><strong>补充检查报告</strong><small>支持照片和 PDF 文件</small></span>${icon('arrow',17)}</button><p class="document-local">文件尚未上传，暂时不能读取报告内容。</p></section>
${warmNote('不用急着自己猜结果。把完整报告准备好，有不明白的项目可以记下来再问。')}${askDocument('看检查报告时，我需要提供哪些内容？')}<p class="document-footnote">补充完整报告后，才能进一步了解检查结果。</p>`];
