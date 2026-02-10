"""
Import edited quadrant PNGs back into the SQLite DB.

Expects filenames matching the pattern: quadrant_X_Y_generation.png

Usage:
    python -m sprite_nyc.e2e_generation.import_quadrants \
        --generation-dir generations/manhattan/ \
        --input-dir edited_quadrants/
"""

from __future__ import annotations

import io
import re
import sqlite3
from pathlib import Path

import click
from PIL import Image


FILENAME_PATTERN = re.compile(r"quadrant_(-?\d+)_(-?\d+)_(generation|render)\.png")


@click.command()
@click.option("--generation-dir", required=True)
@click.option("--input-dir", required=True, help="Directory with edited PNGs")
@click.option("--dry-run", is_flag=True, help="Show what would be imported")
def main(generation_dir: str, input_dir: str, dry_run: bool) -> None:
    """Import edited quadrant PNGs back into the database."""
    gd = Path(generation_dir)
    id = Path(input_dir)
    db_path = gd / "quadrants.db"

    if not db_path.exists():
        raise click.ClickException(f"No database at {db_path}")

    files = sorted(id.glob("quadrant_*_*_*.png"))
    if not files:
        print(f"No matching files in {id}")
        return

    conn = sqlite3.connect(str(db_path))
    imported = 0

    for f in files:
        match = FILENAME_PATTERN.match(f.name)
        if not match:
            print(f"  Skipping {f.name} (doesn't match pattern)")
            continue

        x = int(match.group(1))
        y = int(match.group(2))
        col_name = match.group(3)

        if dry_run:
            print(f"  Would import {f.name} → ({x}, {y}) {col_name}")
            imported += 1
            continue

        img = Image.open(f).convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        blob = buf.getvalue()

        if col_name == "generation":
            conn.execute(
                "UPDATE quadrants SET generation = ?, is_generated = 1 WHERE x = ? AND y = ?",
                (blob, x, y),
            )
        else:
            conn.execute(
                "UPDATE quadrants SET render = ? WHERE x = ? AND y = ?",
                (blob, x, y),
            )
        imported += 1
        print(f"  Imported {f.name} → ({x}, {y})")

    if not dry_run:
        conn.commit()
    conn.close()

    verb = "Would import" if dry_run else "Imported"
    print(f"\n{verb} {imported} images")


if __name__ == "__main__":
    main()
