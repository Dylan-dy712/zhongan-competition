export function isMoney(value:unknown):value is {amount_minor:number;currency:string}{
 return !!value&&typeof value==='object'&&'amount_minor' in value&&'currency' in value;
}
export function factValueText(value:unknown):string{
 if(value===null||value===undefined)return '暂无明确结果';
 if(isMoney(value))return Number.isSafeInteger(value.amount_minor)?`${(value.amount_minor/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})} ${value.currency==='CNY'?'元':value.currency}`:'金额需核对原文';
 if(Array.isArray(value))return value.map(factValueText).join('；');
 if(typeof value==='object'){
  const fields:Record<string,string>={drug_name:'药品',dose:'剂量',frequency:'频次',route:'途径',name:'名称',phase:'阶段',text:'内容'};
  const phases:Record<string,string>={inpatient:'住院期间',discharge:'出院时',outpatient:'门诊',unknown:'待核对',historical:'既往'};
  const entries=Object.entries(value).filter(([key,v])=>key in fields&&v!==null&&v!==undefined);
  return entries.length?entries.map(([key,v])=>`${fields[key]}：${key==='phase'?(phases[String(v)]||String(v)):factValueText(v)}`).join('；'):'结构化详情请展开下方 JSON，原始内容可查看来源。';
 }
 return String(value);
}
