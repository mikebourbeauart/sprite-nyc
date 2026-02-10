"""
Web application for viewing and managing quadrant generations.

Displays the quadrant grid from the SQLite DB, allows clicking to
select quadrants for generation, and shows toast notifications for
success/failure.

Usage:
    python -m sprite_nyc.e2e_generation.view_generations \
        --generation-dir generations/manhattan/
"""

from __future__ import annotations

import base64
import io
import json
import sqlite3
import threading
from pathlib import Path

import click
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


DEFAULT_PORT = 8080


def get_db_path(generation_dir: Path) -> Path:
    return generation_dir / "quadrants.db"


def load_quadrants(db_path: Path) -> list[dict]:
    """Load all quadrants with metadata (no image blobs)."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT id, lat, lng, x, y, is_generated, notes FROM quadrants ORDER BY y, x"
    )
    quadrants = []
    for row in cursor:
        quadrants.append({
            "id": row[0],
            "lat": row[1],
            "lng": row[2],
            "x": row[3],
            "y": row[4],
            "is_generated": bool(row[5]),
            "notes": row[6],
        })
    conn.close()
    return quadrants


def get_quadrant_image(db_path: Path, x: int, y: int, img_type: str = "generation") -> bytes | None:
    """Get a quadrant's image as PNG bytes."""
    col = "generation" if img_type == "generation" else "render"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        f"SELECT {col} FROM quadrants WHERE x = ? AND y = ?", (x, y)
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Sprite NYC — Generation Viewer</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee; }
  header { padding: 16px 24px; background: #16213e; border-bottom: 1px solid #0f3460; }
  header h1 { font-size: 20px; font-weight: 600; }
  .controls { padding: 12px 24px; background: #0f3460; display: flex; gap: 12px; align-items: center; }
  .controls button {
    padding: 8px 16px; border: none; border-radius: 6px;
    background: #e94560; color: white; cursor: pointer; font-size: 14px;
  }
  .controls button:disabled { opacity: 0.5; cursor: not-allowed; }
  .controls button.secondary { background: #533483; }
  .controls .status { margin-left: auto; font-size: 13px; color: #aaa; }

  .grid-container { padding: 24px; overflow: auto; }
  .grid {
    display: inline-grid; gap: 2px;
    background: #0f3460; padding: 2px; border-radius: 4px;
  }
  .cell {
    width: 64px; height: 64px; cursor: pointer;
    border: 2px solid transparent; border-radius: 2px;
    background-size: cover; background-position: center;
    position: relative; transition: border-color 0.15s;
  }
  .cell.empty { background-color: #1a1a2e; }
  .cell.generated { background-color: #2d6a4f; }
  .cell.selected { border-color: #e94560; }
  .cell:hover { border-color: #f8a; }
  .cell .coords {
    position: absolute; bottom: 2px; left: 2px;
    font-size: 9px; color: rgba(255,255,255,0.6);
    pointer-events: none;
  }

  .toast {
    position: fixed; bottom: 24px; right: 24px;
    padding: 12px 20px; border-radius: 8px;
    font-size: 14px; opacity: 0; transition: opacity 0.3s;
    z-index: 100;
  }
  .toast.show { opacity: 1; }
  .toast.success { background: #2d6a4f; color: white; }
  .toast.error { background: #e94560; color: white; }
</style>
</head>
<body>
<header>
  <h1>Sprite NYC — Generation Viewer</h1>
</header>
<div class="controls">
  <button id="generateBtn" onclick="generate()" disabled>Generate Selected</button>
  <button class="secondary" onclick="clearSelection()">Clear Selection</button>
  <button class="secondary" onclick="refresh()">Refresh</button>
  <span class="status" id="statusText">Loading…</span>
</div>
<div class="grid-container">
  <div class="grid" id="grid"></div>
</div>
<div class="toast" id="toast"></div>

<script>
let quadrants = [];
let selected = new Set();
let generating = false;

async function loadQuadrants() {
  const resp = await fetch('/api/quadrants');
  quadrants = await resp.json();
  renderGrid();
}

function renderGrid() {
  const grid = document.getElementById('grid');
  if (!quadrants.length) { grid.innerHTML = '<p>No quadrants</p>'; return; }

  const xs = quadrants.map(q => q.x);
  const ys = quadrants.map(q => q.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const cols = maxX - minX + 1;

  grid.style.gridTemplateColumns = `repeat(${cols}, 64px)`;
  grid.innerHTML = '';

  // Create lookup
  const lookup = {};
  quadrants.forEach(q => { lookup[`${q.x},${q.y}`] = q; });

  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      const key = `${x},${y}`;
      const q = lookup[key];
      const cell = document.createElement('div');
      cell.className = 'cell';

      if (q) {
        cell.className += q.is_generated ? ' generated' : ' empty';
        if (selected.has(key)) cell.className += ' selected';
        if (q.is_generated) {
          cell.style.backgroundImage = `url(/api/image?x=${x}&y=${y}&type=generation&_t=${Date.now()})`;
        }
        cell.onclick = () => toggleSelect(key);
        cell.innerHTML = `<span class="coords">${x},${y}</span>`;
      } else {
        cell.style.background = '#111';
      }

      grid.appendChild(cell);
    }
  }

  const genCount = quadrants.filter(q => q.is_generated).length;
  document.getElementById('statusText').textContent =
    `${genCount}/${quadrants.length} generated | ${selected.size} selected`;
  document.getElementById('generateBtn').disabled = selected.size === 0 || generating;
}

function toggleSelect(key) {
  if (generating) return;
  if (selected.has(key)) selected.delete(key);
  else selected.add(key);
  renderGrid();
}

function clearSelection() {
  selected.clear();
  renderGrid();
}

async function generate() {
  if (generating || selected.size === 0) return;
  generating = true;
  renderGrid();

  const coords = [...selected].map(k => k.split(',').map(Number));
  try {
    const resp = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quadrants: coords }),
    });
    const result = await resp.json();
    if (result.error) {
      showToast(result.error, 'error');
    } else {
      showToast(`Generated ${result.count} quadrant(s)`, 'success');
      selected.clear();
    }
  } catch (e) {
    showToast(`Error: ${e.message}`, 'error');
  }
  generating = false;
  await loadQuadrants();
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => { t.className = 'toast'; }, 4000);
}

function refresh() { loadQuadrants(); }

// Auto-refresh every 10s
setInterval(loadQuadrants, 10000);
loadQuadrants();
</script>
</body>
</html>"""


class ViewerHandler(BaseHTTPRequestHandler):
    generation_dir: Path = Path(".")
    api_key: str = ""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._respond(200, "text/html", HTML_PAGE.encode())
        elif path == "/api/quadrants":
            db_path = get_db_path(self.generation_dir)
            data = load_quadrants(db_path)
            self._respond(200, "application/json", json.dumps(data).encode())
        elif path == "/api/image":
            x = int(params.get("x", [0])[0])
            y = int(params.get("y", [0])[0])
            img_type = params.get("type", ["generation"])[0]
            db_path = get_db_path(self.generation_dir)
            img_data = get_quadrant_image(db_path, x, y, img_type)
            if img_data:
                self._respond(200, "image/png", img_data)
            else:
                self._respond(404, "text/plain", b"Not found")
        else:
            self._respond(404, "text/plain", b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/generate":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            coords = [tuple(c) for c in body.get("quadrants", [])]

            if not coords:
                self._respond(400, "application/json",
                              json.dumps({"error": "No quadrants"}).encode())
                return

            try:
                from sprite_nyc.e2e_generation.generate_omni import (
                    run_generation_for_quadrants,
                )
                results = run_generation_for_quadrants(
                    self.generation_dir, coords, self.api_key
                )
                self._respond(200, "application/json",
                              json.dumps({"count": len(results)}).encode())
            except Exception as e:
                self._respond(500, "application/json",
                              json.dumps({"error": str(e)}).encode())
        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # quiet logging


@click.command()
@click.option("--generation-dir", required=True, help="Generation directory")
@click.option("--port", default=DEFAULT_PORT, type=int)
@click.option("--api-key", envvar="OXEN_INFILL_V02_API_KEY", default="")
def main(generation_dir: str, port: int, api_key: str) -> None:
    """Launch the generation viewer web app."""
    gd = Path(generation_dir)
    if not (gd / "quadrants.db").exists():
        raise click.ClickException(f"No quadrants.db in {gd}")

    ViewerHandler.generation_dir = gd
    ViewerHandler.api_key = api_key

    server = HTTPServer(("0.0.0.0", port), ViewerHandler)
    print(f"Viewer running at http://localhost:{port}")
    print(f"Database: {gd / 'quadrants.db'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
