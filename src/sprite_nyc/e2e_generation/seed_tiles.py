"""
Seed the SQLite database with empty quadrant records.

Reads a generation_config.json and calculates all quadrant positions
within the specified bounds. Populates the DB with empty records ready
for generation.

Usage:
    python -m sprite_nyc.e2e_generation.seed_tiles \
        --generation-dir generations/manhattan/
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

import click


EARTH_RADIUS_M = 6_378_137.0

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS quadrants (
    id TEXT PRIMARY KEY,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    render BLOB,
    generation BLOB,
    is_generated BOOLEAN DEFAULT 0,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_quadrants_xy ON quadrants(x, y);
CREATE INDEX IF NOT EXISTS idx_quadrants_latlng ON quadrants(lat, lng);
"""


def meters_per_degree_lat() -> float:
    return (math.pi / 180) * EARTH_RADIUS_M


def meters_per_degree_lng(lat_deg: float) -> float:
    return (math.pi / 180) * EARTH_RADIUS_M * math.cos(math.radians(lat_deg))


def quadrant_id(x: int, y: int) -> str:
    """Generate a stable hash ID for a quadrant position."""
    raw = f"q_{x}_{y}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def tile_step_vectors(
    config: dict,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """
    Return camera-aligned step vectors for non-overlapping quadrant tiling.

    The orthographic camera is rotated by azimuth and tilted by
    elevation.  Steps move by the full tile width/height along the
    camera's own axes so adjacent quadrants are non-overlapping.

    Returns
    -------
    col_step : (east_m, north_m)
        Ground shift for one column right in the image.
    row_step : (east_m, north_m)
        Ground shift for one row down in the image.
    """
    vh = config["view_height_meters"]
    aspect = config["width"] / config["height"]
    el_rad = math.radians(abs(config.get("elevation", -45)))
    az_rad = math.radians(config.get("azimuth", -15))

    full_w = vh * aspect
    full_h = vh

    # Column step along camera-right (roughly westward for az=-15deg)
    col_step_east = -full_w * math.cos(az_rad)
    col_step_north = full_w * math.sin(az_rad)

    # Row step along camera-down (stretched by 1/sin(elevation))
    ground_h = full_h / math.sin(el_rad)
    row_step_east = ground_h * math.sin(az_rad)
    row_step_north = ground_h * math.cos(az_rad)

    return (col_step_east, col_step_north), (row_step_east, row_step_north)


def meters_to_grid(
    east_m: float,
    north_m: float,
    col_step: tuple[float, float],
    row_step: tuple[float, float],
) -> tuple[float, float]:
    """Convert (east, north) meter offset to fractional grid (x, y)."""
    det = col_step[0] * row_step[1] - col_step[1] * row_step[0]
    x = (east_m * row_step[1] - north_m * row_step[0]) / det
    y = (north_m * col_step[0] - east_m * col_step[1]) / det
    return x, y


def seed_database(generation_dir: Path) -> int:
    """
    Read generation_config.json, calculate quadrant positions, and
    populate the SQLite database. Returns the number of quadrants created.
    """
    config_path = generation_dir / "generation_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"No generation_config.json in {generation_dir}")

    with open(config_path) as f:
        config = json.load(f)

    db_path = generation_dir / "quadrants.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DB_SCHEMA)

    seed_lat = config["center"]["lat"]
    seed_lng = config["center"]["lng"]

    # Bounds: 4 corners [top_left, top_right, bottom_left, bottom_right]
    bounds = config.get("bounds")
    if bounds:
        min_lat = min(b["lat"] for b in bounds)
        max_lat = max(b["lat"] for b in bounds)
        min_lng = min(b["lng"] for b in bounds)
        max_lng = max(b["lng"] for b in bounds)
    else:
        # Default: small area around seed
        min_lat = seed_lat - 0.01
        max_lat = seed_lat + 0.01
        min_lng = seed_lng - 0.01
        max_lng = seed_lng + 0.01

    col_step, row_step = tile_step_vectors(config)
    m_lat = meters_per_degree_lat()
    m_lng = meters_per_degree_lng(seed_lat)

    # Convert geographic bounds corners to grid coordinates
    corner_offsets = [
        ((min_lng - seed_lng) * m_lng, (min_lat - seed_lat) * m_lat),
        ((max_lng - seed_lng) * m_lng, (min_lat - seed_lat) * m_lat),
        ((min_lng - seed_lng) * m_lng, (max_lat - seed_lat) * m_lat),
        ((max_lng - seed_lng) * m_lng, (max_lat - seed_lat) * m_lat),
    ]
    grid_xs, grid_ys = [], []
    for east, north in corner_offsets:
        gx, gy = meters_to_grid(east, north, col_step, row_step)
        grid_xs.append(gx)
        grid_ys.append(gy)

    min_x = math.floor(min(grid_xs))
    max_x = math.ceil(max(grid_xs))
    min_y = math.floor(min(grid_ys))
    max_y = math.ceil(max(grid_ys))

    count = 0
    cursor = conn.cursor()

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            # Compute lat/lng from camera-aligned grid position
            east_m = x * col_step[0] + y * row_step[0]
            north_m = x * col_step[1] + y * row_step[1]
            lat = seed_lat + north_m / m_lat
            lng = seed_lng + east_m / m_lng

            # Check bounds
            if lat < min_lat or lat > max_lat:
                continue
            if lng < min_lng or lng > max_lng:
                continue

            qid = quadrant_id(x, y)
            cursor.execute(
                """
                INSERT OR IGNORE INTO quadrants (id, lat, lng, x, y)
                VALUES (?, ?, ?, ?, ?)
                """,
                (qid, lat, lng, x, y),
            )
            count += cursor.rowcount

    conn.commit()
    conn.close()

    return count


@click.command()
@click.option("--generation-dir", required=True, help="Generation directory with config")
def main(generation_dir: str) -> None:
    """Seed the quadrant database from generation config."""
    gd = Path(generation_dir)
    count = seed_database(gd)
    print(f"Seeded {count} quadrants in {gd / 'quadrants.db'}")


if __name__ == "__main__":
    main()
