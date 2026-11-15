/** Display adapters for the Python engines. No pathfinding or distance inference here. */
import { apiJSON, INDOOR_API_BASE, simulatedClosures } from '../../services/api';
import { normalizeIndoorMap } from './indoorModel';
import ilcDisplayTrace from '../../../../data/plan_wayfinding/sources/ilc/display-trace.json';

export function drawingDisplayMap(raw, portals = []) {
  const elevatorNodes = new Set(raw.connections.filter(e => e.kind === 'elevator').flatMap(e => [e.start, e.end]));
  const entryNodes = new Set(portals.filter(p => p.building_id === raw.building_id).map(p => p.indoor_node_id));
  const floors = [...new Set(raw.nodes.map(n => n.floor_id || raw.floor_id))].map(id => {
    const s = raw.floor_sources[id] || {};
    return {id, label: `Floor ${id}`, coordinate_system: 'image_pixels',
      image_width: Number(s.width) || 1000, image_height: Number(s.height) || 800,
      image_url: s.local_image ? `${INDOOR_API_BASE}/plan-wayfinding/${raw.building_id}/floors/${encodeURIComponent(id)}/image?file=floor.png` : null};
  });
  const nodes = raw.nodes.map((n, i) => ({...n, floor_id: n.floor_id || raw.floor_id,
    x: n.x ?? 100 + (i % 5) * 150, y: n.y ?? 150 + Math.floor(i / 5) * 100,
    kind: entryNodes.has(n.id) ? 'entrance' : elevatorNodes.has(n.id) ? 'elevator_stop' : n.kind || 'room'}));
  const byId = new Map(nodes.map(n => [n.id, n]));
  const edges = raw.connections.map(e => ({...e, length_m: null, bidirectional: true,
    geometry: e.kind === 'elevator' ? null : [e.start, e.end].map(id => [byId.get(id).x, byId.get(id).y])}));
  const model = normalizeIndoorMap({building_id: raw.building_id, name: raw.building_id,
    status: 'drawing_only', floors, nodes, edges, assets: [], portals: []}, {source: 'api'});
  if (!model) return null;
  // Normalizer is shared with measured maps. Its display-scale guesses are never
  // accepted as lengths/georeferences for a drawing graph.
  for (const floor of model.floors) {floor.georef = null; floor.pxPerM = null;}
  for (const floor of model.floors) {
    floor.routeAligned = raw.floor_sources[floor.id]?.route_overlay === 'original_mosaic_pixels';
    const trace = raw.building_id === ilcDisplayTrace.building_id ? ilcDisplayTrace.floors[floor.id] : null;
    if (floor.routeAligned && trace?.source_sha256 === raw.floor_sources[floor.id]?.source_sha256) {
      floor.vectorPlan = trace;
    }
  }
  for (const edge of model.edges) edge.lengthM = null;
  for (const room of model.rooms) room.door = 'unknown';
  model.routingKind = 'drawing'; model.raw = raw; model.residentAccessRequired = raw.resident_access_required;
  if (raw.building_id === 'ilc') model.name = 'Integrative Learning Center';
  model.sourceWarnings = raw.source_warnings || []; model.indoorGpsAvailable = false;
  return model;
}

export function measuredDisplayMap(raw) {
  const model = normalizeIndoorMap(raw, {source: 'api'});
  if (model) {
    model.routingKind = 'indoor'; model.raw = raw; model.indoorGpsAvailable = false;
    for (const room of model.rooms) {
      room.door = raw.edges.find(e => e.kind === 'door' && (e.start === room.id || e.end === room.id))?.door_type || 'unknown';
    }
  }
  return model;
}

export function targetNode(model, target) {
  const floor = /^(.+):@lobby$/.exec(target || '');
  const id = floor ? [...model.nodes.values()].find(n => n.floor === floor[1] && n.kind === 'elevator_stop')?.id : target;
  if (!id || !model.nodes.has(id)) throw new Error('Choose a mapped indoor landmark.');
  return id;
}

export function adaptIndoorDirections(model, wire, targetId) {
  const requested = targetNode(model, targetId);
  const endId = wire.node_path?.at(-1) || wire.steps?.at(-1)?.to_node_id || requested;
  if (!model.nodes.has(endId) || (!targetId.endsWith(':@lobby') && endId !== requested)) {
    throw new Error('The route ends at a different indoor destination.');
  }
  const end = model.nodes.get(endId);
  const room = model.rooms.find(r => r.id === endId) || {
    id: targetId, name: end.label, floor: end.floor, floorLabel: model.floorById.get(end.floor).label,
    x: end.px[0], y: end.px[1], type: 'lobby'};
  const paths = {};
  const push = (floor, points) => {if (points?.length) (paths[floor] ||= []).push(...points);};
  const steps = wire.steps.map((s, i) => {
    const from = model.nodes.get(s.from_node_id), to = model.nodes.get(s.to_node_id);
    const f = model.floorById.get(s.from_floor);
    if (!from || !to || !f) throw new Error('Route does not match the loaded floor map.');
    const geom = Array.isArray(s.geometry) ? s.geometry : s.geometry?.coordinates;
    const pts = s.kind === 'elevator' || !geom ? [from.px] : geom.map(p => f.toPx(p[0], p[1]));
    push(from.floor, pts); if (s.kind === 'elevator') push(to.floor, [to.px]);
    return {id: `backend-${i}`, fromNodeId: s.from_node_id, toNodeId: s.to_node_id, kind: s.kind === 'elevator' ? 'elevator' : s.kind === 'door' ? 'door' : 'straight',
      floor: from.floor, floorFrom: f.level, floorTo: model.floorById.get(to.floor).level,
      floorFromLabel: from.floor, floorToLabel: to.floor, surface: 'unknown',
      text: s.instruction, label: to.label, pts};
  });
  steps.push({id: 'arrive', kind: 'arrive', floor: end.floor, fromNodeId: endId, toNodeId: endId, text: `Arrive at ${room.name}.`, pts: [end.px]});
  push(end.floor, [end.px]);
  for (const floor of Object.keys(paths)) if (paths[floor].length === 1) paths[floor].push(paths[floor][0]);
  return {building: model.name, destination: room.name, room: {...room, doorX: end.px[0], doorY: end.px[1]},
    floors: Object.keys(paths), paths, steps, warnings: wire.warnings || [], backend: true};
}

export async function requestIndoorDirections(model, startId, targetId, closures, consent = {}) {
  const start = targetNode(model, startId), end = targetNode(model, targetId);
  const body = {start_node_id: start, end_node_id: end, closures: simulatedClosures(closures)};
  const wire = model.routingKind === 'drawing'
    ? await apiJSON(`/plan-wayfinding/${encodeURIComponent(model.id)}`, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...body, accept_drawing_only: true, resident_access_confirmed: consent.resident})})
    : await apiJSON('/indoor/route', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        ...body, building_id: model.id, max_grade: consent.preferences?.max_grade_pct ?? 5,
        no_stairs: true, need_automatic_door: !!consent.preferences?.need_automatic_door})});
  return adaptIndoorDirections(model, wire, targetId);
}
