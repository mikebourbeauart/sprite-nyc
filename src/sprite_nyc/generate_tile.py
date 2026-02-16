"""
Generate a single pixel-art tile using the Oxen.ai fine-tuned model.

Pipeline:
  1. Create an infill template from the render + neighbor tiles
  2. Upload template to GCS → public URL
  3. Call the Oxen API with the image URL + prompt
  4. Download the result → generation.png

Usage:
    python -m sprite_nyc.generate_tile \
        --tile-dir tiles/tile_1_1 \
        --tiles-root tiles/ \
        --output generation.png
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import click
import requests
from PIL import Image

from sprite_nyc.create_template import create_guided_template, create_unguided_template
from sprite_nyc.gcs_upload import upload_pil_image


OXEN_API_URL = "https://hub.oxen.ai/api/images/edit"
OXEN_MODEL = "mike804-crazy-yellow-constrictor"
NUM_INFERENCE_STEPS = 28
PROMPT = (
    "Fill in the outlined section with the missing pixels "
    "corresponding to the <sprite nyc pixel art> style. "
    "The red border indicates the region to generate."
)


def load_tile_image(tile_dir: Path, name: str) -> Image.Image | None:
    """Load an image from a tile directory, or None if missing."""
    path = tile_dir / name
    if path.exists():
        return Image.open(path).convert("RGBA")
    return None


def find_neighbor_dirs(tile_dir: Path, tiles_root: Path) -> dict[str, Path | None]:
    """
    Find neighbor tile directories based on naming convention tile_R_C.
    """
    name = tile_dir.name  # e.g. "tile_1_1"
    parts = name.split("_")
    if len(parts) != 3:
        return {}

    r, c = int(parts[1]), int(parts[2])

    neighbor_offsets = {
        "top": (r - 1, c),
        "bottom": (r + 1, c),
        "left": (r, c - 1),
        "right": (r, c + 1),
        "top_left": (r - 1, c - 1),
        "top_right": (r - 1, c + 1),
        "bottom_left": (r + 1, c - 1),
        "bottom_right": (r + 1, c + 1),
    }

    result = {}
    for direction, (nr, nc) in neighbor_offsets.items():
        nb_dir = tiles_root / f"tile_{nr}_{nc}"
        result[direction] = nb_dir if nb_dir.exists() else None

    return result


def build_template(tile_dir: Path, tiles_root: Path | None) -> Image.Image:
    """Build the infill template for a tile."""
    render = load_tile_image(tile_dir, "render.png")
    if render is None:
        raise FileNotFoundError(f"No render.png in {tile_dir}")

    if tiles_root is None:
        return create_unguided_template(render)

    # Collect neighbor generations
    neighbor_dirs = find_neighbor_dirs(tile_dir, tiles_root)
    neighbors: dict[str, Image.Image | None] = {}
    for direction, nb_dir in neighbor_dirs.items():
        if nb_dir is not None:
            neighbors[direction] = load_tile_image(nb_dir, "generation.png")
        else:
            neighbors[direction] = None

    has_any_neighbor = any(v is not None for v in neighbors.values())
    if has_any_neighbor:
        return create_guided_template(render, neighbors)
    else:
        return create_unguided_template(render)


def call_oxen_api(image_url: str, api_key: str) -> Image.Image:
    """Call the Oxen image edit API and return the result image."""
    headers = {
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": OXEN_MODEL,
        "input_image": image_url,
        "prompt": PROMPT,
        "num_inference_steps": NUM_INFERENCE_STEPS,
    }

    resp = requests.post(OXEN_API_URL, json=payload, headers=headers, timeout=300)
    resp.raise_for_status()

    result = resp.json()
    result_url = result.get("url") or result.get("image_url")
    if not result_url and result.get("images"):
        result_url = result["images"][0].get("url")
    if not result_url:
        raise ValueError(f"No result URL in response: {result}")

    # Download result
    img_resp = requests.get(result_url, timeout=60)
    img_resp.raise_for_status()

    from io import BytesIO
    return Image.open(BytesIO(img_resp.content)).convert("RGBA")


@click.command()
@click.option("--tile-dir", required=True, help="Path to the tile directory")
@click.option("--tiles-root", default=None, help="Root tiles directory (for neighbor lookup)")
@click.option("--output", default=None, help="Output path (default: tile_dir/generation.png)")
@click.option("--api-key", envvar="OXEN_INFILL_V02_API_KEY", required=True)
@click.option("--gcs-bucket", default="sprite-nyc-assets")
@click.option("--dry-run", is_flag=True, help="Save template only, don't call API")
def main(
    tile_dir: str,
    tiles_root: str | None,
    output: str | None,
    api_key: str,
    gcs_bucket: str,
    dry_run: bool,
) -> None:
    """Generate pixel art for a single tile."""
    td = Path(tile_dir)
    tr = Path(tiles_root) if tiles_root else None
    out_path = Path(output) if output else td / "generation.png"

    print(f"Building template for {td.name}…")
    template = build_template(td, tr)

    # Save template for debugging
    template_path = td / "template.png"
    template.save(template_path)
    print(f"Saved template to {template_path}")

    if dry_run:
        print("Dry run — skipping API call")
        return

    print("Uploading to GCS…")
    public_url = upload_pil_image(template, bucket_name=gcs_bucket)
    print(f"Uploaded: {public_url}")

    print("Calling Oxen API…")
    start = time.time()
    result = call_oxen_api(public_url, api_key)
    elapsed = time.time() - start
    print(f"Generation took {elapsed:.1f}s")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(out_path)
    print(f"Saved generation to {out_path}")


if __name__ == "__main__":
    main()
