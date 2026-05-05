"""
Structured JSON logging configuration wired to Azure Application Insights.

All modules should obtain their logger via:
    from logging_config import get_logger
    logger = get_logger(__name__)
"""

import logging
import os

from pythonjsonlogger import jsonlogger

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return

    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any existing handlers (Azure Functions may add a default one).
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    # JSON stdout handler.
    stream_handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(log_level)
    root_logger.addHandler(stream_handler)

    # Azure Application Insights handler (optional — only added when the
    # connection string is present so local dev works without App Insights).
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if connection_string:
        try:
            from opencensus.ext.azure.log_exporter import AzureLogHandler

            azure_handler = AzureLogHandler(connection_string=connection_string)
            azure_handler.setLevel(log_level)
            root_logger.addHandler(azure_handler)
        except Exception as exc:  # noqa: BLE001
            # Don't crash the function if App Insights setup fails.
            root_logger.warning("Failed to configure AzureLogHandler: %s", exc)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, ensuring the root logger is configured first."""
    _configure()
    return logging.getLogger(name)
