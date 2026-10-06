import {build} from 'rolldown';
import {mkdir,rm} from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';

export async function loadTestModules(){
  const root=fileURLToPath(new URL('..',import.meta.url));
  const out=path.join(root,'.test-modules');await mkdir(out,{recursive:true});
  await build({input:{App:path.join(root,'src/App.tsx'),PageBoundary:path.join(root,'src/PageBoundary.tsx')},
    external:id=>/^(react|react-dom)(\/|$)/.test(id),
    transform:{jsx:{runtime:'automatic'},define:{'import.meta.env':'{}'}},
    plugins:[{name:'test-assets',load(id){if(/\.(css|webp)$/.test(id))return {code:`export default ${JSON.stringify(id)};`,moduleType:'js'};}}],
    output:{dir:out,format:'esm',entryFileNames:'[name].mjs'}});
  return {App:(await import(pathToFileURL(path.join(out,'App.mjs')).href)).default,
    PageBoundary:(await import(pathToFileURL(path.join(out,'PageBoundary.mjs')).href)).PageBoundary,
    close:()=>rm(out,{recursive:true,force:true})};
}
