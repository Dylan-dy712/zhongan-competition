import {build} from 'rolldown';
import {mkdir,rm} from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';

export async function loadTestModules(){
  const root=fileURLToPath(new URL('..',import.meta.url));
  const out=path.join(root,'.test-modules');await mkdir(out,{recursive:true});
  await build({input:{PatientMemory:path.join(root,'src/PatientMemory.tsx'),EncounterOverview:path.join(root,'src/EncounterOverview.tsx'),AnalysisFlow:path.join(root,'src/AnalysisFlow.tsx'),App:path.join(root,'src/App.tsx'),PageBoundary:path.join(root,'src/PageBoundary.tsx'),api:path.join(root,'src/api.ts'),
    PersonalRecords:path.join(root,'src/PersonalRecords.tsx'),HomeReminders:path.join(root,'src/HomeReminders.tsx'),reminderProjection:path.join(root,'src/reminderProjection.ts')},
    external:id=>/^(react|react-dom)(\/|$)/.test(id),
    transform:{jsx:{runtime:'automatic'},define:{'import.meta.env':'{}'}},
    plugins:[{name:'test-assets',load(id){if(/\.(css|webp)$/.test(id))return {code:`export default ${JSON.stringify(id)};`,moduleType:'js'};}}],
    output:{dir:out,format:'esm',entryFileNames:'[name].mjs'}});
  return {EncounterOverview:(await import(pathToFileURL(path.join(out,'EncounterOverview.mjs')).href)).default,analysisView:(await import(pathToFileURL(path.join(out,'AnalysisFlow.mjs')).href)).analysisView,App:(await import(pathToFileURL(path.join(out,'App.mjs')).href)).default,
    PatientMemory:(await import(pathToFileURL(path.join(out,'PatientMemory.mjs')).href)).PatientMemory,
    api:await import(pathToFileURL(path.join(out,'api.mjs')).href),
    HomeReminders:(await import(pathToFileURL(path.join(out,'HomeReminders.mjs')).href)).default,
    PersonalRecords:(await import(pathToFileURL(path.join(out,'PersonalRecords.mjs')).href)).default,
    reminderProjection:await import(pathToFileURL(path.join(out,'reminderProjection.mjs')).href),
    PageBoundary:(await import(pathToFileURL(path.join(out,'PageBoundary.mjs')).href)).PageBoundary,
    close:()=>rm(out,{recursive:true,force:true})};
}
