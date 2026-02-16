"""
Populate the quadrants DB with 3D renders using Playwright.

Reads quadrants.db, creates a temporary view.json for each quadrant
that lacks a render, and captures renders via the web renderer.
Uses a single Playwright browser session for efficiency.

Usage:
    python -m sprite_nyc.e2e_generation.populate_renders \
        --generation-dir generations/test/ \
        --api-key <google-maps-key>
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import sqlite3
from pathlib import Path

import click
from playwright.async_api import async_playwright


DEFAULT_PORT = 3000


def _get_quadrants_without_renders(db_path: Path) -> list[dict]:
    """Return quadrants that have no render blob."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT id, lat, lng, x, y FROM quadrants WHERE render IS NULL ORDER BY x, y"
    )
    rows = [
        {"id": r[0], "lat": r[1], "lng": r[2], "x": r[3], "y": r[4]}
        for r in cursor
    ]
    conn.close()
    return rows


def _save_render_to_db(db_path: Path, x: int, y: int, png_bytes: bytes) -> None:
    """Save render PNG bytes to the DB."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE quadrants SET render = ? WHERE x = ? AND y = ?",
        (png_bytes, x, y),
    )
    conn.commit()
    conn.close()


async def _populate(
    generation_dir: Path,
    api_key: str,
    port: int,
    headed: bool,
) -> None:
    config_path = generation_dir / "generation_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"No generation_config.json in {generation_dir}")

    with open(config_path) as f:
        config = json.load(f)

    db_path = generation_dir / "quadrants.db"
    if not db_path.exists():
        raise FileNotFoundError(f"No quadrants.db in {generation_dir} — run seed_tiles first")

    quadrants = _get_quadrants_without_renders(db_path)
    if not quadrants:
        print("All quadrants already have renders.")
        return

    total = len(quadrants)
    print(f"Populating renders for {total} quadrants")

    width = config["width"]
    height = config["height"]

    # Temp directory for view configs
    tmp_dir = generation_dir / "_tmp_configs"
    tmp_dir.mkdir(exist_ok=True)

    async with async_playwright() as p:
        launch_args = [
            "--use-gl=angle",
            "--use-angle=default",
            "--enable-webgl",
            "--ignore-gpu-blocklist",
        ]
        browser = await p.chromium.launch(
            headless=not headed,
            args=launch_args,
        )
        page = await browser.new_page(viewport={"width": width, "height": height})
        page.on("console", lambda msg: print(f"  [browser] {msg.text}"))

        for i, q in enumerate(quadrants):
            x, y = q["x"], q["y"]
            print(f"\n[{i + 1}/{total}] Rendering quadrant ({x}, {y})…")

            # Write temp view.json for this quadrant
            tile_cfg = {
                **config,
                "center": {"lat": q["lat"], "lng": q["lng"]},
            }
            # Remove bounds from tile config (not needed for rendering)
            tile_cfg.pop("bounds", None)

            cfg_path = tmp_dir / f"q_{x}_{y}.json"
            with open(cfg_path, "w") as f:
                json.dump(tile_cfg, f, indent=2)

            # Navigate to web renderer
            import os
            config_rel = os.path.relpath(cfg_path).replace("\\", "/")
            url = f"http://localhost:{port}/?key={api_key}&config=/{config_rel}"
            await page.goto(url, wait_until="networkidle")

            # Wait for render loop to start
            await page.wait_for_timeout(2000)

            # Wait for tiles to load
            try:
                await page.evaluate(
                    """() => {
                        return new Promise((resolve, reject) => {
                            const timeout = setTimeout(
                                () => reject(new Error('Tiles timeout after 60s')),
                                60000
                            );
                            window.waitForTilesReady(30).then(() => {
                                clearTimeout(timeout);
                                resolve();
                            });
                        });
                    }"""
                )
            except Exception as e:
                print(f"  Warning: {e}")
                print("  Continuing with capture anyway…")

            # Extra settle time
            await page.wait_for_timeout(2000)

            # Capture render
            render_data = await page.evaluate("() => window.exportPNG()")
            header, encoded = render_data.split(",", 1)
            png_bytes = base64.b64decode(encoded)

            # Save to DB
            _save_render_to_db(db_path, x, y, png_bytes)
            print(f"  Saved render for ({x}, {y}) — {len(png_bytes)} bytes")

        await browser.close()

    # Cleanup temp configs
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\nDone — populated renders for {total} quadrants")


@click.command()
@click.option("--generation-dir", required=True, help="Generation directory with config + DB")
@click.option(
    "--api-key",
    envvar="GOOGLE_MAPS_API_KEY",
    required=True,
    help="Google Maps API key",
)
@click.option("--port", default=DEFAULT_PORT, help="Web renderer dev server port")
@click.option("--headed", is_flag=True, help="Run browser in headed mode for debugging")
def main(generation_dir: str, api_key: str, port: int, headed: bool) -> None:
    """Populate quadrant renders via the web renderer."""
    asyncio.run(_populate(Path(generation_dir), api_key, port, headed))


if __name__ == "__main__":
    main()
