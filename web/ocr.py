"""Optional local OCR for image-only PDF pages. No network calls.

Keep this module importable without the OCR extra. Heavy imports happen inside
the functions so the text-only web runtime can start without them.
"""
import os
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path

MIN_PAGE_TEXT = 40
MAX_IMAGE_SIDE = 2400
RENDER_SCALE = 2.0


class OcrUnavailable(RuntimeError):
    """The optional OCR stack is missing or cannot be used."""


class OcrError(RuntimeError):
    """The OCR stack is present but failed on the document."""


def needs_ocr(text: str, has_image: bool) -> bool:
    """Use OCR only on image pages with little or no extracted text."""
    if not has_image:
        return False
    return len(text.strip()) < MIN_PAGE_TEXT


def _rapidocr_class():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            return None
    return RapidOCR


def _tesseract_command() -> str | None:
    configured = os.environ.get("TESSERACT_CMD", "").strip()
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("tesseract")


def _tesseract_available() -> bool:
    if _tesseract_command() is None:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def _renderer_available() -> bool:
    try:
        import PIL  # noqa: F401
        import pypdfium2  # noqa: F401
    except ImportError:
        return False
    return True


def engine_name() -> str | None:
    if _rapidocr_class() is not None:
        return "rapidocr"
    if _tesseract_available():
        return "tesseract"
    return None


def available() -> bool:
    return _renderer_available() and engine_name() is not None


def _clean(text: str) -> str:
    lines = str(text).replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    return "\n".join(line.strip() for line in lines if line.strip())


class _RapidOcrEngine:
    def __init__(self):
        rapidocr = _rapidocr_class()
        if rapidocr is None:
            raise OcrUnavailable("RapidOCR is not installed.")
        with redirect_stdout(sys.stderr):
            self._engine = rapidocr()

    def text(self, image) -> str:
        with redirect_stdout(sys.stderr):
            result = self._engine(image)
        if isinstance(result, tuple):
            result = result[0]
        if hasattr(result, "txts"):
            lines = list(result.txts or [])
        else:
            lines = [item[1] for item in (result or []) if len(item) >= 2]
        return _clean("\n".join(str(line) for line in lines))


class _TesseractEngine:
    def __init__(self):
        import pytesseract
        command = _tesseract_command()
        if command is None:
            raise OcrUnavailable("Tesseract is not installed.")
        pytesseract.pytesseract.tesseract_cmd = command
        self._pytesseract = pytesseract
        self._lang = "eng"
        try:
            with redirect_stdout(sys.stderr):
                languages = set(pytesseract.get_languages(config=""))
        except Exception:
            languages = set()
        if "ind" in languages:
            self._lang = "ind+eng" if "eng" in languages else "ind"
        elif "eng" in languages:
            self._lang = "eng"

    def text(self, image) -> str:
        with redirect_stdout(sys.stderr):
            return _clean(self._pytesseract.image_to_string(image, lang=self._lang))


_ENGINE = None
_ENGINE_ERROR = None


def _engine():
    global _ENGINE, _ENGINE_ERROR
    if _ENGINE is not None:
        return _ENGINE
    if _ENGINE_ERROR is not None:
        raise _ENGINE_ERROR
    if not _renderer_available():
        _ENGINE_ERROR = OcrUnavailable("pypdfium2 and Pillow are required for OCR.")
        raise _ENGINE_ERROR
    try:
        if _rapidocr_class() is not None:
            _ENGINE = _RapidOcrEngine()
        elif _tesseract_available():
            _ENGINE = _TesseractEngine()
        else:
            raise OcrUnavailable("No local OCR engine is installed.")
    except OcrUnavailable as exc:
        _ENGINE_ERROR = exc
        raise
    except Exception as exc:
        _ENGINE_ERROR = OcrError("The local OCR engine could not start.")
        raise _ENGINE_ERROR from exc
    return _ENGINE


def _render_page(page):
    width, height = page.get_size()
    longest = max(float(width), float(height), 1.0)
    scale = min(RENDER_SCALE, MAX_IMAGE_SIDE / longest)
    bitmap = page.render(scale=scale)
    try:
        return bitmap.to_pil().copy()
    finally:
        bitmap.close()


def ocr_pages(path: Path, page_numbers) -> dict[int, str]:
    numbers = list(page_numbers)
    if not numbers:
        return {}
    engine = _engine()
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise OcrUnavailable("pypdfium2 is required for OCR.") from exc
    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise OcrError("The PDF could not be rendered for OCR.") from exc
    texts = {}
    failures = 0
    try:
        for number in numbers:
            try:
                page = document[number - 1]
                try:
                    texts[number] = engine.text(_render_page(page))
                finally:
                    page.close()
            except Exception:
                failures += 1
                texts[number] = ""
    finally:
        document.close()
    if failures == len(numbers):
        raise OcrError("OCR could not read any page.")
    return texts
