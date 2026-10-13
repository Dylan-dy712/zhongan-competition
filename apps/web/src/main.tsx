import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
const QualityDemo = React.lazy(() => import('./QualityDemo'));
import "./styles.css";
import {PageBoundary} from "./PageBoundary";

function Application() {
  const [demo,setDemo]=React.useState(window.location.hash==='#/quality-demo');
  React.useEffect(()=>{
    const changed=()=>setDemo(window.location.hash==='#/quality-demo');
    window.addEventListener('hashchange',changed);
    return ()=>window.removeEventListener('hashchange',changed);
  },[]);
  return <PageBoundary resetKey={demo?'quality-demo':'application'}>{demo ?
    <React.Suspense fallback={<p role="status">正在打开模拟品质方案…</p>}><QualityDemo /></React.Suspense> : <App />}</PageBoundary>;
}
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><Application /></React.StrictMode>);
