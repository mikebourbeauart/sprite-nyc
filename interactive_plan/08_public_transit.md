# 08 — Public Transit (Real-Time MTA Data)

## Vision

A translucent underground layer beneath the pixel-art city surface showing real subway lines, moving trains, and passengers waiting on platforms — like an X-ray cutaway of the city. Buses appear on the surface layer using the same real-time data. All positions driven by live MTA feeds.

```
┌─────────────────────────────────────────┐
│  Surface (existing)                     │
│    ┌───┐  🚕  🚶 🚶      🚌            │
│    │bld│    road          road          │
│    └───┘                                │
├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┤  ← ground plane (fades to transparent)
│  Underground                            │
│    ════●══════════●══════●════          │  ← subway tracks + stations
│         🚇→→→→→→→→        🚇→→          │  ← train sprites (real-time)
│        🧍🧍🧍   🧍🧍                    │  ← waiting passengers
│    ──────●────────────●───────          │  ← second line (different color)
│           🚇→→→→→→→→                    │
└─────────────────────────────────────────┘
```

## MTA Data Sources

### Subway — GTFS-Realtime (No API key required)

Feeds are protobuf, grouped by line division. Update every 30 seconds.

| Lines | Feed URL |
|---|---|
| 1, 2, 3, 4, 5, 6, 7, S | `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs` |
| A, C, E, H, FS | `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace` |
| B, D, F, M | `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm` |
| G | `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g` |
| J, Z | `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz` |
| L | `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l` |
| N, Q, R, W | `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw` |
| SIR | `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si` |

Each feed contains:
- **TripUpdate** — predicted arrival/departure times at upcoming stops
- **VehiclePosition** — current position and status of each train

MTA uses custom protobuf extensions beyond standard GTFS-RT. Need to download their `.proto` files from the MTA developer portal to decode NYC-specific fields.

### Bus — SIRI API (API key required)

Register at `https://register.developer.obanyc.com/` (typically approved within 30 minutes). JSON format, 30-second rate limit.

| Endpoint | URL |
|---|---|
| Vehicle positions | `https://bustime.mta.info/api/siri/vehicle-monitoring.json?key={API_KEY}` |
| Stop predictions | `https://bustime.mta.info/api/siri/stop-monitoring.json?key={API_KEY}` |

Filter by route with `LineRef` param (e.g., `MTA NYCT_M14`). Requesting all buses at once is expensive — filter by routes within the map viewport.

### Bus — GTFS-RT (Alternative, same API key)

| Feed | URL |
|---|---|
| VehiclePositions | `https://gtfsrt.prod.obanyc.com/vehiclePositions?key={API_KEY}` |
| TripUpdates | `https://gtfsrt.prod.obanyc.com/tripUpdates?key={API_KEY}` |

Protobuf format. Preferred over SIRI for consistency with subway feeds.

### Commuter Rail — LIRR & Metro-North (API key + approval required)

Separate registration and MTA approval process. Lower priority — only relevant if the map extends far enough to include Penn Station / Grand Central approaches.

| Service | URL |
|---|---|
| LIRR (JSON) | `https://mnorth.prod.acquia-sites.com/wse/LIRR/gtfsrt/realtime/{API_KEY}/json` |
| Metro-North | `https://mnorth.prod.acquia-sites.com/wse/gtfsrtwebapi/v1/gtfsrt/{API_KEY}/getfeed` |

### Static GTFS Data (Route Geometry)

Real-time feeds provide positions but not track geometry. The **static GTFS** data provides `shapes.txt` — the actual polyline coordinates of each route. This is used to draw the subway lines on the underground layer.

Download from `https://www.mta.info/developers`:
- Subway GTFS — includes `shapes.txt` with lat/lng polylines for each route
- Bus GTFS — six files by borough

Pre-process these offline into screen-space polylines (same projection as `scene.json`).

## Architecture

### Proxy Server (Required)

MTA feeds don't set CORS headers — browser `fetch()` to `api-endpoint.mta.info` will fail. Two options:

