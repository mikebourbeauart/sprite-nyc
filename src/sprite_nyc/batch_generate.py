"""
Batch-generate pixel art for a grid of tiles using the Oxen.ai API.

Iterates tiles in spiral order from center outward so each tile has
neighbor context from previously generated tiles. Uses the infill
template system for seamless stitching.

Usage:
    python -m sprite_nyc.batch_generate \
        --tiles-dir output/test_grid \
        --api-key <key>
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import click
from PIL import Image

from sprite_nyc.create_template import create_guided_template, create_unguided_template
from sprite_nyc.gcs_upload import upload_pil_image
from sprite_nyc.generate_tile_oxen import generate_from_url, PROMPT


def _load_image(path: Path) -> Image.Image | None:
    if path.exists():
        return Image.open(path).convert("RGBA")
    return None


def _find_neighbors(
    row: int, col: int, tiles_dir: Path
) -> dict[str, Image.Image | None]:
    """Load already-generated neighbor images."""
    offsets = {
        "top": (-1, 0),
        "bottom": (1, 0),
        "left": (0, -1),
        "right": (0, 1),
        "top_left": (-1, -1),
        "top_right": (-1, 1),
        "bottom_left": (1, -1),
        "bottom_right": (1, 1),
    }
    neighbors = {}
    for direction, (dr, dc) in offsets.items():
        gen_path = tiles_dir / f"tile_{row + dr}_{col + dc}" / "generation.png"
        neighbors[direction] = _load_image(gen_path)
    return neighbors


def _spiral_order(rows: int, cols: int) -> list[tuple[int, int]]:
    """Return (row, col) pairs in spiral order from center outward."""
    coords = [(r, c) for r in range(rows) for c in range(cols)]
    if not coords:
        return []

    # Center point
    cr = (rows - 1) / 2
    cc = (cols - 1) / 2

    # Sort by distance from center (Chebyshev distance for ring ordering)
    coords.sort(key=lambda rc: (max(abs(rc[0] - cr), abs(rc[1] - cc)), rc[0], rc[1]))
    return coords


def batch_generate(
    tiles_dir: Path,
    api_key: str,
    gcs_bucket: str,
    dry_run: bool,
) -> None:
    manifest_path = tiles_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.json in {tiles_dir}")

    with open(manifest_path) as f:
        manifest = json.load(f)

    max_row = max(t["row"] for t in manifest)
    max_col = max(t["col"] for t in manifest)
    rows = max_row + 1
    cols = max_col + 1

    order = _spiral_order(rows, cols)
    total = len(order)
    print(f"Generating {total} tiles in spiral order from center")

    for i, (r, c) in enumerate(order):
        tile_dir = tiles_dir / f"tile_{r}_{c}"
        gen_path = tile_dir / "generation.png"

        if gen_path.exists():
            print(f"\n[{i + 1}/{total}] tile_{r}_{c} — already generated, skipping")
            continue

        print(f"\n[{i + 1}/{total}] Generating tile_{r}_{c}…")

        render = _load_image(tile_dir / "render.png")
        if render is None:
            print(f"  No render.png in {tile_dir}, skipping")
            continue

        # Build template with neighbor context
        neighbors = _find_neighbors(r, c, tiles_dir)
        has_neighbors = any(v is not None for v in neighbors.values())

        if has_neighbors:
            template = create_guided_template(render, neighbors)
            print("  Guided template (neighbors found)")
        else:
            template = create_unguided_template(render)
            print("  Unguided template (no neighbors)")

        # Save template for debugging
        template.save(tile_dir / "template.png")

        if dry_run:
            print("  Dry run — skipping API call")
            continue

        # Upload and generate
        print("  Uploading to GCS…")
        public_url = upload_pil_image(template, bucket_name=gcs_bucket)

        print("  Calling Oxen API…")
        start = time.time()
        result = generate_from_url(public_url, api_key, PROMPT)
        elapsed = time.time() - start
        print(f"  Generation took {elapsed:.1f}s")

        result.save(gen_path)
        print(f"  Saved {gen_path}")

    print(f"\nDone — generated {total} tiles")


@click.command()
@click.option("--tiles-dir", required=True, help="Tiles directory with manifest.json")
@click.option(
    "--api-key",
    envvar="OXEN_INFILL_V02_API_KEY",
    required=True,
    help="Oxen API key",
)
@click.option("--gcs-bucket", default="sprite-nyc-assets", help="GCS bucket name")
@click.option("--dry-run", is_flag=True, help="Save templates only, don't call API")
def main(tiles_dir: str, api_key: str, gcs_bucket: str, dry_run: bool) -> None:
    """Batch-generate pixel art tiles with neighbor context."""
    batch_generate(Path(tiles_dir), api_key, gcs_bucket, dry_run)


if __name__ == "__main__":
    main()
