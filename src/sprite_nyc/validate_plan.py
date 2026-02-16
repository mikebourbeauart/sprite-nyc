"""
Validate a tile plan by stitching all rendered tiles into a single image.

Reads the manifest.json produced by plan_tiles.py, finds render.png in each
tile folder, and composites them side-by-side (non-overlapping).

Usage:
    python -m sprite_nyc.validate_plan --tiles-dir tiles/ --output-dir validation/
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import numpy as np
from PIL import Image


def stitch_tiles(
    tiles_dir: Path,
    image_name: str = "render.png",
) -> Image.Image | None:
    """
    Stitch tile images into a single composite.

    Tiles are non-overlapping — each tile step equals the full tile dimension.
    The composite size is:
        width  = tile_w * cols
        height = tile_h * rows
    """
    manifest_path = tiles_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"No manifest.json found in {tiles_dir}")
        return None

    with open(manifest_path) as f:
        manifest = json.load(f)

    if not manifest:
        print("Empty manifest")
        return None

    # Determine grid dimensions
    max_row = max(t["row"] for t in manifest)
    max_col = max(t["col"] for t in manifest)
    rows = max_row + 1
    cols = max_col + 1

    # Load first tile to get dimensions
    first_dir = Path(manifest[0]["dir"])
    first_img_path = first_dir / image_name
    if not first_img_path.exists():
        print(f"No {image_name} in {first_dir} — have you run export_views.py?")
        return None

    first_img = Image.open(first_img_path)
    tile_w, tile_h = first_img.size

    # Non-overlapping: step = full tile size
    comp_w = tile_w * cols
    comp_h = tile_h * rows

    composite = Image.new("RGBA", (comp_w, comp_h), (0, 0, 0, 0))

    for entry in manifest:
        r, c = entry["row"], entry["col"]
        tile_path = Path(entry["dir"]) / image_name
        if not tile_path.exists():
            print(f"  Skipping missing {tile_path}")
            continue

        img = Image.open(tile_path).convert("RGBA")
        x = c * tile_w
        y = r * tile_h

        composite.paste(img, (x, y), img)

    return composite


@click.command()
@click.option("--tiles-dir", default="tiles", help="Tile plan directory")
@click.option("--output-dir", default="validation", help="Output directory")
def main(tiles_dir: str, output_dir: str) -> None:
    """Stitch tiles to validate alignment."""
    td = Path(tiles_dir)
    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    for name, out_name in [("render.png", "full_render.png"), ("generation.png", "full_generation.png")]:
        print(f"Stitching {name}…")
        result = stitch_tiles(td, name)
        if result:
            out_path = od / out_name
            result.save(out_path)
            print(f"  Saved {out_path} ({result.size[0]}×{result.size[1]})")
        else:
            print(f"  Skipped — no {name} tiles found")


if __name__ == "__main__":
    main()