**Option A: Lightweight proxy (recommended for dev)**
```typescript
// server/mta-proxy.ts (runs alongside Vite dev server)
import express from 'express'

const app = express()

app.get('/api/subway/:feed', async (req, res) => {
  const url = `https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2F${req.params.feed}`
  const response = await fetch(url)
  const buffer = await response.arrayBuffer()
  res.set('Content-Type', 'application/x-protobuf')
  res.send(Buffer.from(buffer))
})

app.get('/api/bus/vehicles', async (req, res) => {
  const url = `https://bustime.mta.info/api/siri/vehicle-monitoring.json?key=${MTA_BUS_API_KEY}&${req.query}`
  const response = await fetch(url)
  res.json(await response.json())
})

app.listen(3002)
```

**Option B: Serverless function (production)**
Deploy as a Cloudflare Worker or Vercel Edge Function. Cache responses for 25 seconds (feeds update every 30s).

### Data Flow

```
MTA GTFS-RT feeds (30s interval)
       │
       ▼
  Proxy server (CORS + cache)
       │
       ▼
  TransitDataService (browser)
       │
       ├── decode protobuf → normalized train/bus positions
       │
       ▼
  TransitSystem (Becsy ECS)
       │
       ├── interpolate positions between feed updates
       ├── spawn/despawn train entities
       ├── update platform passenger counts
       │
       ▼
  Renderer (PixiJS underground layer)
```

### Protobuf Decoding in Browser

Use `protobufjs` to decode GTFS-RT messages client-side:

```typescript
import protobuf from 'protobufjs'

// Load GTFS-RT + MTA extension schemas
const root = await protobuf.load([
  'proto/gtfs-realtime.proto',
  'proto/nyct-subway.proto'  // MTA custom extensions
])
const FeedMessage = root.lookupType('transit_realtime.FeedMessage')

async function fetchSubwayFeed(feedId: string): Promise<SubwayUpdate[]> {
  const response = await fetch(`/api/subway/${feedId}`)
  const buffer = await response.arrayBuffer()
  const message = FeedMessage.decode(new Uint8Array(buffer))
  return parseVehiclePositions(message)
}
```

## Underground Render Layer

### Layer Placement in PixiJS

Insert between the tile layer and the sprite layer (see 02_renderer.md):

```
Stage
├── TileLayer (surface pixel art)
├── UndergroundLayer (NEW)         ← rendered with transparency
│   ├── SubwayLineGraphics         ← colored track polylines
│   ├── StationMarkers             ← platform sprites at stops
│   ├── TrainSprites               ← moving train sprites
│   └── PlatformPassengers         ← tiny waiting pedestrian sprites
├── GroundPlaneOverlay (NEW)       ← semi-transparent surface mask
├── RoadDebugLayer
├── SpriteLayer (vehicles, pedestrians)
└── UILayer
```

### Cutaway Visual Effect

The underground should feel like looking through translucent ground:

1. **GroundPlaneOverlay** — a semi-transparent dark tint (rgba 20,15,30,0.4) over the tile layer, applied only in areas where subway lines run. This dims the surface to make the underground visible.

2. **Alternative: viewport toggle** — user clicks "Underground View" and the surface fades to 30% opacity, revealing the full underground network. Simpler to implement, more dramatic effect.

3. **Depth-based opacity** — subway lines closer to the surface (shallow tunnels) are more opaque; deep tunnels are more faded. Adds visual depth but requires per-station depth data.

**Recommended: Start with viewport toggle (Option 2) for MVP.** A simple opacity slider between surface and underground is easy to build and visually striking.

```typescript
// Toggle underground visibility
function setUndergroundMode(enabled: boolean, surfaceOpacity = 0.3) {
  tileLayer.alpha = enabled ? surfaceOpacity : 1.0
  spriteLayer.alpha = enabled ? surfaceOpacity : 1.0
  undergroundLayer.visible = enabled
  groundPlaneOverlay.visible = false  // not needed in toggle mode
}
```

### Subway Line Rendering

Draw each route as a colored polyline using official MTA line colors:

```typescript
const MTA_LINE_COLORS: Record<string, number> = {
  '1': 0xEE352E, '2': 0xEE352E, '3': 0xEE352E,          // red
  '4': 0x00933C, '5': 0x00933C, '6': 0x00933C,          // green
  '7': 0xB933AD,                                          // purple
  'A': 0x0039A6, 'C': 0x0039A6, 'E': 0x0039A6,          // blue
  'B': 0xFF6319, 'D': 0xFF6319, 'F': 0xFF6319, 'M': 0xFF6319, // orange
  'G': 0x6CBE45,                                          // light green
  'J': 0x996633, 'Z': 0x996633,                           // brown
  'L': 0xA7A9AC,                                          // gray
  'N': 0xFCCC0A, 'Q': 0xFCCC0A, 'R': 0xFCCC0A, 'W': 0xFCCC0A, // yellow
  'S': 0x808183,                                          // shuttle gray
}

