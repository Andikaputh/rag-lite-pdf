"""Parse untrusted PDFs in a short-lived subprocess; stdout is bounded JSON."""
import json
import logging
import sys
from pathlib import Path

from pypdf import PdfReader

logging.getLogger("pypdf").setLevel(logging.CRITICAL)


def parse_pdf(path: Path, max_pages: int, max_chars: int) -> dict:
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
            for number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                characters += len(text)
                if characters > max_chars:
                    return error("too_much_text", "The PDF contains too much text. Split it into smaller documents.")
                empty_pages += not bool(text)
                pages.append({"page": number, "text": text})
            if not characters:
                return error("no_text", "The PDF has no readable text and may be scanned. OCR is not available.")
            return {"page_count": count, "text_characters": characters, "empty_pages": empty_pages, "pages": pages}
    except Exception:
        # Do not return internal paths, parser traces, or document text in errors.
        return error("corrupt_pdf", "The PDF is corrupt or uses an unsupported structure. Export it again and retry.")


if __name__ == "__main__":
    payload = parse_pdf(Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]))
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
