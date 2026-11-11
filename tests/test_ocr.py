import tempfile
import unittest
from pathlib import Path

from tests.pdf_fixtures import pdf_bytes, scanned_pdf_bytes
from web.ocr import available, needs_ocr
from web.pdf_worker import parse_pdf


class OcrDecisionTests(unittest.TestCase):
    def test_needs_ocr_only_for_image_pages_with_little_text(self):
        self.assertFalse(needs_ocr("", False))
        self.assertFalse(needs_ocr("A" * 100, True))
        self.assertTrue(needs_ocr("", True))
        self.assertTrue(needs_ocr("Page 1", True))


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
    def test_ocr_page_cap_is_reported_before_ocr(self):
        result = parse_pdf(self.write(scanned_pdf_bytes()), 3, 1_000_000, max_ocr_pages=0)
        self.assertEqual(result["error"]["code"], "too_many_ocr_pages")


if __name__ == "__main__":
    unittest.main()
