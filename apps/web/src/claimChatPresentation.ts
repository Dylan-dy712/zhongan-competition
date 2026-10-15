import type {ChatTurn} from './types';

const sampleNotice='这是一组主办方比赛样例的脱敏体验资料，不代表账号使用者本人病史。';
const prefix='请帮我整理本次就医资料，解释费用与需要补充的材料。用户填写的信息：';
const separator='；材料分类：';
const suffix='。这些是个人补充信息，请以材料原文核对，不代表已确认事实。';

/** Recognize the claim form's generated request, including saved sample conversations. */
export function isClaimSubmission(turn:ChatTurn):boolean {
  if(turn.input_kind!=='user')return false;
  const question=turn.question.startsWith(sampleNotice)?turn.question.slice(sampleNotice.length):turn.question;
  if(!question.startsWith(prefix)||!question.endsWith(suffix))return false;
  const split=question.lastIndexOf(separator);
  if(split<prefix.length)return false;
  try {
    const form=JSON.parse(question.slice(prefix.length,split));
    const groups=JSON.parse(question.slice(split+separator.length,-suffix.length));
    return !!form&&typeof form==='object'&&!Array.isArray(form)&&typeof form.kind==='string'
      &&Array.isArray(groups)&&groups.every(group=>group&&typeof group.category==='string'&&Number.isInteger(group.count)&&group.count>=0);
  } catch {return false;}
}