function drawSubwayLines(graphics: PIXI.Graphics, routes: SubwayRoute[]) {
  for (const route of routes) {
    graphics.lineStyle(3, MTA_LINE_COLORS[route.lineId] ?? 0xFFFFFF, 0.8)
    const points = route.screenPath  // pre-projected from shapes.txt
    graphics.moveTo(points[0][0], points[0][1])
    for (let i = 1; i < points.length; i++) {
      graphics.lineTo(points[i][0], points[i][1])
    }
  }
}
```

### Station Markers

Small platform sprites at each station — a simple rectangular platform graphic with the station name:

```typescript
function drawStation(station: SubwayStation): PIXI.Container {
  const container = new PIXI.Container()

  // Platform rectangle
  const platform = new PIXI.Graphics()
  platform.beginFill(0x3a3a4a, 0.9)
  platform.drawRoundedRect(-20, -6, 40, 12, 2)
  platform.endFill()
  container.addChild(platform)

  // Station name label (only visible at close zoom)
  const label = new PIXI.BitmapText(station.name, { fontName: 'PixelFont', fontSize: 6 })
  label.y = -12
  label.anchor.set(0.5, 1)
  container.addChild(label)

  container.position.set(station.screenX, station.screenY)
  return container
}
```

## ECS Components & Systems

### Transit Components

```typescript
import { component, Type, field } from '@lastolivegames/becsy'

@component class SubwayTrain {
  @field(Type.staticString([
    '1','2','3','4','5','6','7',
    'A','C','E','B','D','F','M',
    'G','J','Z','L',
    'N','Q','R','W','S','SIR'
  ])) declare line: string
  @field(Type.dynamicString(32)) declare tripId: string
  @field(Type.dynamicString(8)) declare direction: string  // 'N' or 'S'
  @field(Type.staticString([
    'in_transit', 'at_station', 'approaching'
  ])) declare status: string
  @field(Type.dynamicString(8)) declare nextStopId: string
  @field(Type.float32) declare nextStopEta: number  // seconds
}

@component class Bus {
  @field(Type.dynamicString(16)) declare routeId: string   // e.g. "M14A-SBS"
  @field(Type.dynamicString(8)) declare vehicleRef: string  // MTA vehicle ID
  @field(Type.dynamicString(8)) declare direction: string
}

@component class PlatformPassenger {
  @field(Type.dynamicString(8)) declare stationId: string
  @field(Type.float32) declare waitTime: number  // seconds waiting
}
```

Trains and buses also get `Position`, `Movement`, `Renderable`, and `EntityState` components (shared with traffic entities from 04_simulation.md).

### TransitDataService

Polls MTA feeds on a 30-second interval, normalizes data, and pushes updates to the ECS:

```typescript
class TransitDataService {
  private pollInterval = 30_000  // ms
  private lastUpdate: Map<string, TrainPosition[]> = new Map()

  async start() {
    await this.poll()
    setInterval(() => this.poll(), this.pollInterval)
  }

  private async poll() {
    // Fetch all subway feeds in parallel
    const feeds = ['gtfs', 'gtfs-ace', 'gtfs-bdfm', 'gtfs-g',
                   'gtfs-jz', 'gtfs-l', 'gtfs-nqrw', 'gtfs-si']
    const results = await Promise.all(
      feeds.map(f => fetchSubwayFeed(f))
    )

    // Flatten and deduplicate by trip ID
    this.lastUpdate = groupByTripId(results.flat())
  }

  getTrainPositions(): TrainPosition[] {
    return [...this.lastUpdate.values()].flat()
  }
}

