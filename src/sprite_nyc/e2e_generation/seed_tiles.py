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


def calculate_step_degrees(config: dict) -> tuple[float, float]:
    """
    Calculate the lat/lng step between adjacent quadrants.

    Each quadrant is one view-sized tile. With the isometric projection,
    the ground footprint depends on view_height_meters and the
    camera angles.
    """
    vh = config["view_height_meters"]
    aspect = config["width"] / config["height"]
    el = abs(config.get("elevation", -45))

    sin_el = math.sin(math.radians(el))

    # Ground extent in meters
    north_m = vh / sin_el
    east_m = vh * aspect / sin_el

    # Step = half the extent (50% overlap)
    step_north = north_m / 2
    step_east = east_m / 2

    center_lat = config["center"]["lat"]
    step_lat = step_north / meters_per_degree_lat()
    step_lng = step_east / meters_per_degree_lng(center_lat)

    return step_lat, step_lng


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

    step_lat, step_lng = calculate_step_degrees(config)

    count = 0
    cursor = conn.cursor()

    # Calculate x,y grid range
    # x increases east (lng increases), y increases south (lat decreases)
    min_x = math.floor((min_lng - seed_lng) / step_lng)
    max_x = math.ceil((max_lng - seed_lng) / step_lng)
    min_y = math.floor((seed_lat - max_lat) / step_lat)  # note: inverted
    max_y = math.ceil((seed_lat - min_lat) / step_lat)

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            qid = quadrant_id(x, y)
            lat = seed_lat - y * step_lat  # y increases southward
            lng = seed_lng + x * step_lng

            # Check bounds
            if lat < min_lat or lat > max_lat:
                continue
            if lng < min_lng or lng > max_lng:
                continue

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
