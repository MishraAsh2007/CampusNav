/**
 * Step-free routing inside one building, on a model from indoorModel.js, plus turn-by-turn steps in the
 * shape the 2D map, 3D view and voice use:
 *   { id, kind: 'door'|'straight'|'turn-left'|'turn-right'|'elevator'|'arrive', floor, text, label,
 *     surface, distanceFt?, door?, floorFrom?, floorTo?, floorFromLabel?, floorToLabel?, pts: [x,y][] }
 *
 * Rules (same as the campus_routing indoor engine): no stairs, no edges marked not step-free or not
 * public; elevators that a closure marks out of service are skipped; manual doors cost extra so an
 * automatic one wins when there is a choice.
 */
import { inSentence, lobbyId } from './indoorModel';

const FT_PER_M = 3.28084;
const TURN_DEG = 35;
const MANUAL_DOOR_PENALTY_M = 25;
const ELEVATOR_PENALTY_M = 12;

const dist = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const ft = (m) => Math.max(5, Math.round((m * FT_PER_M) / 5) * 5);
const samePt = (a, b) => dist(a, b) < 0.5;

/** Elevators (asset ids) that closures put out of service. Matches asset_id, else elevator closures near the asset. */
export function closedAssets(model, closures = []) {
  const out = new Set();
  for (const c of closures) {
    if (c.status === 'repaired' || c.type !== 'elevator') continue;
    if (c.asset_id) {
      if (!c.building_id || c.building_id === model.id) out.add(c.asset_id);
      continue;
    }
    for (const [id, a] of model.assets) {
      if (!a.position) continue;
      const d = Math.hypot((a.position.lat - c.lat) * 110540, (a.position.lng - c.lng) * 111320 * Math.cos((c.lat * Math.PI) / 180));
      if (d <= Math.max(12, c.radius ?? 0)) out.add(id);
    }
  }
  return out;
}

function usable(edge, closed) {
  if (edge.kind === 'steps' || edge.step_free === false || edge.public_access === false) return false;
  if (edge.kind === 'elevator' && edge.asset_id && closed.has(edge.asset_id)) return false;
  return true;
}

function cost(edge) {
  let c = edge.lengthM;
  if (edge.door_type === 'manual') c += MANUAL_DOOR_PENALTY_M;
  if (edge.kind === 'elevator') c += ELEVATOR_PENALTY_M;
  return c;
}

/** Dijkstra from one node to the cheapest of several targets. Returns [{ node, edge }] or null. */
function shortestPath(model, from, targets, closed) {
  const goal = new Set(targets);
  if (!model.nodes.has(from) || !goal.size) return null;
  const best = new Map([[from, 0]]);
  const prev = new Map();
  const done = new Set();
  const queue = [[0, from]];
  while (queue.length) {
    let k = 0;
    for (let i = 1; i < queue.length; i++) if (queue[i][0] < queue[k][0]) k = i;
    const [d, id] = queue.splice(k, 1)[0];
    if (done.has(id)) continue;
    done.add(id);
    if (goal.has(id)) {
      const path = [{ node: id, edge: null }];
      let cur = id;
      while (prev.has(cur)) {
        const p = prev.get(cur);
        path[0].edge = p.edge;
        path.unshift({ node: p.from, edge: null });
        cur = p.from;
      }
      return path;
    }
    for (const { to, edge } of model.adj.get(id) ?? []) {
      if (done.has(to) || !usable(edge, closed)) continue;
      const nd = d + cost(edge);
      if (nd < (best.get(to) ?? Infinity)) {
        best.set(to, nd);
        prev.set(to, { from: id, edge });
        queue.push([nd, to]);
      }
    }
  }
  return null;
}

/** Target id -> node ids: a room node, or every elevator stop on a floor ("<floor>:@lobby"). */
export function targetNodes(model, targetId) {
  const m = /^(.+):@lobby$/.exec(targetId ?? '');
  if (m) return [...model.nodes.values()].filter((n) => n.floor === m[1] && n.kind === 'elevator_stop').map((n) => n.id);
  return model.nodes.has(targetId) ? [targetId] : [];
}

