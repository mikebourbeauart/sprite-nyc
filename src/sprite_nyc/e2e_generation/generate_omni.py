"""
Reusable generation library for the E2E pipeline.

Provides core functions:
  - parse_quadrant_tuple()  — parse "x,y" strings
  - call_oxen_api()         — call the fine-tuned model
  - download_image_to_pil() — fetch an image from URL
  - render_quadrant()       — render a quadrant's 3D view
  - run_generation_for_quadrants() — full generation pipeline
"""

from __future__ import annotations

import io
import sqlite3
import time
from pathlib import Path

import requests
from PIL import Image

from sprite_nyc.e2e_generation.infill_template import (
    QuadrantPosition,
    QuadrantState,
    create_template_image,
    extract_generated_quadrants,
    validate_generation_config,
)
from sprite_nyc.gcs_upload import upload_pil_image


OXEN_API_URL = "https://hub.oxen.ai/api/images/edit"
OXEN_MODEL = "mike804-arrogant-brown-hoverfly"
NUM_INFERENCE_STEPS = 28
PROMPT = (
    "Fill in the outlined section with the missing pixels "
    "corresponding to the <sprite nyc pixel art> style. "
    "The red border indicates the region to generate. "
    "Variant: quadrant."
)


def parse_quadrant_tuple(s: str) -> tuple[int, int]:
    """Parse a 'x,y' string into (x, y) integers."""
    parts = s.strip().split(",")
    if len(parts) != 2:
        raise ValueError(f"Expected 'x,y' format, got: {s}")
    return int(parts[0].strip()), int(parts[1].strip())


def call_oxen_api(
    image_url: str,
    api_key: str,
    prompt: str = PROMPT,
    timeout: int = 120,
) -> str:
    """
    Call the Oxen image edit API.

    Returns the URL of the generated image.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": OXEN_MODEL,
        "input_image": image_url,
        "prompt": prompt,
        "num_inference_steps": NUM_INFERENCE_STEPS,
    }

    resp = requests.post(
        OXEN_API_URL, json=payload, headers=headers, timeout=timeout
    )
    resp.raise_for_status()
    result = resp.json()

    result_url = result.get("url") or result.get("image_url")
    if not result_url and "images" in result:
        images = result["images"]
        if images and isinstance(images, list) and images[0].get("url"):
            result_url = images[0]["url"]
    if not result_url:
        raise ValueError(f"No result URL in API response: {result}")

    return result_url


def download_image_to_pil(url: str, timeout: int = 60) -> Image.Image:
    """Download an image URL and return as a PIL Image."""
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


def load_grid_from_db(
    db_path: Path,
) -> dict[tuple[int, int], QuadrantPosition]:
    """Load all quadrants from the SQLite DB into a grid dict."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT id, lat, lng, x, y, generation, is_generated FROM quadrants"
    )

    grid: dict[tuple[int, int], QuadrantPosition] = {}
    for row in cursor:
        qid, lat, lng, x, y, gen_blob, is_gen = row
        state = QuadrantState.GENERATED if is_gen else QuadrantState.EMPTY

        image = None
        if gen_blob:
            image = Image.open(io.BytesIO(gen_blob)).convert("RGBA")

        grid[(x, y)] = QuadrantPosition(x=x, y=y, state=state, image=image)

    conn.close()
    return grid


def load_render_from_db(
    db_path: Path, x: int, y: int
) -> Image.Image | None:
    """Load a single quadrant's render from the DB."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT render FROM quadrants WHERE x = ? AND y = ?", (x, y)
    )
    row = cursor.fetchone()
    conn.close()

    if row and row[0]:
        return Image.open(io.BytesIO(row[0])).convert("RGBA")
    return None


def _ensure_extra_columns(db_path: Path) -> None:
    """Add template and prompt columns if they don't exist yet."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("PRAGMA table_info(quadrants)")
    columns = {row[1] for row in cursor}
    if "template" not in columns:
        conn.execute("ALTER TABLE quadrants ADD COLUMN template BLOB")
    if "prompt" not in columns:
        conn.execute("ALTER TABLE quadrants ADD COLUMN prompt TEXT")
    conn.commit()
    conn.close()


