/**
 * The built-in sample layouts (floorPlans.js) as IndoorMap v1 documents, the same format the data
 * pipeline produces (contracts/indoor-map.schema.json). The app treats them exactly like a real map
 * file; a real map for the same building replaces them (see indoorCatalog.js).
 *
 * Every door of the outdoor building (mockBuildings.ts) becomes an entrance on the plan, so the indoor
 * route can start at whichever door the routing engine picked.
 */
import { BOTTOM_WALL_Y, FT_PER_PX, INDOOR_BUILDINGS, PLAN_H, PLAN_W, SPINE_Y, TOP_WALL_Y, X_MAX, X_MIN, floorPlanImage } from './floorPlans';
import { geoToPlan, planCalibration, planToGeo } from './floorCalibration';
import { UMASS_BUILDINGS } from '../../data/mockBuildings';

const M_PER_PX = FT_PER_PX * 0.3048;
const len = (a, b) => Math.round(Math.hypot(b[0] - a[0], b[1] - a[1]) * M_PER_PX * 10) / 10;
const doorType = (d) => (d === 'manual' ? 'manual' : d === 'push-button' ? 'push-button' : 'automatic');

/** Doors of the outdoor building, placed on the nearer long wall of the plan. */
function outdoorEntrances(id) {
  const b = UMASS_BUILDINGS.find((x) => x.id === id);
  const out = [];
  for (const e of b?.entrances ?? []) {
    const p = geoToPlan(id, e.lat, e.lng);
    if (!p || !p.every(Number.isFinite)) continue;
    const outside = Math.max(X_MIN - 20 - p[0], p[0] - (X_MAX + 20), TOP_WALL_Y - p[1], p[1] - BOTTOM_WALL_Y, 0);
    if (outside > 160) continue;
    out.push({
      id: `${id}-door-${e.id}`,
      x: Math.round(Math.max(X_MIN + 40, Math.min(X_MAX - 40, p[0]))),
      side: p[1] < SPINE_Y ? 'top' : 'bottom',
      name: e.name,
      door: doorType(e.door_type),
      stepFree: e.step_free !== false,
      position: { lat: e.lat, lng: e.lng }
    });
  }
  return out;
}

