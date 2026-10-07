/** Update the legacy design while retaining live controls, focus and scroll containers. */
function identity(node:Node):string {
 if(node.nodeType!==1)return String(node.nodeType);
 const element=node as Element;
 return [element.tagName,element.getAttribute('data-claim-field')||element.getAttribute('data-claim-action')||element.getAttribute('data-claim-remove')||element.getAttribute('data-claim-preview')||element.getAttribute('aria-label')||element.getAttribute('class')||''].join(':');
}
function syncChildren(target:Node,source:Node){
 let cursor:Node|null=target.firstChild;
 for(const desired of Array.from(source.childNodes)){
  let match:Node|null=cursor;
  while(match&&identity(match)!==identity(desired))match=match.nextSibling;
  if(!match){match=desired.cloneNode(true);target.insertBefore(match,cursor);}
  else {
   if(match!==cursor)target.insertBefore(match,cursor);
   if(match.nodeType===1&&desired.nodeType===1){
    const live=match as Element, fresh=desired as Element;
    for(const attr of Array.from(live.attributes))if(!fresh.hasAttribute(attr.name))live.removeAttribute(attr.name);
    for(const attr of Array.from(fresh.attributes))if(live.getAttribute(attr.name)!==attr.value)live.setAttribute(attr.name,attr.value);
    syncChildren(match,desired);
    if(live.tagName==='INPUT'||live.tagName==='SELECT'){
     const control=live as HTMLInputElement|HTMLSelectElement, wanted=fresh as HTMLInputElement|HTMLSelectElement;
     if(control.value!==wanted.value)control.value=wanted.value;
    }
   }else if(match.nodeValue!==desired.nodeValue)match.nodeValue=desired.nodeValue;
  }
  cursor=match.nextSibling;
 }
 while(cursor){const next=cursor.nextSibling;target.removeChild(cursor);cursor=next;}
}
export function syncClaimMarkup(target:HTMLElement,html:string){
 const template=document.createElement('template');template.innerHTML=html;
 syncChildren(target,template.content);
}
