/**
 * In-browser fallback router for CampusNav.
 *
 * Runs on the real UMass central-campus pedestrian network (src/data/campusGraph.json, built by
 * scripts/build-campus-graph.mjs from OpenStreetMap walkways + USGS 1 m lidar elevation).
 * Same request/response contract as the Role 1 Python engine, so the UI does not care which one answered.
 */
import type {
  AvoidedBarrier,
  Closure,
  RouteGeoJSONFeature,
  RouteResponse,
  RouteStep,
  StepIcon,
  UserPreferences
} from '../types';

// ---------- graph types ----------

export interface RawEdge {
  a: number;
  b: number;
  d: number; // length m
  r: number; // rise a->b in m
  k: 'footway' | 'steps' | 'crossing' | 'service' | 'pedestrian' | 'path' | 'elevator' | 'indoor';
  s?: 's' | 'b' | 'x'; // smooth / bumpy (pavers, brick) / unpaved
  c?: 1; // covered / indoor
  n?: string;
  sc?: number; // step count
  hr?: 1; // handrail
  wc?: string; // OSM wheelchair=*
  inc?: number; // OSM numeric incline
  kr?: 1; // raised kerb
  g?: [number, number][]; // interior geometry [lat, lng]
  osm?: number;
  id?: string; // curated connector id
}

export interface CampusGraph {
  meta: { vertices: number; edges: number; staircases: number; total_steps: number; walkway_km: number; sources: string[] };
  v: [number, number, number][]; // lat, lng, elevation m
  e: RawEdge[];
  adj: number[][]; // vertex -> edge indices
  grade: Float32Array; // absolute grade % per edge
}

let graphPromise: Promise<CampusGraph> | null = null;
let graphSync: CampusGraph | null = null;

export function prepareGraph(raw: Omit<CampusGraph, 'adj' | 'grade'>): CampusGraph {
  const adj: number[][] = raw.v.map(() => []);
  const grade = new Float32Array(raw.e.length);
  raw.e.forEach((e, i) => {
    adj[e.a].push(i);
    adj[e.b].push(i);
    grade[i] = edgeGrade(e);
  });
  return { ...raw, adj, grade };
}

