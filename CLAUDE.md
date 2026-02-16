# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

sprite-nyc is a pipeline for generating giant isometric pixel-art maps of NYC from Google Maps 3D tiles using AI-powered image generation. It combines Playwright-based 3D rendering, geospatial calculations, and fine-tuned diffusion models (via Oxen.ai API) to create seamless pixel-art cityscapes viewable as gigapixel images.

Project writeup and process reference: https://cannoneyed.com/projects/isometric-nyc

**IMPORTANT**: Always follow the steps and conventions described in the author's writeup above. Do not deviate from the author's approach unless explicitly told to by the user.

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

### Batch Pipeline Flow (grid-based)
1. **Plan + Render** (`batch_export.py`) — Plans tile grid via `plan_tiles.py`, launches Playwright to capture all renders, writes `manifest.json`
2. **Generate** (`batch_generate.py`) — Iterates tiles in spiral order (cardinal-first), builds composite templates with neighbor context, calls Oxen API
3. **Validate** (`validate_plan.py`) — Stitches tiles into full composite for visual inspection

### E2E Pipeline Flow (quadrant-based, large-scale)
1. **Plan** (`plan_tiles.py`) — Convert lat/lng center + grid dimensions into a tile manifest with 50% overlapping positions
2. **Render** (`export_views.py`) — Playwright captures 3D tile views from the web renderer
3. **Template** (`e2e_generation/infill_template.py`) — Compose infill template with 1 ring of neighbor context
4. **Upload** (`gcs_upload.py`) — Upload template to GCS bucket (Oxen API requires public URLs)
5. **Generate** (`generate_tile_oxen.py`) — Call Oxen.ai fine-tuned model to produce pixel art
6. **Export** (`e2e_generation/export_tiles.py`) — Stitch all quadrants into DZI tile pyramid for OpenSeaDragon

### Training Data Pipeline
1. **Render landmarks** (`batch_export.py --landmarks`) — Capture 3D renders for training locations
2. **Generate pairs** — Manually or via model to create pixel art targets for each render
3. **Create dataset** (`synthetic_data/create_omni_dataset.py`) — Combine render/generation pairs into training variants (full, quadrant, half, middle, rect_strip, rect_infill)
4. **Train** — Upload inputs/targets to Oxen.ai for LoRA fine-tuning

### Key Modules

- **`src/sprite_nyc/`** — Core pipeline: template creation, rendering, GCS upload, single-tile generation, tile planning/validation
- **`src/sprite_nyc/e2e_generation/`** — SQLite-backed state machine for large-scale generation. Includes auto-generation with spiral expansion, strip planning, web-based generation manager (port 8080), and DZI export
- **`src/sprite_nyc/synthetic_data/`** — Training data generators for fine-tuning (infill, inpainting, omni datasets with controlled variant distributions)
- **`web/`** — Three.js orthographic renderer with Google 3D Tiles, isometric camera
- **`viewer/`** — OpenSeaDragon-based gigapixel viewer for browsing exported maps

### Critical Conventions

- **Non-overlapping tiles**: Tiles are placed edge-to-edge with no overlap, matching the original author's quadrant approach. Grid step = full tile size.
- **Red border convention**: 1px red (#FF0000) borders mark regions for AI to generate. The model is fine-tuned to recognize these. The red-bordered region should be 1/9 of the template image (center of a 3×3 grid).
- **3×3 templates**: `batch_generate.py` builds 3×3 non-overlapping templates (3072×3072 for 1024 tiles) with the target tile's render + red border at center, surrounded by 8 neighbor tiles as pixel art context.
- **Spiral generation order**: Tiles are generated center-outward in Chebyshev rings, with cardinal neighbors processed before diagonal ones, to maximize available pixel art context for each tile.
- **Resolution**: Renders are 1024×1024 (set in `view.json`). Training data and model input/output are all 1024×1024. Training generations that are larger must be downscaled to match.
- **Render/generation size alignment**: When creating training data, renders and generations MUST be the same dimensions. `create_omni_dataset.py` downscales to the smaller of the two sizes to avoid zoom artifacts in red-bordered regions.
- **Camera-aligned tile stepping**: `plan_tiles.py` steps along camera axes (not axis-aligned east/north) due to azimuth rotation. The azimuth is -15° so image-right maps to roughly westward on the ground.
- **Grid coordinates**: Origin (0,0) at seed lat/lng. X increases eastward, Y increases southward. Integers, stored in SQLite.
- **SQLite as state store**: E2E pipeline stores renders and generations as BLOBs, tracks `is_generated` flag per quadrant. Enables pause/resume.
- **CLI pattern**: All modules use Click, runnable as `python -m sprite_nyc.<module>`. API keys via env vars (e.g., `OXEN_INFILL_V02_API_KEY`).

### Known Issues

- **`seed_tiles.py`** has an azimuth stepping bug — it computes axis-aligned east/north steps ignoring the camera rotation. Needs the same fix applied to `plan_tiles.py`.

### Configuration Files

- **`view.json`** (root) — Camera config: center lat/lng, azimuth (-15°), elevation (-45°), view_height_meters, width/height
- **`generation_config.json`** (per generation directory) — Extends view.json with bounds polygon for E2E pipeline
- **`.env.local`** — API keys (Google Maps, Oxen AI). Not committed to git.
