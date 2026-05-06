"""
PDF renderer — converts a PDF (bytes) into per-page PNG images using PyMuPDF.

If a rendered page's longer side exceeds 4096 px the page is split into 2×2
tiles (rendered directly from the page using a clip rect) and each tile is
returned with a distinct tile_index. The caller should aggregate (sum) counts
per page after detection.

TODO: Replace the simple summation with IoU-based de-duplication to avoid
      double-counting symbols that fall on tile boundaries.
"""

import io
from dataclasses import dataclass

import fitz  # PyMuPDF

from logging_config import get_logger

logger = get_logger(__name__)

_DPI = 300  # Increased from 200 for better furniture symbol recognition
_MAX_SIDE_PX = 4096


@dataclass
class PageImage:
    """A single rendered image (full page or tile)."""

    page_num: int      # 1-based page number
    tile_index: int    # 0 for full-page images; 0–3 for 2×2 tiles
    png_bytes: bytes
    width: int
    height: int


def _pixmap_to_png_bytes(pix: fitz.Pixmap) -> bytes:
    buf = io.BytesIO()
    buf.write(pix.tobytes("png"))
    return buf.getvalue()


def render_pages(pdf_bytes: bytes) -> list[PageImage]:
    """
    Render every page of *pdf_bytes* to PNG at _DPI.

    Pages whose longer side (in pixels at _DPI) exceeds _MAX_SIDE_PX are split
    into 2×2 tiles by clipping in PDF coordinates and rendering each tile
    directly. Returns a flat list of PageImage objects.
    """
    images: list[PageImage] = []

    zoom = _DPI / 72.0  # PyMuPDF's default unit is 72 DPI
    mat = fitz.Matrix(zoom, zoom)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    logger.info("Rendering PDF: %d page(s) at %d DPI", doc.page_count, _DPI)

    try:
        for page_index in range(doc.page_count):
            page_num = page_index + 1
            page = doc.load_page(page_index)

            page_rect = page.rect  # in PDF points
            est_w = int(page_rect.width * zoom)
            est_h = int(page_rect.height * zoom)
            longer_side = max(est_w, est_h)

            if longer_side > _MAX_SIDE_PX:
                logger.info(
                    "Page %d (~%dx%d px @ %d DPI) exceeds %d px — rendering as 2×2 tiles",
                    page_num, est_w, est_h, _DPI, _MAX_SIDE_PX,
                )
                half_w = page_rect.width / 2.0
                half_h = page_rect.height / 2.0
                tile_index = 0
                for row in range(2):
                    for col in range(2):
                        x0 = page_rect.x0 + col * half_w
                        y0 = page_rect.y0 + row * half_h
                        x1 = x0 + half_w
                        y1 = y0 + half_h
                        clip = fitz.Rect(x0, y0, x1, y1)
                        tile_pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
                        png_bytes = _pixmap_to_png_bytes(tile_pix)
                        images.append(
                            PageImage(
                                page_num=page_num,
                                tile_index=tile_index,
                                png_bytes=png_bytes,
                                width=tile_pix.width,
                                height=tile_pix.height,
                            )
                        )
                        logger.debug(
                            "Page %d tile %d: %dx%d px, %d bytes",
                            page_num, tile_index,
                            tile_pix.width, tile_pix.height, len(png_bytes),
                        )
                        tile_index += 1
            else:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                png_bytes = _pixmap_to_png_bytes(pix)
                images.append(
                    PageImage(
                        page_num=page_num,
                        tile_index=0,
                        png_bytes=png_bytes,
                        width=pix.width,
                        height=pix.height,
                    )
                )
                logger.debug(
                    "Page %d: %dx%d px, %d bytes",
                    page_num, pix.width, pix.height, len(png_bytes),
                )

        logger.info("Rendered %d image(s) from %d page(s)", len(images), doc.page_count)
    finally:
        doc.close()

    return images
