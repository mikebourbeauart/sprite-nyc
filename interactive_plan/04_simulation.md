# 04 — Simulation Systems

## Architecture: Entity-Component-System (Lightweight)

No need for a full ECS framework. A simple loop with typed arrays:

```typescript
interface Entity {
  id: number
  type: 'car' | 'pedestrian' | 'bus' | 'taxi'
  x: number           // world pixel position
  y: number
  speed: number       // pixels per second
  heading: number     // radians
  currentEdge: string // road edge ID
  edgeProgress: number // 0..1 along edge
  pathQueue: string[] // remaining edge IDs to traverse
  state: EntityState
  spriteId: string    // which sprite variant to render
}

type EntityState =
  | 'moving'
  | 'waiting_at_light'
  | 'yielding'
  | 'parking'       // cars only
  | 'entering'      // pedestrians entering building
  | 'exiting'       // pedestrians leaving building
  | 'idle'          // pedestrians standing
```

## System 1: Traffic

### Vehicle Lifecycle

```
Spawn at road edge node (map boundary or parking spot)
  │
  ▼
Pick random destination (another edge node)
  │
  ▼
A* shortest path through road graph
  │
  ▼
Follow path: ──► move along edge ──► reach intersection ──►
  │                                        │
  │              ┌─────────────────────────┘
  │              ▼
  │        Check traffic light
  │        ├── green → proceed
  │        ├── red → stop and wait
  │        └── no light → yield if needed
  │              │
  │              ▼
  │        Turn onto next edge
  │              │
  └──────────────┘
  │
  ▼
Reach destination → despawn (or park + become idle)
```

### Traffic Lights

```typescript
interface TrafficLight {
  intersectionId: string
  phases: TrafficPhase[]
  currentPhase: number
  timer: number  // seconds remaining in current phase
}

interface TrafficPhase {
  greenEdges: string[]   // edges that have green
  duration: number       // seconds
}
```

Default cycle: 30s green, 5s yellow, 30s green (perpendicular). Derived from intersection topology — the two most-perpendicular road groups alternate.

### Car-Following Model

Simple: each car checks distance to the car ahead on the same lane. If too close, decelerate. If far, accelerate up to road speed limit.

```typescript
function updateVehicle(entity: Entity, dt: number, graph: RoadGraph) {
  const edge = graph.edges.get(entity.currentEdge)
  const maxSpeed = speedForRoadType(edge.highway) // px/s

  // Check car ahead
  const carAhead = findCarAheadOnEdge(entity)
  if (carAhead && distanceTo(carAhead) < MIN_FOLLOWING_DISTANCE) {
    entity.speed = Math.max(0, entity.speed - DECEL * dt)
  } else {
    entity.speed = Math.min(maxSpeed, entity.speed + ACCEL * dt)
  }

  // Check traffic light at upcoming intersection
  if (approachingIntersection(entity) && lightIsRed(entity)) {
    entity.speed = Math.max(0, entity.speed - HARD_DECEL * dt)
  }

  // Advance along edge
  entity.edgeProgress += (entity.speed * dt) / edge.length
  if (entity.edgeProgress >= 1.0) {
    advanceToNextEdge(entity)
  }

  // Update pixel position from edge progress
  const pos = interpolateEdge(edge.screenPath, entity.edgeProgress)
  entity.x = pos[0]
  entity.y = pos[1]
  entity.heading = edgeHeadingAt(edge, entity.edgeProgress)
}
```

### Road Speed Defaults

| Road Type | Real Speed | Pixel Speed (~) |
|-----------|-----------|----------------|
| motorway | 55 mph | 80 px/s |
| primary | 30 mph | 45 px/s |
| secondary | 25 mph | 35 px/s |
| residential | 20 mph | 25 px/s |
| service | 10 mph | 15 px/s |

(Pixel speeds are approximate — tuned to look natural at default zoom.)

### Vehicle Types & Distribution

| Type | % of traffic | Behavior |
|------|-------------|----------|
| Sedan | 40% | Standard pathfinding |
| Taxi (yellow) | 25% | Occasionally stops at buildings |
| SUV/Truck | 15% | Slightly slower, wider sprite |
| Bus | 10% | Follows fixed routes, stops at bus stops |
| Delivery van | 10% | Parks in loading zones briefly |

## System 2: Pedestrians

### Pedestrian Lifecycle