export function findTarget(model, targetId) {
  if (!model || !targetId) return null;
  const m = /^(.+):@lobby$/.exec(targetId);
  if (m) {
    const f = model.floorById.get(m[1]);
    const stop = [...model.nodes.values()].find((n) => n.floor === m[1] && n.kind === 'elevator_stop');
    return f && stop ? { id: targetId, name: `${f.label} elevator lobby`, floor: f.id, floorLabel: f.label, x: stop.px[0], y: stop.px[1], type: 'lobby', door: 'automatic' } : null;
  }
  return model.rooms.find((r) => r.id === targetId) ?? null;
}

/** Entrance the outdoor route ends at: the entrance node nearest to that lat/lng (within 60 m). */
export function entranceNear(model, lat, lng) {
  if (!model || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  let best = null;
  for (const e of model.entrances) {
    let d = Infinity;
    if (e.geo) d = Math.hypot((e.geo.lat - lat) * 110540, (e.geo.lng - lng) * 111320 * Math.cos((lat * Math.PI) / 180));
    else {
      const g = model.floorById.get(e.floor)?.georef;
      if (g) d = dist(g.toPx(lat, lng), e.px) * g.mPerPx;
    }
    if (d < 60 && (!best || d < best.d)) best = { e, d };
  }
  return best?.e ?? null;
}

/** Default entrance: step-free, automatic door preferred, on the entry floor. */
export function defaultEntrance(model) {
  const score = (e) => (e.stepFree ? 0 : 100) + (e.door === 'manual' ? 10 : 0) + (e.floor === model.entryFloor ? 0 : 5);
  return [...model.entrances].sort((a, b) => score(a) - score(b))[0] ?? null;
}

// ------------------------------------------------------------------ steps

function turnBetween(a, b, c) {
  const v1 = [b[0] - a[0], b[1] - a[1]];
  const v2 = [c[0] - b[0], c[1] - b[1]];
  const ang = (Math.atan2(v1[0] * v2[1] - v1[1] * v2[0], v1[0] * v2[0] + v1[1] * v2[1]) * 180) / Math.PI;
  if (Math.abs(ang) < TURN_DEG) return null;
  return ang > 0 ? 'turn-right' : 'turn-left'; // pixels are y-down
}

/** Split a polyline into straight legs at bends sharper than TURN_DEG. */
function legsOf(pts) {
  const clean = pts.filter((p, i) => i === 0 || !samePt(pts[i - 1], p));
  const legs = [];
  let cur = [clean[0]];
  for (let i = 1; i < clean.length; i++) {
    cur.push(clean[i]);
    if (i < clean.length - 1 && turnBetween(clean[i - 1], clean[i], clean[i + 1])) {
      legs.push(cur);
      cur = [clean[i]];
    }
  }
  if (cur.length > 1) legs.push(cur);
  return legs;
}

const sideWord = (heading, toPoint) => (heading[0] * toPoint[1] - heading[1] * toPoint[0] > 0 ? 'right' : 'left');

function edgePts(model, edge, fromId) {
  const a = model.nodes.get(edge.start).px;
  const b = model.nodes.get(edge.end).px;
  const g = edge.pxGeom ?? [a, b];
  return fromId === edge.start ? g : [...g].reverse();
}

/**
 * Route from a mapped node to a target.
 *   opts.entrance   entrance object (from model.entrances) -> starts with "Enter through the …"
 *   opts.closures   active closures (elevators out of service)
 */
export function routeIndoor(model, targetId, { entrance = null, startNode = null, closures = [] } = {}) {
  if (!model) return null;
  const room = findTarget(model, targetId);
  const targets = targetNodes(model, targetId);
  const start = entrance?.id ?? startNode ?? defaultEntrance(model)?.id;
  if (!room || !targets.length || !start) return null;
  const closed = closedAssets(model, closures);
  const path = shortestPath(model, start, targets, closed);
  if (!path) return { blocked: true, room, reason: closed.size ? 'An elevator on every step-free path is out of service.' : 'No step-free path reaches this room on the map.' };
  return renderPath(model, room, path, { entrance });
}

/** Draw the server's reviewed path using the same steps and map views as the Role 2 router. */
export function renderReviewedPath(model, targetId, result) {
  const room = findTarget(model, targetId);
  const path = result?.node_path?.map((node, index) => {
    if (!model.nodes.has(node)) return null;
    if (!index) return {node};
    const edge = model.adj.get(result.node_path[index - 1])?.find(
      item => item.to === node && item.edge.id === result.steps[index - 1]?.edge_id,
    )?.edge;
    return edge ? {node, edge} : null;
  });
  if (!room || !path?.length || path.some(item => !item)) return null;
  return {...renderPath(model, room, path), reviewedPath: result.node_path};
}

function renderPath(model, room, path, { entrance = null } = {}) {
  const start = path[0].node;
  const steps = [];
  const paths = {};
  let n = 0;
  const startN = model.nodes.get(start);
  const floorOf = (id) => model.floorById.get(model.nodes.get(id).floor);
  const surface = (f) => f?.surface ?? 'tile';
  const pushPath = (floorId, pts) => {
    const cur = (paths[floorId] ??= []);
    for (const p of pts) if (!cur.length || !samePt(cur[cur.length - 1], p)) cur.push(p);
  };

  const ent = entrance ?? (startN.kind === 'entrance' ? model.entrances.find((e) => e.id === start) : null);
  if (ent) {
    steps.push({
      id: `st${n++}`,
      kind: 'door',
      door: ent.door === 'manual' ? 'manual' : 'automatic',
      floor: startN.floor,
      surface: 'wet-tile',
      label: ent.name,
      text: `Enter through the ${inSentence(ent.name)}${ent.door === 'manual' ? ' (manual door)' : ent.door === 'automatic' || ent.door === 'push-button' ? ' using the push plate' : ''}.`,
      pts: [startN.px]
    });
  }

  // Group the path into runs: walking on one floor, or riding an elevator
  const runs = [];
  for (let i = 1; i < path.length; i++) {
    const edge = path[i].edge;
    const kind = edge.kind === 'elevator' ? 'ride' : 'walk';
    const last = runs[runs.length - 1];
    if (last && last.kind === kind && (kind === 'ride' || floorOf(path[i - 1].node).id === last.floor)) last.items.push({ from: path[i - 1].node, to: path[i].node, edge });
    else runs.push({ kind, floor: floorOf(path[i - 1].node).id, items: [{ from: path[i - 1].node, to: path[i].node, edge }] });
  }

  let prevHeading = null;
  let afterElevator = false;
  let lastPt = startN.px;

  runs.forEach((run, ri) => {
    const f = model.floorById.get(run.floor);
    if (run.kind === 'ride') {
      const a = model.nodes.get(run.items[0].from);
      const z = model.nodes.get(run.items[run.items.length - 1].to);
      const fa = model.floorById.get(a.floor);
      const fz = model.floorById.get(z.floor);
      const label = a.assetLabel ?? 'Elevator';
      steps.push({
        id: `st${n++}`,
        kind: 'elevator',
        floor: fa.id,
        floorFrom: fa.level,
        floorTo: fz.level,
        floorFromLabel: fa.id,
        floorToLabel: fz.id,
        surface: 'tile',
        label,
        text: `Take the ${inSentence(label)} ${fz.level > fa.level ? 'up' : 'down'} to ${fz.label}.`,
        pts: [a.px]
      });
      pushPath(fz.id, [z.px]);
      lastPt = z.px;
      prevHeading = null;
      afterElevator = true;
      return;
    }

    // Walking: one polyline for the run, then legs and turns
    const pts = [];
    const ramps = [];
    const manualDoors = [];
    for (const it of run.items) {
      const g = edgePts(model, it.edge, it.from);
      pts.push(...(pts.length ? g.slice(1) : g));
      if (it.edge.kind === 'ramp') ramps.push(g);
      if (it.edge.kind === 'door' && it.edge.door_type === 'manual' && model.nodes.get(it.to).kind !== 'room') manualDoors.push(it);
    }
    pushPath(f.id, pts);
    const legs = legsOf(pts);
    const isLastRun = ri === runs.length - 1;
    legs.forEach((leg, li) => {
      const a = leg[0];
      const b = leg[leg.length - 1];
      const heading = [b[0] - a[0], b[1] - a[1]];
      const metres = leg.reduce((s, p, i) => (i ? s + dist(leg[i - 1], p) : 0), 0) / f.pxPerM;
      // Leaving the elevator: the short hop into the corridor is noise; the next turn says where to go
      if (afterElevator && li === 0 && legs.length > 1 && metres < 4) {
        prevHeading = heading;
        lastPt = b;
        return;
      }
      // The last short leg into the room is described by the arrival step ("… is on your left")
      const finalStub = isLastRun && li === legs.length - 1 && legs.length > 1 && metres < 6;
      if (prevHeading && li > 0 && !finalStub) {
        const t = turnBetween([a[0] - prevHeading[0], a[1] - prevHeading[1]], a, b);
        const dir = t === 'turn-left' ? 'left' : 'right';
        if (t) steps.push({ id: `st${n++}`, kind: t, floor: f.id, surface: surface(f), label: 'Corridor', text: afterElevator ? `Leave the elevator and turn ${dir}.` : `Turn ${dir}.`, pts: [a] });
      }
      afterElevator = false;
      if (!finalStub && metres >= 1) {
        const onRamp = ramps.some((g) => leg.some((p) => g.some((q) => samePt(p, q))));
        steps.push({
          id: `st${n++}`,
          kind: 'straight',
          floor: f.id,
          surface: surface(f),
          distanceFt: ft(metres),
          label: 'Corridor',
          text: `Go straight ${ft(metres)} feet${onRamp ? ' along the ramp' : ''}.`,
          pts: [a, b]
        });
        prevHeading = heading;
      }
      lastPt = b;
    });
    for (const d of manualDoors) {
      const node = model.nodes.get(d.to);
      steps.push({ id: `st${n++}`, kind: 'door', door: 'manual', floor: f.id, surface: surface(f), label: 'Door', text: 'Go through the manual door ahead.', pts: [node.px] });
    }
  });

  // Arrival
  const endNode = model.nodes.get(path[path.length - 1].node);
  const endFloor = model.floorById.get(endNode.floor);
  if (room.door === 'manual' && room.type !== 'lobby') {
    steps.push({ id: `st${n++}`, kind: 'door', door: 'manual', floor: endNode.floor, surface: surface(endFloor), label: room.name, text: `The door to ${room.name} is a heavy manual door with no opener.`, pts: [endNode.px] });
  }
  let arriveText;
  if (room.type === 'lobby') arriveText = `You have arrived on ${endFloor.label}.`;
  else {
    const walk = paths[endNode.floor] ?? [];
    const k = walk.length;
    // Side: compare the corridor heading with the direction of the last stub into the room
    const corridor = k >= 3 ? [walk[k - 2][0] - walk[k - 3][0], walk[k - 2][1] - walk[k - 3][1]] : null;
    const stub = k >= 2 ? [walk[k - 1][0] - walk[k - 2][0], walk[k - 1][1] - walk[k - 2][1]] : null;
    const side = corridor && stub && Math.hypot(...corridor) > 1 && Math.abs(corridor[0] * stub[1] - corridor[1] * stub[0]) > 0.3 * Math.hypot(...corridor) * Math.hypot(...stub) ? sideWord(corridor, stub) : null;
    arriveText = side ? `${room.name} is on your ${side}. You have arrived.` : `You have arrived at ${room.name}.`;
  }
  steps.push({ id: `st${n++}`, kind: 'arrive', floor: endNode.floor, surface: surface(endFloor), label: room.name, text: arriveText, pts: [endNode.px] });

  // Every floor on the route needs at least a 2-point path for the map
  for (const [fid, pts] of Object.entries(paths)) if (pts.length === 1) paths[fid] = [pts[0], pts[0]];
  return { building: model.name, destination: room.name, room: { ...room, doorX: endNode.px[0], doorY: endNode.px[1] }, floors: Object.keys(paths), paths, steps };
}

/** Nearest routable node to a point on the floor plan. */
export function nearestNode(model, floorId, point) {
  let best = null;
  for (const n of model.nodes.values()) {
    if (n.floor !== floorId || n.kind === 'room') continue;
    if (!(model.adj.get(n.id) ?? []).length) continue;
    const d = dist(n.px, point);
    if (!best || d < best.d) best = { id: n.id, d };
  }
  return best?.id ?? null;
}

export { lobbyId };
