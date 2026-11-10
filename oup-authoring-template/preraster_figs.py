"""Pre-rasterise vector figure regions of manuscript.pdf into embedded images.

pdf2docx reads the vector art of each figure as table borders and explodes it
into hundreds of text-grid cells (~13k chars of body prose end up trapped in
fake tables, and 7 pages render as 27).  Replacing each figure region with a
single high-DPI raster image before conversion makes pdf2docx emit one image
paragraph per figure instead.

Regions are taken from the PDF's own drawing unions (never estimated).  The
source of truth stays manuscript.pdf; this writes a derived copy only.
"""
import sys

import pymupdf

SRC = "manuscript.pdf"
DST = "/tmp/jk_fig/src/manuscript_raster.pdf"
DPI = 600

# (page_index, x0, y0, x1, y1) -- drawing-union bounds of each figure body.
# Captions sit below these boxes and stay as real, editable text.
REGIONS = [
    (1, 306.0, 50.0, 560.0, 262.0),   # Figure 1  protocol overview
    (2, 306.0, 92.0, 560.0, 268.0),   # Figure 2  CDM architecture
    (3, 306.0, 350.0, 560.0, 558.0),  # Figure 3  computational evaluation
]


def main() -> int:
    import os

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    doc = pymupdf.open(SRC)
    zoom = DPI / 72.0

    for pno, x0, y0, x1, y1 in REGIONS:
        page = doc[pno]
        rect = pymupdf.Rect(x0, y0, x1, y1)
        pix = page.get_pixmap(clip=rect, matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        png = pix.tobytes("png")
        with open(f"/tmp/jk_fig/fig_p{pno + 1}.png", "wb") as fh:
            fh.write(png)
        print(f"p{pno + 1} clip={[round(v) for v in rect]} -> {pix.width}x{pix.height}px {len(png)}B")

        # Drop the vector art and its in-figure text labels, then lay the
        # raster down in the same rectangle.
        page.add_redact_annot(rect)
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )
        page.insert_image(rect, stream=png)

    doc.save(DST, garbage=4, deflate=True)
    print("wrote", DST, doc.page_count, "pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
