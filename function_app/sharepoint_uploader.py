"""
SharePoint uploader — uploads a file to a SharePoint document library using the
Microsoft Graph API, authenticated via ClientSecretCredential.

Environment variables consumed:
  GRAPH_TENANT_ID            — Azure AD tenant ID
  GRAPH_CLIENT_ID            — App registration client ID
  GRAPH_CLIENT_SECRET        — Client secret (injected via Key Vault reference)
  SHAREPOINT_SITE_HOSTNAME   — e.g. brigholme.sharepoint.com
  SHAREPOINT_SITE_PATH       — e.g. / (root site)
  SHAREPOINT_FOLDER_PATH     — e.g. /IT-PowerAppStorage/Layout-Counter
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import PurePosixPath

import httpx
from azure.identity import ClientSecretCredential

from logging_config import get_logger

logger = get_logger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_LARGE_FILE_THRESHOLD = 4 * 1024 * 1024  # 4 MB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_credential() -> ClientSecretCredential:
    tenant_id = os.environ["GRAPH_TENANT_ID"]
    client_id = os.environ["GRAPH_CLIENT_ID"]
    client_secret = os.environ["GRAPH_CLIENT_SECRET"]
    return ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


def _get_access_token(credential: ClientSecretCredential) -> str:
    token = credential.get_token("https://graph.microsoft.com/.default")
    return token.token


def _auth_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _resolve_site_id(client: httpx.Client, headers: dict) -> str:
    """Resolve the SharePoint site ID from hostname + site path."""
    hostname = os.environ.get("SHAREPOINT_SITE_HOSTNAME", "brigholme.sharepoint.com")
    site_path = os.environ.get("SHAREPOINT_SITE_PATH", "/").strip("/")
    if site_path:
        url = f"{_GRAPH_BASE}/sites/{hostname}:/{site_path}"
    else:
        url = f"{_GRAPH_BASE}/sites/{hostname}"
    resp = client.get(url, headers=headers)
    resp.raise_for_status()
    site_id: str = resp.json()["id"]
    logger.info("Resolved SharePoint site ID: %s", site_id)
    return site_id


def _resolve_drive_id(client: httpx.Client, headers: dict, site_id: str) -> str:
    """Resolve the default Documents drive ID for the given site."""
    url = f"{_GRAPH_BASE}/sites/{site_id}/drive"
    resp = client.get(url, headers=headers)
    resp.raise_for_status()
    drive_id: str = resp.json()["id"]
    logger.info("Resolved SharePoint drive ID: %s", drive_id)
    return drive_id


def _build_remote_path(original_filename: str) -> str:
    """Construct the remote SharePoint path including timestamp-stamped filename."""
    folder_path = os.environ.get(
        "SHAREPOINT_FOLDER_PATH", "/IT-PowerAppStorage/Layout-Counter"
    ).rstrip("/")
    stem = PurePosixPath(original_filename).stem
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"{stem}-{timestamp}.xlsx"
    return f"{folder_path}/{filename}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def upload(
    xlsx_bytes: bytes,
    original_filename: str,
) -> str:
    """
    Upload *xlsx_bytes* to SharePoint and return the ``webUrl`` of the uploaded file.

    Uses a simple PUT for files ≤ 4 MB; falls back to an upload session for
    larger files (spreadsheets will be small, but the branch is here for safety).
    """
    credential = _get_credential()
    access_token = _get_access_token(credential)
    headers = _auth_headers(access_token)

    remote_path = _build_remote_path(original_filename)
    logger.info("Uploading to SharePoint path: %s", remote_path)

    with httpx.Client(timeout=120) as client:
        site_id = _resolve_site_id(client, headers)
        drive_id = _resolve_drive_id(client, headers, site_id)

        if len(xlsx_bytes) <= _LARGE_FILE_THRESHOLD:
            web_url = _simple_put(client, headers, drive_id, remote_path, xlsx_bytes)
        else:
            web_url = _upload_session(client, headers, drive_id, remote_path, xlsx_bytes)

    logger.info("File uploaded successfully. webUrl: %s", web_url)
    return web_url


def _simple_put(
    client: httpx.Client,
    headers: dict,
    drive_id: str,
    remote_path: str,
    file_bytes: bytes,
) -> str:
    """PUT upload for files ≤ 4 MB."""
    # Encode colons and spaces in path segments for Graph API.
    encoded_path = remote_path.lstrip("/")
    url = f"{_GRAPH_BASE}/drives/{drive_id}/root:/{encoded_path}:/content"
    put_headers = {
        **headers,
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    resp = client.put(url, headers=put_headers, content=file_bytes)
    resp.raise_for_status()
    return resp.json().get("webUrl", "")


def _upload_session(
    client: httpx.Client,
    headers: dict,
    drive_id: str,
    remote_path: str,
    file_bytes: bytes,
) -> str:
    """Large-file upload using a Graph upload session."""
    encoded_path = remote_path.lstrip("/")
    create_url = f"{_GRAPH_BASE}/drives/{drive_id}/root:/{encoded_path}:/createUploadSession"
    session_resp = client.post(
        create_url,
        headers=headers,
        json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
    )
    session_resp.raise_for_status()
    upload_url: str = session_resp.json()["uploadUrl"]

    # Upload in one chunk (the file is large but typically < 60 MB).
    chunk_headers = {
        "Content-Length": str(len(file_bytes)),
        "Content-Range": f"bytes 0-{len(file_bytes) - 1}/{len(file_bytes)}",
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    upload_resp = client.put(upload_url, headers=chunk_headers, content=file_bytes)
    upload_resp.raise_for_status()
    return upload_resp.json().get("webUrl", "")