```
Spawn at building entrance (or subway entrance, or map edge)
  │
  ▼
Pick destination:
  ├── nearby building (70%)
  ├── nearby POI / shop (20%)
  └── subway entrance / map edge (10%)
  │
  ▼
Walk along sidewalks (A* on sidewalk graph)
  │
  ├── At crosswalk → wait for walk signal, then cross
  │
  ▼
Arrive at destination → enter building (fade out) → despawn after delay
```

### Sidewalk Movement

Pedestrians don't follow strict graph edges like cars. Instead:

1. **Coarse path**: A* on sidewalk graph (node = sidewalk intersection, edge = sidewalk segment)
2. **Fine movement**: Add small random lateral offset so pedestrians don't walk in a perfect line
3. **Crowd behavior**: If density on a sidewalk segment is high, slow down

```typescript
function updatePedestrian(entity: Entity, dt: number) {
  // Jitter: slight random offset perpendicular to path
  const jitter = (Math.random() - 0.5) * JITTER_AMOUNT

  // Crowd density check
  const density = getPedestrianDensity(entity.currentEdge)
  const crowdFactor = Math.max(0.3, 1 - density * 0.1)

  entity.speed = BASE_WALK_SPEED * crowdFactor
  entity.edgeProgress += (entity.speed * dt) / edgeLength

  // Apply jitter perpendicular to heading
  const perpX = -Math.sin(entity.heading) * jitter
  const perpY = Math.cos(entity.heading) * jitter
  entity.x = baseX + perpX
  entity.y = baseY + perpY
}
```

### Crosswalk Behavior

When a pedestrian's path crosses a road:
1. Walk to crosswalk point
2. Check traffic light phase — if walk signal, proceed; otherwise wait
3. Cross the road (slightly faster than normal walk speed)
4. Resume sidewalk path

### Crowd Clusters

At popular POIs (subway exits, Times Square, etc.), spawn bursts of 10–20 pedestrians that disperse in different directions. This creates natural-looking crowd pulses.

```typescript
function spawnCrowdBurst(poi: POI, count: number) {
  for (let i = 0; i < count; i++) {
    const ped = spawnPedestrian(poi.entrance)
    ped.destination = pickRandomNearbyDestination(poi, radius: 500)
    // Stagger departure so they don't all move at once
    ped.departureDelay = Math.random() * 3.0 // seconds
  }
}
```

## System 3: Day/Night Cycle (Tier 2+)

Optional ambient system:

```typescript
interface DayNightCycle {
  timeOfDay: number       // 0–24 (hours, continuous)
  speed: number           // real seconds per sim hour
  ambientTint: number     // hex color applied to tile layer
  spawnRateMultiplier: number // fewer cars/peds at night
}

// Tint ramp
const TINTS = [
  { hour: 0,  tint: 0x1a1a3e, spawn: 0.1 },  // midnight
  { hour: 6,  tint: 0xffa366, spawn: 0.3 },  // dawn
  { hour: 8,  tint: 0xffffff, spawn: 1.0 },  // morning rush
  { hour: 12, tint: 0xffffff, spawn: 0.8 },  // midday
  { hour: 17, tint: 0xffffff, spawn: 1.0 },  // evening rush
  { hour: 19, tint: 0xff8844, spawn: 0.6 },  // sunset
  { hour: 21, tint: 0x2a2a5e, spawn: 0.3 },  // night
]
```

At night, building windows could randomly light up using small yellow/warm sprite overlays on building footprints.

## Spatial Indexing

With 500+ entities, naive collision/proximity checks are O(n^2). Use a spatial hash:

```typescript
class SpatialHash {
  private cellSize: number = 64  // pixels
  private grid: Map<string, Entity[]> = new Map()

  insert(entity: Entity) {
    const key = `${Math.floor(entity.x / this.cellSize)},${Math.floor(entity.y / this.cellSize)}`
    // ...
  }

  queryRadius(x: number, y: number, radius: number): Entity[] {
    // Check cells within radius, return entities
  }
}
```

Rebuild the hash each frame (cheap for <2000 entities).

## Simulation Budget

Target: entire simulation update in <4ms per frame (leaving 12ms for rendering at 60fps).

| System | Budget |
|--------|--------|
| Vehicle updates (200 entities) | 1ms |
| Pedestrian updates (300 entities) | 1ms |
| Spatial hash rebuild | 0.5ms |
| Traffic light ticks | 0.1ms |
| Spawn/despawn logic | 0.3ms |
| **Total** | **~3ms** |

If performance is tight, reduce entity count or simulate distant entities at lower frequency (every 4th frame).
