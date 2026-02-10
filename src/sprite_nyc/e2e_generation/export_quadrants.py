"""
Export quadrant images from SQLite DB as individual PNGs for manual editing.

Usage:
    python -m sprite_nyc.e2e_generation.export_quadrants \
        --generation-dir generations/manhattan/ \
        --output-dir exported_quadrants/ \
        --type generation
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import click
from PIL import Image


@click.command()
@click.option("--generation-dir", required=True)
@click.option("--output-dir", required=True, help="Directory to export PNGs to")
@click.option(
    "--type",
    "img_type",
    type=click.Choice(["generation", "render", "both"]),
    default="generation",
)
@click.argument("quadrants", nargs=-1)
def main(generation_dir: str, output_dir: str, img_type: str, quadrants: tuple[str, ...]) -> None:
    """Export quadrant images as individual PNGs."""
    gd = Path(generation_dir)
    od = Path(output_dir)
    od.mkdir(parents=True, exist_ok=True)

    db_path = gd / "quadrants.db"
    conn = sqlite3.connect(str(db_path))

    if quadrants:
        from sprite_nyc.e2e_generation.generate_omni import parse_quadrant_tuple
        coords = [parse_quadrant_tuple(q) for q in quadrants]
        placeholders = " OR ".join(["(x = ? AND y = ?)"] * len(coords))
        flat_coords = [v for c in coords for v in c]
        where = f"WHERE ({placeholders})"
        params = flat_coords
    else:
        where = "WHERE is_generated = 1"
        params = []

    columns = []
    if img_type in ("generation", "both"):
        columns.append("generation")
    if img_type in ("render", "both"):
        columns.append("render")

    cursor = conn.execute(
        f"SELECT x, y, {', '.join(columns)} FROM quadrants {where}",
        params,
    )

    count = 0
    for row in cursor:
        x, y = row[0], row[1]
        for i, col_name in enumerate(columns):
            blob = row[2 + i]
            if not blob:
                continue

            img = Image.open(io.BytesIO(blob))
            fname = f"quadrant_{x}_{y}_{col_name}.png"
            img.save(od / fname)
            count += 1

    conn.close()
    print(f"Exported {count} images to {od}")


if __name__ == "__main__":
    main()
