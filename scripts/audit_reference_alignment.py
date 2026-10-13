"""Flag reference/source alignment questions without rewriting gold or predictions."""
import argparse
from pathlib import Path

from scripts.preliminary_kr1 import load, normalize, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if Path(args.output).resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error('reference diagnostics must remain outside the public repository')
    manifest = load(args.manifest)
    rows = []
    for row in manifest['documents']:
        if sha(row['reference']) != row['reference_sha256']:
            raise ValueError('reference changed after freeze')
        reference = load(row['reference'])
        text = normalize(load(row['ocr']).get('text', '')) if row['ocr'] else ''
        names = [normalize(item['detailName']) for block in reference['fields'].get('blocks', [])
                 for item in block.get('costDetailList', []) if item.get('detailName')]
        matched = sum(name in text for name in names)
        # Low OCR support can mean OCR failure, source mismatch, or a reference issue.
        # It is not authority to exclude or remap a sample.
        if len(names) >= 5 and matched / len(names) < .25:
            rows.append({'document_id': row['document_id'], 'case_id': row['case_id'],
                         'image': row['image'], 'reference': row['reference'],
                         'image_sha256': row['image_sha256'], 'reference_sha256': row['reference_sha256'],
                         'reference_fee_rows': len(names), 'ocr_supported_names': matched,
                         'ocr_characters': len(text), 'status': 'requires_source_review'})
    result = {'manifest_sha256': sha(args.manifest), 'documents': len(manifest['documents']),
              'candidate_questions': len(rows), 'case_count': len({r['case_id'] for r in rows}),
              'method': 'reference_fee_names_literal_ocr_support_below_25_percent_min_5_rows',
              'exclusions_applied': 0, 'gold_changes_applied': 0,
              'limits': 'OCR errors can trigger flags; independent visual or provider review required',
              'rows': rows}
    write(args.output, result)
    print({key: result[key] for key in ('documents', 'candidate_questions', 'case_count', 'exclusions_applied')})


if __name__ == '__main__':
    main()
