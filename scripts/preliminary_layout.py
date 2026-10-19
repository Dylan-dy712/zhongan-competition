"""Freeze image-only VLM layout plans before OCR; retain uncertain/failed pages."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import time

import requests

from services.api.app.llm_extractor import OpenAiCompatibleExtractor
from services.api.app.material_layout import LAYOUT_VERSION, MaterialLayout, analyze_material_layout
from scripts.preliminary_kr1 import load, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    for path in (args.output_root, args.output):
        if Path(path).resolve().is_relative_to(repo):
            parser.error('layout inputs and outputs must remain outside Git')
    os.environ.update({key: str(value) for key, value in load(args.config).items() if key.startswith('LLM_')})
    provider = OpenAiCompatibleExtractor()
    if provider.provider == 'mock':
        parser.error('layout effect experiments require a live model')
    manifest = load(args.manifest)
    provenance = {'version': LAYOUT_VERSION, 'model_id': provider.model_id,
        'source_manifest_sha256': sha(args.manifest),
        'implementation_sha256': {name: sha(repo/name) for name in (
            'scripts/preliminary_layout.py', 'services/api/app/material_layout.py',
            'services/api/app/model_workloads.py')}}

    def plan(index, original):
        row = dict(original)
        destination = Path(args.output_root)/f"{row['document_id']}.json"
        record = load(destination) if destination.exists() else {}
        if record and any(record.get(key) != value for key, value in provenance.items()):
            raise ValueError('layout source or implementation changed; use a new output directory')
        if record.get('status') != 'completed':
            record = {**provenance, 'status': 'failed', 'attempts': []}
            started = time.monotonic()
            image = Path(row['image']).read_bytes()
            for _ in range(2):
                try:
                    payload, content = analyze_material_layout(provider, image)
                    prediction = MaterialLayout.model_validate_json(content)
                    record.update(status='completed', plan=prediction.model_dump(mode='json'))
                    record['attempts'].append({'status': 'completed', 'usage': payload.get('usage', {})})
                    break
                except (requests.RequestException, ValueError, KeyError) as exc:
                    record['attempts'].append({'status': 'failed', 'error_code': type(exc).__name__})
            record['seconds'] = round(time.monotonic()-started, 3)
        prediction = record.get('plan', {})
        accepted = (record['status'] == 'completed' and prediction.get('rotation_degrees') is not None
                    and prediction['orientation_confidence'] >= .9)
        original_rotation = row.get('image_rotation_degrees', 0)
        record.update(original_rotation_degrees=original_rotation,
                      orientation_selected=accepted, requires_review=not accepted,
                      confidence_method='model_self_report_uncalibrated')
        if accepted:
            row.update(image_rotation_degrees=prediction['rotation_degrees'],
                       orientation_method=LAYOUT_VERSION, orientation_review_required=False)
        record['adopted_rotation_degrees'] = row.get('image_rotation_degrees', 0)
        row['material_layout'] = record
        write(destination, record)
        return index, row

    rows = list(manifest['documents'])
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
        jobs = [pool.submit(plan, index, row) for index, row in enumerate(rows)]
        for count, job in enumerate(as_completed(jobs), 1):
            index, row = job.result()
            rows[index] = row
            print({'done': count, 'total': len(rows), 'status': rows[index]['material_layout']['status']}, flush=True)
    manifest.update(documents=rows, layout_preparation=provenance)
    write(args.output, manifest)


if __name__ == '__main__':
    main()
