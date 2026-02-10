"""
Visualize generation bounds on a web preview.

Renders a simple HTML page showing the bounding box overlaid on
a map-like grid to help plan generation regions.

Usage:
    python -m sprite_nyc.e2e_generation.visualize_bounds \
        --generation-dir generations/manhattan/ \
        --top-left "40.73,-74.01" \
        --bottom-right "40.70,-73.99"
"""

from __future__ import annotations

import json
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import click


DEFAULT_PORT = 8081


def load_quadrants_for_viz(db_path: Path) -> list[dict]:
    """Load quadrant positions and status for visualization."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT x, y, lat, lng, is_generated FROM quadrants ORDER BY y, x"
    )
    quads = []
    for row in cursor:
        quads.append({
            "x": row[0], "y": row[1],
            "lat": row[2], "lng": row[3],
            "is_generated": bool(row[4]),
        })
    conn.close()
    return quads


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Bounds Visualizer</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: system-ui; background: #1a1a2e; color: #eee; padding: 24px; }
  h1 { font-size: 18px; margin-bottom: 16px; }
  .info { font-size: 13px; color: #aaa; margin-bottom: 16px; }
  canvas { border: 1px solid #333; border-radius: 4px; }
  .legend { margin-top: 12px; font-size: 12px; display: flex; gap: 16px; }
  .legend span { display: inline-flex; align-items: center; gap: 4px; }
  .legend .swatch { width: 12px; height: 12px; border-radius: 2px; display: inline-block; }
</style>
</head>
<body>
<h1>Generation Bounds Visualizer</h1>
<div class="info" id="info">Loading…</div>
<canvas id="canvas" width="2000" height="1200"></canvas>
<div class="legend">
  <span><span class="swatch" style="background:#2d6a4f"></span> Generated</span>
  <span><span class="swatch" style="background:#1a1a2e;border:1px solid #444"></span> Empty</span>
  <span><span class="swatch" style="background:transparent;border:2px solid #e94560"></span> Selection bounds</span>
</div>
<script>
const CONFIG = __CONFIG__;

async function main() {
  const resp = await fetch('/api/quadrants');
  const quads = await resp.json();

  const canvas = document.getElementById('canvas');
  const ctx = canvas.getContext('2d');

  if (!quads.length) {
    document.getElementById('info').textContent = 'No quadrants in DB';
    return;
  }

  const xs = quads.map(q => q.x);
  const ys = quads.map(q => q.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const cols = maxX - minX + 1;
  const rows = maxY - minY + 1;

  const cellSize = Math.min(
    Math.floor((canvas.width - 40) / cols),
    Math.floor((canvas.height - 40) / rows),
    24
  );

  const offsetX = 20, offsetY = 20;

  // Draw grid
  const lookup = {};
  quads.forEach(q => { lookup[`${q.x},${q.y}`] = q; });

  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      const q = lookup[`${x},${y}`];
      const px = offsetX + (x - minX) * cellSize;
      const py = offsetY + (y - minY) * cellSize;

      if (q) {
        ctx.fillStyle = q.is_generated ? '#2d6a4f' : '#1a1a2e';
        ctx.fillRect(px, py, cellSize - 1, cellSize - 1);
        ctx.strokeStyle = '#333';
        ctx.strokeRect(px, py, cellSize - 1, cellSize - 1);
      }
    }
  }

  // Draw bounds rectangle if specified
  if (CONFIG.tl && CONFIG.br) {
    // Convert lat/lng bounds to x,y grid coordinates
    // Find quadrants closest to the corners
    const tlQuad = findClosest(quads, CONFIG.tl[0], CONFIG.tl[1]);
    const brQuad = findClosest(quads, CONFIG.br[0], CONFIG.br[1]);

    if (tlQuad && brQuad) {
      const bx0 = offsetX + (tlQuad.x - minX) * cellSize;
      const by0 = offsetY + (tlQuad.y - minY) * cellSize;
      const bx1 = offsetX + (brQuad.x - minX + 1) * cellSize;
      const by1 = offsetY + (brQuad.y - minY + 1) * cellSize;

      ctx.strokeStyle = '#e94560';
      ctx.lineWidth = 2;
      ctx.strokeRect(bx0, by0, bx1 - bx0, by1 - by0);
    }
  }

  const genCount = quads.filter(q => q.is_generated).length;
  document.getElementById('info').textContent =
    `Grid: ${cols}×${rows} (${quads.length} quadrants, ${genCount} generated)` +
    (CONFIG.tl ? ` | Bounds: ${CONFIG.tl} → ${CONFIG.br}` : '');
}

function findClosest(quads, lat, lng) {
  let best = null, bestDist = Infinity;
  for (const q of quads) {
    const d = Math.abs(q.lat - lat) + Math.abs(q.lng - lng);
    if (d < bestDist) { bestDist = d; best = q; }
  }
  return best;
}

main();
</script>
</body>
</html>"""


class BoundsHandler(BaseHTTPRequestHandler):
    generation_dir: Path = Path(".")
    config: dict = {}

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            html = HTML_TEMPLATE.replace("__CONFIG__", json.dumps(self.config))
            self._respond(200, "text/html", html.encode())
        elif parsed.path == "/api/quadrants":
            db_path = self.generation_dir / "quadrants.db"
            data = load_quadrants_for_viz(db_path)
            self._respond(200, "application/json", json.dumps(data).encode())
        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def parse_coord(s: str) -> tuple[float, float]:
    parts = s.split(",")
    return float(parts[0].strip()), float(parts[1].strip())


@click.command()
@click.option("--generation-dir", required=True)
@click.option("--top-left", default=None, help="Top-left corner as 'lat,lng'")
@click.option("--bottom-right", default=None, help="Bottom-right corner as 'lat,lng'")
@click.option("--port", default=DEFAULT_PORT, type=int)
def main(generation_dir: str, top_left: str | None, bottom_right: str | None, port: int) -> None:
    """Visualize generation bounds."""
    gd = Path(generation_dir)

    config = {}
    if top_left and bottom_right:
        config["tl"] = list(parse_coord(top_left))
        config["br"] = list(parse_coord(bottom_right))

    BoundsHandler.generation_dir = gd
    BoundsHandler.config = config

    server = HTTPServer(("0.0.0.0", port), BoundsHandler)
    print(f"Bounds visualizer at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
