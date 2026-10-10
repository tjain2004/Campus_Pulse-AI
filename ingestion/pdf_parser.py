"""PDF digest pipeline: extract text per page, chunk it, pull out key points.

Every key point keeps its page number so answers can cite "(Page 4)".
Scanned PDFs (no text layer) are reported instead of guessed at; OCR via
pytesseract can be plugged into `_ocr_page` if installed.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import List, Tuple

KEY_HINTS = re.compile(
    r"\b(must|should|required|mandatory|deadline|due|last date|submit|eligib|team|template|"
    r"format|maximum|minimum|at least|not allowed|disqualif|round|date|venue)\w*",
    re.I,
)


@dataclass
class PdfDigest:
    pages: List[Tuple[int, str]] = field(default_factory=list)  # (page_number, chunk)
    key_points: List[Tuple[int, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.key_points:
            return "No clear requirements found. " + " ".join(self.warnings)
        return "\n".join(f"- {pt} (Page {p})" for p, pt in self.key_points[:8])


def _ocr_page(_page) -> str:  # pragma: no cover - optional hook
    return ""


def chunk_text(text: str, size: int = 700) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z])", text) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) > size and buf:
            chunks.append(buf.strip())
            buf = ""
        buf += " " + p
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


def digest_pdf(data: bytes) -> PdfDigest:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pypdf is required for PDF import: pip install pypdf") from exc

    digest = PdfDigest()
    reader = PdfReader(io.BytesIO(data))
    empty_pages = 0
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip() or _ocr_page(page)
        if not text:
            empty_pages += 1
            continue
        text = re.sub(r"[ \t]+", " ", text)
        for chunk in chunk_text(text):
            digest.pages.append((idx, chunk))
        for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
            s = sentence.strip(" -•\t")
            if 15 <= len(s) <= 220 and KEY_HINTS.search(s):
                digest.key_points.append((idx, s))
    if empty_pages:
        digest.warnings.append(
            f"{empty_pages} page(s) had no extractable text (possibly scanned); they were not summarised."
        )
    return digest
