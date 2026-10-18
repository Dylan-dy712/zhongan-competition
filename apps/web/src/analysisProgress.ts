// Extraction and insight checks overlap on the worker: neither is complete until guidance starts.
export const analysisSteps=[['parse','识别材料'],['analysis','分析与核对'],['guidance','整理重点'],['validate','校验来源'],['narrative','写好解读']] as const;
export function analysisStageIndex(stage?:string) {
  switch(stage){
    case 'parse':return 0;
    case 'extract':case 'insights':case 'reconcile':return 1;
    case 'guidance':return 2;
    case 'validate':return 3;
    case 'narrative':return 4;
    default:return -1;
  }
}

// Display estimates stay inside the current real stage. They never complete a step.
export function estimatedStagePercent(index:number,elapsedSeconds:number) {
  const durations=[18,55,35,15,45];
  const base=index/analysisSteps.length*100;
  return Math.min(base+19,base+Math.floor(20*(1-Math.exp(-Math.max(0,elapsedSeconds)/durations[index]))));
}
export function smoothPercent(previous:number,target:number) {
  return previous<target?Math.min(target,previous+1):previous;
}
