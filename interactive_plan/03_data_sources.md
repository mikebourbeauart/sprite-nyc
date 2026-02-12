# 03 — Data Sources

## Overview

The simulation needs real-world geometry to drive movement. We extract roads, sidewalks, buildings, and POIs from OpenStreetMap and transform them into the pixel coordinate space of the stitched map.

## Coordinate Pipeline

```
OSM (lat/lng, WGS-84)
    │
    ▼
Project to local meters (using map center as origin)
    │
    ▼
Apply isometric projection (azimuth -15°, elevation -45°)
    │
    ▼
Scale to pixel space (meters_per_pixel from view.json)
    │
    ▼
Offset to world pixel coords (match DZI tile positions)
```

### Projection Math

The existing pipeline already computes this in `plan_tiles.py`:

```python
# From the existing codebase — ground footprint per tile
north_extent = view_height / sin(abs(elevation))
east_extent  = view_height * aspect / sin(abs(elevation))

# Meters per pixel
meters_per_px_x = east_extent * 2 / width
meters_per_px_y = north_extent * 2 / height
```

The isometric transform (azimuth rotation) is:
```python
# Rotate a lat/lng offset into screen space
def latlng_to_screen(lat, lng, center_lat, center_lng):
    # Approximate meters from center
    dx = (lng - center_lng) * 111320 * cos(radians(center_lat))
    dy = (center_lat - lat) * 110540  # Y increases southward

    # Apply azimuth rotation (-15°)
    azimuth_rad = radians(-15)
    rx = dx * cos(azimuth_rad) - dy * sin(azimuth_rad)
    ry = dx * sin(azimuth_rad) + dy * cos(azimuth_rad)

    # Scale to pixels
    px = rx / meters_per_px_x + world_width / 2
    py = ry / meters_per_px_y + world_height / 2
    return (px, py)
```

## Source 1: Road Network (OSM Overpass API)

### Query

```
[out:json][timeout:60];
(
  way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|service|unclassified)$"]
    ({{bbox}});
);
out body;
>;
out skel qt;
```

Where `{{bbox}}` is the bounding box of the generated map area (from `generation_config.json` bounds polygon).

### Output: Road Graph

```typescript
interface RoadNode {
  id: string
  lat: number
  lng: number
  screenX: number   // projected pixel coord
  screenY: number
  connections: string[]  // adjacent node IDs
  isIntersection: boolean
  trafficLight?: TrafficLightState
}

interface RoadEdge {
  from: string       // node ID
  to: string
  highway: string    // "primary", "residential", etc.
  lanes: number
  oneway: boolean
  name?: string
  screenPath: [number, number][]  // projected polyline
  length: number     // in pixels
}

interface RoadGraph {
  nodes: Map<string, RoadNode>
  edges: RoadEdge[]
}
```

### Lane Geometry

For each road edge, compute parallel lane centerlines:

```
  ◄── lane 1 ──►◄── lane 2 ──►
  ─────────────────────────────  road edge polyline
       offset left    offset right
```

Lane width in pixels = ~3–4px at the default zoom level (represents ~3m real-world lane). Cars follow lane centerlines, not raw OSM node positions.

## Source 2: Buildings (OSM)

### Query

```
[out:json][timeout:60];
(
  way["building"]({{bbox}});
  relation["building"]({{bbox}});
);
out body;
>;
out skel qt;
```

### Output: Building Data

```typescript
interface Building {
  id: string
  polygon: [number, number][]  // screen-space outline
  centroid: [number, number]
  entrances: [number, number][]  // door positions (see below)
  tags: {
    name?: string
    amenity?: string
    shop?: string
    building?: string  // "commercial", "residential", etc.
    height?: number
  }
}
```

### Entrance Detection

OSM sometimes tags entrances explicitly (`entrance=yes`). When missing, heuristic:

1. Find the building edge closest to a road
2. Place entrance at the midpoint of that edge
3. Snap to nearest sidewalk node

## Source 3: Sidewalks & Crosswalks

OSM sidewalk coverage in NYC is inconsistent. Fallback strategy:

1. **If tagged**: Use `footway=sidewalk` ways
2. **If not tagged**: Generate synthetic sidewalks by buffering road edges outward by ~2m (converted to pixels)
3. **Crosswalks**: Place at intersections, perpendicular to the road, connecting sidewalks across the street

```typescript
interface Sidewalk {
  path: [number, number][]  // screen-space polyline
  width: number             // in pixels
  adjacentRoadId: string
  side: 'left' | 'right'
}
```

## Source 4: Points of Interest

Already partially available in `landmarks.json`. Extend with OSM POI queries:

```
[out:json][timeout:60];
(
  node["amenity"]({{bbox}});
  node["shop"]({{bbox}});
  node["tourism"]({{bbox}});
  node["public_transport"="station"]({{bbox}});
);
out body;
```

Subway entrances are particularly useful — they become spawn/despawn points for pedestrian clusters.

## Pre-processing Pipeline

All OSM data should be fetched and projected **offline** (not at runtime). This produces a static JSON file the viewer loads:

```
interactive_plan/
  tools/
    fetch_osm.py          ← Overpass query + save raw GeoJSON
    project_to_screen.py  ← Apply isometric projection
    build_road_graph.py   ← Construct graph with lanes, intersections
    detect_entrances.py   ← Building entrance heuristics
    export_scene.json     ← Final combined output
```

### scene.json Schema

```json
{
  "bounds": {
    "topLeft": [0, 0],
    "bottomRight": [49152, 32768],
    "centerLatLng": [40.7128, -74.0060]
  },
  "roads": {
    "nodes": [...],
    "edges": [...]
  },
  "buildings": [...],
  "sidewalks": [...],
  "pois": [...],
  "trafficLights": [...]
}
```

Estimated size for a ~100-block area: 2–5 MB (gzipped: 300–800 KB).

## Data Refresh

The OSM data only needs to be re-fetched if:
- The map area changes (new `generation_config.json`)
- You want updated road/building data

Otherwise, `scene.json` is generated once and bundled with the viewer.
