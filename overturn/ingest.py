"""Document ingestion: PDF via PyMuPDF, images via RapidOCR, plain text.

Both extractors run fully offline.
"""
from io import BytesIO

import pymupdf

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _ext(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def extract_text(data: bytes, filename: str) -> str:
    ext = _ext(filename)
    if ext == ".pdf":
        return pdf_to_text(data)
    if ext in _IMAGE_EXTS:
        return image_to_text(data)
    return data.decode("utf-8", errors="replace")


def pdf_to_text(data: bytes) -> str:
    parts = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            text = page.get_text().strip()
            if text:
                parts.append(text)
            else:
                # Scanned page with no embedded text -> OCR the rendered image
                pix = page.get_pixmap(dpi=200)
                parts.append(image_to_text(pix.tobytes("png")))
    return "\n\n".join(p for p in parts if p)


_ocr_engine = None


def image_to_text(data: bytes) -> str:
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    result, _ = _ocr_engine(BytesIO(data))
    if not result:
        return ""
    return "\n".join(line[1] for line in result)
