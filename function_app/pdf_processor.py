def render_pages(pdf_bytes: bytes) -> List[PageImage]:
    """
    Render every page of *pdf_bytes* to PNG at 200 DPI.

    Pages whose longer side exceeds 4096 px are split into 2×2 tiles.
    Returns a flat list of :class:`PageImage` objects.
    """
    images: List[PageImage] = []

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
    finally:
        doc.close()
        
    logger.info("Rendered %d image(s) from %d page(s)", len(images), len(images))
    return images
