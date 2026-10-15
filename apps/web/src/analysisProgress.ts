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