function sampleMap(b) {
  const cal = planCalibration(b.id);
  const bounds = cal ? { topLeft: cal.topLeft, bottomRight: cal.bottomRight } : undefined;
  const nodes = [];
  const edges = [];
  const assets = [];
  const elevatorStops = [];
  const node = (n) => (nodes.push(n), n);
  const edge = (e) => edges.push({ bidirectional: true, public_access: true, step_free: true, grade_percent: 0, width_m: 2, door_type: 'unknown', asset_id: null, source_id: 'sample', evidence: 'Sample layout', ...e });

  // Entrances: the outdoor doors on the entry floor, plus the plan's own door if none is close to it
  const doors = outdoorEntrances(b.id);
  const entryDef = b.floors.find((f) => f.id === b.entryFloor)?.entrance;
  if (entryDef && !doors.some((d) => Math.abs(d.x - entryDef.x) < 70 && d.side === 'bottom')) {
    const p = [entryDef.x, BOTTOM_WALL_Y];
    doors.push({ id: `${b.id}-door-default`, x: entryDef.x, side: 'bottom', name: entryDef.name, door: doorType(entryDef.door), stepFree: true, position: cal ? planToGeo(b.id, p) : null });
  }
  // Keep doors apart so their labels don't collide
  const placed = [];
  for (const d of doors.sort((a, z) => a.x - z.x)) if (!placed.some((q) => q.side === d.side && Math.abs(q.x - d.x) < 90)) placed.push(d);

  const floors = b.floors.map((f) => {
    const entrances = f.id === b.entryFloor ? placed : [];
    return {
      id: f.id,
      label: f.label,
      level: f.level,
      surface: f.surface,
      coordinate_system: 'image_pixels',
      image_url: floorPlanImage({ ...f, entrances }),
      image_width: PLAN_W,
      image_height: PLAN_H,
      bounds,
      source_id: 'sample',
      aliases: []
    };
  });

  for (const f of b.floors) {
    const entrances = f.id === b.entryFloor ? placed : [];
    // Junctions along the corridor at every doorway, the elevator and each entrance
    const xs = new Set([...f.rooms.filter((r) => r.type !== 'service').map((r) => Math.round(r.doorX)), ...entrances.map((e) => e.x)]);
    if (f.elevator) xs.add(Math.round(f.elevator.x));
    const junction = new Map();
    [...xs].sort((a, z) => a - z).forEach((x) => junction.set(x, node({ id: `${f.id}:j${x}`, label: 'Corridor', floor_id: f.id, kind: 'junction', x, y: SPINE_Y, position: null, aliases: [] })));
    const js = [...junction.values()];
    for (let i = 1; i < js.length; i++) edge({ id: `${f.id}:c${i}`, start: js[i - 1].id, end: js[i].id, kind: 'corridor', length_m: len([js[i - 1].x, SPINE_Y], [js[i].x, SPINE_Y]), geometry: [[js[i - 1].x, SPINE_Y], [js[i].x, SPINE_Y]] });

    for (const r of f.rooms) {
      if (r.type === 'service') continue;
      const j = junction.get(Math.round(r.doorX));
      node({ id: r.id, label: r.name, floor_id: f.id, kind: 'room', x: r.doorX, y: r.doorY, position: null, aliases: [], area: { x: r.x, y: r.y, w: r.w, h: r.h } });
      edge({ id: `${r.id}:door`, start: j.id, end: r.id, kind: 'door', door_type: r.door === 'manual' ? 'manual' : 'automatic', length_m: len([r.doorX, SPINE_Y], [r.doorX, r.doorY]), geometry: [[r.doorX, SPINE_Y], [r.doorX, r.doorY]] });
    }
    for (const e of entrances) {
      const y = e.side === 'top' ? TOP_WALL_Y : BOTTOM_WALL_Y;
      node({ id: e.id, label: e.name, floor_id: f.id, kind: 'entrance', x: e.x, y, position: e.position, aliases: [], door_type: e.door, step_free: e.stepFree });
      edge({ id: `${e.id}:in`, start: e.id, end: junction.get(e.x).id, kind: 'corridor', door_type: e.door, step_free: e.stepFree, length_m: len([e.x, y], [e.x, SPINE_Y]), geometry: [[e.x, y], [e.x, SPINE_Y]] });
    }
    if (f.elevator) {
      const el = f.elevator;
      const stop = node({ id: `${f.id}:elevator`, label: el.name, floor_id: f.id, kind: 'elevator_stop', x: el.x, y: el.y, position: null, aliases: [] });
      edge({ id: `${f.id}:to-elevator`, start: junction.get(Math.round(el.x)).id, end: stop.id, kind: 'corridor', length_m: len([el.x, SPINE_Y], [el.x, el.y]), geometry: [[el.x, SPINE_Y], [el.x, el.y]] });
      elevatorStops.push({ stop, level: f.level, name: el.name });
    }
  }

  // One elevator shaft linking the floors in level order
  const assetId = `${b.id}-elevator`;
  elevatorStops.sort((a, z) => a.level - z.level);
  if (elevatorStops.length > 1) {
    const s0 = elevatorStops[0].stop;
    assets.push({ id: assetId, label: elevatorStops[0].name, kind: 'elevator', position: cal ? planToGeo(b.id, [s0.x, s0.y]) : null, source_id: 'sample', aliases: [] });
    for (let i = 1; i < elevatorStops.length; i++) {
      edge({ id: `${assetId}:${i}`, start: elevatorStops[i - 1].stop.id, end: elevatorStops[i].stop.id, kind: 'elevator', asset_id: assetId, door_type: 'automatic', length_m: 4, geometry: null });
    }
  }

  return {
    version: 1,
    building_id: b.id,
    name: b.name,
    synthetic: true,
    status: 'reviewed',
    reviewed_at: null,
    review_notes: 'Built-in sample layout, not a surveyed plan.',
    entry_floor: b.entryFloor,
    sources: [{ id: 'sample', url: null, edition: 'sample', observed_at: null }],
    floors,
    nodes,
    assets,
    edges,
    portals: [],
    maneuvers: []
  };
}

/** All built-in sample maps, IndoorMap v1. */
export function sampleIndoorMaps() {
  return Object.values(INDOOR_BUILDINGS).map(sampleMap);
}
