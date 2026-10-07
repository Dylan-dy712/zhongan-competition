# Generate isolated styles directly from the original demo. Run from any directory.
from pathlib import Path
root=Path(__file__).resolve().parents[3]; src=root/'output_dir/product-design'; out=root/'apps/web/src/demo-original.css'
def scope(css):
    result=[]; pos=0
    while pos<len(css):
        begin=css.find('{',pos)
        if begin<0:
            result.append(css[pos:]); break
        head=css[pos:begin]; depth=1; end=begin+1
        while end<len(css) and depth:
            if css[end]=='{': depth+=1
            elif css[end]=='}': depth-=1
            end+=1
        body=css[begin+1:end-1]
        import re
        clean=re.sub(r'/\*.*?\*/','',head,flags=re.S).strip()
        if clean.startswith('@media') or clean.startswith('@supports'):
            result.append(clean+'{'+scope(body)+'}')
        elif clean.startswith('@'): result.append(clean+'{'+body+'}')
        else:
            selectors=[]
            # Original selectors have no commas inside functional pseudos except :is().
            parts=re.split(r',\s*(?![^()]*\))',clean)
            for sel in parts:
                selectors.append('.demo-pages' if sel==':root' else '.demo-pages '+sel)
            result.append(','.join(selectors)+'{'+body+'}')
        pos=end
    return ''.join(result)
base='.demo-pages{flex:1;min-height:0;overflow:auto;background:#f3f8f5;color:#243c33;font:15px/1.6 "Microsoft YaHei UI","PingFang SC",sans-serif}.demo-pages *{box-sizing:border-box}.demo-pages :is(p,h1,h2,h3,h4){margin:0}.demo-pages button{font:inherit;border:0;background:none;cursor:pointer;color:inherit}.demo-pages button:disabled{cursor:wait;opacity:.5}.demo-pages svg{flex-shrink:0}.demo-pages .brand{display:flex;align-items:center}.demo-pages .page{padding:10px 18px 24px}.demo-pages .home{padding:0 20px 24px}.demo-pages em{font-style:normal}'
text=base+'\n'+ '\n'.join(scope((src/name).read_text(encoding='utf-8')) for name in ['care-home.css','records-page.css','care-polish.css','care-usability.css'])
text=text.replace('assets/','../../../output_dir/product-design/assets/')
text+='\n.demo-pages{--care-ink:#243c33;--care-copy:#425e52;--care-muted:#5c7368;--care-green:#007b5a;--care-border:#d6e9df;--care-tint:#ecfaf3}.demo-pages>.replica-home,.demo-pages>.records-screen,.demo-pages>.records-detail-screen{max-width:780px;margin:auto;min-height:100%}.demo-pages .demo-claim-link{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:16px;color:#007b5a;font-size:13px}.demo-pages .demo-back{padding:8px 0 18px;color:#007b5a}.demo-pages .records-profile-art{pointer-events:none}.demo-pages .replica-appointment strong{overflow-wrap:anywhere}.demo-pages .records-filters{overflow:auto}.demo-pages .records-person{position:relative;z-index:1}.demo-pages .records-person h2{overflow-wrap:anywhere}'
text += '\n.demo-pages .demo-account{max-width:680px;margin:auto;padding-top:24px}.demo-account>.records-profile{padding-bottom:20px;margin-bottom:20px}.demo-account h1{font-size:22px;overflow-wrap:anywhere}.demo-account h2{font-size:17px;margin:0 0 12px}.demo-account .records-detail-card>p{margin:10px 0}.demo-account .records-detail-card>small{display:block;margin-top:16px;font-size:12px;line-height:1.8}'
out.write_text(text,encoding='utf-8')
