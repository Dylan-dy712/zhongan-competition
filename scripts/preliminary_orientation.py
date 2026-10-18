"""Freeze 0/180 image orientation from existing OCR boxes; never read labels."""
import argparse
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
from scripts.preliminary_kr1 import load, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if Path(args.output).resolve().is_relative_to(repo):
        parser.error('private manifests must remain outside Git')
    manifest = load(args.manifest)
    classifier = RapidOCR().text_cls
    counts = Counter()
    for row in manifest['documents']:
        if sha(row['ocr']) != row['ocr_sha256']:
            raise ValueError('orientation OCR changed after source freeze')
        cache = load(row['ocr'])
        crops = []
        with Image.open(row['image']) as image:
            image = image.convert('RGB')
            width, height = image.size
            for line in cache.get('lines', []):
                box = line.get('bbox')
                if (not isinstance(box, list) or len(box) != 4 or
                    not 0 <= box[0] < box[2] <= 1 or not 0 <= box[1] < box[3] <= 1 or
                    sum('\u4e00' <= c <= '\u9fff' for c in line.get('text', '')) < 3):
                    continue
                points = [round(v * (width if i % 2 == 0 else height)) for i, v in enumerate(box)]
                crop = np.asarray(image.crop(points))[:, :, ::-1]
                if crop.shape[0] >= 8 and crop.shape[1] > crop.shape[0] * 2:
                    crops.append(crop)
                if len(crops) == 12:
                    break
        votes = []
        if crops:
            _, labels, _ = classifier(crops)
            votes = [(int(label), float(confidence)) for label, confidence in labels]
        reliable = Counter(angle for angle, confidence in votes if confidence >= .95)
        best, support = reliable.most_common(1)[0] if reliable else (0, 0)
        accepted = support >= 3 and support / sum(reliable.values()) >= .8
        row.update(image_rotation_degrees=best if accepted else 0,
            orientation_method='rapidocr_text_cls_' + version('rapidocr-onnxruntime') + '_bbox_votes',
            orientation_votes=votes, orientation_review_required=not accepted)
        counts.update([str(row['image_rotation_degrees']) if accepted else 'uncertain'])
    manifest['orientation_preparation'] = {'implementation_sha256': sha(__file__),
        'source_manifest_sha256': sha(args.manifest), 'counts': dict(counts),
        'thresholds': {'confidence': .95, 'minimum_votes': 3, 'agreement': .8},
        'scope': 'only 0/180; uncertain pages preserved without rotation; not OCR quality validation'}
    write(args.output, manifest)
    print(dict(counts))


if __name__ == '__main__':
    main()
