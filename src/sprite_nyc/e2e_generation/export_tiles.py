"""
Export generated quadrants from the SQLite DB as a Deep Zoom Image (DZI)
tile pyramid for use with OpenSeaDragon.

DZI format: a directory of zoom levels, each containing tile images.
Level 0 is 1×1 pixel, and each subsequent level doubles the resolution.

Usage:
    python -m sprite_nyc.e2e_generation.export_tiles \
        --generation-dir generations/manhattan/ \
        --output-dir viewer/tiles/
"""

from __future__ import annotations

import io
import math
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import click
import numpy as np
from PIL import Image


DZI_TILE_SIZE = 256
DZI_OVERLAP = 1
DZI_FORMAT = "png"


def load_all_generations(db_path: Path) -> dict[tuple[int, int], Image.Image]:
    """Load all generated quadrant images from the DB."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT x, y, generation FROM quadrants WHERE is_generated = 1 AND generation IS NOT NULL"
    )

    images = {}
    for row in cursor:
        x, y, blob = row
        img = Image.open(io.BytesIO(blob)).convert("RGBA")
        images[(x, y)] = img

    conn.close()
    return images


def stitch_full_image(
    images: dict[tuple[int, int], Image.Image],
    tile_size: int = 1024,
) -> Image.Image:
    """
    Stitch all quadrant images into a single large image.

    With 50% overlap between tiles, each step is tile_size/2.
    """
    if not images:
        raise ValueError("No images to stitch")

    xs = [k[0] for k in images]
    ys = [k[1] for k in images]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    cols = max_x - min_x + 1
    rows = max_y - min_y + 1

    # With 50% overlap, step = half tile size
    step = tile_size // 2

    # Full image dimensions
    full_w = step * (cols - 1) + tile_size
    full_h = step * (rows - 1) + tile_size

    full = Image.new("RGBA", (full_w, full_h), (0, 0, 0, 255))

    for (x, y), img in images.items():
        resized = img.resize((tile_size, tile_size), Image.LANCZOS)
        px = (x - min_x) * step
        py = (y - min_y) * step
        full.paste(resized, (px, py), resized)

    return full


def create_dzi_tiles(
    full_image: Image.Image,
    output_dir: Path,
    tile_size: int = DZI_TILE_SIZE,
    overlap: int = DZI_OVERLAP,
) -> dict:
    """
    Create a DZI tile pyramid from a full image.

    Returns metadata dict with width, height, max_level.
    """
    w, h = full_image.size
    max_dim = max(w, h)
    max_level = math.ceil(math.log2(max_dim)) if max_dim > 0 else 0

    tiles_dir = output_dir / "tiles_files"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    for level in range(max_level + 1):
        level_dir = tiles_dir / str(level)
        level_dir.mkdir(parents=True, exist_ok=True)

        # Scale factor for this level
        scale = 2 ** (level - max_level)
        level_w = max(1, int(w * scale))
        level_h = max(1, int(h * scale))

        # Resize the full image for this level
        level_img = full_image.resize((level_w, level_h), Image.LANCZOS)

        # Tile the level image
        cols = math.ceil(level_w / tile_size)
        rows = math.ceil(level_h / tile_size)

        for row in range(rows):
            for col in range(cols):
                # Crop coordinates with overlap
                x0 = col * tile_size - (overlap if col > 0 else 0)
                y0 = row * tile_size - (overlap if row > 0 else 0)
                x1 = min((col + 1) * tile_size + overlap, level_w)
                y1 = min((row + 1) * tile_size + overlap, level_h)

                x0 = max(0, x0)
                y0 = max(0, y0)

                tile = level_img.crop((x0, y0, x1, y1))
                tile.save(level_dir / f"{col}_{row}.{DZI_FORMAT}")

    # Write DZI descriptor
    dzi_xml = ET.Element("Image", {
        "xmlns": "http://schemas.microsoft.com/deepzoom/2008",
        "Format": DZI_FORMAT,
        "Overlap": str(overlap),
        "TileSize": str(tile_size),
    })
    ET.SubElement(dzi_xml, "Size", {
        "Width": str(w),
        "Height": str(h),
    })

    tree = ET.ElementTree(dzi_xml)
    dzi_path = output_dir / "tiles.dzi"
    tree.write(str(dzi_path), xml_declaration=True, encoding="UTF-8")

    return {"width": w, "height": h, "max_level": max_level, "dzi_path": str(dzi_path)}


@click.command()
@click.option("--generation-dir", required=True)
@click.option("--output-dir", default="viewer", help="Output directory for DZI tiles")
@click.option("--tile-size", default=1024, type=int, help="Quadrant render size")
def main(generation_dir: str, output_dir: str, tile_size: int) -> None:
    """Export generated quadrants as a DZI tile pyramid."""
    gd = Path(generation_dir)
    od = Path(output_dir)
    db_path = gd / "quadrants.db"

    print("Loading generated quadrants…")
    images = load_all_generations(db_path)
    print(f"Loaded {len(images)} quadrants")

    if not images:
        print("No generated quadrants to export")
        return

    print("Stitching full image…")
    full = stitch_full_image(images, tile_size)
    print(f"Full image: {full.size[0]}×{full.size[1]}")

    # Save the full image too
    full_path = od / "full_generation.png"
    od.mkdir(parents=True, exist_ok=True)
    full.save(full_path)
    print(f"Saved full image to {full_path}")

    print("Creating DZI tile pyramid…")
    meta = create_dzi_tiles(full, od)
    print(f"DZI: {meta['max_level']+1} levels, {meta['width']}×{meta['height']}")
    print(f"Descriptor: {meta['dzi_path']}")


if __name__ == "__main__":
    main()