interface TrainPosition {
  tripId: string
  routeId: string         // "1", "A", "L", etc.
  direction: 'N' | 'S'
  currentStopId: string | null
  nextStopId: string
  nextStopArrival: number  // unix timestamp
  timestamp: number
  // lat/lng from VehiclePosition (when available)
  lat?: number
  lng?: number
}
```

### TransitSystem (Becsy)

```typescript
@system class TransitSystem extends System {
  trains = this.query(q => q.current.with(SubwayTrain, Position, Movement))

  private transitData: TransitDataService
  private routeGeometry: Map<string, ScreenPath>  // from static GTFS shapes

  execute() {
    const dt = this.delta / 1000
    const livePositions = this.transitData.getTrainPositions()

    // Reconcile live data with ECS entities
    this.reconcileTrains(livePositions)

    // Interpolate between feed updates for smooth animation
    for (const entity of this.trains.current) {
      const train = entity.read(SubwayTrain)
      const pos = entity.write(Position)
      const movement = entity.write(Movement)

      if (train.status === 'in_transit') {
        // Interpolate along route geometry between last known and next stop
        const route = this.routeGeometry.get(train.line)
        const progress = this.estimateProgress(train)
        const screenPos = interpolateAlongPath(route, progress)
        pos.x = screenPos[0]
        pos.y = screenPos[1]
        movement.heading = pathHeadingAt(route, progress)
      }
    }
  }

  private estimateProgress(train: SubwayTrain): number {
    // Linear interpolation based on ETA to next stop
    // Feeds update every 30s, so we smooth between snapshots
    const totalSegmentTime = 120  // avg ~2min between stops
    const remaining = train.nextStopEta
    return Math.max(0, 1 - remaining / totalSegmentTime)
  }

  private reconcileTrains(live: TrainPosition[]) {
    // Spawn new train entities for trips not yet in ECS
    // Update existing entities with fresh position data
    // Despawn entities for trips that disappeared from feed
  }
}
```

### Platform Passengers

Cosmetic entities that appear on station platforms when a train is approaching or loading:

```typescript
@system class PlatformSystem extends System {
  passengers = this.query(q => q.current.with(PlatformPassenger, Position, Renderable))
  trains = this.query(q => q.current.with(SubwayTrain, Position))

  execute() {
    const dt = this.delta / 1000

    for (const station of this.stations) {
      // Check if a train is approaching or at this station
      const nearbyTrain = this.findTrainNearStation(station)

      if (nearbyTrain) {
        const train = nearbyTrain.read(SubwayTrain)
        if (train.status === 'approaching') {
          // Spawn 5-15 waiting passengers on platform
          this.ensurePlatformCrowd(station, randomInt(5, 15))
        } else if (train.status === 'at_station') {
          // Passengers board — fade them out over 1-2 seconds
          this.boardPassengers(station)
        }
      } else {
        // Slow trickle: occasionally spawn 1-2 passengers arriving at platform
        if (Math.random() < 0.01) {
          this.spawnWaitingPassenger(station)
        }
      }
    }
  }

  private ensurePlatformCrowd(station: SubwayStation, count: number) {
    // Spawn passengers spread along platform width
    // Small random offsets so they don't stack
    // Use the shared Pedestrian sprites (idle state)
  }
}
```

## Surface Buses

Buses from MTA data integrate with the existing vehicle system from 04_simulation.md. They use the same `Position`, `Movement`, `Renderable` components but add a `Bus` component and follow real-time positions instead of simulated A* paths.

```typescript
@system class BusDataSystem extends System {
  buses = this.query(q => q.current.with(Bus, Position, Movement))

  private busData: BusDataService  // polls SIRI or GTFS-RT every 30s

