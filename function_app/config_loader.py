"""
Loads furniture_categories.yaml and exposes typed category objects.

Usage:
    from config_loader import get_categories, Category
    categories = get_categories()
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from logging_config import get_logger

logger = get_logger(__name__)

# Resolve the YAML path.
# When running locally (from the repo root or inside function_app/), look for
# the file at <repo_root>/config/furniture_categories.yaml first, then fall
# back to <function_app_dir>/config/furniture_categories.yaml (the path used
# after deploy.sh copies the config into the function package).
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)
_YAML_CANDIDATES = [
    os.path.join(_REPO_ROOT, "config", "furniture_categories.yaml"),  # local dev
    os.path.join(_MODULE_DIR, "config", "furniture_categories.yaml"),  # deployed
]
_YAML_PATH = next(
    (p for p in _YAML_CANDIDATES if os.path.isfile(p)),
    _YAML_CANDIDATES[0],  # fallback (will raise FileNotFoundError with a clear message)
)


@dataclass
class Category:
    name: str
    aliases: list[str] = field(default_factory=list)
    description: str = ""


@lru_cache(maxsize=1)
def get_categories() -> list[Category]:
    """Load and validate furniture categories from YAML. Cached after first call."""
    logger.info("Loading furniture categories from %s", _YAML_PATH)
    try:
        with open(_YAML_PATH, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"furniture_categories.yaml not found at {_YAML_PATH}"
        ) from exc

    if not isinstance(data, dict) or "categories" not in data:
        raise ValueError(
            "furniture_categories.yaml must contain a top-level 'categories' list."
        )

    raw_list = data["categories"]
    if not isinstance(raw_list, list):
        raise ValueError("'categories' must be a YAML list.")

    categories: list[Category] = []
    for item in raw_list:
        if not isinstance(item, dict) or "name" not in item:
            raise ValueError(f"Each category entry must have a 'name' key. Got: {item}")
        categories.append(
            Category(
                name=str(item["name"]),
                aliases=[str(a) for a in item.get("aliases", [])],
                description=str(item.get("description", "")),
            )
        )

    logger.info("Loaded %d furniture categories", len(categories))
    return categories
