"""
Batch-export isometric renders for a list of positions or a grid.

Reuses a single Playwright browser session to efficiently capture many tiles,
avoiding the overhead of relaunching Chromium per tile.

Grid mode outputs to tile_R_C/ directories with view.json + render.png,
matching the plan_tiles.py convention. Landmarks mode outputs flat files.

Usage (grid):
    python -m sprite_nyc.batch_export \
        --config view.json \
        --rows 3 --cols 3 \
        --output-dir output/test_grid \
        --api-key <key>

Usage (landmarks):
    python -m sprite_nyc.batch_export \
        --config view.json \
        --landmarks landmarks.json \
        --output-dir output/training_renders \
        --api-key <key>
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import click
from playwright.async_api import async_playwright

from sprite_nyc.export_views import _save_data_url
from sprite_nyc.plan_tiles import plan_tile_grid


def _build_tile_list(
    cfg: dict,
    landmarks_path: str | None,
    rows: int,
    cols: int,
) -> list[tuple[str, dict]]:
    """Return a list of (name, tile_config) tuples."""
    if landmarks_path:
        with open(landmarks_path) as f:
            landmarks = json.load(f)
        tiles = []
        for lm in landmarks:
            tile_cfg = {**cfg, "center": {"lat": lm["lat"], "lng": lm["lng"]}}
            tiles.append((lm["name"], tile_cfg))
        return tiles

    center_lat = cfg["center"]["lat"]
    center_lng = cfg["center"]["lng"]
    grid = plan_tile_grid(center_lat, center_lng, rows, cols, cfg)
    return [(f"tile_{t['row']}_{t['col']}", t["config"]) for t in grid]


async def _batch_capture(
    config_path: str,
    landmarks_path: str | None,
    rows: int,
    cols: int,
    output_dir: str,
    api_key: str,
    port: int,
    headed: bool,
) -> None:
    with open(config_path) as f:
        cfg = json.load(f)

    width = cfg["width"]
    height = cfg["height"]
    is_grid = landmarks_path is None

    tiles = _build_tile_list(cfg, landmarks_path, rows, cols)
    total = len(tiles)
    print(f"Planned {total} tiles")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    if is_grid:
        # Grid mode: tile_R_C/ directories with view.json
        tile_configs: list[tuple[str, Path]] = []
        manifest = []
        for name, tile_cfg in tiles:
            tile_dir = output / name
            tile_dir.mkdir(parents=True, exist_ok=True)
            cfg_path = tile_dir / "view.json"
            with open(cfg_path, "w") as f:
                json.dump(tile_cfg, f, indent=2)
            # Parse row/col from name
            parts = name.split("_")
            r, c = int(parts[1]), int(parts[2])
            manifest.append({
                "row": r,
                "col": c,
                "dir": str(tile_dir),
                "center": tile_cfg["center"],
            })
            tile_configs.append((name, cfg_path))

        # Write manifest for validate_plan.py
        with open(output / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)
    else:
        # Landmarks mode: flat renders/ directory
        renders_dir = output / "renders"
        renders_dir.mkdir(parents=True, exist_ok=True)
        tile_configs = []
        configs_dir = output / "_configs"
        configs_dir.mkdir(parents=True, exist_ok=True)
        for name, tile_cfg in tiles:
            cfg_path = configs_dir / f"{name}.json"
            with open(cfg_path, "w") as f:
                json.dump(tile_cfg, f, indent=2)
            tile_configs.append((name, cfg_path))

    # Launch browser once
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

        for i, (name, cfg_path) in enumerate(tile_configs):
            print(f"\n[{i + 1}/{total}] Capturing {name}…")

            # Navigate to web renderer with this tile's config
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

            # Log tile status
            status = await page.evaluate("""() => {
                return {
                    visible: window.tiles?.visibleTiles?.size ?? 0,
                    active: window.tiles?.activeTiles?.size ?? 0,
                };
            }""")
            print(f"  Tile status: {status}")

            # Capture render
            render_data = await page.evaluate("() => window.exportPNG()")
            if is_grid:
                render_path = output / name / "render.png"
            else:
                render_path = output / "renders" / f"{name}.png"
            _save_data_url(render_data, render_path)
            print(f"  Saved {render_path}")

        await browser.close()

    print(f"\nDone — captured {total} tiles in {output}")


@click.command()
@click.option("--config", default="view.json", help="Path to base view.json")
@click.option("--landmarks", default=None, help="Path to landmarks JSON (overrides --rows/--cols)")
@click.option("--rows", type=int, default=3, help="Number of grid rows")
@click.option("--cols", type=int, default=3, help="Number of grid columns")
@click.option("--output-dir", default="output/batch", help="Output directory")
@click.option(
    "--api-key",
    envvar="GOOGLE_MAPS_API_KEY",
    required=True,
    help="Google Maps API key",
)
@click.option("--port", default=3000, help="Web renderer dev server port")
@click.option("--headed", is_flag=True, help="Run browser in headed mode for debugging")
def main(
    config: str,
    landmarks: str | None,
    rows: int,
    cols: int,
    output_dir: str,
    api_key: str,
    port: int,
    headed: bool,
) -> None:
    """Batch-export isometric renders across a grid or list of landmarks."""
    asyncio.run(
        _batch_capture(config, landmarks, rows, cols, output_dir, api_key, port, headed)
    )


if __name__ == "__main__":
    main()