  execute() {
    const liveBuses = this.busData.getVehiclePositions()

    // Filter to buses within the current map bounds
    const visible = liveBuses.filter(b => this.isInMapBounds(b.lat, b.lng))

    // Reconcile with ECS entities
    for (const live of visible) {
      const existing = this.findByVehicleRef(live.vehicleRef)
      if (existing) {
        // Smooth interpolation toward new position
        const pos = existing.write(Position)
        const target = latlngToScreen(live.lat, live.lng)
        pos.x += (target[0] - pos.x) * 0.1  // lerp
        pos.y += (target[1] - pos.y) * 0.1
      } else {
        // Spawn new bus entity
        this.spawnBus(live)
      }
    }
  }
}
```

## Sprites

### Train Sprites

Side-view pixel art train cars, colored by line:

| Sprite | Size | Variants |
|--------|------|----------|
| Subway car (single) | 24x10 | Colored by line (apply tint to grayscale base) |
| Subway train (3-car) | 64x10 | For zoomed-out view — single long sprite |
| Bus | 24x12 | Existing from 05_sprites.md, add MTA blue+white livery variant |

Trains only need **2 directions** (not 8 like surface vehicles) since they follow fixed track geometry. Just flip horizontally for opposite direction.

### Platform Passengers

Reuse the existing pedestrian idle sprites from 05_sprites.md. Place them in a row on the platform rectangle with small random offsets.

### Station Entrance Indicators

Small stairway sprites on the surface layer marking subway entrances. When underground mode is active, these glow or pulse to show the connection between layers.

## Static Data Pre-Processing

Add to the existing `tools/` pipeline (see 06_integration.md):

```
tools/
  fetch_transit_routes.py    ← download static GTFS, extract shapes.txt
  project_transit.py         ← project route polylines to screen space
  extract_stations.py        ← station positions + platform geometry
  export_transit.json        ← output: route paths, station positions
```

### transit.json Schema

```json
{
  "routes": {
    "1": {
      "color": "#EE352E",
      "paths": {
        "N": [[px, py], [px, py], ...],
        "S": [[px, py], [px, py], ...]
      }
    },
    "A": { ... }
  },
  "stations": [
    {
      "id": "120",
      "name": "96 St",
      "lines": ["1", "2", "3"],
      "screenX": 12345,
      "screenY": 6789,
      "entrances": [
        { "screenX": 12340, "screenY": 6780, "type": "stairs" }
      ]
    }
  ]
}
```

Estimated size: ~500KB (gzipped ~80KB) for all subway routes in NYC.

## Polling Strategy

```typescript
// Poll cadence — match MTA update frequency, no faster
const SUBWAY_POLL_MS = 30_000   // feeds update every 30s
const BUS_POLL_MS = 30_000      // SIRI rate limit: 1 req / 30s

// Stagger subway feed requests to avoid burst
async function pollSubwayFeeds() {
  const feeds = ['gtfs', 'gtfs-ace', 'gtfs-bdfm', 'gtfs-g',
                 'gtfs-jz', 'gtfs-l', 'gtfs-nqrw', 'gtfs-si']
  // Fetch all in parallel (8 small requests, ~5-20KB each)
  return Promise.all(feeds.map(fetchSubwayFeed))
}

// Bus: only fetch routes visible in viewport to stay under rate limit
async function pollBusPositions(viewport: Viewport) {
  const visibleRoutes = getRoutesInViewport(viewport)
  // Pick top 3-5 routes by passenger volume
  const priority = visibleRoutes.slice(0, 5)
  return Promise.all(priority.map(r => fetchBusPositions(r.routeId)))
}
```

## Integration Touchpoints

This system connects to several existing plan documents:

| Document | Change Needed |
|---|---|
| **01_overview.md** | Add transit to Tier 2/3 scope |
| **02_renderer.md** | Add `UndergroundLayer` to layer architecture |
| **03_data_sources.md** | Add static GTFS as Source 5, MTA real-time as Source 6 |
| **04_simulation.md** | Add `TransitSystem`, `PlatformSystem`, `BusDataSystem` to Becsy world |
| **05_sprites.md** | Add train sprites, bus MTA livery variant, station entrance sprites |
| **06_integration.md** | Add `transit.json` to data pipeline, proxy server to project structure |
| **07_milestones.md** | Add transit milestones |

## Implementation Order

1. **Static subway map first** — download GTFS shapes, project to screen, render colored lines on underground layer with toggle. No real-time data yet. Validates the visual concept.
2. **Real-time train positions** — add proxy server, poll GTFS-RT feeds, spawn train entities, interpolate movement along route geometry.
3. **Station platforms + passengers** — add station markers, spawn waiting passengers when trains approach.
4. **Surface buses** — add bus API polling, reconcile with surface vehicle layer.
5. **Subway entrance connections** — pedestrians spawn from/despawn into subway entrances on the surface, connecting the two layers.
