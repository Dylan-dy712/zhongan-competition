// The form owns uncertainty and free-text controls, including for saved replies.
const choiceKey=(value:string)=>value.normalize('NFKC').replace(/\s+/gu,'').replace(/[。！？!?，,；;：:、.]+$/u,'').toLowerCase();
const uncertainty=/^(?:我)?(?:目前|现在)?(?:还|暂时|暂|尚)?(?:不太?确定|不太?清楚|不知道|不记得|记不清楚?|没确定|未确定|无法确定|想不起来)(?:具体)?(?:复查时间|复查医院|用药情况|过敏情况|恢复情况|时间|医院|药名|过敏史)?(?:了)?$/;
const custom=/^(?:我来补充|我想补充|自行填写|手动填写|自己填写|其他|其他情况)$/;

export function distinctFollowupChoices<T extends {label:string;message:string}>(options:T[]):T[]{
  const labels=new Set<string>(),messages=new Set<string>();
  return options.filter(option=>{
    const label=choiceKey(option.label),message=choiceKey(option.message);
    if(uncertainty.test(label)||custom.test(label)||labels.has(label)||messages.has(message))return false;
    labels.add(label);messages.add(message);return true;
  });
}
