# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

sprite-nyc is a pipeline for generating giant isometric pixel-art maps of NYC from Google Maps 3D tiles using AI-powered image generation. It combines Playwright-based 3D rendering, geospatial calculations, and fine-tuned diffusion models (via Oxen.ai API) to create seamless pixel-art cityscapes viewable as gigapixel images.

Project writeup and process reference: https://cannoneyed.com/projects/isometric-nyc

## Commands

### Python
```bash
uv run python -m sprite_nyc.<module_name>   # Run any CLI module
uv run pytest                                # Run tests
uv run ruff check src/                       # Lint
uv run ruff format src/                      # Format
```

### Web renderer (Three.js + Google 3D Tiles)
```bash
cd web && npm install && npm run dev         # Dev server on port 3000
```

### Viewer (OpenSeaDragon gigapixel viewer)
Serve `viewer/` with any static file server.

## Architecture

### Generation Pipeline Flow
1. **Plan** (`plan_tiles.py`) — Convert lat/lng center + grid dimensions into a tile manifest with 50% overlapping positions
2. **Render** (`export_views.py`) — Playwright captures 3D tile views (textured + whitebox) from the web renderer
3. **Template** (`create_template.py`) — Compose infill template showing neighbor context + render with red border marking the region to generate
4. **Upload** (`gcs_upload.py`) — Upload template to GCS bucket (Oxen API requires public URLs)
5. **Generate** (`generate_tile_oxen.py`) — Call Oxen.ai fine-tuned model to produce pixel art
6. **Export** (`e2e_generation/export_tiles.py`) — Stitch all quadrants into DZI tile pyramid for OpenSeaDragon

### Key Modules

- **`src/sprite_nyc/`** — Core pipeline: template creation, rendering, GCS upload, single-tile generation, tile planning/validation
- **`src/sprite_nyc/e2e_generation/`** — SQLite-backed state machine for large-scale generation. Includes auto-generation with spiral expansion, strip planning, web-based generation manager (port 8080), and DZI export
- **`src/sprite_nyc/synthetic_data/`** — Training data generators for fine-tuning (infill, inpainting, omni datasets with controlled variant distributions)
- **`web/`** — Three.js orthographic renderer with Google 3D Tiles, isometric camera, whitebox mode
- **`viewer/`** — OpenSeaDragon-based gigapixel viewer for browsing exported maps

### Critical Conventions

- **50% overlap system**: All tiles overlap by half in both axes. Grid step = `tile_size / 2`. This enables seamless stitching and neighbor context.
- **Red border convention**: 1px red (#FF0000) borders mark regions for AI to generate. The model is fine-tuned to recognize these.
- **Grid coordinates**: Origin (0,0) at seed lat/lng. X increases eastward, Y increases southward. Integers, stored in SQLite.
- **SQLite as state store**: E2E pipeline stores renders and generations as BLOBs, tracks `is_generated` flag per quadrant. Enables pause/resume.
- **CLI pattern**: All modules use Click, runnable as `python -m sprite_nyc.<module>`. API keys via env vars (e.g., `OXEN_INFILL_V02_API_KEY`).

### Configuration Files

- **`view.json`** (root) — Camera config: center lat/lng, azimuth (-15°), elevation (-45°), view_height_meters, width/height
- **`generation_config.json`** (per generation directory) — Extends view.json with bounds polygon for E2E pipeline
