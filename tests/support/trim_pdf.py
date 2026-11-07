"""Cut a committed test fixture out of a downloaded BSEE PDF (spec 002, plan.md#Test fixtures).

Trimming keeps whole pages: the selected pages are imported, in order, into a new document with pypdfium2, so their
text layer is the published one. Optionally, image objects whose placed area is larger than a threshold (photographs,
which may be third-party material) are removed from the kept pages and their pixel data is blanked out of the file;
logos and letterhead banners stay when they are under the threshold. Text objects are never touched.

It is run once, by hand, when a fixture is cut; each run is recorded in tests/fixtures/bsee/SOURCES.md:

    python -m tests.support.trim_pdf data/raw/<sha256>.pdf tests/fixtures/bsee/<name>.pdf --pages 3-9
    python -m tests.support.trim_pdf data/raw/<sha256>.pdf tests/fixtures/bsee/<name>.pdf --drop-images-over 60000
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c


@dataclass(frozen=True)
class DroppedImage:
    page: int  # 1-based page number in the trimmed document
    width: float  # placed size in PDF points
    height: float
    pixels: tuple[int, int]  # width, height in pixels


def parse_pages(spec: str, page_count: int) -> list[int]:
    """`"3-9"`, `"1,3,5-6"` or `"all"` → 1-based page numbers, in the given order."""
    if spec == "all":
        return list(range(1, page_count + 1))
    pages: list[int] = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        lo, hi = int(a), int(b or a)
        pages.extend(range(lo, hi + 1))
    bad = [p for p in pages if not 1 <= p <= page_count]
    if bad:
        raise ValueError(f"pages {bad} are outside 1..{page_count}")
    return pages


def trim_pdf(
    src: Path, dest: Path, pages: Sequence[int] | None = None, drop_images_over: float | None = None
) -> list[DroppedImage]:
    """Write to `dest` the whole `pages` of `src` (1-based; all when None), dropping large images if asked."""
    source = pdfium.PdfDocument(str(src))
    keep = list(pages) if pages is not None else list(range(1, len(source) + 1))
    out = pdfium.PdfDocument.new()
    out.import_pages(source, [p - 1 for p in keep])
    dropped: list[DroppedImage] = []
    if drop_images_over is not None:
        for index in range(len(out)):
            page = out[index]
            changed = False
            for obj in list(page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=1)):
                left, bottom, right, top = obj.get_bounds()
                w, h = right - left, top - bottom
                if w * h > drop_images_over:
                    px_w, px_h = obj.get_px_size()
                    page.remove_obj(obj)
                    dropped.append(DroppedImage(index + 1, round(w, 1), round(h, 1), (int(px_w), int(px_h))))
                    changed = True
            if changed:
                page.gen_content()
    data = _save(out)
    if dropped:
        data = _save_repaired(_blank_image_streams(data, {d.pixels for d in dropped}))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dropped


# An image XObject dictionary followed by its stream keyword.
_IMAGE_STREAM_RE = re.compile(
    rb"<<((?:(?!>>\s*stream).)*?/Subtype\s*/Image(?:(?!>>\s*stream).)*?)>>\s*stream\r?\n", re.S
)
_BLANK_IMAGE = b"<</BitsPerComponent 8/ColorSpace/DeviceGray/Height 1/Length 1/Subtype/Image/Type/XObject/Width 1>>"


def _blank_image_streams(data: bytes, pixel_sizes: set[tuple[int, int]]) -> bytes:
    """Replace the streams of the removed images (matched by pixel size) with a 1x1 white image.

    Removing an image object from the page content leaves its stream in the page resources, so the photograph
    would still be inside the committed file. Its bytes are replaced here; `_save_repaired` rebuilds the xref.
    """
    out = bytearray()
    pos = 0
    for m in _IMAGE_STREAM_RE.finditer(data):
        head = m.group(1)
        wm = re.search(rb"/Width\s+(\d+)", head)
        hm = re.search(rb"/Height\s+(\d+)", head)
        lm = re.search(rb"/Length\s+(\d+)", head)
        if not (wm and hm and lm) or (int(wm.group(1)), int(hm.group(1))) not in pixel_sizes:
            continue
        end = m.end() + int(lm.group(1))
        if not data[end : end + 32].lstrip().startswith(b"endstream"):
            raise ValueError("unexpected stream layout; refusing to rewrite the file")
        out += data[pos : m.start()] + _BLANK_IMAGE + b"stream\n\xff"
        pos = end
    out += data[pos:]
    return bytes(out)


def _save(doc: pdfium.PdfDocument) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _save_repaired(data: bytes) -> bytes:
    """Load (pdfium repairs the cross-reference table) and save the pages again into a fresh document."""
    src = pdfium.PdfDocument(data)
    out = pdfium.PdfDocument.new()
    out.import_pages(src)
    return _save(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--pages", default="all", help='1-based pages to keep, e.g. "3-9" or "1,3" (default: all)')
    parser.add_argument("--drop-images-over", type=float, default=None, help="remove images larger than N pt²")
    args = parser.parse_args(argv)
    count = len(pdfium.PdfDocument(str(args.src)))
    pages = parse_pages(args.pages, count)
    dropped = trim_pdf(args.src, args.dest, pages, args.drop_images_over)
    data = args.dest.read_bytes()
    print(f"source: {args.src} ({count} pages), sha256 {hashlib.sha256(args.src.read_bytes()).hexdigest()}")
    print(f"kept pages: {pages}")
    for d in dropped:
        print(f"dropped image on trimmed page {d.page}: {d.width} x {d.height} pt, {d.pixels[0]} x {d.pixels[1]} px")
    print(f"wrote: {args.dest} ({len(data)} bytes), sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
