"""Conservative, non-blocking photo triage. Thresholds are heuristics, not OCR accuracy."""
import io
import re
from PIL import Image, ImageFilter, ImageStat, ImageOps

KINDS = [('医疗发票', r'发票|财政.*票据|医疗.*收费票据'),
         ('费用清单', r'费用.*清单|费用.*明细|收费.*明细'),
         ('出院小结', r'出院记录|出院小结|出院总结'),
         ('检查报告', r'检验报告|检查报告|影像诊断|超声报告'),
         ('病历', r'门诊病历|住院病历|入院记录|病程记录')]


def classify_material(text):
    hits = [name for name, pattern in KINDS if re.search(pattern, text[:3000])]
    return (hits[0], 'likely') if len(hits) == 1 else ('就医材料', 'unknown')


def inspect_photo(data, ocr_factory=None):
    with Image.open(io.BytesIO(data)) as original:
        if original.width * original.height > 24_000_000:
            raise ValueError('图片像素过大，请压缩到 2400 万像素以内。')
        original.verify()
    with Image.open(io.BytesIO(data)) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
    width, height = image.size
    gray = image.convert('L')
    gray.thumbnail((1200, 1200))
    brightness = ImageStat.Stat(gray).mean[0]
    edges = gray.filter(ImageFilter.FIND_EDGES).crop((2, 2, gray.width-2, gray.height-2)) if min(gray.size) > 4 else gray
    sharpness = ImageStat.Stat(edges).var[0]
    blocks, text, ocr_status = [], '', 'unavailable'
    if ocr_factory:
        try:
            # Normalize camera rotation for OCR and keep the original unmodified.
            stream = io.BytesIO()
            image.save(stream, format='JPEG', quality=92)
            result = ocr_factory().recognize(stream.getvalue(), width, height)
            blocks, text, ocr_status = result.get('blocks', []), result.get('text', ''), 'checked'
        except RuntimeError:
            pass  # Unconfigured/unavailable OCR is never described as a clear image.
    scored = [(b.get('text', ''), b.get('metadata', {}).get('confidence_score')) for b in blocks]
    scored = [(t, score) for t, score in scored if isinstance(score, (int, float)) and 0 <= score <= 1]
    reliable_characters = sum(len(t.strip()) for t, score in scored if score >= .8)
    reliable_share = sum(len(t.strip()) for t, score in scored if score >= .8) / max(1, sum(len(t.strip()) for t, _ in scored))
    readable = ocr_status == 'checked' and reliable_characters >= 12 and reliable_share >= .6
    # Whole-page edges are dominated by paper margins and cannot prove blur.
    # Successful OCR overrides image heuristics; uncertainty about individual
    # fields remains separate from physical photo quality.
    issues = []
    if not readable:
        if min(width, height) < 400:
            issues.append('图片分辨率偏低，建议核对文字是否看得清')
        if brightness < 35:
            issues.append('照片偏暗，建议核对文字是否看得清')
        if ocr_status == 'checked' and len(text.strip()) < 12 and (sharpness < 15 or issues):
            issues.append('可读文字较少，建议补拍文字区域或上传更清晰的照片')
        elif scored and sum(score < .5 for _, score in scored) / len(scored) >= .5:
            issues.append('部分文字识别把握较低，请核对；必要时重新拍摄')
    kind, certainty = classify_material(text)
    return {'material_type': kind, 'type_certainty': certainty,
            'status': 'warning' if issues else ('checked' if ocr_status == 'checked' else 'partial'),
            'issues': issues, 'ocr_status': ocr_status, 'recognized_excerpt': text[:180],
            'width': width, 'height': height, 'method': 'photo-triage-v2-ocr-corroborated',
            'notice': '清晰度检查仅供提醒，仍需核对识别内容。' if ocr_status == 'checked'
                      else 'OCR 预检暂不可用，已检查图片尺寸与对比情况；尚未确认文字可读。'}
