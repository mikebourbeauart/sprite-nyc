# 07 — Milestones

## Phase 0: Foundation

**Goal**: PixiJS renders the existing tile map with pan/zoom, replacing OpenSeaDragon.

### Deliverables
- [ ] `interactive/` project scaffolded (Vite + TypeScript + PixiJS v8)
- [ ] DZITileLoader loads tile pyramid from `viewer/tiles/`
- [ ] Viewport supports pan, zoom, pinch (matching current viewer behavior)
- [ ] Progressive tile loading (low-res first, then sharp)
- [ ] LRU tile cache (~200 textures)
- [ ] Performance: 60fps pan/zoom on 2020-era laptop

### Validates
- PixiJS can efficiently serve as a DZI tile viewer
- Tile loading performance is acceptable

---

## Phase 1: Road Graph

**Goal**: Extract and visualize the road network overlaid on the map.

### Deliverables
- [ ] `tools/fetch_osm.py` — Overpass API query for roads, buildings in map bounds
- [ ] `tools/project_to_screen.py` — lat/lng → isometric pixel coordinate projection
- [ ] `tools/build_road_graph.py` — construct graph with nodes, edges, lane centerlines
- [ ] `scene.json` generated for the current map area
- [ ] Debug overlay in PixiJS showing road edges as colored lines
- [ ] Verify road positions align with pixel-art streets on the tile backdrop

### Validates
- Coordinate projection is correct (roads land on actual streets)
- Road graph is connected and navigable
- Scene data size is manageable

---

## Phase 2: First Car

**Goal**: A single car sprite drives along a road.

### Deliverables
- [ ] Hand-draw 1 car sprite (sedan) — 8 directions, 16×12px each
- [ ] Sprite sheet loaded into PixiJS
- [ ] Car follows a hardcoded road edge path (pick one straight road)
- [ ] Car faces correct direction based on heading
- [ ] Car rendered at correct depth (z-sorted with other sprites)
- [ ] Car speed looks natural at default zoom

### Validates
- Isometric sprite direction system works
- Sprite size/style matches the map aesthetic
- Movement looks believable

---

## Phase 3: Traffic

**Goal**: Multiple cars navigate the road network with pathfinding.

### Deliverables
- [ ] A* pathfinding on road graph
- [ ] Cars spawn at map edges, pick random destinations, navigate, despawn
- [ ] 50–100 simultaneous vehicles
- [ ] Car-following behavior (decelerate behind slower car)
- [ ] Traffic lights at major intersections (cycle red/green)
- [ ] Cars stop at red lights
- [ ] Vehicle variety: sedans, taxis, buses (3 sprite types)
- [ ] Sprite pooling for entity recycling

### Validates
- Pathfinding performance is adequate
- Traffic flow looks organic
- No cars driving through buildings or off-road

---

## Phase 4: Pedestrians

**Goal**: NPC pedestrians walk along sidewalks and enter/exit buildings.

### Deliverables
- [ ] Sidewalk graph (generated or from OSM)
- [ ] Building entrance detection
- [ ] Hand-draw 1 pedestrian sprite — 8 directions × 4 walk frames
- [ ] Pedestrians spawn at building entrances, walk to nearby destinations
- [ ] Walk animation synced to movement speed
- [ ] Crosswalk behavior (wait for walk signal at traffic lights)
- [ ] Crowd jitter (slight random lateral offset)
- [ ] 100–200 simultaneous pedestrians
- [ ] Pedestrian color variants (randomized clothing)

### Validates
- Sidewalk paths align with map geometry
- Walk animation reads clearly at pixel scale
- Crowd density feels city-like

---

## Phase 5: Polish & Interaction

**Goal**: Make it feel alive and explorable.

### Deliverables
- [ ] Click/tap building → show info panel (name, type, address from OSM)
- [ ] UI controls: simulation speed slider, entity density slider
- [ ] Minimap in corner showing full map extent with viewport indicator
- [ ] Crowd bursts at subway entrances (spawn clusters of peds)
- [ ] Bus routes (fixed paths with stops)
- [ ] Ambient variety: delivery vans stopping, taxis picking up passengers
- [ ] Performance profiling and optimization pass
- [ ] Mobile-friendly touch controls

### Validates
- Interactivity adds engagement without hurting performance
- The simulation tells a story — it feels like NYC

---

## Phase 6: Atmosphere (Stretch)

**Goal**: Environmental effects that add depth.

### Deliverables
- [ ] Day/night cycle with tint overlay
- [ ] Building windows glow at night (small sprite overlays)
- [ ] Ambient sound layer (city noise, honks, crosswalk chirps)
- [ ] Weather: rain particles, snow overlay
- [ ] Seasonal palette shifts
- [ ] Time-of-day affects traffic density (rush hour peaks)

### Validates
- Atmospheric effects enhance without overwhelming
- Performance holds with particle effects

---

## Dependency Graph

```
Phase 0 (PixiJS viewer)
   │
   ▼
Phase 1 (Road graph) ──────────┐
   │                           │
   ▼                           ▼
Phase 2 (First car)      Phase 4 (Pedestrians)
   │                           │
   ▼                           │
Phase 3 (Traffic) ◄────────────┘
   │
   ▼
Phase 5 (Polish)
   │
   ▼
Phase 6 (Atmosphere)
```

Phases 1→2→3 and 1→4 can run in parallel after Phase 1 completes. Phase 5 requires both traffic and pedestrians. Phase 6 is independent stretch work.

## Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| Renderer | PixiJS v8 |
| Viewport | pixi-viewport |
| Build | Vite + TypeScript |
| Data pipeline | Python (uv) + Overpass API |
| Tile source | Existing DZI pyramid |
| Sprite art | Hand-drawn (Aseprite/Piskel) |
| State format | JSON (scene.json) |
| Sound (Phase 6) | @pixi/sound or Howler.js |