def save_generation_to_db(
    db_path: Path, x: int, y: int, image: Image.Image,
    template: Image.Image | None = None,
    prompt: str | None = None,
) -> None:
    """Save a generated image (and optionally its template/prompt) to the DB."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    blob = buf.getvalue()

    tmpl_blob = None
    if template is not None:
        tbuf = io.BytesIO()
        template.save(tbuf, format="PNG")
        tmpl_blob = tbuf.getvalue()

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE quadrants SET generation = ?, template = ?, prompt = ?, is_generated = 1 WHERE x = ? AND y = ?",
        (blob, tmpl_blob, prompt, x, y),
    )
    conn.commit()
    conn.close()


def load_template_from_db(
    db_path: Path, x: int, y: int
) -> Image.Image | None:
    """Load a stored template image from the DB."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT template FROM quadrants WHERE x = ? AND y = ?", (x, y)
        )
        row = cursor.fetchone()
        if row and row[0]:
            return Image.open(io.BytesIO(row[0])).convert("RGBA")
    except sqlite3.OperationalError:
        pass  # template column doesn't exist yet
    finally:
        conn.close()
    return None


def render_quadrant(
    generation_dir: Path, x: int, y: int
) -> Image.Image | None:
    """
    Get the 3D render for a quadrant. First checks the DB, then
    falls back to running the web renderer (not yet implemented —
    returns None as a placeholder).
    """
    db_path = generation_dir / "quadrants.db"
    render = load_render_from_db(db_path, x, y)
    if render:
        return render

    # TODO: Launch Playwright to render this quadrant
    return None


def run_generation_for_quadrants(
    generation_dir: Path,
    quadrant_coords: list[tuple[int, int]],
    api_key: str,
    gcs_bucket: str = "sprite-nyc-assets",
    tile_size: int = 1024,
    dry_run: bool = False,
) -> dict[tuple[int, int], Image.Image]:
    """
    Full generation pipeline for a set of quadrant coordinates.

    1. Load grid from DB
    2. Validate the selection
    3. Create the infill template
    4. Upload to GCS
    5. Call Oxen API
    6. Extract and save results

    Returns a dict of (x, y) → generated Image.
    """
    db_path = generation_dir / "quadrants.db"
    _ensure_extra_columns(db_path)
    grid = load_grid_from_db(db_path)

    # Build selected list
    selected: list[QuadrantPosition] = []
    for x, y in quadrant_coords:
        q = grid.get((x, y))
        if q is None:
            raise ValueError(f"Quadrant ({x}, {y}) not found in DB")
        selected.append(q)

    # Validate
    errors = validate_generation_config(selected, grid)
    if errors:
        raise ValueError(f"Invalid generation config: {'; '.join(errors)}")

    # Load renders for selected tiles + their neighbors
    render_lookup: dict[tuple[int, int], Image.Image] = {}
    keys_to_load = set()
    for q in selected:
        keys_to_load.add(q.key)
        for nb_key in q.neighbor_keys().values():
            keys_to_load.add(nb_key)
    for key in keys_to_load:
        x, y = key
        render = render_quadrant(generation_dir, x, y)
        if render:
            render_lookup[key] = render

    # Create template
    template, layout = create_template_image(selected, grid, render_lookup, tile_size)

    # Save template for debugging
    template_path = generation_dir / "last_template.png"
    template.save(template_path)
    print(f"Saved template to {template_path}")

    if dry_run:
        print("Dry run — skipping API call")
        return {}

    # Upload and generate
    print("Uploading template to GCS…")
    public_url = upload_pil_image(template, bucket_name=gcs_bucket)
    print(f"Uploaded: {public_url}")

    print("Calling Oxen API…")
    start = time.time()
    result_url = call_oxen_api(public_url, api_key)
    result_image = download_image_to_pil(result_url)
    elapsed = time.time() - start
    print(f"Generation took {elapsed:.1f}s")

    # Template is now 1024×1024 — same as model output, no resize needed
    assert result_image.size == (1024, 1024), (
        f"Expected 1024×1024 result, got {result_image.size}"
    )

    # Extract quadrants (crops 512×512 cells, upscales to 1024×1024)
    results = extract_generated_quadrants(result_image, selected, layout)

    # Save to DB (include the template and prompt that were used)
    for (x, y), img in results.items():
        save_generation_to_db(db_path, x, y, img, template=template, prompt=PROMPT)
        print(f"Saved quadrant ({x}, {y})")

    return results
