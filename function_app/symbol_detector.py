"""
Furniture symbol detector — calls Azure OpenAI GPT-4o vision per page/tile.

Environment variables consumed:
  AZURE_OPENAI_ENDPOINT       — required
  AZURE_OPENAI_DEPLOYMENT     — default: gpt-4o
  AZURE_OPENAI_API_VERSION    — default: 2024-08-01-preview

Authentication uses the Function App's system-assigned Managed Identity via
DefaultAzureCredential, which is granted the "Cognitive Services OpenAI User"
role on the AOAI resource by the deploy script.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass, field

from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI

from config_loader import Category, get_categories
from logging_config import get_logger
from pdf_processor import PageImage

logger = get_logger(__name__)

_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")

# Limit concurrent AOAI calls to avoid rate-limit errors.
_SEMAPHORE_LIMIT = 5


@dataclass
class PageResult:
    """Detection result for a single page (tiles already aggregated)."""

    page_num: int
    counts: dict[str, int] = field(default_factory=dict)
    notes: str = ""


def _build_system_prompt(categories: list[Category]) -> str:
    lines = [
        "You are an expert at analyzing architectural office floorplan drawings.",
        "Your task is to COUNT the number of each furniture/equipment symbol visible "
        "in the image provided.",
        "",
        "CATEGORIES TO COUNT:",
    ]
    for cat in categories:
        alias_str = (
            f" (also known as: {', '.join(cat.aliases)})" if cat.aliases else ""
        )
        desc_str = f" — {cat.description}" if cat.description else ""
        lines.append(f"   {cat.name}{alias_str}{desc_str}")

    lines += [
        "",
        "RULES:",
        "1. Return STRICT JSON only — no markdown, no commentary.",
        '2. The JSON must have exactly two keys: "counts" and "notes".',
        '3. "counts" maps EVERY category name (exactly as listed above) to an integer.',
        "   Use 0 for categories not present — do NOT omit any category.",
        "4. Normalize any alias to the canonical category name shown above.",
        '5. "notes" is a brief free-text string describing any ambiguities (may be "").',
        "",
        'Example output: {"counts": {"Desk": 12, "Chair": 24, ...}, "notes": ""}',
    ]
    return "\n".join(lines)


def _image_to_data_url(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


async def _get_aoai_client() -> AsyncAzureOpenAI:
    """Create an AsyncAzureOpenAI client authenticated via DefaultAzureCredential."""
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )

    client = AsyncAzureOpenAI(
        azure_endpoint=_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version=_API_VERSION,
    )
    return client


async def detect_page(
    image: PageImage,
    client: AsyncAzureOpenAI,
    system_prompt: str,
    categories: list[Category],
    semaphore: asyncio.Semaphore,
) -> dict[str, int]:
    """
    Send one page/tile image to GPT-4o and return a dict of category counts.

    Includes one retry on JSON parse failure.
    """
    category_names = [c.name for c in categories]

    async with semaphore:
        data_url = _image_to_data_url(image.png_bytes)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "high"},
                    },
                    {
                        "type": "text",
                        "text": "This is an architectural office floorplan drawing. Look carefully at all the small shapes and symbols representing furniture. Count each type of furniture symbol you can identify. Pay special attention to desks (rectangular shapes at workstations), chairs (small circles or curved shapes), filing cabinets (small rectangles along walls), and other furniture items. Return only the JSON with counts for all categories.",
                    },
                ],
            },
        ]

        for attempt in range(2):
            start_ts = time.monotonic()
            try:
                response = await client.chat.completions.create(
                    model=_DEPLOYMENT,
                    messages=messages,  # type: ignore[arg-type]
                    response_format={"type": "json_object"},
                    temperature=0,
                    max_tokens=1024,
                )
            except Exception:
                logger.exception(
                    "Page %d tile %d — AOAI call failed (attempt %d)",
                    image.page_num,
                    image.tile_index,
                    attempt + 1,
                )
                raise

            latency = time.monotonic() - start_ts
            usage = response.usage
            raw_content = response.choices[0].message.content or ""

            logger.info(
                "Page %d tile %d — latency=%.2fs prompt_tokens=%s completion_tokens=%s",
                image.page_num,
                image.tile_index,
                latency,
                usage.prompt_tokens if usage else "?",
                usage.completion_tokens if usage else "?",
            )

            try:
                parsed = json.loads(raw_content)
                counts_raw: dict = parsed.get("counts", {})
                notes: str = parsed.get("notes", "")

                # Normalize: ensure all categories are present and values are ints.
                counts: dict[str, int] = {}
                for name in category_names:
                    counts[name] = int(counts_raw.get(name, 0))

                logger.info(
                    "Page %d tile %d counts: %s",
                    image.page_num,
                    image.tile_index,
                    counts,
                )
                return counts

            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                if attempt == 0:
                    logger.warning(
                        "Page %d tile %d — JSON parse failed (%s); retrying with re-prompt.",
                        image.page_num,
                        image.tile_index,
                        exc,
                    )
                    messages.append({"role": "assistant", "content": raw_content})
                    messages.append(
                        {
                            "role": "user",
                            "content": "Return ONLY valid JSON with keys 'counts' and 'notes'.",
                        }
                    )
                else:
                    logger.error(
                        "Page %d tile %d — JSON parse failed after retry. Raw: %s",
                        image.page_num,
                        image.tile_index,
                        raw_content[:500],
                    )
                    raise ValueError(
                        f"GPT-4o returned invalid JSON for page {image.page_num} tile {image.tile_index}"
                    ) from exc

    # Should be unreachable.
    return {name: 0 for name in category_names}


async def detect_all_pages(images: list[PageImage]) -> list[PageResult]:
    """
    Detect furniture symbols across all page images in parallel (max 5 concurrent).

    Tiles belonging to the same page are aggregated by summation.

    TODO: Replace per-tile summation with IoU-based de-duplication so that
          symbols straddling a tile boundary are not counted twice.
    """
    categories = get_categories()
    system_prompt = _build_system_prompt(categories)
    semaphore = asyncio.Semaphore(_SEMAPHORE_LIMIT)

    client = await _get_aoai_client()

    tasks = [
        detect_page(img, client, system_prompt, categories, semaphore)
        for img in images
    ]
    results_raw: list[dict[str, int]] = await asyncio.gather(*tasks)

    # Aggregate tiles per page (simple sum — see TODO above).
    page_aggregates: dict[int, dict[str, int]] = {}
    page_notes: dict[int, list[str]] = {}

    for img, counts in zip(images, results_raw):
        pn = img.page_num
        if pn not in page_aggregates:
            page_aggregates[pn] = {c.name: 0 for c in categories}
            page_notes[pn] = []
        for cat_name, count in counts.items():
            page_aggregates[pn][cat_name] = page_aggregates[pn].get(cat_name, 0) + count

    page_results: list[PageResult] = []
    for page_num in sorted(page_aggregates.keys()):
        page_results.append(
            PageResult(
                page_num=page_num,
                counts=page_aggregates[page_num],
                notes="; ".join(filter(None, page_notes[page_num])),
            )
        )

    return page_results
