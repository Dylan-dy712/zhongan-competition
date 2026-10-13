import {narrativeBlocks,type NarrativeBlock} from './narrativeFormatting';
export const overviewTabs=[['facts','病历摘要'],['insights','需要关注'],['care','康复指引'],['quality','就医参考']] as const;
export type OverviewTab=typeof overviewTabs[number][0];
// Reorganize already reviewed prose verbatim; do not generate clinical advice.
export function overviewNarrative(text:string):Record<OverviewTab,NarrativeBlock[]> {
 const blocks=narrativeBlocks(text);
 const care=(b:NarrativeBlock)=>b.kind==='closing'||/康复|恢复|复诊|随访|出院后|回家后|术后.*(?:护理|安排)|接下来|下一步|后续安排/.test([b.text,...b.paragraphs].join('\n'));
 const attention=(b:NarrativeBlock)=>/核对|确认|注意|关注|待补|不确定|缺少|未见|未提供|暂无|尚未|不能|需.*确认|无法|疑点|冲突|费用|报销|支付/.test([b.text,...b.paragraphs].join('\n'));
 const reference=(b:NarrativeBlock)=>/复诊|随访|就医|就诊|问诊|医生|医院|检查.*(?:安排|复查)/.test([b.text,...b.paragraphs].join('\n'));
 const summary=blocks.filter(b=>!care(b));
 return {facts:summary.length?summary:blocks,insights:blocks.filter(attention),care:blocks.filter(care),quality:blocks.filter(reference)};
}
