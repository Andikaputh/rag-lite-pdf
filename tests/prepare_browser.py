"""Generate synthetic browser-test PDFs: python -m tests.prepare_browser."""
from pathlib import Path

from tests.pdf_fixtures import pdf_bytes


def main():
    output = Path(".tools")
    output.mkdir(exist_ok=True)
    fixtures = {
        "valid.pdf": pdf_bytes(pages=2, blank_last=True),
        "blank.pdf": pdf_bytes(""),
        "warranty.pdf": pdf_bytes(
            "Masa garansi perangkat adalah 24 bulan. "
            "Layanan pelanggan tersedia setiap Senin sampai Jumat."
        ),
        "grounding-repair.pdf": pdf_bytes(
            "Masa garansi perangkat adalah 30 bulan. "
            "Kerusakan akibat air tidak ditanggung garansi."
        ),
        "precision.pdf": pdf_bytes(
            "The device warranty lasts 27 months. "
            "Readings are stored for 28 days. "
            "Calibration takes 6 days."
        ),
    }
    for name, content in fixtures.items():
        target = output / name
        if target.exists():
            print(f"Kept existing fixture: {target}")
        else:
            target.write_bytes(content)
            print(f"Created synthetic fixture: {target}")


if __name__ == "__main__":
    main()
