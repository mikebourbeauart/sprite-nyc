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

import json
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

import click


DEFAULT_PORT = 8080


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def get_db_path(generation_dir: Path) -> Path:
    return generation_dir / "quadrants.db"


def load_quadrants(db_path: Path) -> list[dict]:
    """Load all quadrants with metadata (no image blobs)."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT id, lat, lng, x, y, is_generated, notes, render IS NOT NULL FROM quadrants ORDER BY y, x"
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
            "has_render": bool(row[7]),
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


HTML_PAGE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Sprite NYC — Generation Viewer</title>
<style>
  :root {
    --tile-size: 160px;
    --bg-dark: #0d1117;
    --bg-panel: #161b22;
    --bg-tile: #1c2333;
    --border-color: #30363d;
    --red: #da3633;
    --purple: #8957e5;
    --green: #3fb950;
    --blue: #58a6ff;
    --orange: #d29922;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg-dark);
    color: var(--text-primary);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── Toolbar Rows ── */
  .toolbar-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    background: var(--bg-panel);
    border-bottom: 1px solid var(--border-color);
    flex-shrink: 0;
    flex-wrap: wrap;
  }
  .toolbar-row h1 {
    font-size: 16px;
    font-weight: 600;
    margin-right: 8px;
    white-space: nowrap;
  }
  .toolbar-row .sep {
    width: 1px;
    height: 22px;
    background: var(--border-color);
    margin: 0 2px;
    flex-shrink: 0;
  }
  .toolbar-row .spacer { flex: 1; }

  .tb-btn {
    padding: 4px 10px;
    border: 1px solid var(--border-color);
    border-radius: 5px;
    background: var(--bg-dark);
    color: var(--text-primary);
    font-size: 12px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    white-space: nowrap;
    line-height: 18px;
  }
  .tb-btn:hover { background: #21262d; border-color: #484f58; }
  .tb-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .tb-btn:disabled:hover { background: var(--bg-dark); border-color: var(--border-color); }
  .tb-btn.active {
    background: #238636;
    border-color: #2ea043;
    color: #fff;
    font-weight: 600;
  }
  .tb-btn.active:hover { background: #2ea043; }
  .tb-btn.primary {
    background: #238636;
    border-color: #2ea043;
    font-weight: 600;
  }
  .tb-btn.primary:hover { background: #2ea043; }
  .tb-btn.primary:disabled { background: #238636; border-color: #2ea043; }
  .tb-btn.danger {
    color: var(--red);
    border-color: var(--red);
  }
  .tb-btn.danger:hover { background: #da363322; }
  .tb-btn.orange {
    background: #d29922;
    border-color: #d29922;
    color: #fff;
    font-weight: 600;
  }
  .tb-btn.orange:hover { background: #e3a620; }
  .tb-btn.arrow {
    padding: 4px 6px;
    font-size: 14px;
    line-height: 16px;
  }

  /* Contextual row: always visible, selection-dependent buttons dim when nothing selected */

  /* ── Status Bar ── */
  .status-bar {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 6px 12px;
    background: var(--bg-panel);
    border-bottom: 1px solid var(--border-color);
    font-size: 11px;
    color: var(--text-secondary);
    flex-shrink: 0;
    font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
  }
  .status-item {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .status-dot.red { background: var(--red); }
  .status-dot.green { background: var(--green); }
  .status-dot.purple { background: var(--purple); }
  .status-dot.blue { background: var(--blue); }
  .status-dot.idle { background: var(--text-secondary); }

  /* ── Grid Viewport ── */
  .grid-viewport {
    flex: 1;
    overflow: hidden;
    position: relative;
    cursor: grab;
  }
  .grid-viewport.panning { cursor: grabbing; }
  .zoom-wrapper {
    transform-origin: 0 0;
    position: absolute;
    top: 0;
    left: 0;
    padding: 24px;
  }
  .grid {
    display: inline-grid;
    gap: 2px;
    background: #010409;
    padding: 2px;
    border-radius: 4px;
  }
  .zoom-indicator {
    position: absolute;
    bottom: 12px;
    left: 12px;
    font-size: 11px;
    color: var(--text-secondary);
    background: var(--bg-panel);
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid var(--border-color);
    pointer-events: none;
    z-index: 10;
  }

  /* ── Tile Cell ── */
  .cell {
    width: var(--tile-size);
    height: var(--tile-size);
    cursor: pointer;
    border: 2px solid transparent;
    border-radius: 3px;
    background-size: cover;
    background-position: center;
    background-color: var(--bg-tile);
    position: relative;
    transition: border-color 0.15s;
  }
  .cell.empty-slot {
    background: #010409;
    cursor: default;
  }

  /* Dim overlay for ungenerated renders */
  .cell.has-render::after {
    content: '';
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    border-radius: 1px;
    pointer-events: none;
  }
  .cell.generated::after { display: none; }

  /* Selected */
  .cell.selected {
    border-color: var(--red);
    box-shadow: inset 0 0 0 1px var(--red);
  }
  .cell.selected::after {
    content: '';
    position: absolute;
    inset: 0;
    background: rgba(218, 54, 51, 0.20);
    border-radius: 1px;
    pointer-events: none;
  }

  /* Queued */
  .cell.queued {
    border-color: #6e40a9;
    box-shadow: inset 0 0 0 1px #6e40a9;
  }
  .cell.queued::after {
    content: '';
    position: absolute;
    inset: 0;
    background: rgba(137, 87, 229, 0.15);
    border-radius: 1px;
    pointer-events: none;
  }

  /* Processing */
  .cell.processing {
    border-color: var(--purple);
    box-shadow: inset 0 0 0 1px var(--purple);
  }
  .cell.processing::after {
    content: '';
    position: absolute;
    inset: 0;
    background: rgba(137, 87, 229, 0.30);
    border-radius: 1px;
    pointer-events: none;
  }

  /* Spinner for processing */
  @keyframes spin { to { transform: rotate(360deg); } }
  .cell.processing::before {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 28px;
    height: 28px;
    margin: -14px 0 0 -14px;
    border: 3px solid rgba(137, 87, 229, 0.3);
    border-top-color: var(--purple);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    z-index: 2;
    pointer-events: none;
  }

  .cell:not(.empty-slot):not(.processing):not(.queued):hover {
    border-color: #484f58;
  }

  /* Coordinate label */
  .coord-label {
    position: absolute;
    top: 4px;
    left: 4px;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 5px;
    border-radius: 3px;
    pointer-events: none;
    z-index: 3;
    line-height: 16px;
    font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
  }
  .coord-label.green { background: rgba(63, 185, 80, 0.85); color: #fff; }
  .coord-label.blue  { background: rgba(88, 166, 255, 0.85); color: #fff; }
  .coord-label.red   { background: rgba(218, 54, 51, 0.85); color: #fff; }
  .coord-label.purple { background: rgba(137, 87, 229, 0.85); color: #fff; }

  /* ── Context Menu ── */
  .ctx-menu {
    position: fixed;
    background: var(--bg-panel);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 4px 0;
    min-width: 160px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    z-index: 2000;
    display: none;
  }
  .ctx-menu.visible { display: block; }
  .ctx-menu-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 14px;
    font-size: 13px;
    cursor: pointer;
    color: var(--text-primary);
  }
  .ctx-menu-item:hover { background: #21262d; }
  .ctx-menu-item .ctx-icon { width: 16px; text-align: center; flex-shrink: 0; }
  .ctx-menu-sep {
    height: 1px;
    background: var(--border-color);
    margin: 4px 0;
  }

  /* ── Debug Modal ── */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.7);
    z-index: 3000;
    display: none;
    align-items: center;
    justify-content: center;
  }
  .modal-overlay.visible { display: flex; }
  .modal-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    width: 900px;
    max-width: 95vw;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: 0 16px 48px rgba(0,0,0,0.6);
  }
  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-color);
  }
  .modal-header h2 { font-size: 16px; font-weight: 600; }
  .modal-close {
    background: none; border: none; color: var(--text-secondary);
    cursor: pointer; font-size: 22px; line-height: 1; padding: 4px;
  }
  .modal-close:hover { color: var(--text-primary); }
  .modal-body { padding: 20px; }

  .debug-section { margin-bottom: 20px; }
  .debug-section-title {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    color: var(--text-secondary);
    margin-bottom: 8px;
    letter-spacing: 0.5px;
  }

  .debug-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .debug-table td {
    padding: 5px 10px;
    border-bottom: 1px solid #21262d;
  }
  .debug-table td:first-child {
    color: var(--text-secondary);
    width: 120px;
    font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
    font-size: 12px;
  }
  .debug-table td:last-child {
    font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
    font-size: 12px;
  }

  .debug-images {
    display: flex;
    gap: 12px;
  }
  .debug-img-card {
    flex: 1;
    background: var(--bg-dark);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    overflow: hidden;
    text-align: center;
  }
  .debug-img-card .label {
    padding: 6px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    border-bottom: 1px solid var(--border-color);
  }
  .debug-img-card img {
    width: 100%;
    aspect-ratio: 1;
    object-fit: contain;
    cursor: pointer;
    background: #000;
  }
  .debug-img-card .placeholder {
    width: 100%;
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-secondary);
    font-size: 12px;
    background: #000;
  }

  .debug-neighbors {
    display: inline-grid;
    grid-template-columns: repeat(3, 64px);
    gap: 3px;
  }
  .debug-nb-cell {
    width: 64px;
    height: 64px;
    border-radius: 4px;
    background-size: cover;
    background-position: center;
    background-color: var(--bg-dark);
    border: 2px solid var(--border-color);
    position: relative;
  }
  .debug-nb-cell.center { border-color: var(--red); }
  .debug-nb-cell.generated { border-color: var(--green); }
  .debug-nb-cell.has-render { border-color: var(--blue); }
  .debug-nb-cell.missing { border-color: #21262d; opacity: 0.4; }
  .debug-nb-label {
    position: absolute;
    bottom: 2px;
    left: 2px;
    font-size: 8px;
    font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
    background: rgba(0,0,0,0.7);
    padding: 0 3px;
    border-radius: 2px;
    color: #fff;
  }

  .debug-config {
    background: var(--bg-dark);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 12px;
    font-size: 12px;
    font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
    color: var(--text-secondary);
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .debug-toggle {
    cursor: pointer;
    user-select: none;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .debug-toggle .arrow { transition: transform 0.15s; }
  .debug-toggle .arrow.open { transform: rotate(90deg); }

  /* ── Notifications ── */
  .notification-container {
    position: fixed;
    bottom: 20px;
    right: 20px;
    display: flex;
    flex-direction: column-reverse;
    gap: 8px;
    z-index: 1000;
    max-width: 380px;
  }
  .notification {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 12px 14px;
    background: #1c2333;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    border-left: 4px solid var(--text-secondary);
    font-size: 13px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    animation: slideIn 0.25s ease-out;
    position: relative;
    min-width: 280px;
  }
  @keyframes slideIn {
    from { opacity: 0; transform: translateX(40px); }
    to   { opacity: 1; transform: translateX(0); }
  }
  @keyframes fadeOut {
    from { opacity: 1; transform: translateX(0); }
    to   { opacity: 0; transform: translateX(40px); }
  }
  .notification.removing {
    animation: fadeOut 0.2s ease-in forwards;
  }
  .notification.success { border-left-color: var(--green); }
  .notification.error   { border-left-color: var(--red); }
  .notification.progress { border-left-color: var(--purple); }
  .notification.info     { border-left-color: var(--blue); }

  .notification .icon { font-size: 16px; flex-shrink: 0; margin-top: 1px; }
  .notification .body { flex: 1; }
  .notification .title { font-weight: 600; margin-bottom: 2px; }
  .notification .msg { color: var(--text-secondary); font-size: 12px; }
  .notification .close-btn {
    background: none; border: none; color: var(--text-secondary);
    cursor: pointer; font-size: 16px; padding: 0 2px; line-height: 1;
    flex-shrink: 0;
  }
  .notification .close-btn:hover { color: var(--text-primary); }
</style>
</head>
<body>

<!-- Toolbar Row 1: Tools -->
<div class="toolbar-row">
  <h1>Sprite NYC</h1>
  <div class="sep"></div>
  <button class="tb-btn active" id="toolSelect" onclick="setTool('select')">Select</button>
  <button class="tb-btn" id="toolFixWater" onclick="setTool('fixwater')">Fix Water</button>
  <button class="tb-btn" id="toolWaterFill" onclick="setTool('waterfill')">Water Fill</button>
  <button class="tb-btn" id="toolWaterSelect" onclick="setTool('waterselect')">Water Select</button>
</div>

<!-- Toolbar Row 2: Contextual Actions -->
<div class="toolbar-row" id="contextRow">
  <button class="tb-btn sel-btn" onclick="clearSelection()" disabled>Deselect</button>
  <button class="tb-btn danger sel-btn" onclick="deleteSelected()" disabled>Delete</button>
  <button class="tb-btn sel-btn" onclick="stubAction('Flag')" disabled>Flag</button>
  <button class="tb-btn sel-btn" onclick="stubAction('Star')" disabled>Star</button>
  <div class="sep"></div>
  <button class="tb-btn arrow" onclick="stubAction('Prev')">&laquo;</button>
  <button class="tb-btn arrow" onclick="stubAction('Next')">&raquo;</button>
  <button class="tb-btn orange" onclick="stubAction('Starred')">Starred</button>
  <button class="tb-btn arrow" onclick="stubAction('Next starred')">&raquo;</button>
  <div class="sep"></div>
  <button class="tb-btn sel-btn" onclick="stubAction('Reference')" disabled>Reference</button>
  <button class="tb-btn" onclick="stubAction('Clear Refs')">Clear Refs</button>
  <div class="sep"></div>
  <button class="tb-btn sel-btn" onclick="stubAction('Render')" disabled>Render</button>
  <button class="tb-btn primary sel-btn" id="generateBtn" onclick="generateSelected()" disabled>Generate</button>
  <button class="tb-btn sel-btn" onclick="stubAction('+ Prompt')" disabled>+ Prompt</button>
  <button class="tb-btn sel-btn" onclick="stubAction('- Neg Prompt')" disabled>- Neg Prompt</button>
  <div class="sep"></div>
  <button class="tb-btn sel-btn" onclick="stubAction('Gen Rect')" disabled>Gen Rect</button>
  <button class="tb-btn sel-btn" onclick="stubAction('Fill Rect')" disabled>Fill Rect</button>
  <button class="tb-btn sel-btn" onclick="stubAction('Export Cmd')" disabled>Export Cmd</button>
  <button class="tb-btn sel-btn" onclick="stubAction('Export')" disabled>Export</button>
  <div class="spacer"></div>
  <button class="tb-btn danger" onclick="clearQueue()">Clear Queue</button>
  <button class="tb-btn" onclick="refresh()">Refresh</button>
</div>

<!-- Status Bar -->
<div class="status-bar">
  <div class="status-item">
    <span class="status-dot red" id="selDot" style="opacity:0.3"></span>
    <span id="selectionStatus">0 selected</span>
  </div>
  <span id="selCoordsList"></span>
  <div class="status-item">
    <span class="status-dot purple" id="queueDot" style="opacity:0.3"></span>
    <span id="queueStatus">Queue idle</span>
  </div>
  <div class="status-item">
    <span class="status-dot green"></span>
    <span id="genStatus">0/0 generated</span>
  </div>
</div>

<!-- Grid -->
<div class="grid-viewport" id="viewport">
  <div class="zoom-wrapper" id="zoomWrapper">
    <div class="grid" id="grid"></div>
  </div>
  <div class="zoom-indicator" id="zoomIndicator">100%</div>
</div>

<!-- Context Menu -->
<div class="ctx-menu" id="ctxMenu">
  <div class="ctx-menu-item" onclick="ctxDebug()"><span class="ctx-icon">&#128269;</span> Debug</div>
  <div class="ctx-menu-sep"></div>
  <div class="ctx-menu-item" onclick="ctxDelete()"><span class="ctx-icon">&#128465;</span> Delete</div>
  <div class="ctx-menu-item" onclick="ctxStub('Flag')"><span class="ctx-icon">&#9873;</span> Flag</div>
  <div class="ctx-menu-item" onclick="ctxStub('Star')"><span class="ctx-icon">&#9733;</span> Star</div>
</div>

<!-- Debug Modal -->
<div class="modal-overlay" id="debugModal">
  <div class="modal-panel">
    <div class="modal-header">
      <h2 id="debugTitle">Debug: Tile (0, 0)</h2>
      <button class="modal-close" onclick="closeDebugModal()">&times;</button>
    </div>
    <div class="modal-body" id="debugBody"></div>
  </div>
</div>

<!-- Notifications -->
<div class="notification-container" id="notifications"></div>

<script>
let quadrants = [];
let selected = new Set();  // "x,y" keys
let queue = [];            // [{id, x, y, status}]  status: queued | processing | done | error
let nextQueueId = 1;
let activeTool = 'select';
let ctxTarget = null;      // {x, y} of right-clicked tile

// ── Tools ──

function setTool(name) {
  const tools = ['select', 'fixwater', 'waterfill', 'waterselect'];
  const ids = ['toolSelect', 'toolFixWater', 'toolWaterFill', 'toolWaterSelect'];
  activeTool = name;
  tools.forEach((t, i) => {
    document.getElementById(ids[i]).classList.toggle('active', t === name);
  });
  if (name !== 'select') {
    notify('info', 'Tool', `${name} — not yet implemented`);
  }
}

function stubAction(name) {
  notify('info', name, 'Not yet implemented');
}

// ── Data ──

let lastSnapshot = '';

async function loadQuadrants() {
  try {
    const resp = await fetch('/api/quadrants');
    const data = await resp.json();
    const snap = JSON.stringify(data.map(q => q.x + ',' + q.y + ':' + q.is_generated));
    if (snap !== lastSnapshot) {
      quadrants = data;
      lastSnapshot = snap;
      renderGrid();
    } else {
      quadrants = data;
      updateStatus();
    }
  } catch(e) {
    // silent retry
  }
}

function quadrantLookup() {
  const m = {};
  quadrants.forEach(q => { m[q.x + ',' + q.y] = q; });
  return m;
}

function queueLookup() {
  const m = {};
  queue.forEach(item => {
    if (item.status === 'queued' || item.status === 'processing') {
      m[item.x + ',' + item.y] = item;
    }
  });
  return m;
}

// ── Grid Rendering ──

function renderGrid() {
  const grid = document.getElementById('grid');
  if (!quadrants.length) {
    grid.innerHTML = '<div style="padding:40px;color:var(--text-secondary)">No quadrants found</div>';
    return;
  }

  const xs = quadrants.map(q => q.x);
  const ys = quadrants.map(q => q.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const cols = maxX - minX + 1;

  grid.style.gridTemplateColumns = `repeat(${cols}, var(--tile-size))`;
  grid.innerHTML = '';

  const lookup = quadrantLookup();
  const qLookup = queueLookup();

  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      const key = x + ',' + y;
      const q = lookup[key];
      const queueItem = qLookup[key];
      const cell = document.createElement('div');
      cell.className = 'cell';
      cell.dataset.x = x;
      cell.dataset.y = y;

      if (!q) {
        cell.classList.add('empty-slot');
        grid.appendChild(cell);
        continue;
      }

      // Background image
      if (q.is_generated) {
        cell.classList.add('generated');
        cell.style.backgroundImage = `url(/api/image?x=${x}&y=${y}&type=generation)`;
      } else if (q.has_render) {
        cell.classList.add('has-render');
        cell.style.backgroundImage = `url(/api/image?x=${x}&y=${y}&type=render)`;
      }

      // State classes
      if (queueItem && queueItem.status === 'processing') {
        cell.classList.add('processing');
      } else if (queueItem && queueItem.status === 'queued') {
        cell.classList.add('queued');
      } else if (selected.has(key)) {
        cell.classList.add('selected');
      }

      // Coordinate label
      const label = document.createElement('span');
      label.className = 'coord-label';
      label.textContent = `${x},${y}`;

      if (queueItem && (queueItem.status === 'processing' || queueItem.status === 'queued')) {
        label.classList.add('purple');
      } else if (selected.has(key)) {
        label.classList.add('red');
      } else if (q.is_generated) {
        label.classList.add('green');
      } else if (q.has_render) {
        label.classList.add('blue');
      }

      cell.appendChild(label);

      // Left-click handler
      cell.addEventListener('click', () => {
        if (activeTool === 'select') toggleSelect(key);
      });

      // Right-click handler for context menu
      cell.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        ctxTarget = { x, y, key };
        showContextMenu(e.clientX, e.clientY);
      });

      grid.appendChild(cell);
    }
  }

  updateStatus();
}

// ── Context Menu ──

function showContextMenu(mx, my) {
  const menu = document.getElementById('ctxMenu');
  menu.style.left = mx + 'px';
  menu.style.top = my + 'px';
  menu.classList.add('visible');

  // Adjust if off-screen
  requestAnimationFrame(() => {
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth) menu.style.left = (mx - rect.width) + 'px';
    if (rect.bottom > window.innerHeight) menu.style.top = (my - rect.height) + 'px';
  });
}

function hideContextMenu() {
  document.getElementById('ctxMenu').classList.remove('visible');
}

function ctxDebug() {
  hideContextMenu();
  if (ctxTarget) openDebugModal(ctxTarget.x, ctxTarget.y);
}

function ctxDelete() {
  hideContextMenu();
  if (ctxTarget) deleteGeneration(ctxTarget.x, ctxTarget.y);
}

function ctxStub(name) {
  hideContextMenu();
  stubAction(name);
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('.ctx-menu')) hideContextMenu();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    hideContextMenu();
    closeDebugModal();
  }
});

// ── Debug Modal ──

async function openDebugModal(x, y) {
  const modal = document.getElementById('debugModal');
  const title = document.getElementById('debugTitle');
  const body = document.getElementById('debugBody');

  title.textContent = `Debug: Tile (${x}, ${y})`;
  body.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-secondary)">Loading...</div>';
  modal.classList.add('visible');

  try {
    const [debugResp, configResp] = await Promise.all([
      fetch(`/api/debug?x=${x}&y=${y}`),
      fetch('/api/config'),
    ]);
    const debug = await debugResp.json();
    let config = null;
    if (configResp.ok) config = await configResp.json();

    let html = '';

    // Metadata table
    html += '<div class="debug-section">';
    html += '<div class="debug-section-title">Metadata</div>';
    html += '<table class="debug-table">';
    html += `<tr><td>ID</td><td>${debug.id}</td></tr>`;
    html += `<tr><td>Coords</td><td>(${debug.x}, ${debug.y})</td></tr>`;
    html += `<tr><td>Lat / Lng</td><td>${debug.lat}, ${debug.lng}</td></tr>`;
    html += `<tr><td>Generated</td><td>${debug.is_generated ? 'Yes' : 'No'}</td></tr>`;
    html += `<tr><td>Has Render</td><td>${debug.has_render ? 'Yes' : 'No'}</td></tr>`;
    html += `<tr><td>Prompt</td><td style="font-size:11px;word-break:break-all">${debug.prompt || '—'}</td></tr>`;
    html += `<tr><td>Notes</td><td>${debug.notes || '—'}</td></tr>`;
    html += '</table></div>';

    // Images row
    html += '<div class="debug-section">';
    html += '<div class="debug-section-title">Images</div>';
    html += '<div class="debug-images">';

    // Render
    html += '<div class="debug-img-card"><div class="label">Render</div>';
    if (debug.has_render) {
      html += `<img src="/api/image?x=${x}&y=${y}&type=render" onclick="window.open(this.src)" title="Click to open full size">`;
    } else {
      html += '<div class="placeholder">No render</div>';
    }
    html += '</div>';

    // Generated
    html += '<div class="debug-img-card"><div class="label">Generated</div>';
    if (debug.has_generation) {
      html += `<img src="/api/image?x=${x}&y=${y}&type=generation" onclick="window.open(this.src)" title="Click to open full size">`;
    } else {
      html += '<div class="placeholder">Not generated</div>';
    }
    html += '</div>';

    // Template (recreated on the fly)
    html += '<div class="debug-img-card"><div class="label">Template</div>';
    html += `<img src="/api/template?x=${x}&y=${y}" onclick="window.open(this.src)" title="Click to open full size" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`;
    html += '<div class="placeholder" style="display:none">Template error</div>';
    html += '</div>';

    html += '</div></div>';

    // Neighbors mini-grid
    html += '<div class="debug-section">';
    html += '<div class="debug-section-title">Neighbors</div>';
    html += '<div class="debug-neighbors">';
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const nx = x + dx, ny = y + dy;
        const nkey = `${nx},${ny}`;
        if (dx === 0 && dy === 0) {
          // Center tile
          let bgStyle = '';
          if (debug.has_generation) bgStyle = `background-image:url(/api/image?x=${x}&y=${y}&type=generation);`;
          else if (debug.has_render) bgStyle = `background-image:url(/api/image?x=${x}&y=${y}&type=render);`;
          html += `<div class="debug-nb-cell center" style="${bgStyle}"><span class="debug-nb-label">${x},${y}</span></div>`;
        } else {
          const nb = debug.neighbors[nkey];
          if (nb) {
            let cls = nb.is_generated ? 'generated' : (nb.has_render ? 'has-render' : '');
            let bgStyle = '';
            if (nb.is_generated) bgStyle = `background-image:url(/api/image?x=${nx}&y=${ny}&type=generation);`;
            else if (nb.has_render) bgStyle = `background-image:url(/api/image?x=${nx}&y=${ny}&type=render);`;
            html += `<div class="debug-nb-cell ${cls}" style="${bgStyle}"><span class="debug-nb-label">${nx},${ny}</span></div>`;
          } else {
            html += `<div class="debug-nb-cell missing"><span class="debug-nb-label">${nx},${ny}</span></div>`;
          }
        }
      }
    }
    html += '</div></div>';

    // Config section (collapsible)
    if (config) {
      html += '<div class="debug-section">';
      html += '<div class="debug-section-title debug-toggle" onclick="toggleConfig()">';
      html += '<span class="arrow" id="configArrow">&#9654;</span> View Config';
      html += '</div>';
      html += `<div class="debug-config" id="configContent" style="display:none">${JSON.stringify(config, null, 2)}</div>`;
      html += '</div>';
    }

    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red)">Error loading debug data: ${e.message}</div>`;
  }
}

function toggleConfig() {
  const content = document.getElementById('configContent');
  const arrow = document.getElementById('configArrow');
  const visible = content.style.display !== 'none';
  content.style.display = visible ? 'none' : 'block';
  arrow.classList.toggle('open', !visible);
}

function closeDebugModal() {
  document.getElementById('debugModal').classList.remove('visible');
}

// Close modal on overlay click
document.getElementById('debugModal').addEventListener('click', (e) => {
  if (e.target === document.getElementById('debugModal')) closeDebugModal();
});

// ── Selection ──

function toggleSelect(key) {
  const qLookup = queueLookup();
  if (qLookup[key]) return; // can't select queued/processing tiles

  if (selected.has(key)) selected.delete(key);
  else selected.add(key);
  renderGrid();
}

function clearSelection() {
  selected.clear();
  renderGrid();
}

// ── Delete ──

async function deleteGeneration(x, y) {
  try {
    const resp = await fetch(`/api/generation?x=${x}&y=${y}`, { method: 'DELETE' });
    const result = await resp.json();
    if (result.ok) {
      notify('success', 'Deleted', `Generation cleared for (${x}, ${y})`);
      lastSnapshot = ''; // force re-render
      await loadQuadrants();
    } else {
      notify('error', 'Delete failed', result.error || 'Unknown error');
    }
  } catch (e) {
    notify('error', 'Delete failed', e.message);
  }
}

async function deleteSelected() {
  if (selected.size === 0) return;
  const coords = [...selected];
  selected.clear();
  for (const key of coords) {
    const [x, y] = key.split(',').map(Number);
    await deleteGeneration(x, y);
  }
}

// ── Queue System ──

function generateSelected() {
  if (selected.size === 0) return;

  const coords = [...selected];
  selected.clear();

  coords.forEach(key => {
    const [x, y] = key.split(',').map(Number);
    queue.push({ id: nextQueueId++, x, y, status: 'queued' });
  });

  notify('info', 'Added to queue', `${coords.length} tile(s) queued for generation`);
  renderGrid();
  processQueue();
}

async function processQueue() {
  const processing = queue.find(i => i.status === 'processing');
  if (processing) return;

  const next = queue.find(i => i.status === 'queued');
  if (!next) return;

  next.status = 'processing';
  renderGrid();

  const progressId = notify('progress', 'Generating...', `Processing tile (${next.x}, ${next.y})`);

  try {
    const resp = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quadrants: [[next.x, next.y]] }),
    });
    const result = await resp.json();

    dismissNotification(progressId);

    if (result.error) {
      next.status = 'error';
      notify('error', 'Generation failed', `(${next.x}, ${next.y}): ${result.error}`);
    } else {
      next.status = 'done';
      notify('success', 'Complete!', `Tile (${next.x}, ${next.y}) generated successfully`);
    }
  } catch (e) {
    dismissNotification(progressId);
    next.status = 'error';
    notify('error', 'Network error', `(${next.x}, ${next.y}): ${e.message}`);
  }

  await loadQuadrants();
  processQueue();
}

function clearQueue() {
  const removed = queue.filter(i => i.status === 'queued').length;
  queue = queue.filter(i => i.status !== 'queued');
  if (removed > 0) {
    notify('info', 'Queue cleared', `Removed ${removed} pending item(s)`);
  }
  renderGrid();
}

// ── Status ──

function updateStatus() {
  // Selection
  const selCount = selected.size;
  document.getElementById('selectionStatus').textContent = `${selCount} selected`;
  document.getElementById('selDot').style.opacity = selCount > 0 ? '1' : '0.3';

  // Selected coords list
  const coordsList = document.getElementById('selCoordsList');
  if (selCount > 0 && selCount <= 12) {
    coordsList.textContent = [...selected].map(k => `(${k})`).join(' ');
  } else if (selCount > 12) {
    const shown = [...selected].slice(0, 8).map(k => `(${k})`).join(' ');
    coordsList.textContent = shown + ` +${selCount - 8} more`;
  } else {
    coordsList.textContent = '';
  }

  // Enable/disable selection-dependent buttons
  document.querySelectorAll('.sel-btn').forEach(btn => {
    btn.disabled = selCount === 0;
  });

  // Queue
  const pending = queue.filter(i => i.status === 'queued').length;
  const processing = queue.find(i => i.status === 'processing');
  const queueDot = document.getElementById('queueDot');
  const queueText = document.getElementById('queueStatus');

  if (processing) {
    queueText.textContent = `Processing (${pending} pending)`;
    queueDot.style.opacity = '1';
  } else if (pending > 0) {
    queueText.textContent = `${pending} pending`;
    queueDot.style.opacity = '1';
  } else {
    queueText.textContent = 'Queue idle';
    queueDot.style.opacity = '0.3';
  }

  // Generation progress
  const genCount = quadrants.filter(q => q.is_generated).length;
  document.getElementById('genStatus').textContent = `${genCount}/${quadrants.length} generated`;

  // (generateBtn is covered by .sel-btn above)
}

// ── Notifications ──

let notifyId = 0;
const ICONS = {
  success:  '\u2713',
  error:    '\u2717',
  progress: '\u25F7',
  info:     '\u2139',
};

function notify(type, title, msg) {
  const id = ++notifyId;
  const container = document.getElementById('notifications');

  const el = document.createElement('div');
  el.className = `notification ${type}`;
  el.dataset.id = id;
  el.innerHTML = `
    <span class="icon">${ICONS[type]}</span>
    <div class="body">
      <div class="title">${title}</div>
      <div class="msg">${msg}</div>
    </div>
    <button class="close-btn" onclick="dismissNotification(${id})">&times;</button>
  `;

  container.appendChild(el);

  if (type !== 'progress') {
    setTimeout(() => dismissNotification(id), 5000);
  }

  return id;
}

function dismissNotification(id) {
  const container = document.getElementById('notifications');
  const el = container.querySelector(`[data-id="${id}"]`);
  if (!el) return;
  el.classList.add('removing');
  setTimeout(() => el.remove(), 200);
}

// ── Refresh ──

function refresh() {
  lastSnapshot = '';
  loadQuadrants();
  notify('info', 'Refreshed', 'Grid data reloaded');
}

// ── Zoom & Pan ──

let zoom = 1;
let panX = 0, panY = 0;
let isPanning = false;
let panStartX, panStartY;
const MIN_ZOOM = 0.15, MAX_ZOOM = 3;

function applyTransform() {
  const wrapper = document.getElementById('zoomWrapper');
  wrapper.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  document.getElementById('zoomIndicator').textContent = `${Math.round(zoom * 100)}%`;
}

const viewport = document.getElementById('viewport');

viewport.addEventListener('wheel', (e) => {
  e.preventDefault();
  const rect = viewport.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
  const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * factor));

  panX = mx - (mx - panX) * (newZoom / zoom);
  panY = my - (my - panY) * (newZoom / zoom);
  zoom = newZoom;
  applyTransform();
}, { passive: false });

viewport.addEventListener('mousedown', (e) => {
  // Middle click to pan, or left click on empty space
  if (e.button === 1 || e.target === viewport || e.target.id === 'zoomWrapper') {
    isPanning = true;
    panStartX = e.clientX - panX;
    panStartY = e.clientY - panY;
    viewport.classList.add('panning');
    e.preventDefault();
  }
});

window.addEventListener('mousemove', (e) => {
  if (!isPanning) return;
  panX = e.clientX - panStartX;
  panY = e.clientY - panStartY;
  applyTransform();
});

window.addEventListener('mouseup', () => {
  isPanning = false;
  viewport.classList.remove('panning');
});

// Suppress default context menu on viewport (but tiles handle their own)
viewport.addEventListener('contextmenu', (e) => e.preventDefault());

// Center the grid on first load
function centerGrid() {
  const vp = document.getElementById('viewport');
  const grid = document.getElementById('grid');
  if (!grid.children.length) return;
  const vr = vp.getBoundingClientRect();
  const gr = grid.getBoundingClientRect();
  const gridW = gr.width / zoom;
  const gridH = gr.height / zoom;
  const fitZoom = Math.min(vr.width / (gridW + 48), vr.height / (gridH + 48), 1);
  zoom = fitZoom;
  panX = (vr.width - gridW * zoom) / 2;
  panY = (vr.height - gridH * zoom) / 2;
  applyTransform();
}

// Auto-refresh every 8s
setInterval(() => {
  loadQuadrants();
}, 8000);

loadQuadrants().then(() => {
  requestAnimationFrame(centerGrid);
});
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
        elif path == "/api/debug":
            x = int(params.get("x", [0])[0])
            y = int(params.get("y", [0])[0])
            self._handle_debug(x, y)
        elif path == "/api/template":
            x = int(params.get("x", [0])[0])
            y = int(params.get("y", [0])[0])
            self._handle_template(x, y)
        elif path == "/api/config":
            self._handle_config()
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
                import traceback
                traceback.print_exc()
                self._respond(500, "application/json",
                              json.dumps({"error": str(e)}).encode())
        else:
            self._respond(404, "text/plain", b"Not found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/api/generation":
            x = int(params.get("x", [0])[0])
            y = int(params.get("y", [0])[0])
            db_path = get_db_path(self.generation_dir)
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "UPDATE quadrants SET generation = NULL, template = NULL, prompt = NULL, is_generated = 0 WHERE x = ? AND y = ?",
                (x, y),
            )
            conn.commit()
            conn.close()
            self._respond(200, "application/json",
                          json.dumps({"ok": True, "x": x, "y": y}).encode())
        else:
            self._respond(404, "text/plain", b"Not found")

    def _handle_debug(self, x: int, y: int):
        db_path = get_db_path(self.generation_dir)
        conn = sqlite3.connect(str(db_path))
        # Try to read prompt column; fall back if it doesn't exist yet
        try:
            cursor = conn.execute(
                "SELECT id, lat, lng, x, y, is_generated, notes, "
                "render IS NOT NULL, generation IS NOT NULL, prompt "
                "FROM quadrants WHERE x = ? AND y = ?",
                (x, y),
            )
        except sqlite3.OperationalError:
            cursor = conn.execute(
                "SELECT id, lat, lng, x, y, is_generated, notes, "
                "render IS NOT NULL, generation IS NOT NULL "
                "FROM quadrants WHERE x = ? AND y = ?",
                (x, y),
            )
        row = cursor.fetchone()
        if not row:
            conn.close()
            self._respond(404, "application/json",
                          json.dumps({"error": "Not found"}).encode())
            return

        tile = {
            "id": row[0], "lat": row[1], "lng": row[2],
            "x": row[3], "y": row[4], "is_generated": bool(row[5]),
            "notes": row[6], "has_render": bool(row[7]),
            "has_generation": bool(row[8]),
            "prompt": row[9] if len(row) > 9 else None,
        }

        # Neighbor states
        neighbors = {}
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                nc = conn.execute(
                    "SELECT is_generated, render IS NOT NULL FROM quadrants WHERE x = ? AND y = ?",
                    (nx, ny),
                )
                nr = nc.fetchone()
                if nr:
                    neighbors[f"{nx},{ny}"] = {
                        "x": nx, "y": ny,
                        "is_generated": bool(nr[0]),
                        "has_render": bool(nr[1]),
                    }
                else:
                    neighbors[f"{nx},{ny}"] = None

        conn.close()
        tile["neighbors"] = neighbors
        self._respond(200, "application/json", json.dumps(tile).encode())

    def _handle_template(self, x: int, y: int):
        import io
        try:
            from sprite_nyc.e2e_generation.generate_omni import (
                load_grid_from_db,
                load_render_from_db,
                load_template_from_db,
            )
            from sprite_nyc.e2e_generation.infill_template import (
                create_template_image,
            )

            db_path = get_db_path(self.generation_dir)

            # Serve the stored template if this tile was already generated
            stored = load_template_from_db(db_path, x, y)
            if stored is not None:
                buf = io.BytesIO()
                stored.save(buf, format="PNG")
                self._respond(200, "image/png", buf.getvalue())
                return

            # Otherwise compute a live preview
            grid = load_grid_from_db(db_path)
            q = grid.get((x, y))
            if not q:
                self._respond(404, "text/plain", b"Quadrant not found")
                return

            selected = [q]
            render_lookup = {}
            keys_to_load = {q.key}
            for nb_key in q.neighbor_keys().values():
                keys_to_load.add(nb_key)
            for key in keys_to_load:
                render = load_render_from_db(db_path, key[0], key[1])
                if render:
                    render_lookup[key] = render

            template, _layout = create_template_image(selected, grid, render_lookup)
            buf = io.BytesIO()
            template.save(buf, format="PNG")
            self._respond(200, "image/png", buf.getvalue())
        except Exception as e:
            self._respond(500, "application/json",
                          json.dumps({"error": str(e)}).encode())

    def _handle_config(self):
        config_path = self.generation_dir / "generation_config.json"
        if config_path.exists():
            self._respond(200, "application/json", config_path.read_bytes())
        else:
            self._respond(404, "application/json",
                          json.dumps({"error": "No generation_config.json"}).encode())

    def _respond(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if args and '500' in str(args):
            import sys
            print(format % args, file=sys.stderr)


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

    # Ensure DB has template/prompt columns
    from sprite_nyc.e2e_generation.generate_omni import _ensure_extra_columns
    _ensure_extra_columns(gd / "quadrants.db")

    server = ThreadedHTTPServer(("0.0.0.0", port), ViewerHandler)
    print(f"Viewer running at http://localhost:{port}")
    print(f"Database: {gd / 'quadrants.db'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
