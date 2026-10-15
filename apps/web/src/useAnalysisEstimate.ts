import {useEffect,useRef,useState} from 'react';
import {estimatedStagePercent,smoothPercent} from './analysisProgress';

export function useAnalysisEstimate(runKey:string,kind:string,index:number,confirmed:number|null) {
  const clock=useRef({runKey,stage:index,started:Date.now()});
  const [display,setDisplay]=useState({runKey,value:confirmed??0});
  useEffect(()=>{
    if(kind!=='processing'||index<0)return;
    const now=Date.now();
    if(clock.current.runKey!==runKey||clock.current.stage!==index)clock.current={runKey,stage:index,started:now};
    const tick=()=>setDisplay(previous=>{
      const value=previous.runKey===runKey
        ?smoothPercent(previous.value,estimatedStagePercent(index,(Date.now()-clock.current.started)/1000))
        :confirmed??0;
      return previous.runKey===runKey&&previous.value===value?previous:{runKey,value};
    });
    tick();const timer=setInterval(tick,250);return()=>clearInterval(timer);
  },[runKey,kind,index,confirmed]);
  if(kind!=='processing'||index<0||confirmed===null)return confirmed;
  return display.runKey===runKey?display.value:confirmed;
}
