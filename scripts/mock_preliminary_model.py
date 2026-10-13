"""Local-only OpenAI-compatible replay mock; never fabricates unknown-case answers."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
import uvicorn

from scripts.preliminary_kr1 import load, sha


def create_app(manifest=None, predictions_dir=None):
    app = FastAPI(title='Preliminary replay mock — not effect evidence')
    repo = Path(__file__).resolve().parents[1]
    care = load(repo / 'apps/web/src/care-demo.json')
    by_material = {record['material']: record for record in care}
    by_image, by_text = {}, {}
    if bool(manifest) != bool(predictions_dir):
        raise ValueError('document replay requires both manifest and predictions directory')
    if manifest:
        for row in load(manifest)['documents']:
            path = Path(predictions_dir) / (row['document_id'] + '.json')
            if not path.exists():
                continue
            prediction = load(path)
            if prediction.get('status') != 'completed':
                continue
            if prediction.get('image_sha256') != row['image_sha256'] or prediction.get('ocr_sha256') != row['ocr_sha256']:
                raise ValueError('replay prediction does not match frozen sources')
            by_image[row['image_sha256']] = prediction['result']
            if row.get('ocr') and sha(row['ocr']) == row['ocr_sha256']:
                text = load(row['ocr']).get('text', '')
                by_text[hashlib.sha256(text.encode()).hexdigest()] = prediction['result']

    @app.get('/health')
    def health():
        return {'status': 'ok', 'execution_mode': 'mock', 'backend': 'saved_result_replay',
                'synthetic_care_cases': len(care), 'document_sources': len(by_image),
                'official_effect_evidence': False}

    @app.post('/chat/completions')
    def completion(request: dict):
        source, image_hash = None, None
        for message in request.get('messages', []):
            if message.get('role') != 'user':
                continue
            content = message.get('content', '')
            if isinstance(content, list):
                for part in content:
                    if part.get('type') == 'image_url' and image_hash is None:
                        url = part.get('image_url', {}).get('url', '')
                        if url.startswith('data:'):
                            try:
                                image_hash = hashlib.sha256(base64.b64decode(url.split(',', 1)[1], validate=True)).hexdigest()
                            except (ValueError, IndexError):
                                raise HTTPException(400, 'invalid inline image')
                content = next((part['text'] for part in content if part.get('type') == 'text'), '')
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict) and 'schema' in parsed:
                source = parsed
                break
        if source is None:
            raise HTTPException(422, 'mock supports frozen structured requests, not free chat or tool calls')
        title = source['schema'].get('title')
        if title == 'DocumentPrediction':
            result = by_image.get(image_hash) if image_hash else by_text.get(
                hashlib.sha256(source.get('text', '').encode()).hexdigest())
            if result is None:
                raise HTTPException(422, 'source not registered for replay; no fabricated prediction')
            output = {key: result.get(key, {}) for key in ('fields', 'confidence', 'evidence', 'image_boxes')}
        else:
            record = by_material.get(source.get('material'))
            if record is None:
                raise HTTPException(422, 'unknown synthetic care material; no fabricated guidance')
            if title == 'DraftReport':
                output = record['draft']
            elif title == 'SemanticInsights':
                keys = {'label', 'evidence_quote', 'rationale', 'suggested_action', 'knowledge_refs', 'confidence'}
                output = {'candidates': [{k: v for k, v in item.items() if k in keys} for item in record['insights']]}
            else:
                raise HTTPException(422, 'schema not supported by the replay mock')
        return {'model': 'mock-preliminary-replay', 'execution_mode': 'mock',
                'official_effect_evidence': False,
                'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
                    'content': json.dumps(output, ensure_ascii=False)}}],
                'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest')
    parser.add_argument('--predictions-dir')
    parser.add_argument('--port', type=int, default=8021)
    args = parser.parse_args()
    uvicorn.run(create_app(args.manifest, args.predictions_dir), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
