# 04 — Simulation Systems

## Architecture: Becsy ECS

Using [Becsy](https://github.com/LastOliveGames/becsy) as the ECS framework. It supports string fields natively (via `Type.staticString` and `Type.dynamicString`), stores data in contiguous buffers for cache efficiency, and has built-in multithreading via Web Workers for scaling to thousands of entities.

### Why Becsy over bitECS
- **String support**: `currentEdge`, `spriteId`, `pathQueue` are all strings. bitECS only supports numeric typed arrays, requiring constant map lookups that negate its speed advantage.
- **Variable-length data**: Path queues (arrays of edge IDs) can't be stored in bitECS at all. Becsy handles object-type fields.
- **Multithreading**: Becsy can split systems across Web Workers. Traffic and pedestrian systems are independent and parallelizable.
- **Built-in system scheduling**: Declares read/write dependencies between systems, enabling automatic parallelization.

### Components

```typescript
import { component, Type, field } from '@lastolivegames/becsy'

@component class Position {
  @field(Type.float32) declare x: number    // world pixel position
  @field(Type.float32) declare y: number
}

@component class Movement {
  @field(Type.float32) declare speed: number     // pixels per second
  @field(Type.float32) declare heading: number   // radians
}

@component class PathFollower {
  @field(Type.dynamicString(64)) declare currentEdge: string  // road edge ID
  @field(Type.float32) declare edgeProgress: number           // 0..1 along edge
  @field(Type.object) declare pathQueue: string[]             // remaining edge IDs
}

@component class Renderable {
  @field(Type.dynamicString(32)) declare spriteId: string
}

@component class Vehicle {
  @field(Type.staticString([
    'sedan', 'taxi', 'suv', 'bus', 'delivery_van'
  ])) declare vehicleType: string
}

@component class Pedestrian {
  @field(Type.dynamicString(64)) declare destination: string
  @field(Type.float32) declare departureDelay: number
}

@component class EntityState {
  @field(Type.staticString([
    'moving', 'waiting_at_light', 'yielding', 'parking',
    'entering', 'exiting', 'idle'
  ])) declare state: string
}
```

### World Setup

```typescript
import { World } from '@lastolivegames/becsy'

const world = await World.create({
  maxEntities: 10_000,
  defs: [
    // systems (defined below)
    TrafficSystem, PedestrianSystem, TrafficLightSystem, SpawnSystem,
    // components registered automatically via system declarations
  ]
})

// Game loop
function tick(dt: number) {
  world.execute(dt)
}
```

### Spawning Entities

```typescript
function spawnVehicle(world: World, edge: string, vehicleType: string, spriteId: string) {
  world.createEntity(
    Position, { x: 0, y: 0 },
    Movement, { speed: 0, heading: 0 },
    PathFollower, { currentEdge: edge, edgeProgress: 0, pathQueue: [] },
    Renderable, { spriteId },
    Vehicle, { vehicleType },
    EntityState, { state: 'moving' },
  )
}

function spawnPedestrian(world: World, edge: string, destination: string) {
  world.createEntity(
    Position, { x: 0, y: 0 },
    Movement, { speed: 0, heading: 0 },
    PathFollower, { currentEdge: edge, edgeProgress: 0, pathQueue: [] },
    Renderable, { spriteId: 'ped_walk' },
    Pedestrian, { destination, departureDelay: 0 },
    EntityState, { state: 'moving' },
  )
}
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
import { system, System } from '@lastolivegames/becsy'

@system class TrafficSystem extends System {
  // Declare queries — Becsy auto-tracks matching entities
  vehicles = this.query(q => q.current.with(Vehicle, Position, Movement, PathFollower, EntityState))

  execute() {
    const dt = this.delta / 1000  // Becsy provides delta in ms

    for (const entity of this.vehicles.current) {
      const path = entity.read(PathFollower)
      const movement = entity.write(Movement)
      const pos = entity.write(Position)
      const state = entity.read(EntityState)

      if (state.state !== 'moving') continue

      const edge = roadGraph.edges.get(path.currentEdge)
      const maxSpeed = speedForRoadType(edge.highway)

      // Check car ahead (via spatial hash)
      const carAhead = findCarAheadOnEdge(entity, path.currentEdge)
      if (carAhead && distanceTo(carAhead, pos) < MIN_FOLLOWING_DISTANCE) {
        movement.speed = Math.max(0, movement.speed - DECEL * dt)
      } else {
        movement.speed = Math.min(maxSpeed, movement.speed + ACCEL * dt)
      }

      // Check traffic light at upcoming intersection
      if (approachingIntersection(path) && lightIsRed(path)) {
        movement.speed = Math.max(0, movement.speed - HARD_DECEL * dt)
      }

      // Advance along edge
      const pathW = entity.write(PathFollower)
      pathW.edgeProgress += (movement.speed * dt) / edge.length
      if (pathW.edgeProgress >= 1.0) {
        advanceToNextEdge(pathW)
      }

      // Update pixel position from edge progress
      const screenPos = interpolateEdge(edge.screenPath, pathW.edgeProgress)
      pos.x = screenPos[0]
      pos.y = screenPos[1]
      movement.heading = edgeHeadingAt(edge, pathW.edgeProgress)
    }
  }
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
@system class PedestrianSystem extends System {
  pedestrians = this.query(q => q.current.with(Pedestrian, Position, Movement, PathFollower, EntityState))

  execute() {
    const dt = this.delta / 1000

    for (const entity of this.pedestrians.current) {
      const state = entity.read(EntityState)
      if (state.state !== 'moving') continue

      const path = entity.read(PathFollower)
      const movement = entity.write(Movement)
      const pos = entity.write(Position)

      // Jitter: slight random offset perpendicular to path
      const jitter = (Math.random() - 0.5) * JITTER_AMOUNT

      // Crowd density check (via spatial hash)
      const density = getPedestrianDensity(path.currentEdge)
      const crowdFactor = Math.max(0.3, 1 - density * 0.1)

      movement.speed = BASE_WALK_SPEED * crowdFactor
      const pathW = entity.write(PathFollower)
      const edge = sidewalkGraph.edges.get(path.currentEdge)
      pathW.edgeProgress += (movement.speed * dt) / edge.length

      // Update position with jitter
      const basePos = interpolateEdge(edge.screenPath, pathW.edgeProgress)
      const perpX = -Math.sin(movement.heading) * jitter
      const perpY = Math.cos(movement.heading) * jitter
      pos.x = basePos[0] + perpX
      pos.y = basePos[1] + perpY
      movement.heading = edgeHeadingAt(edge, pathW.edgeProgress)
    }
  }
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
function spawnCrowdBurst(world: World, poi: POI, count: number) {
  for (let i = 0; i < count; i++) {
    const dest = pickRandomNearbyDestination(poi, 500)
    spawnPedestrian(world, poi.entranceEdge, dest)
    // Stagger departure via departureDelay field on Pedestrian component
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

With thousands of entities, naive collision/proximity checks are O(n^2). Use a spatial hash, rebuilt each frame:

```typescript
class SpatialHash {
  private cellSize: number = 64  // pixels
  private grid: Map<number, Entity[]> = new Map()  // int key for speed

  private key(x: number, y: number): number {
    return (Math.floor(x / this.cellSize) << 16) | (Math.floor(y / this.cellSize) & 0xFFFF)
  }

  insert(entity: Entity) {
    const k = this.key(entity.x, entity.y)
    let bucket = this.grid.get(k)
    if (!bucket) { bucket = []; this.grid.set(k, bucket) }
    bucket.push(entity)
  }

  queryRadius(x: number, y: number, radius: number): Entity[] {
    // Check cells within radius, return entities
  }

  clear() { this.grid.clear() }
}
```

The spatial hash is shared state accessed by both TrafficSystem and PedestrianSystem. In single-threaded mode, rebuild once per frame before systems run. If using Becsy's multithreading, the hash should be rebuilt in a dedicated system that runs before traffic/pedestrian systems (Becsy's scheduler handles ordering via read/write declarations).

## Simulation Budget

Target: entire simulation update in <8ms per frame (leaving 8ms for rendering at 60fps). Becsy's multithreading can split traffic + pedestrian systems across workers when needed.

| System | Budget (single-threaded) | Multithreaded |
|--------|--------------------------|---------------|
| Vehicle updates (2000 entities) | 3ms | ~1.5ms |
| Pedestrian updates (3000 entities) | 3ms | ~1.5ms |
| Spatial hash rebuild | 1ms | 1ms |
| Traffic light ticks | 0.1ms | 0.1ms |
| Spawn/despawn logic | 0.5ms | 0.5ms |
| **Total** | **~7.5ms** | **~4.5ms** |

### Scaling strategies for >5000 entities
- **LOD simulation**: Only fully simulate entities near the viewport. Distant entities update every 4th frame or use simplified movement (advance edgeProgress without car-following checks).
- **Multithreading**: Enable Becsy's Web Worker mode to parallelize TrafficSystem and PedestrianSystem.
- **Hybrid frequency**: Traffic lights and spawn logic run at 10Hz instead of 60Hz (timer accumulation).
