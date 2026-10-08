// Visual estimates stay inside the current persisted stage. Completion is server-owned.
const stageSeconds=[22,32,30,45,12,45];
export function estimateWithinStage(base:number,index:number,elapsedSeconds:number) {
  const ceiling=index===5?99:index===4?94:base+19;
  const duration=stageSeconds[index] || 30;
  const fraction=1-Math.exp(-Math.max(0,elapsedSeconds)/duration);
  return Math.min(ceiling,base+1+(ceiling-base)*fraction);
}
