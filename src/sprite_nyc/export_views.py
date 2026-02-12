"""
Export isometric views by launching the web renderer and capturing screenshots.

Usage:
    python -m sprite_nyc.export_views --config view.json --output-dir output/
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

import click
from playwright.async_api import async_playwright


DEFAULT_PORT = 3000


async def _capture(
    config_path: str,
    output_dir: str,
    api_key: str,
    port: int,
    headed: bool,
) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    # Read config to know canvas size
    with open(config_path) as f:
        cfg = json.load(f)

    width = cfg["width"]
    height = cfg["height"]

    async with async_playwright() as p:
        # Use headed mode or headless with GPU enabled
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

        # Listen for console messages for debugging
        page.on("console", lambda msg: print(f"  [browser] {msg.text}"))

        # Navigate to the dev server
        config_rel = os.path.relpath(config_path).replace("\\", "/")
        url = f"http://localhost:{port}/?key={api_key}&config=/{config_rel}"
        print(f"Navigating to {url}")
        await page.goto(url, wait_until="networkidle")

        # Give the page a moment to start the render loop
        await page.wait_for_timeout(2000)

        # Wait for tiles to settle — with a timeout
        print("Waiting for tiles to load…")
        try:
            await page.evaluate(
                """() => {
                    return new Promise((resolve, reject) => {
                        const timeout = setTimeout(() => reject(new Error('Tiles timeout after 60s')), 60000);
                        window.waitForTilesReady(30).then(() => {
                            clearTimeout(timeout);
                            resolve();
                        });
                    });
                }""",
            )
        except Exception as e:
            print(f"Warning: {e}")
            print("Continuing with capture anyway…")

        # Extra wait for rendering to settle
        await page.wait_for_timeout(2000)

        # Check tile status
        status = await page.evaluate("""() => {
            return {
                visible: window.tiles?.visibleTiles?.size ?? 0,
                active: window.tiles?.activeTiles?.size ?? 0,
            };
        }""")
        print(f"Tile status: {status}")

        # Capture render
        render_data = await page.evaluate("() => window.exportPNG()")
        _save_data_url(render_data, output / "render.png")
        print(f"Saved {output / 'render.png'}")

        await page.wait_for_timeout(1000)
        await browser.close()


def _save_data_url(data_url: str, path: Path) -> None:
    """Save a data:image/png;base64,... string to a file."""
    header, encoded = data_url.split(",", 1)
    path.write_bytes(base64.b64decode(encoded))


@click.command()
@click.option("--config", default="view.json", help="Path to view.json")
@click.option("--output-dir", default="output", help="Output directory")
@click.option("--api-key", envvar="GOOGLE_MAPS_API_KEY", required=True, help="Google Maps API key")
@click.option("--port", default=DEFAULT_PORT, help="Dev server port")
@click.option("--headed", is_flag=True, help="Run browser in headed mode for debugging")
def main(config: str, output_dir: str, api_key: str, port: int, headed: bool) -> None:
    """Capture isometric view screenshots via the web renderer."""
    asyncio.run(_capture(config, output_dir, api_key, port, headed))


if __name__ == "__main__":
    main()
