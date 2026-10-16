"""Prepare material-only extraction and candidate identification; never a report."""
import argparse,hashlib,json,os,subprocess,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from services.judge_demo.app import sample_manifest
from services.api.app.worker import recognition_profile,KnowledgeAssembler,DiseaseCode,infer_disease_code
from services.api.app.judge_sample_cache import read_sample_pages
from services.api.app.judge_model_cache import canonical_material,read_models,write_models
from services.api.app.llm_extractor import OpenAiCompatibleExtractor,validate_evidence_quotes
from services.api.app.insight_llm import detect_semantic


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--from-worker-environment',action='store_true')
    args=parser.parse_args()
    if args.from_worker_environment:
        pid=subprocess.check_output(['systemctl','show','zhongan-worker','-p','MainPID','--value'],text=True).strip()
        if not pid.isdigit() or pid=='0':raise RuntimeError('WORKER_NOT_RUNNING')
        values=dict(item.split('=',1) for item in Path('/proc',pid,'environ').read_bytes().decode().split('\0') if '=' in item)
        os.environ.update({key:value for key,value in values.items() if key.startswith(('LLM_','ZHONGAN_'))})
    started=time.monotonic();directory,manifest=sample_manifest()
    profile,versions=recognition_profile('document-parser-v1');documents=[]
    for item in manifest['documents']:
        if hashlib.sha256((directory/item['file']).read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('SAMPLE_HASH_MISMATCH')
        pages=read_sample_pages(manifest,item,profile,versions)
        if len(pages)!=item['page_count']:raise RuntimeError('PREPARE_SAMPLE_OCR_FIRST')
        documents.append(({'source_hash':item['sha256']},list(pages.values())))
    material=canonical_material(documents);assembler=KnowledgeAssembler()
    entries=assembler.select(DiseaseCode.ty,patient_visible=False).allowed
    disease=infer_disease_code(material)
    if disease:
        assembler.check_exclusions(disease,material);entries+=assembler.select(disease,patient_visible=False).allowed
    reused=read_models(documents,entries,profile) is not None
    if not reused:
        client=OpenAiCompatibleExtractor()
        knowledge=[{'entry_id':entry.entry_id,'title':entry.title,'content':entry.content[:500],'anchoring':entry.anchoring} for entry in entries[:80]]
        with ThreadPoolExecutor(max_workers=2) as pool:
            fields=pool.submit(client.extract,material);insights=pool.submit(detect_semantic,material,knowledge)
            fields,insights=validate_evidence_quotes(fields.result(),material),insights.result()
        write_models(documents,entries,profile,fields,insights)
    print(json.dumps({'sample_id':manifest['sample_id'],'version':manifest['version'],'preprocessing_ready':True,
        'reused':reused,'seconds':round(time.monotonic()-started,3),'created_cases':0,'generated_reports':0}))


if __name__=='__main__':main()
