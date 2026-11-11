import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.pdf_fixtures import mixed_pdf_bytes, pdf_bytes, scanned_pdf_bytes
from web.ocr import available, needs_ocr
from web.pdf_worker import parse_pdf

try:
    from PIL import Image  # noqa: F401
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False


class OcrDecisionTests(unittest.TestCase):
    def test_needs_ocr_only_for_image_pages_with_little_text(self):
        self.assertFalse(needs_ocr("", False))
        self.assertFalse(needs_ocr("A" * 100, True))
        self.assertTrue(needs_ocr("", True))
        self.assertTrue(needs_ocr("Page 1", True))

    def test_clean_strips_control_characters(self):
        from web.ocr import _clean
        self.assertEqual(_clean("a\x00b\x0bc\r\nd"), "a b c\nd")
        self.assertEqual(_clean("x\x7fy"), "x y")
        self.assertEqual(_clean("  a  \n\n b "), "a\nb")

    def test_scale_for_size_preserves_native_resolution(self):
        from web.ocr import _scale_for_size
        self.assertAlmostEqual(_scale_for_size(612, 792), 4.0)
        self.assertAlmostEqual(_scale_for_size(612, 792, 4.166), 4.166, places=3)
        self.assertAlmostEqual(_scale_for_size(612, 792, 8.0), 5.0)
        self.assertAlmostEqual(_scale_for_size(2000, 3000), 4000 / 3000, places=3)


class EngineSelectionTests(unittest.TestCase):
    def test_tesseract_is_used_when_rapidocr_cannot_start(self):
        from web import ocr

        class BrokenRapid:
            def __init__(self):
                raise RuntimeError("boom")

        class FakeTesseract:
            def __init__(self):
                pass

            def text(self, image):
                return "fake"

        with patch.object(ocr, "_renderer_available", return_value=True), \
             patch.object(ocr, "_rapidocr_class", return_value=BrokenRapid), \
             patch.object(ocr, "_tesseract_available", return_value=True), \
             patch.object(ocr, "_TesseractEngine", FakeTesseract), \
             patch.object(ocr, "_ENGINE", None), \
             patch.object(ocr, "_ENGINE_ERROR", None), \
             patch.object(ocr, "_ENGINE_NAME", None):
            engine = ocr._engine()
            self.assertIsInstance(engine, FakeTesseract)
            self.assertEqual(ocr.engine_name(), "tesseract")


class PdfWorkerOcrTests(unittest.TestCase):
    def setUp(self):
        Path(".tools").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=".tools")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, content):
        path = self.root / "sample.pdf"
        path.write_bytes(content)
        return path

    def test_text_pdf_does_not_request_ocr(self):
        result = parse_pdf(self.write(pdf_bytes()), 3, 1_000_000)
        self.assertNotIn("ocr_required", result)
        self.assertEqual(result["ocr_pages"], 0)
        self.assertIn("Folio synthetic", result["pages"][0]["text"])

    def test_blank_pdf_reports_no_text_without_requesting_ocr(self):
        result = parse_pdf(self.write(pdf_bytes(text="")), 3, 1_000_000)
        self.assertEqual(result["error"]["code"], "no_text")
        self.assertIn("no readable text", result["error"]["message"])

    @unittest.skipUnless(available(), "optional OCR dependencies are not installed")
    def test_scanned_pdf_requests_and_uses_ocr(self):
        path = self.write(scanned_pdf_bytes())
        first = parse_pdf(path, 3, 1_000_000)
        self.assertTrue(first.get("ocr_required"))
        second = parse_pdf(path, 3, 1_000_000, ocr=True)
        self.assertNotIn("error", second)
        self.assertGreaterEqual(second["ocr_pages"], 1)
        self.assertIn(second["ocr_engine"], {"rapidocr", "tesseract"})
        text = second["pages"][0]["text"].lower()
        self.assertIn("home office", text)
        self.assertIn("allowance", text)

    @unittest.skipUnless(available(), "optional OCR dependencies are not installed")
    def test_small_text_scan_is_read(self):
        result = parse_pdf(self.write(scanned_pdf_bytes(font_size=24)), 3, 1_000_000, ocr=True)
        self.assertNotIn("error", result)
        text = result["pages"][0]["text"].lower()
        self.assertIn("allowance", text)
        self.assertIn("500", text)

    @unittest.skipUnless(available(), "optional OCR dependencies are not installed")
    def test_low_contrast_scan_is_read(self):
        result = parse_pdf(self.write(scanned_pdf_bytes(contrast=0.5)), 3, 1_000_000, ocr=True)
        self.assertNotIn("error", result)
        self.assertIn("allowance", result["pages"][0]["text"].lower())

    @unittest.skipUnless(available(), "optional OCR dependencies are not installed")
    def test_blurred_scan_is_read(self):
        result = parse_pdf(self.write(scanned_pdf_bytes(blur=0.8)), 3, 1_000_000, ocr=True)
        self.assertNotIn("error", result)
        self.assertIn("allowance", result["pages"][0]["text"].lower())

    @unittest.skipUnless(available(), "optional OCR dependencies are not installed")
    def test_mixed_text_and_scanned_pages(self):
        result = parse_pdf(self.write(mixed_pdf_bytes()), 3, 1_000_000, ocr=True)
        self.assertNotIn("error", result)
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["ocr_pages"], 1)
        self.assertIn("Text page content", result["pages"][0]["text"])
        self.assertIn("allowance", result["pages"][1]["text"].lower())
        self.assertTrue(result["pages"][1].get("ocr"))

    @unittest.skipUnless(available(), "optional OCR dependencies are not installed")
    def test_ocr_page_cap_is_reported_before_ocr(self):
        result = parse_pdf(self.write(scanned_pdf_bytes()), 3, 1_000_000, max_ocr_pages=0)
        self.assertEqual(result["error"]["code"], "too_many_ocr_pages")

    @unittest.skipUnless(PILLOW_AVAILABLE, "Pillow is not installed")
    def test_ocr_failure_is_reported(self):
        from web import ocr
        path = self.write(scanned_pdf_bytes())
        with patch.object(ocr, "ocr_pages", side_effect=ocr.OcrError("boom")):
            result = parse_pdf(path, 3, 1_000_000, ocr=True)
        self.assertEqual(result["error"]["code"], "ocr_failed")

    @unittest.skipUnless(PILLOW_AVAILABLE, "Pillow is not installed")
    def test_ocr_unavailable_is_reported(self):
        from web import ocr
        path = self.write(scanned_pdf_bytes())
        with patch.object(ocr, "ocr_pages", side_effect=ocr.OcrUnavailable("missing")):
            result = parse_pdf(path, 3, 1_000_000, ocr=True)
        self.assertEqual(result["error"]["code"], "no_text")
        self.assertIn("OCR", result["error"]["message"])

    @unittest.skipUnless(PILLOW_AVAILABLE, "Pillow is not installed")
    def test_ocr_failure_keeps_text_pages(self):
        from web import ocr
        path = self.write(mixed_pdf_bytes())
        with patch.object(ocr, "ocr_pages", side_effect=ocr.OcrError("boom")):
            result = parse_pdf(path, 3, 1_000_000, ocr=True)
        self.assertNotIn("error", result)
        self.assertEqual(result["ocr_pages"], 0)
        self.assertIn("Text page content", result["pages"][0]["text"])


if __name__ == "__main__":
    unittest.main()
