"""Run the official HPD Transformers implementation on a frozen image manifest.

Only writes private OCR artifacts; gold is copied by reference, never read by inference.
Run in an isolated environment containing torch, torchvision, transformers and timm.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-root', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output-root', required=True)
    parser.add_argument('--output-manifest', required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output, output_manifest = Path(args.output_root).resolve(), Path(args.output_manifest).resolve()
    if any(p.is_relative_to(repo) for p in (output, output_manifest)):
        parser.error('Medical artifacts must stay outside Git')
    model_root = Path(args.model_root).resolve()
    manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8-sig'))
    rows = manifest['documents'][:args.limit] if args.limit else manifest['documents']

    import torch
    import transformers
    from PIL import Image
    from transformers import AutoModel, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError('HPD experiment requires a working CUDA GPU')
    # Official model repository contains custom architecture and preprocessing code.
    spec = importlib.util.spec_from_file_location('hpd_image_preprocess', model_root / 'image_preprocess.py')
    preprocess = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preprocess)
    version = 'hpd-parsing-transformers-bf16-mtp6-24tiles-v1'
    metadata = {'parser_version': version, 'torch': torch.__version__,
                'transformers': transformers.__version__, 'cuda': torch.version.cuda,
                'device': torch.cuda.get_device_name(0), 'max_new_tokens_per_branch': 8000,
                'batch_children': False, 'use_mtp': True, 'num_speculative_tokens': 6,
                'model_files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in model_root.iterdir() if p.suffix in {'.py', '.json'}},
                'model_weights_bytes': (model_root / 'model.safetensors').stat().st_size}
    output.mkdir(parents=True, exist_ok=True)
    write(output / 'runtime.json', metadata)
    print({'stage': 'loading', 'device': metadata['device'], 'profile': version}, flush=True)
    started = time.monotonic()
    model, loading = AutoModel.from_pretrained(str(model_root), torch_dtype=torch.bfloat16,
        trust_remote_code=True, local_files_only=True, output_loading_info=True,
        use_flash_attn=False)
    if loading.get('missing_keys') or loading.get('mismatched_keys'):
        write(output / 'loading-issues.json', loading)
        raise RuntimeError('Model has missing or mismatched weights; refusing a random-weight comparison')
    model = model.eval().to('cuda')
    model.load_mtp_weights()
    tokenizer = AutoTokenizer.from_pretrained(str(model_root), trust_remote_code=True,
                                              local_files_only=True, use_fast=False)
    metadata['load_seconds'] = round(time.monotonic() - started, 3)
    write(output / 'runtime.json', metadata)
    completed_rows = []
    for index, row in enumerate(rows, 1):
        destination = output / row['case_id'] / (Path(row['image']).stem + '.json')
        if destination.exists():
            raise RuntimeError('Use a fresh output directory; do not silently reuse or overwrite predictions')
        started = time.monotonic()
        torch.cuda.reset_peak_memory_stats()
        pixel_values = None
        try:
            with Image.open(row['image']) as source:
                width, height = source.size
                image = source.convert('RGB')
            rotation = row.get('image_rotation_degrees', 0)
            if rotation not in (0, 90, 180, 270):
                raise ValueError('Invalid frozen image rotation')
            if rotation:
                image = image.rotate(-rotation, expand=True)
            with tempfile.TemporaryDirectory(prefix='hpd-page-', dir=output) as tmp:
                image_path = Path(tmp) / 'input.png'
                image.save(image_path)
                pixel_values = preprocess.load_image(str(image_path)).to(dtype=torch.bfloat16, device='cuda')
                with torch.inference_mode():
                    response = model.generate_hpd(tokenizer, pixel_values,
                        'document parsing with fork.', {'max_new_tokens': 8000},
                        use_mtp=True, num_speculative_tokens=6, batch_children=False)
            torch.cuda.synchronize()
            # Preserve the complete structured representation, including table content.
            # No synthetic cell boxes or confidence scores are invented for VLM output.
            cache = {'text': response, 'raw_hpd_output': response, 'lines': [],
                     'ocr_status': 'ok' if response.strip() else 'empty',
                     'image_size': [width, height], 'image_rotation_degrees': rotation,
                     'tiles': int(pixel_values.shape[0]),
                     'peak_gpu_allocated_bytes': torch.cuda.max_memory_allocated()}
        except Exception as exc:
            cache = {'text': '', 'lines': [], 'ocr_status': 'failed',
                     'error_code': type(exc).__name__}
            # Keep diagnostic detail only in the explicitly private artifact directory.
            write(destination.with_suffix('.error.json'), {'error': str(exc)})
        finally:
            del pixel_values
            torch.cuda.empty_cache()
        cache.update(parser='hpd_parsing', parser_version=version,
                     seconds=round(time.monotonic() - started, 3))
        write(destination, cache)
        updated = dict(row, ocr=str(destination),
                       ocr_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                       ocr_source_status=cache['ocr_status'])
        completed_rows.append(updated)
        write(output_manifest, dict(manifest, documents=completed_rows))
        print({'done': index, 'total': len(rows), 'status': cache['ocr_status'],
               'seconds': cache['seconds']}, flush=True)


if __name__ == '__main__':
    main()
