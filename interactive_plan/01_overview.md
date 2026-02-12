# 01 — Overview

## Vision

Transform the static gigapixel pixel-art map of NYC into a living, interactive scene where cars drive along real streets, traffic lights cycle, and crowds of pixel NPCs walk in and out of buildings — all rendered at the same isometric pixel-art aesthetic as the existing map.

## Scope Tiers

### Tier 1 — Alive (MVP)
- PixiJS renderer loads existing DZI tiles as a static backdrop
- 50–100 car sprites drive along major roads on fixed loops
- 20–30 pedestrian sprites walk along sidewalks
- Traffic lights cycle red/green at intersections
- Pan/zoom works like current viewer

### Tier 2 — Simulated
- Full road graph from OSM with A* pathfinding
- Cars spawn at edges, navigate to random destinations, despawn
- Pedestrians spawn at building entrances, walk to nearby POIs
- Proper intersection logic (yielding, turning, queuing)
- Day/night lighting cycle (tint overlay + window glow sprites)

### Tier 3 — Interactive
- Click buildings to see info (name, type, address)
- Adjustable simulation speed / population density
- Sound design (ambient city noise, honks, crosswalk chirps)
- Subway entrances that spawn/absorb pedestrian clusters
- Seasonal/weather overlays (snow, rain, autumn leaves)

## Architectural Overview

```
┌─────────────────────────────────────────────────┐
│                   Browser                        │
│                                                  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐ │
│  │ Tile Layer  │  │ Road Debug  │  │ Sprite     │ │
│  │ (static    │  │ Layer       │  │ Layer      │ │
│  │  backdrop) │  │ (optional)  │  │ (animated) │ │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘ │
│        │               │               │        │
│        └───────────┬────┴───────────────┘        │
│                    │                             │
│              ┌─────▼─────┐                       │
│              │  PixiJS    │                       │
│              │  Stage     │                       │
│              └─────┬──────┘                       │
│                    │                             │
│              ┌─────▼──────┐                      │
│              │  Simulation │                     │
│              │  Loop (ECS) │                     │
│              └─────┬───────┘                     │
│                    │                             │
│         ┌──────────┼──────────┐                  │
│         ▼          ▼          ▼                  │
│    ┌─────────┐ ┌────────┐ ┌───────┐             │
│    │ Traffic  │ │ Crowd  │ │ Light │             │
│    │ System   │ │ System │ │ Cycle │             │
│    └─────────┘ └────────┘ └───────┘             │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │  Road Graph (from OSM GeoJSON)           │    │
│  │  - nodes (intersections)                 │    │
│  │  - edges (road segments)                 │    │
│  │  - sidewalk polygons                     │    │
│  │  - building entrance points              │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

## Key Constraints

1. **Isometric projection must match** — the existing map uses azimuth -15°, elevation -45°. All sprite movement and sorting must use this same projection.

2. **Performance budget** — target 60fps on mid-range hardware with 500+ active sprites. PixiJS's WebGL batching makes this feasible but sprite count needs monitoring.

3. **Coordinate mapping** — the simulation needs a clean mapping between lat/lng (OSM data), grid coordinates (tile system), and screen pixels (PixiJS). This is the most critical piece to get right early.

4. **Existing pipeline unchanged** — the static tile generation pipeline should not be modified. The interactive layer reads from DZI tiles and overlays on top.
