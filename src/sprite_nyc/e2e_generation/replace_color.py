"""
Soft-blend color replacement for fixing water and other color artifacts.

Uses alpha compositing to smoothly replace colors within a tolerance
range, avoiding hard edges.

Usage:
    python -m sprite_nyc.e2e_generation.replace_color \
        --generation-dir generations/manhattan/ \
        --target-color "64,128,200" \
        --replacement-color "40,80,140" \
        --blend-softness 40 \
        --dry-run

    # Process specific quadrants:
    python -m sprite_nyc.e2e_generation.replace_color \
        --generation-dir generations/manhattan/ \
        --target-color "64,128,200" \
        --replacement-color "40,80,140" \
        --quadrants "0,0" "1,0" "2,0"
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import click
import numpy as np
from PIL import Image

from sprite_nyc.e2e_generation.generate_omni import parse_quadrant_tuple


def color_distance(pixels: np.ndarray, target: np.ndarray) -> np.ndarray:
    """
    Compute per-pixel Euclidean distance from target color.
    Returns an array of shape (H, W) with distances in [0, 441].
    """
    diff = pixels[:, :, :3].astype(float) - target[:3].astype(float)
    return np.sqrt(np.sum(diff ** 2, axis=2))


def soft_replace_color(
    image: Image.Image,
    target_color: tuple[int, int, int],
    replacement_color: tuple[int, int, int],
    blend_softness: int = 40,
) -> Image.Image:
    """
    Replace *target_color* with *replacement_color* using soft blending.

    Pixels close to the target color are blended toward the replacement.
    The *blend_softness* parameter (20–100) controls the transition range:
    lower = tighter match, higher = broader blend.
    """
    arr = np.array(image.convert("RGBA"), dtype=np.float64)
    target = np.array(target_color, dtype=np.float64)
    replacement = np.array(replacement_color, dtype=np.float64)

    dist = color_distance(arr, target)

    # Compute blend factor: 1.0 at distance=0, 0.0 at distance>=softness
    alpha = np.clip(1.0 - dist / blend_softness, 0.0, 1.0)

    # Blend: result = original * (1 - alpha) + replacement * alpha
    for c in range(3):  # RGB channels
        arr[:, :, c] = arr[:, :, c] * (1 - alpha) + replacement[c] * alpha

    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def process_quadrant_in_db(
    db_path: Path,
    x: int,
    y: int,
    target_color: tuple[int, int, int],
    replacement_color: tuple[int, int, int],
    blend_softness: int,
    dry_run: bool,
    export_dir: Path | None = None,
) -> bool:
    """Process a single quadrant's generation image. Returns True if modified."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT generation FROM quadrants WHERE x = ? AND y = ? AND is_generated = 1",
        (x, y),
    )
    row = cursor.fetchone()
    if not row or not row[0]:
        conn.close()
        return False

    image = Image.open(io.BytesIO(row[0])).convert("RGBA")
    result = soft_replace_color(image, target_color, replacement_color, blend_softness)

    if dry_run and export_dir:
        export_dir.mkdir(parents=True, exist_ok=True)
        result.save(export_dir / f"preview_{x}_{y}.png")
        print(f"  Preview saved: {export_dir / f'preview_{x}_{y}.png'}")
    elif not dry_run:
        buf = io.BytesIO()
        result.save(buf, format="PNG")
        conn.execute(
            "UPDATE quadrants SET generation = ? WHERE x = ? AND y = ?",
            (buf.getvalue(), x, y),
        )
        conn.commit()

    conn.close()
    return True


def parse_color(s: str) -> tuple[int, int, int]:
    parts = s.split(",")
    return int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip())


@click.command()
@click.option("--generation-dir", required=True)
@click.option("--target-color", required=True, help="Color to replace as 'R,G,B'")
@click.option("--replacement-color", required=True, help="New color as 'R,G,B'")
@click.option("--blend-softness", default=40, type=int, help="Blend range (20-100)")
@click.option("--dry-run", is_flag=True, help="Export previews instead of modifying DB")
@click.option("--export-dir", default=None, help="Directory for dry-run previews")
@click.argument("quadrants", nargs=-1)
def main(
    generation_dir: str,
    target_color: str,
    replacement_color: str,
    blend_softness: int,
    dry_run: bool,
    export_dir: str | None,
    quadrants: tuple[str, ...],
) -> None:
    """Replace colors in generated quadrants."""
    gd = Path(generation_dir)
    db_path = gd / "quadrants.db"
    tc = parse_color(target_color)
    rc = parse_color(replacement_color)
    ed = Path(export_dir) if export_dir else gd / "color_previews"

    if quadrants:
        coords = [parse_quadrant_tuple(q) for q in quadrants]
    else:
        # Process all generated quadrants
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT x, y FROM quadrants WHERE is_generated = 1"
        )
        coords = [(row[0], row[1]) for row in cursor]
        conn.close()

    print(f"Processing {len(coords)} quadrants")
    print(f"Target: {tc} → Replacement: {rc} (softness={blend_softness})")

    modified = 0
    for x, y in coords:
        if process_quadrant_in_db(db_path, x, y, tc, rc, blend_softness, dry_run, ed):
            modified += 1
            print(f"  ({x}, {y}): {'previewed' if dry_run else 'updated'}")

    print(f"\n{'Previewed' if dry_run else 'Modified'} {modified} quadrants")


if __name__ == "__main__":
    main()
