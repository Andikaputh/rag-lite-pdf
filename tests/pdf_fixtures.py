"""Generate small synthetic PDFs without external files or paid tooling."""
from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def pdf_bytes(text="Folio synthetic document for local testing.", *, pages=1, encrypted=False, blank_last=False):
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        if text and not (blank_last and index == pages - 1):
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            content = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(content)
    if encrypted:
        writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _fixture_font(size):
    from PIL import ImageFont
    for name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    for path in (
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def scanned_pdf_bytes(text="The home office allowance is 500 USD per year.", *, width=2200, height=1400):
    """Create an image-only PDF. Pillow is optional; callers skip when missing."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _fixture_font(64)
    draw.text((120, 160), "SCANNED DOCUMENT", fill="black", font=font)
    draw.text((120, 320), text, fill="black", font=font)
    output = BytesIO()
    image.save(output, format="PDF", resolution=150)
    return output.getvalue()
