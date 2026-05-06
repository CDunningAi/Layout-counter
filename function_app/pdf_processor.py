"""
PDF renderer — converts a PDF (bytes) into per-page PNG images using PyMuPDF.

If a rendered page's longer side exceeds 4096 px the page is split into 2×2
tiles and each tile is returned with a distinct tile_index.  The caller should
aggregate (sum) counts per page after detection.

TODO: Replace the simple summation with IoU-based de-duplication to avoid
      double-counting symbols that fall on tile boundaries.
"""

from __future__ import annotations

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


def _render_page_at_dpi(page: fitz.Page) -> fitz.Pixmap:
    zoom = _DPI / 72.0  # PyMuPDF's default unit is 72 DPI
    mat = fitz.Matrix(zoom, zoom)
    return page.get_pixmap(matrix=mat, alpha=False)


def _tile_pixmap(pix: fitz.Pixmap) -> list[fitz.Pixmap]:
    """Split a Pixmap into four 2×2 tiles."""
    w, h = pix.width, pix.height
    half_w, half_h = w // 2, h // 2
    tiles: list[fitz.Pixmap] = []
    for row in range(2):
        for col in range(2):
            x0 = col * half_w
            y0 = row * half_h
            x1 = w if col == 1 else half_w
            y1 = h if row == 1 else half_h
            clip = fitz.IRect(x0, y0, x1, y1)
            tile_pix = fitz.Pixmap(pix, clip)
            tiles.append(tile_pix)
    return tiles


def render_pages(pdf_bytes: bytes) -> list[PageImage]:
    """
    Render every page of *pdf_bytes* to PNG at 300 DPI.

    Pages whose longer side exceeds 4096 px are split into 2×2 tiles.
    Returns a flat list of :class:`PageImage` objects.
    """
    images: list[PageImage] = []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    logger.info("Rendering PDF: %d page(s)", doc.page_count)

    try:
        for page_index in range(doc.page_count):
            page_num = page_index + 1
            page = doc.load_page(page_index)
            pix = _render_page_at_dpi(page)

            longer_side = max(pix.width, pix.height)
            if longer_side > _MAX_SIDE_PX:
                logger.info(
                    "Page %d (%dx%d px) exceeds %d px — splitting into 2×2 tiles",
                    page_num,
                    pix.width,
                    pix.height,
                    _MAX_SIDE_PX,
                )
                tiles = _tile_pixmap(pix)
                for tile_index, tile_pix in enumerate(tiles):
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
                        page_num,
                        tile_index,
                        tile_pix.width,
                        tile_pix.height,
                        len(png_bytes),
                    )
            else:
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
                    page_num,
                    pix.width,
                    pix.height,
                    len(png_bytes),
                )

        logger.info("Rendered %d image(s) from %d page(s)", len(images), doc.page_count)
    finally:
        doc.close()

    return images
