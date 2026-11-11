"""Parse untrusted PDFs in a short-lived subprocess; stdout is bounded JSON."""
import argparse
import json
import logging
import sys
from pathlib import Path

from pypdf import PdfReader

from web.ocr import needs_ocr

logging.getLogger("pypdf").setLevel(logging.CRITICAL)


def page_has_image(page) -> bool:
    """Check for an image XObject without decoding image data."""
    try:
        resources = page.get("/Resources")
        if not resources:
            return False
        xobjects = resources.get("/XObject")
        if not xobjects:
            return False
        for item in xobjects.values():
            candidate = item.get_object()
            if candidate.get("/Subtype") == "/Image":
                return True
    except Exception:
        return False
    return False


def parse_pdf(path: Path, max_pages: int, max_chars: int, *, ocr: bool = False,
              max_ocr_pages: int = 25) -> dict:
    def error(code, message):
        return {"error": {"code": code, "message": message}}

    try:
        with path.open("rb") as source:
            if source.read(5) != b"%PDF-":
                return error("invalid_signature", "The file contents are not a valid PDF, regardless of its extension.")
            source.seek(0)
            reader = PdfReader(source, strict=True)
            if reader.is_encrypted:
                return error("encrypted_pdf", "The PDF is password-protected. Upload an unencrypted copy.")
            count = len(reader.pages)
            if count < 1:
                return error("empty_pdf", "The PDF has no pages.")
            if count > max_pages:
                return error("too_many_pages", f"PDFs may contain up to {max_pages} pages. Split the document and try again.")
            pages, characters, empty_pages = [], 0, 0
            ocr_needed = []
            for number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                characters += len(text)
                if characters > max_chars:
                    return error("too_much_text", "The PDF contains too much text. Split it into smaller documents.")
                empty_pages += not bool(text)
                pages.append({"page": number, "text": text})
                if needs_ocr(text, page_has_image(page)):
                    ocr_needed.append(number)
    except Exception:
        # Do not return internal paths, parser traces, or document text in errors.
        return error("corrupt_pdf", "The PDF is corrupt or uses an unsupported structure. Export it again and retry.")

    needed = len(ocr_needed)
    too_many = (f"This PDF appears to be scanned and has {needed} "
                f"{'page' if needed == 1 else 'pages'} that need OCR. "
                f"The limit is {max_ocr_pages} OCR pages per document. Split it and try again.")

    if ocr_needed and not ocr:
        from web.ocr import available
        if not available():
            if not characters:
                return error("no_text", "The PDF has no readable text and may be scanned. Install the optional OCR dependencies to read it.")
            return {"page_count": count, "text_characters": characters, "empty_pages": empty_pages,
                    "ocr_pages": 0, "ocr_engine": None, "pages": pages}
        if needed > max_ocr_pages:
            return error("too_many_ocr_pages", too_many)
        return {"ocr_required": True, "page_count": count, "text_characters": characters,
                "empty_pages": empty_pages, "ocr_page_count": needed}

    if ocr and ocr_needed:
        if needed > max_ocr_pages:
            return error("too_many_ocr_pages", too_many)
        try:
            from web.ocr import OcrError, OcrUnavailable, engine_name, ocr_pages
            texts = ocr_pages(path, ocr_needed)
        except OcrUnavailable:
            if not characters:
                return error("no_text", "The PDF has no readable text and may be scanned. Install the optional OCR dependencies to read it.")
            texts = {}
        except OcrError:
            if not characters:
                return error("ocr_failed", "OCR could not read this PDF. Try a clearer scan or a text-based PDF.")
            texts = {}
        except Exception:
            if not characters:
                return error("ocr_failed", "OCR could not read this PDF. Try a clearer scan or a text-based PDF.")
            texts = {}
        used = 0
        for number, text in texts.items():
            text = (text or "").strip()
            if text and len(text) > len(pages[number - 1]["text"]):
                pages[number - 1]["text"] = text
                pages[number - 1]["ocr"] = True
                used += 1
        characters = sum(len(page["text"]) for page in pages)
        empty_pages = sum(not page["text"] for page in pages)
        if characters > max_chars:
            return error("too_much_text", "The PDF contains too much text. Split it into smaller documents.")
        if not characters:
            return error("no_text", "The PDF has no readable text, and OCR could not extract enough text. Try a clearer scan or a text-based PDF.")
        return {"page_count": count, "text_characters": characters, "empty_pages": empty_pages,
                "ocr_pages": used, "ocr_engine": engine_name() if used else None, "pages": pages}

    if not characters:
        return error("no_text", "The PDF has no readable text. It may be blank or contain only images without readable text.")
    return {"page_count": count, "text_characters": characters, "empty_pages": empty_pages,
            "ocr_pages": 0, "ocr_engine": None, "pages": pages}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("max_pages", type=int)
    parser.add_argument("max_chars", type=int)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--max-ocr-pages", type=int, default=25)
    args = parser.parse_args(argv)
    payload = parse_pdf(Path(args.path), args.max_pages, args.max_chars,
                        ocr=args.ocr, max_ocr_pages=args.max_ocr_pages)
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
