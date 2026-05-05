"""
Azure Function HTTP trigger — POST /api/process-floorplan

Accepts an office floorplan PDF (multipart form-data field 'pdf' or raw
application/pdf body), runs it through the symbol-detection pipeline, and
returns the SharePoint URL of the generated .xlsx report.

Python v2 programming model.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid

import azure.functions as func

from config_loader import get_categories
from excel_builder import build_workbook
from logging_config import get_logger
from pdf_processor import render_pages
from sharepoint_uploader import upload
from symbol_detector import detect_all_pages

logger = get_logger(__name__)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

_MAX_PDF_BYTES = 50 * 1024 * 1024  # 50 MB


def _extract_pdf_bytes(req: func.HttpRequest) -> tuple[bytes, str]:
    """
    Extract PDF bytes and original filename from the request.

    Supports:
      • multipart/form-data with a 'pdf' file field
      • raw application/pdf body

    Returns (pdf_bytes, original_filename).
    Raises ValueError with a human-readable message on validation failure.
    """
    content_type = req.headers.get("Content-Type", "")

    if "multipart/form-data" in content_type:
        files = req.files
        if "pdf" not in files:
            raise ValueError("Multipart request must include a 'pdf' file field.")
        pdf_file = files["pdf"]
        pdf_bytes = pdf_file.read()
        filename = pdf_file.filename or "floorplan.pdf"
    elif "application/pdf" in content_type:
        pdf_bytes = req.get_body()
        filename = req.params.get("filename", "floorplan.pdf")
    else:
        raise ValueError(
            "Unsupported Content-Type. Send multipart/form-data with a 'pdf' field "
            "or a raw application/pdf body."
        )

    if not pdf_bytes:
        raise ValueError("PDF content is empty.")

    # Basic PDF magic-bytes check.
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Uploaded file does not appear to be a valid PDF.")

    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise ValueError(
            f"PDF is too large ({len(pdf_bytes) / 1024 / 1024:.1f} MB). "
            f"Maximum allowed size is 50 MB."
        )

    return pdf_bytes, filename


def _error_response(
    message: str, step: str, status_code: int = 500
) -> func.HttpResponse:
    body = json.dumps({"error": message, "step": step})
    return func.HttpResponse(
        body=body,
        status_code=status_code,
        mimetype="application/json",
    )


@app.function_name(name="ProcessFloorplan")
@app.route(route="process-floorplan", methods=["POST"])
def process_floorplan(req: func.HttpRequest) -> func.HttpResponse:
    """Main HTTP trigger handler."""
    request_id = str(uuid.uuid4())
    logger.info("ProcessFloorplan invoked — request_id=%s", request_id)

    # ------------------------------------------------------------------ #
    # Step 1: Validate input
    # ------------------------------------------------------------------ #
    try:
        pdf_bytes, original_filename = _extract_pdf_bytes(req)
    except ValueError as exc:
        logger.warning("Input validation failed: %s", exc)
        status = 413 if "too large" in str(exc).lower() else 400
        return _error_response(str(exc), "input_validation", status)

    logger.info(
        "Received PDF: filename=%s size=%d bytes request_id=%s",
        original_filename,
        len(pdf_bytes),
        request_id,
    )

    # ------------------------------------------------------------------ #
    # Step 2: Save to /tmp
    # ------------------------------------------------------------------ #
    tmp_path: str | None = None
    try:
        suffix = ".pdf"
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, dir="/tmp"
        ) as tmp_file:
            tmp_file.write(pdf_bytes)
            tmp_path = tmp_file.name
        logger.info("Saved PDF to %s", tmp_path)
    except Exception as exc:
        logger.exception("Failed to save PDF to /tmp")
        return _error_response(f"Could not write temporary file: {exc}", "save_temp")

    # ------------------------------------------------------------------ #
    # Step 3: Render PDF pages to PNG
    # ------------------------------------------------------------------ #
    try:
        page_images = render_pages(pdf_bytes)
        logger.info("Rendered %d image(s)", len(page_images))
    except Exception as exc:
        logger.exception("PDF rendering failed")
        return _error_response(f"PDF rendering failed: {exc}", "pdf_render")

    # ------------------------------------------------------------------ #
    # Step 4: Detect furniture symbols (async GPT-4o)
    # ------------------------------------------------------------------ #
    try:
        page_results = asyncio.run(detect_all_pages(page_images))
        logger.info("Symbol detection complete: %d page result(s)", len(page_results))
    except Exception as exc:
        logger.exception("Symbol detection failed")
        return _error_response(f"Symbol detection failed: {exc}", "symbol_detect")

    # ------------------------------------------------------------------ #
    # Step 5: Build Excel workbook
    # ------------------------------------------------------------------ #
    try:
        categories = get_categories()
        category_names = [c.name for c in categories]
        xlsx_bytes = build_workbook(page_results, category_names)
        logger.info("Excel workbook built: %d bytes", len(xlsx_bytes))
    except Exception as exc:
        logger.exception("Excel build failed")
        return _error_response(f"Excel build failed: {exc}", "excel_build")

    # ------------------------------------------------------------------ #
    # Step 6: Upload to SharePoint
    # ------------------------------------------------------------------ #
    try:
        sharepoint_url = upload(xlsx_bytes, original_filename)
        logger.info("Uploaded to SharePoint: %s", sharepoint_url)
    except Exception as exc:
        logger.exception("SharePoint upload failed")
        return _error_response(f"SharePoint upload failed: {exc}", "sharepoint_upload")

    # ------------------------------------------------------------------ #
    # Step 7: Return result
    # ------------------------------------------------------------------ #
    body = json.dumps({"url": sharepoint_url})
    logger.info(
        "ProcessFloorplan complete — request_id=%s url=%s", request_id, sharepoint_url
    )
    return func.HttpResponse(body=body, status_code=200, mimetype="application/json")
