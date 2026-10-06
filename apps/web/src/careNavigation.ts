import {useCallback,useEffect,useState} from 'react';
import type {CarePanel} from './carePresentation';

export function readCarePanel(hash:string):CarePanel {
  const name=hash.replace(/^#\/?/, '').split('?')[0];
  return ['home','chat','report','records','review','claim','account'].includes(name) ? name as CarePanel : 'home';
}

export function useCareNavigation() {
  const [panel,updatePanel]=useState(()=>readCarePanel(window.location.hash));
  useEffect(()=>{
    const sync=()=>updatePanel(readCarePanel(window.location.hash));
    window.addEventListener('hashchange',sync);
    return ()=>window.removeEventListener('hashchange',sync);
  },[]);
  const navigate=useCallback((next:CarePanel)=>{
    if(window.location.hash!==`#/${next}`) window.location.hash=`/${next}`;
    updatePanel(next);
  },[]);
  return [panel,navigate] as const;
}
