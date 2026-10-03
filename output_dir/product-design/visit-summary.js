// Presentation structure informed by source-document categories, without patient data.
const reportSection=(number,title,description,source)=>`<section class="card summary-section"><span class="summary-number">${number}</span><h3>${title}</h3><p>${description}</p>${btn('查看相关资料',source,'link')}</section>`;
details.summary=['这次看病的总结',`${documentHero('discharge','把这次看病的经过理清楚','结合病历、检查报告和治疗记录整理')}
<section class="card document-focus"><span class="soft-tag">等待资料整理</span><h3 style="margin-top:12px">还没有可以展示的总结</h3><p style="margin-top:8px">当前尚未读取你的看病资料。资料中的诊断、检查和治疗信息，会按下面的顺序整理在一起。</p></section>
<section class="card document-check"><h3>先分清是哪次看病</h3><p>按就诊日期整理经过。多次看病分别记录；只有确认属于同一次的资料，才放在一起。日期或归属不清楚时，先请你核对。</p></section>
${reportSection('01','为什么去看病','主要不适、就诊原因和医生记录的诊断放在一起说明；初步判断与最终诊断会分开呈现。','raw-record')}
${reportSection('02','做了哪些检查，结果怎么说','结合检验、影像、病理等资料整理结果，保留日期和出处。多次检查分开呈现，未出结果不当作正常。','raw-test')}
${reportSection('03','接受了哪些治疗','根据现有资料整理用药、处置和治疗经过。有手术记录才展示手术内容；开过药、买过药和实际用过药分别说明。','raw-record')}
${reportSection('04','这次看病后，目前了解到什么','归纳医生记录的治疗结果和目前情况。仍需确认的内容单独说明，不把缺少结果当成正常。','materials')}
<section class="card document-check"><h3>想单独看看费用？</h3><p>费用总额、报销和自付，放在一起解释。</p>${btn('这次看病的费用','evidence','outline')}</section>
${warmNote('资料可以一份份补齐。有不明白的内容，可以带着相关资料问暖暖。')}${askDocument('帮我解释这次看病的总结。','看病的事，问问暖暖')}`];
details['raw-record']=['病历记录',`${documentHero('discharge','医生怎么记录这次看病','门诊病历、住院记录或出院小结')}<section class="card document-focus"><h3>还没有可查看的病历原文</h3><p>这里保留你提交的原始资料。门诊病历和出院小结都会归到本次就医，不要求必须有住院经历。</p>${uploadButtonForRecord()}</section><section class="card document-check"><h3>想看整理后的说明？</h3><p>诊断、检查和治疗经过会放在同一份总结里。</p>${btn('这次看病的总结','summary','outline')}</section>`];
function uploadButtonForRecord(){return '<button class="outline" data-action="upload">＋ 补充看病资料</button><p class="document-local">文件仅在当前页面预览，尚未上传。</p>';}
details['raw-test']=['检查报告',`${documentHero('test','检查报告，按原件保存','检验、影像及其他检查资料')}<section class="card document-focus"><h3>还没有可查看的检查原文</h3><p>检查项目、结果、单位、参考范围和日期一起保留，方便你核对。相同检查的不同日期不会混在一起。</p>${uploadButtonForRecord()}</section><section class="card document-check"><h3>检查结果放回这次看病里理解</h3><p>检查与诊断、治疗的关系，会在看病总结里一起说明。</p>${btn('这次看病的总结','summary','outline')}</section>`];
// Old links retain a destination; they now open the single integrated summary.
details.discharge=details.summary;details.test=details['raw-test'];details.guide=details.summary;
details.materials=['看病资料',`<section class="card"><h2>这次看病的原始资料</h2><p>病历、检查和费用分开保存，方便查找。</p>${row('病历记录','门诊病历、住院记录、出院小结','raw-record')}${row('检查报告','检验、影像及其他检查','raw-test')}${row('用药与治疗','处方、用药清单、处置和手术记录','raw-treatment')}${row('费用资料','收费票据、购药凭证、费用明细与结算','evidence','cost')}${row('其他资料','诊断证明、转诊资料等','raw-other')}</section>`];
details.records=['就医记录',`<section class="card"><h2>看病经过，放在一起</h2><p>按每次就医整理，门诊和住院都可以记录。</p>${row('这次看病的总结','一起了解诊断、检查和治疗经过','summary')}${row('这次看病的费用','查看费用、报销与自付说明','evidence','cost')}${row('看病资料','查看或补充原始文件','materials')}</section>`];
details.evidence[0]='这次看病的费用';
home=function(){return `<div class="home"><header class="brand"><img src="assets/home-brand.webp?img=20261002c" alt="暖愈智护"></header><div class="hero"><img src="assets/home-hero.webp?img=20261002c" alt=""><h1>你好</h1><p>看懂这次看病，心里更有底。</p></div><section class="card summary"><span class="eyebrow">这次看病</span><h2>看病的事，一起理清楚</h2><p class="detail-sub">把病历、检查和治疗经过放在一起，了解医生怎么说。</p>${btn('查看看病总结 '+icon('arrow',16),'summary')}${row('这次看病的费用','费用、报销和自付说明','evidence','cost')}</section><div class="section-head"><h2>看病资料</h2></div><section class="card">${row('查看或补充资料','病历、检查报告、处方和费用单','materials')}</section><button class="card visit" data-go="chat"><img src="assets/home-chat.webp?img=20261002c" alt="" width="45"><span><h3>有不明白的，问问暖暖</h3><p>从你最在意的一件事开始</p></span>${icon('arrow',16)}</button><p class="footnote"></p></div>`;};

details['raw-treatment']=['用药与治疗',`${documentHero('discharge','用过哪些药，做过哪些治疗','处方、用药清单、处置及手术记录')}<section class="card document-focus"><h3>还没有可查看的原始资料</h3><p>处方说明医生开了什么药，购药凭证说明买了什么；不能仅凭这两项判断是否已经使用。治疗和手术记录按实际发生日期分别保存。</p>${uploadButtonForRecord()}</section>${btn('这次看病的总结','summary','outline')}`];
details['raw-other']=['其他资料',`${documentHero('discharge','其他看病资料，也放在这里','诊断证明、转诊资料等')}<section class="card document-focus"><h3>还没有可查看的原始资料</h3><p>不确定属于哪一类也可以先添加；整理时需要确认资料日期、所属就医，以及是否清晰完整。</p>${uploadButtonForRecord()}</section>`];