export function loadCampusGraph(): Promise<CampusGraph> {
  if (!graphPromise) {
    // Served from public/ so the 270 KB graph is fetched once and cached instead of bundled
    graphPromise = fetch(`${import.meta.env.BASE_URL}data/campusGraph.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`campusGraph.json HTTP ${r.status}`);
        return r.json() as Promise<Omit<CampusGraph, 'adj' | 'grade'>>;
      })
      .then((raw) => {
        graphSync = prepareGraph(raw);
        return graphSync;
      })
      .catch((err) => {
        graphPromise = null; // allow a retry
        throw err;
      });
  }
  return graphPromise;
}

export function getLoadedGraph(): CampusGraph | null {
  return graphSync;
}

function edgeGrade(e: RawEdge): number {
  if (e.k === 'steps' || e.k === 'elevator') return 0;
  if (typeof e.inc === 'number' && Number.isFinite(e.inc)) return Math.min(Math.abs(e.inc), 30);
  // Short edges amplify lidar noise at kerbs; measure them over at least 6 m.
  return Math.min((Math.abs(e.r) / Math.max(e.d, 6)) * 100, 30);
}

// ---------- geometry ----------

export function getDistanceMeters(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371e3;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dp = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function bearing(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const y = Math.sin(((lng2 - lng1) * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180);
  const x =
    Math.cos((lat1 * Math.PI) / 180) * Math.sin((lat2 * Math.PI) / 180) -
    Math.sin((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.cos(((lng2 - lng1) * Math.PI) / 180);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

/** Distance from point P to segment AB in meters (equirectangular, fine at campus scale). */
function pointToSegmentMeters(plat: number, plng: number, alat: number, alng: number, blat: number, blng: number): number {
  const kx = 111320 * Math.cos((plat * Math.PI) / 180);
  const ky = 110540;
  const ax = (alng - plng) * kx;
  const ay = (alat - plat) * ky;
  const bx = (blng - plng) * kx;
  const by = (blat - plat) * ky;
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  return Math.sqrt(cx * cx + cy * cy);
}

/** Edge polyline as [lat, lng] in the a->b direction. */
function edgeLatLngs(G: CampusGraph, e: RawEdge): [number, number][] {
  const A = G.v[e.a];
  const B = G.v[e.b];
  return [[A[0], A[1]], ...(e.g ?? []), [B[0], B[1]]];
}

function edgeMinDistance(G: CampusGraph, e: RawEdge, lat: number, lng: number): number {
  const pts = edgeLatLngs(G, e);
  let best = Infinity;
  for (let i = 1; i < pts.length; i++) {
    best = Math.min(best, pointToSegmentMeters(lat, lng, pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]));
  }
  return best;
}

// ---------- closures ----------

interface ClosureIndex {
  blocked: Map<number, Closure>; // edge index -> closure
  degraded: Map<number, Closure>;
}

function indexClosures(G: CampusGraph, closures: Closure[]): ClosureIndex {
  const blocked = new Map<number, Closure>();
  const degraded = new Map<number, Closure>();
  for (const c of closures) {
    if (c.status === 'repaired') continue;
    // Road work that leaves the sidewalk open affects buses, not walkers
    if (c.affects === 'road') continue;
    const target = c.status === 'closed' ? blocked : degraded;
    if (c.connector_id) {
      G.e.forEach((e, i) => {
        if (e.id === c.connector_id) target.set(i, c);
      });
      continue;
    }
    if (c.type === 'elevator') {
      // Backend reports may drop connector_id: close the nearest elevator within reach instead of the sidewalk.
      let best = -1;
      let bd = Math.max(30, c.radius);
      G.e.forEach((e, i) => {
        if (e.k !== 'elevator') return;
        const d = edgeMinDistance(G, e, c.lat, c.lng);
        if (d < bd) {
          bd = d;
          best = i;
        }
      });
      if (best >= 0) target.set(best, c);
      continue;
    }
    // Automatic-door issues affect the entrance, not the walkway.
    if (c.type === 'automatic_door') continue;
    const radius = Math.max(4, c.radius);
    G.e.forEach((e, i) => {
      if (e.k === 'elevator') return; // elevators are only closed by connector id
      if (edgeMinDistance(G, e, c.lat, c.lng) <= radius) target.set(i, c);
    });
  }
  return { blocked, degraded };
}

// ---------- cost model ----------

export type RouteMode = 'accessible' | 'standard';

function makeCost(G: CampusGraph, prefs: UserPreferences, mode: RouteMode, idx: ClosureIndex | null) {
  const wheels = prefs.wheelchair_required || prefs.mobility_preset === 'stroller';
  const noStairs = prefs.wheelchair_required || prefs.no_stairs;
  const maxG = Math.max(1, prefs.max_grade_pct);

  return (ei: number): number => {
    const e = G.e[ei];
    if (mode === 'standard') return e.k === 'elevator' ? e.d + 25 : e.d;

    if (idx?.blocked.has(ei)) return Infinity;
    let cost = e.d;

    if (e.k === 'steps') {
      if (noStairs) return Infinity;
      if (prefs.handrails_required && !e.hr) return Infinity;
      cost = e.d * 2 + (e.sc ?? 10) * 1.5;
    } else if (e.k === 'elevator') {
      cost = e.d + 25; // waiting for the car
    } else {
      if (wheels && (e.kr || e.wc === 'no')) return Infinity;
      const g = G.grade[ei];
      if (g > maxG) {
        if (prefs.wheelchair_required) return Infinity;
        cost *= 4;
      } else {
        cost *= 1 + (g / maxG) ** 2 * 0.8;
      }
      if (e.s === 'x') cost *= wheels || prefs.avoid_rough_surfaces ? 3.5 : 1.2;
      else if (e.s === 'b' && prefs.avoid_rough_surfaces) cost *= 1.5;
      if (e.k === 'service') cost *= 1.25;
      if (e.k === 'crossing') cost += prefs.minimize_crossings ? 45 : 6;
    }

    if (prefs.prefer_indoor && e.c) cost *= 0.75;
    if (idx?.degraded.has(ei)) cost *= wheels ? 4 : 1.5;
    return cost;
  };
}

// ---------- search ----------

class MinHeap {
  private k: number[] = [];
  private v: number[] = [];
  get size() {
    return this.k.length;
  }
  push(key: number, val: number) {
    const k = this.k;
    const v = this.v;
    k.push(key);
    v.push(val);
    let i = k.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (k[p] <= k[i]) break;
      [k[p], k[i]] = [k[i], k[p]];
      [v[p], v[i]] = [v[i], v[p]];
      i = p;
    }
  }
  pop(): [number, number] {
    const k = this.k;
    const v = this.v;
    const top: [number, number] = [k[0], v[0]];
    const lk = k.pop()!;
    const lv = v.pop()!;
    if (k.length) {
      k[0] = lk;
      v[0] = lv;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < k.length && k[l] < k[m]) m = l;
        if (r < k.length && k[r] < k[m]) m = r;
        if (m === i) break;
        [k[m], k[i]] = [k[i], k[m]];
        [v[m], v[i]] = [v[i], v[m]];
        i = m;
      }
    }
    return top;
  }
}

export interface Endpoint {
  lat: number;
  lng: number;
  label: string;
  /** Extra cost (m) for picking this endpoint, e.g. a less convenient entrance. */
  penalty?: number;
  id?: string;
}

interface Anchor {
  vertex: number;
  offset: number; // walking metres between endpoint and vertex
  endpoint: Endpoint;
}

function anchorsFor(G: CampusGraph, ep: Endpoint, cost: (ei: number) => number): Anchor[] {
  const cands: { i: number; d: number }[] = [];
  for (let i = 0; i < G.v.length; i++) {
    const d = getDistanceMeters(ep.lat, ep.lng, G.v[i][0], G.v[i][1]);
    if (d < 120) cands.push({ i, d });
  }
  cands.sort((x, y) => x.d - y.d);
  // Only snap to vertices about as close as the nearest usable one, otherwise a route could
  // "teleport" past a staircase by walking a straight line off-network.
  const out: Anchor[] = [];
  let limit = Infinity;
  for (const c of cands) {
    if (c.d > limit) break;
    if (G.adj[c.i].some((ei) => Number.isFinite(cost(ei)))) {
      if (!out.length) limit = Math.min(c.d + 6, 70);
      out.push({ vertex: c.i, offset: c.d, endpoint: ep });
      if (out.length >= 3) break;
    }
  }
  return out;
}

interface SearchResult {
  edges: { ei: number; forward: boolean }[];
  start: Anchor;
  end: Anchor;
  cost: number;
}

function search(G: CampusGraph, starts: Anchor[], ends: Anchor[], cost: (ei: number) => number): SearchResult | null {
  if (!starts.length || !ends.length) return null;
  const n = G.v.length;
  const dist = new Float64Array(n).fill(Infinity);
  const prevEdge = new Int32Array(n).fill(-1);
  const startOf = new Int32Array(n).fill(-1);
  const endBy = new Map<number, Anchor[]>();
  for (const a of ends) {
    const list = endBy.get(a.vertex) ?? [];
    list.push(a);
    endBy.set(a.vertex, list);
  }
  const heap = new MinHeap();
  starts.forEach((s, si) => {
    const c = s.offset * 1.2 + (s.endpoint.penalty ?? 0);
    if (c < dist[s.vertex]) {
      dist[s.vertex] = c;
      startOf[s.vertex] = si;
      heap.push(c, s.vertex);
    }
  });

  let best: { total: number; end: Anchor } | null = null;
  while (heap.size) {
    const [d, u] = heap.pop();
    if (d > dist[u]) continue;
    if (best && d >= best.total) break;
    const endsHere = endBy.get(u);
    if (endsHere) {
      for (const a of endsHere) {
        const total = d + a.offset * 1.2 + (a.endpoint.penalty ?? 0);
        if (!best || total < best.total) best = { total, end: a };
      }
    }
    for (const ei of G.adj[u]) {
      const w = cost(ei);
      if (!Number.isFinite(w)) continue;
      const e = G.e[ei];
      const v = e.a === u ? e.b : e.a;
      const nd = d + w;
      if (nd < dist[v]) {
        dist[v] = nd;
        prevEdge[v] = ei;
        startOf[v] = startOf[u];
        heap.push(nd, v);
      }
    }
  }
  if (!best) return null;

  // Walk back until we reach a seeded start vertex (prevEdge -1)
  const edges: { ei: number; forward: boolean }[] = [];
  let cur = best.end.vertex;
  let guard = 0;
  while (prevEdge[cur] !== -1 && guard++ < n) {
    const ei = prevEdge[cur];
    const e = G.e[ei];
    const from = e.a === cur ? e.b : e.a;
    edges.unshift({ ei, forward: e.a === from });
    cur = from;
  }
  const seedCost = (s: Anchor) => s.offset * 1.2 + (s.endpoint.penalty ?? 0);
  const start =
    starts.filter((s) => s.vertex === cur).sort((x, y) => seedCost(x) - seedCost(y))[0] ??
    starts[Math.max(0, startOf[best.end.vertex])];
  return { edges, start, end: best.end, cost: best.total };
}

// ---------- describing a path ----------

export interface Landmark {
  name: string;
  lat: number;
  lng: number;
}

const PACE_MPS: Record<UserPreferences['mobility_preset'], number> = {
  manual_wheelchair: 1.0,
  power_wheelchair: 1.3,
  walker_cane: 0.75,
  crutches: 0.8,
  stroller: 1.15,
  low_vision: 1.0,
  custom: 1.1
};

function nearestLandmark(landmarks: Landmark[], lat: number, lng: number, within = 70): string | null {
  let best: string | null = null;
  let bd = within;
  for (const l of landmarks) {
    const d = getDistanceMeters(lat, lng, l.lat, l.lng);
    if (d < bd) {
      bd = d;
      best = l.name;
    }
  }
  return best;
}

function cardinal(b: number): string {
  return ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest'][Math.round(b / 45) % 8];
}

interface Leg {
  ei: number;
  e: RawEdge;
  to: number; // vertex reached at the end of this leg
  pts: [number, number][]; // lat,lng in travel direction
  rise: number;
  grade: number; // signed % in travel direction
  startBearing: number;
  endBearing: number;
}

function describe(
  G: CampusGraph,
  res: SearchResult,
  prefs: UserPreferences,
  landmarks: Landmark[],
  originLabel: string,
  destLabel: string
): RouteResponse {
  const legs: Leg[] = res.edges.map(({ ei, forward }) => {
    const e = G.e[ei];
    const pts = edgeLatLngs(G, e);
    if (!forward) pts.reverse();
    const rise = forward ? e.r : -e.r;
    const g = G.grade[ei] * Math.sign(rise || 0);
    const n = pts.length;
    return {
      ei,
      e,
      to: forward ? e.b : e.a,
      pts,
      rise,
      grade: g,
      startBearing: bearing(pts[0][0], pts[0][1], pts[1][0], pts[1][1]),
      endBearing: bearing(pts[n - 2][0], pts[n - 2][1], pts[n - 1][0], pts[n - 1][1])
    };
  });

  // Full line, including the short walk from endpoints onto the network
  const startLL: [number, number] = [res.start.endpoint.lat, res.start.endpoint.lng];
  const endLL: [number, number] = [res.end.endpoint.lat, res.end.endpoint.lng];
  const sv = G.v[res.start.vertex];
  const ev = G.v[res.end.vertex];

  // Features: merge consecutive legs of the same class
  const features: RouteGeoJSONFeature[] = [];
  const classOf = (l: Leg) => (l.e.k === 'steps' ? 'steps' : l.e.k === 'elevator' ? 'elevator' : l.grade && Math.abs(l.grade) >= 5 ? 'steep' : 'walk');
  const toLngLat = (p: [number, number]): [number, number] => [p[1], p[0]];
  const pushFeature = (cls: string, coords: [number, number][], ls: Leg[]) => {
    features.push({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: coords },
      properties: {
        grade: Math.round(Math.max(0, ...ls.map((l) => Math.abs(l.grade))) * 10) / 10,
        surface: ls[0]?.e.s === 'b' ? 'pavers' : ls[0]?.e.s === 'x' ? 'unpaved' : 'paved',
        is_step: cls === 'steps',
        is_ramp: cls === 'steep',
        is_elevator: cls === 'elevator',
        is_indoor: ls.some((l) => !!l.e.c),
        step_count: cls === 'steps' ? ls.reduce((s, l) => s + (l.e.sc ?? 0), 0) : undefined,
        segment_name: ls.find((l) => l.e.n && l.e.n !== 'sidewalk')?.e.n ?? cls
      }
    });
  };
  {
    let cls = legs.length ? classOf(legs[0]) : 'walk';
    let coords: [number, number][] = [toLngLat(startLL), [sv[1], sv[0]]];
    let group: Leg[] = [];
    for (const l of legs) {
      const c = classOf(l);
      if (c !== cls && group.length) {
        pushFeature(cls, coords, group);
        coords = [coords[coords.length - 1]];
        group = [];
        cls = c;
      }
      group.push(l);
      for (let i = 1; i < l.pts.length; i++) coords.push(toLngLat(l.pts[i]));
    }
    coords.push([ev[1], ev[0]], toLngLat(endLL));
    pushFeature(cls, coords, group);
  }

  // Metrics
  let dist = res.start.offset + res.end.offset;
  let maxGrade = 0;
  let gradeWeighted = 0;
  let gain = 0;
  let stairs = 0;
  let rough = 0;
  let covered = 0;
  const elevators: string[] = [];
  const profile: { d: number; z: number }[] = [{ d: 0, z: sv[2] }];
  let acc = res.start.offset;
  profile.push({ d: acc, z: sv[2] });
  for (const l of legs) {
    dist += l.e.d;
    if (l.e.k === 'steps') stairs += l.e.sc ?? 0;
    else if (l.e.k === 'elevator') elevators.push(l.e.n ?? 'Elevator');
    else {
      const g = Math.abs(l.grade);
      maxGrade = Math.max(maxGrade, g);
      gradeWeighted += g * l.e.d;
      if (l.rise > 0) gain += l.rise;
    }
    if (l.e.s === 'b' || l.e.s === 'x') rough += l.e.d;
    if (l.e.c) covered += l.e.d;
    acc += l.e.d;
    profile.push({ d: Math.round(acc), z: G.v[l.to][2] });
  }
  profile.push({ d: Math.round(dist), z: ev[2] });

  const steps = buildSteps(legs, landmarks, originLabel, destLabel, res);
  const pace = PACE_MPS[prefs.mobility_preset] ?? 1.1;
  const duration = dist / pace + elevators.length * 45 + stairs * 0.6;

  return {
    type: 'FeatureCollection',
    summary: {
      total_distance_m: Math.round(dist),
      total_duration_s: Math.round(duration),
      max_grade_pct: Math.round(maxGrade * 10) / 10,
      avg_grade_pct: legs.length ? Math.round((gradeWeighted / Math.max(1, dist)) * 10) / 10 : 0,
      elevation_gain_m: Math.round(gain * 10) / 10,
      is_step_free: stairs === 0,
      stair_count: stairs,
      warnings: [],
      engine: 'local',
      elevators_used: elevators,
      rough_surface_m: Math.round(rough),
      covered_m: Math.round(covered)
    },
    features,
    steps,
    profile
  };
}

function turnWord(delta: number): { word: string; icon: StepIcon } | null {
  const a = Math.abs(delta);
  if (a < 30) return null;
  const left = delta < 0;
  if (a < 60) return { word: left ? 'Bear left' : 'Bear right', icon: left ? 'slight-left' : 'slight-right' };
  if (a < 150) return { word: left ? 'Turn left' : 'Turn right', icon: left ? 'turn-left' : 'turn-right' };
  return { word: 'Turn around', icon: left ? 'turn-left' : 'turn-right' };
}

function buildSteps(legs: Leg[], landmarks: Landmark[], originLabel: string, destLabel: string, res: SearchResult): RouteStep[] {
  interface Group {
    legs: Leg[];
    kind: 'walk' | 'steps' | 'elevator' | 'crossing';
    turn: { word: string; icon: StepIcon } | null;
  }
  const kindOf = (l: Leg): Group['kind'] =>
    l.e.k === 'steps' ? 'steps' : l.e.k === 'elevator' ? 'elevator' : l.e.k === 'crossing' ? 'crossing' : 'walk';
  const groups: Group[] = [];
  for (const l of legs) {
    const k = kindOf(l);
    const g = groups[groups.length - 1];
    const prev = g?.legs[g.legs.length - 1];
    let delta = prev ? ((l.startBearing - prev.endBearing + 540) % 360) - 180 : 0;
    const groupLen = g ? g.legs.reduce((s, x) => s + x.e.d, 0) : 0;
    const turn = prev ? turnWord(delta) : null;
    const named = l.e.n && l.e.n !== 'sidewalk' ? l.e.n : null;
    const prevNamed = prev?.e.n && prev.e.n !== 'sidewalk' ? prev.e.n : null;
    const newGroup =
      !g ||
      k !== g.kind ||
      k !== 'walk' ||
      (turn && groupLen > 12) ||
      (named && prevNamed && named !== prevNamed);
    if (newGroup) {
      groups.push({ legs: [l], kind: k, turn });
    } else {
      g.legs.push(l);
      delta = 0;
    }
  }
  // Fold tiny walking groups into their neighbour so the list stays readable
  const merged: Group[] = [];
  for (const g of groups) {
    const len = g.legs.reduce((s, l) => s + l.e.d, 0);
    const last = merged[merged.length - 1];
    if (last && g.kind === 'walk' && last.kind === 'walk' && len < 15) {
      last.legs.push(...g.legs);
    } else {
      merged.push(g);
    }
  }

  const steps: RouteStep[] = [];
  merged.forEach((g, i) => {
    const d = Math.round(g.legs.reduce((s, l) => s + l.e.d, 0));
    const first = g.legs[0];
    const mid = first.pts[Math.floor(first.pts.length / 2)];
    const at: [number, number] = [first.pts[0][1], first.pts[0][0]];
    const name = g.legs.find((l) => l.e.n && l.e.n !== 'sidewalk')?.e.n;
    const lm = nearestLandmark(landmarks, mid[0], mid[1]);
    const covered = g.legs.every((l) => l.e.c);
    const maxG = Math.max(0, ...g.legs.map((l) => Math.abs(l.grade)));
    const netRise = g.legs.reduce((s, l) => s + l.rise, 0);

    if (g.kind === 'steps') {
      const sc = g.legs.reduce((s, l) => s + (l.e.sc ?? 0), 0);
      const hr = g.legs.every((l) => l.e.hr);
      steps.push({
        instruction: `Take the stairs ${netRise >= 0 ? 'up' : 'down'}${lm ? ` by ${lm}` : ''} (${sc} steps${hr ? ', handrail' : ', no handrail'})`,
        distance_m: d,
        grade_pct: 0,
        icon: 'stairs',
        at
      });
      return;
    }
    if (g.kind === 'elevator') {
      steps.push({
        instruction: `Take the ${first.e.n ?? 'elevator'} ${netRise >= 0 ? 'up' : 'down'}`,
        distance_m: d,
        grade_pct: 0,
        icon: 'elevator',
        accessible_landmark: first.e.n,
        is_indoor: true,
        at
      });
      return;
    }
    if (g.kind === 'crossing') {
      steps.push({
        instruction: `Cross ${name ? name : 'the street'} at the crosswalk`,
        distance_m: d,
        grade_pct: Math.round(maxG * 10) / 10,
        icon: 'crossing',
        at
      });
      return;
    }

    let lead: string;
    let icon: StepIcon = 'straight';
    if (i === 0) {
      lead = `Head ${cardinal(first.startBearing)} from ${res.start.endpoint.label || originLabel}`;
      icon = 'start';
    } else if (g.turn) {
      lead = g.turn.word;
      icon = g.turn.icon;
    } else {
      lead = 'Continue';
    }
    let text = lead;
    if (name) text += `${i === 0 ? ' along' : ' onto'} ${name}`;
    else if (lm && i > 0) text += ` past ${lm}`;
    text += ` for ${d} m`;
    if (maxG >= 4) {
      const up = netRise >= 0;
      text += `, ${up ? 'uphill' : 'downhill'} up to ${maxG.toFixed(1)}%`;
      if (icon === 'straight') icon = up ? 'ramp-up' : 'ramp-down';
    }
    if (covered) text += ' (covered)';
    steps.push({ instruction: text, distance_m: d, grade_pct: Math.round(maxG * 10) / 10, icon, is_indoor: covered, at });
  });

  steps.push({
    instruction: `Arrive at ${res.end.endpoint.label || destLabel}`,
    distance_m: 0,
    grade_pct: 0,
    icon: 'destination',
    at: [res.end.endpoint.lng, res.end.endpoint.lat]
  });
  return steps;
}

// ---------- public API ----------

export interface RouteQuery {
  /** Endpoints usable with the person's needs (e.g. step-free entrances only). */
  starts: Endpoint[];
  ends: Endpoint[];
  /** Endpoints a regular map would use (any entrance). Defaults to starts/ends. */
  standardStarts?: Endpoint[];
  standardEnds?: Endpoint[];
  originLabel: string;
  destLabel: string;
  prefs: UserPreferences;
  closures: Closure[];
  landmarks: Landmark[];
}

export interface RouteBundle {
  accessible: RouteResponse | null;
  standard: RouteResponse | null;
  /** Why no accessible route exists, when it does not. */
  failure?: string;
  /** The chosen destination entrance id, if any. */
  endEndpointId?: string;
  startEndpointId?: string;
}

function routeEdgeSet(r: SearchResult | null): Set<number> {
  return new Set(r?.edges.map((x) => x.ei) ?? []);
}

export function computeRoutes(G: CampusGraph, q: RouteQuery): RouteBundle {
  const t0 = performance.now();
  const idx = indexClosures(G, q.closures);
  const accCost = makeCost(G, q.prefs, 'accessible', idx);
  const accCostNoClosures = makeCost(G, q.prefs, 'accessible', null);
  const stdCost = makeCost(G, q.prefs, 'standard', null);

  const accRes = search(G, q.starts.flatMap((s) => anchorsFor(G, s, accCost)), q.ends.flatMap((e) => anchorsFor(G, e, accCost)), accCost);
  // A "regular map" route: shortest walk, stairs welcome, no idea what is broken today.
  const stdStarts = (q.standardStarts ?? q.starts).map((s) => ({ ...s, penalty: 0 }));
  const stdEnds = (q.standardEnds ?? q.ends).map((e) => ({ ...e, penalty: 0 }));
  const stdRes = search(G, stdStarts.flatMap((s) => anchorsFor(G, s, stdCost)), stdEnds.flatMap((e) => anchorsFor(G, e, stdCost)), stdCost);
  // Same needs, but pretending everything works: tells us what today's outages cost.
  const idealRes = q.closures.length
    ? search(G, q.starts.flatMap((s) => anchorsFor(G, s, accCostNoClosures)), q.ends.flatMap((e) => anchorsFor(G, e, accCostNoClosures)), accCostNoClosures)
    : accRes;

  const standard = stdRes ? describe(G, stdRes, { ...q.prefs, mobility_preset: 'custom' }, q.landmarks, q.originLabel, q.destLabel) : null;
  let accessible = accRes ? describe(G, accRes, q.prefs, q.landmarks, q.originLabel, q.destLabel) : null;

  if (accessible && accRes) {
    const accSet = routeEdgeSet(accRes);
    const avoided: AvoidedBarrier[] = [];

    // Stairs and steep bits on the regular route that we skipped
    if (stdRes) {
      let run: { sc: number; at: [number, number] } | null = null;
      const flush = () => {
        if (run && run.sc > 0) {
          const lm = nearestLandmark(q.landmarks, run.at[1], run.at[0], 90);
          avoided.push({ kind: 'stairs', label: `${run.sc} steps${lm ? ` by ${lm}` : ''}`, at: run.at, step_count: run.sc });
        }
        run = null;
      };
      for (const { ei } of stdRes.edges) {
        const e = G.e[ei];
        if (e.k === 'steps' && !accSet.has(ei)) {
          const A = G.v[e.a];
          if (!run) run = { sc: 0, at: [A[1], A[0]] };
          run.sc += e.sc ?? 0;
        } else {
          flush();
          if (e.k !== 'elevator' && G.grade[ei] > q.prefs.max_grade_pct && e.d > 8 && !accSet.has(ei)) {
            const A = G.v[e.a];
            avoided.push({ kind: 'steep', label: `${G.grade[ei].toFixed(1)}% slope`, at: [A[1], A[0]], grade_pct: G.grade[ei] });
          }
        }
      }
      flush();
    }

    // Outages that changed our route
    const closuresAvoided: string[] = [];
    if (idealRes && idealRes !== accRes) {
      for (const { ei } of idealRes.edges) {
        const c = idx.blocked.get(ei) ?? idx.degraded.get(ei);
        if (c && !closuresAvoided.includes(c.title) && !accSet.has(ei)) {
          closuresAvoided.push(c.title);
          avoided.push({ kind: 'closure', label: c.title, at: [c.lng, c.lat] });
        }
      }
    }
    const warnings: string[] = [];
    if (closuresAvoided.length && idealRes) {
      const ideal = describe(G, idealRes, q.prefs, q.landmarks, q.originLabel, q.destLabel);
      const extraM = accessible.summary.total_distance_m - ideal.summary.total_distance_m;
      const extraMin = Math.round((accessible.summary.total_duration_s - ideal.summary.total_duration_s) / 60);
      warnings.push(
        `Rerouted around ${closuresAvoided.join(' and ')}` +
          (extraM > 5 ? ` (+${extraM} m${extraMin >= 1 ? `, about ${extraMin} min` : ''})` : '')
      );
    }
    // Degraded spots we still pass through
    for (const { ei } of accRes.edges) {
      const c = idx.degraded.get(ei);
      if (c && !warnings.some((w) => w.includes(c.title))) warnings.push(`Passes ${c.title}. Reported ${c.source === 'community' ? 'by students' : 'officially'}.`);
    }
    if ((accessible.summary.rough_surface_m ?? 0) > 60 && q.prefs.avoid_rough_surfaces) {
      warnings.push(`${accessible.summary.rough_surface_m} m of brick or paver surface could not be avoided.`);
    }

    accessible = {
      ...accessible,
      avoided: avoided.slice(0, 8),
      summary: { ...accessible.summary, warnings, closures_avoided: closuresAvoided, compute_ms: Math.round((performance.now() - t0) * 10) / 10 }
    };
  }

  let failure: string | undefined;
  if (!accRes) {
    failure = q.prefs.wheelchair_required
      ? `No route stays under ${q.prefs.max_grade_pct}% slope without stairs or raised kerbs.`
      : `No route matches your current needs.`;
    if (idealRes && q.closures.length) failure = `Today's outages cut off every step-free route to this destination.`;
  }

  if (standard) {
    const w: string[] = [];
    if ((standard.summary.stair_count ?? 0) > 0) w.push(`${standard.summary.stair_count} steps on this route.`);
    if (standard.summary.max_grade_pct !== null && standard.summary.max_grade_pct > q.prefs.max_grade_pct) w.push(`Slopes up to ${standard.summary.max_grade_pct}%.`);
    standard.summary.warnings = w;
  }

  return {
    accessible,
    standard,
    failure,
    endEndpointId: accRes?.end.endpoint.id ?? stdRes?.end.endpoint.id,
    startEndpointId: accRes?.start.endpoint.id ?? stdRes?.start.endpoint.id
  };
}
