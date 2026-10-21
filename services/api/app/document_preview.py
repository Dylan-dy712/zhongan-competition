"""Render one authorized PDF page and locate only its original evidence text."""
import io
import math
from contextlib import closing
from pathlib import Path
import threading
import unicodedata

import pypdfium2 as pdfium


# PDFium is not thread safe; API requests share one process, unlike workers.
PDF_LOCK = threading.Lock()
MAX_EDGE = 2000
MAX_TEXT_CHARS = 100_000


def ocr_regions(quote, blocks):
    """Locate exact OCR text in its stored geometry, never guess a paraphrase."""
    target=compact(quote)
    if not target:return []
    usable=[b for b in blocks if b.get('bbox') and not (b.get('metadata') or {}).get('needs_clearer_photo')
            and (b.get('metadata') or {}).get('coordinate_precision')!='page' and compact(b.get('text_content') or '')]
    parts=[compact(b['text_content']) for b in usable];text=''.join(parts)
    start=text.find(target);end=start+len(target);offset=0;regions=[]
    for block,part in zip(usable,parts):
        matched=(offset<end and offset+len(part)>start) if start>=0 else (len(part)>=4 and part in target)
        offset+=len(part)
        box=block['bbox']
        if matched and len(box)==4 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in box) and 0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1:
            regions.append(list(box))
    # Long page-level excerpts retain all matching lines in bounded reading bands.
    size=max(1,math.ceil(len(regions)/32))
    return [[min(b[0] for b in regions[i:i+size]),min(b[1] for b in regions[i:i+size]),
             max(b[2] for b in regions[i:i+size]),max(b[3] for b in regions[i:i+size])] for i in range(0,len(regions),size)]


def evidence_ocr_regions(conn,evidence_id,quote):
    blocks=conn.execute('''SELECT b.text_content,b.bbox,b.metadata FROM evidence e JOIN page_blocks b
        ON b.run_id=e.run_id AND b.case_id=e.case_id AND b.document_id=e.document_id
        AND b.document_version=e.document_version AND b.page_index=e.page_index
        AND b.source_hash=e.source_hash AND b.parser_version=e.parser_version
        WHERE e.evidence_id=%s ORDER BY b.reading_order LIMIT 3000''',(evidence_id,)).fetchall()
    return ocr_regions(quote,blocks)


def render_source_image(path):
    from PIL import Image,ImageOps
    with Image.open(path) as original:
        with ImageOps.exif_transpose(original) as image:
            image.thumbnail((MAX_EDGE,MAX_EDGE))
            output=io.BytesIO();image.convert('RGB').save(output,format='PNG')
            return output.getvalue()


def compact(value):
    return ''.join(char for char in unicodedata.normalize('NFKC', value)
                   if not char.isspace() and char != '\u00ad')


def text_regions(page, bitmap, quote):
    target = compact(quote)
    if not target:
        return []
    with closing(page.get_textpage()) as textpage:
        count = textpage.count_chars()
        if count > MAX_TEXT_CHARS:
            return []
        # Map normalized text back to PDFium character indexes, including PDFs
        # where extracted text inserts or omits characters relative to that list.
        parts, indexes = [], []
        for index in range(count):
            part = compact(textpage.get_text_range(index, 1))
            parts.append(part)
            indexes.extend([index] * len(part))
        text = ''.join(parts)
        offset, matches = 0, []
        while len(matches) < 20:
            start = text.find(target, offset)
            if start < 0:
                break
            matches.append((indexes[start], indexes[start + len(target) - 1] + 1))
            offset = start + len(target)
        conversion = bitmap.get_posconv(page)
        regions = []
        textpage.count_rects()
        for start, end in matches:
            for index in range(textpage.count_rects(start, end - start)):
                left, bottom, right, top = textpage.get_rect(index)
                points = [conversion.to_bitmap(x, y) for x in (left, right) for y in (bottom, top)]
                xs, ys = zip(*points)
                box = [max(0, min(xs) / bitmap.width), max(0, min(ys) / bitmap.height),
                       min(1, max(xs) / bitmap.width), min(1, max(ys) / bitmap.height)]
                if box[0] < box[2] and box[1] < box[3]:
                    regions.append([round(value, 6) for value in box])
        # Keep response headers bounded for long excerpts, while retaining the
        # region covering the actual matched text rather than truncating it.
        if len(regions) > 64:
            regions = [[min(box[0] for box in regions), min(box[1] for box in regions),
                        max(box[2] for box in regions), max(box[3] for box in regions)]]
        return regions


def render_evidence_page(path: Path, page_index: int, *, quote='', bbox=None):
    with PDF_LOCK, pdfium.PdfDocument(str(path)) as document:
        if not 0 <= page_index < len(document):
            raise IndexError('PDF page is unavailable')
        with closing(document[page_index]) as page:
            width, height = page.get_size()
            if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                raise ValueError('Invalid PDF page size')
            with closing(page.render(scale=min(2.0, MAX_EDGE / max(width, height)))) as bitmap:
                # OCR boxes were produced from the same PDFium page orientation.
                # Native PDFs have no stored box, so locate their original text.
                try:
                    regions = [list(bbox)] if bbox else text_regions(page, bitmap, quote)
                except (pdfium.PdfiumError, ValueError, IndexError):
                    regions = []
                output = io.BytesIO()
                with bitmap.to_pil() as image:
                    image.save(output, format='PNG')
                return output.getvalue(), regions
