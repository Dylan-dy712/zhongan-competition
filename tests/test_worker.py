import unittest

from services.api.app.worker import looks_like_title, text_chunks
from services.api.app.tencent_ocr import normalize_bbox


class Point:
    def __init__(self, x, y):
        self.X = x
        self.Y = y


class Detection:
    Polygon = [Point(10, 20), Point(90, 20), Point(90, 60), Point(10, 60)]


class WorkerTests(unittest.TestCase):
    def test_chunks_use_python_unicode_code_point_offsets(self):
        text = "肺炎🙂复诊"
        chunks = list(text_chunks(text, limit=3))
        self.assertEqual(chunks, [(0, 3, "肺炎🙂"), (3, 5, "复诊")])
        for start, end, value in chunks:
            self.assertEqual(text[start:end], value)

    def test_whitespace_only_chunks_do_not_become_evidence(self):
        self.assertEqual(list(text_chunks("   ", limit=2)), [])

    def test_numbered_heading_is_structural_title(self):
        self.assertTrue(looks_like_title("1. 住院经过"))
        self.assertFalse(looks_like_title("患者今日情况稳定。"))

    def test_ocr_bbox_is_normalized_to_original_image(self):
        self.assertEqual(normalize_bbox(Detection(), 100, 100), [0.1, 0.2, 0.9, 0.6])


if __name__ == "__main__":
    unittest.main()
