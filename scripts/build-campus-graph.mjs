#!/usr/bin/env node
/**
 * Builds public/data/campusGraph.json: the real UMass Amherst central-campus pedestrian
 * network used by the in-browser fallback router.
 *
 *   Walkways, stairs (with step counts), surfaces, covered passages, kerbs: OpenStreetMap (Overpass API)
 *   Elevation at every intersection:                                        USGS 3DEP 1 m lidar (EPQS)
 *   Elevators / indoor connectors:                                          scripts/curated-connectors.json
 *
 * Usage:  node scripts/build-campus-graph.mjs            (uses scripts/cache/* when present)
 *         node scripts/build-campus-graph.mjs --refresh  (re-downloads OSM; elevation cache is kept)
 *
 * OSM data © OpenStreetMap contributors (ODbL). USGS 3DEP is public domain.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CACHE = path.join(ROOT, 'scripts', 'cache');
const OSM_CACHE = path.join(CACHE, 'osm.json');
const ELEV_CACHE = path.join(CACHE, 'elevation.json');
const CURATED = path.join(ROOT, 'scripts', 'curated-connectors.json');
const OUT = path.join(ROOT, 'frontend', 'public', 'data', 'campusGraph.json');
const REFRESH = process.argv.includes('--refresh');

// South, West, North, East: central campus from Southwest/Boyden to Worcester/Hasbrouck
const BBOX = [42.3850, -72.5330, 42.3945, -72.5230];

fs.mkdirSync(CACHE, { recursive: true });

// ---------- helpers ----------
const R = 6371e3;
function haversine(lat1, lng1, lat2, lng2) {
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dp = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lng2 - lng1) * Math.PI) / 180;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
const r6 = (x) => Math.round(x * 1e6) / 1e6;
const r1 = (x) => Math.round(x * 10) / 10;
const r2 = (x) => Math.round(x * 100) / 100;

// ---------- 1. OSM ----------
async function loadOsm() {
  if (!REFRESH && fs.existsSync(OSM_CACHE)) return JSON.parse(fs.readFileSync(OSM_CACHE, 'utf8'));
  const bbox = BBOX.join(',');
  const q = `[out:json][timeout:90];
(
  way["highway"~"^(footway|path|pedestrian|steps|service|corridor)$"](${bbox});
);
out body; >; out body qt;`;
  console.log('Downloading OSM walkways from Overpass...');
  const res = await fetch('https://overpass-api.de/api/interpreter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'CampusNav/1.0 (HackUMass 2026)' },
    body: 'data=' + encodeURIComponent(q)
  });
  if (!res.ok) throw new Error(`Overpass HTTP ${res.status}`);
  const data = await res.json();
  fs.writeFileSync(OSM_CACHE, JSON.stringify(data));
  return data;
}

function surfaceClass(s) {
  if (!s) return 'u';
  if (['asphalt', 'concrete', 'paved', 'concrete:plates', 'metal', 'wood', 'concrete:lanes', 'rubber'].includes(s)) return 's'; // smooth
  if (['paving_stones', 'bricks', 'sett', 'cobblestone', 'unhewn_cobblestone', 'grass_paver'].includes(s)) return 'b'; // bumpy
  return 'x'; // unpaved: gravel, dirt, earth, grass...
}

// ---------- 2. elevation ----------
async function fetchElevations(points) {
  const cache = fs.existsSync(ELEV_CACHE) ? JSON.parse(fs.readFileSync(ELEV_CACHE, 'utf8')) : {};
  const key = (p) => `${p[0].toFixed(6)},${p[1].toFixed(6)}`;
  const todo = points.filter((p) => cache[key(p)] === undefined);
  console.log(`Elevation: ${points.length - todo.length} cached, ${todo.length} to fetch from USGS 3DEP...`);
  let done = 0;
  const CONCURRENCY = 12;
  let cursor = 0;
  async function worker() {
    while (cursor < todo.length) {
      const p = todo[cursor++];
      for (let attempt = 0; attempt < 4; attempt++) {
        try {
          const url = `https://epqs.nationalmap.gov/v1/json?x=${p[1]}&y=${p[0]}&units=Meters&wkid=4326&includeDate=false`;
          const ctrl = new AbortController();
          const t = setTimeout(() => ctrl.abort(), 20000);
          const r = await fetch(url, { signal: ctrl.signal });
          clearTimeout(t);
          const j = await r.json();
          const v = parseFloat(j.value);
          if (Number.isFinite(v) && v > 0) {
            cache[key(p)] = r2(v);
            break;
          }
        } catch {
          await new Promise((res) => setTimeout(res, 800 * (attempt + 1)));
        }
      }
      done++;
      if (done % 100 === 0) {
        console.log(`  ${done}/${todo.length}`);
        fs.writeFileSync(ELEV_CACHE, JSON.stringify(cache));
      }
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  fs.writeFileSync(ELEV_CACHE, JSON.stringify(cache));
  return points.map((p) => cache[key(p)]);
}

// ---------- 3. build ----------
const osm = await loadOsm();
const osmNodes = new Map();
for (const e of osm.elements) if (e.type === 'node') osmNodes.set(e.id, e);

const ways = osm.elements.filter((e) => {
  if (e.type !== 'way' || !e.tags) return false;
  const t = e.tags;
  if (['private', 'no'].includes(t.access) && t.foot !== 'yes') return false;
  if (t.foot === 'no') return false;
  if (t.highway === 'service' && ['parking_aisle', 'drive-through'].includes(t.service)) return false;
  if (t.area === 'yes') return false;
  return true;
});

// Vertices = way endpoints + nodes shared by 2+ ways
const usage = new Map();
for (const w of ways) for (const id of w.nodes) usage.set(id, (usage.get(id) || 0) + 1);
const isVertex = (w, i) => i === 0 || i === w.nodes.length - 1 || usage.get(w.nodes[i]) > 1;

const rawEdges = [];
for (const w of ways) {
  let start = 0;
  for (let i = 1; i < w.nodes.length; i++) {
    if (!isVertex(w, i)) continue;
    const ids = w.nodes.slice(start, i + 1);
    if (ids.every((id) => osmNodes.has(id)) && ids[0] !== ids[ids.length - 1]) rawEdges.push({ way: w, ids });
    start = i;
  }
}

// Keep the largest connected component
const parent = new Map();
const find = (x) => {
  while (parent.get(x) !== x) {
    parent.set(x, parent.get(parent.get(x)));
    x = parent.get(x);
  }
  return x;
};
for (const e of rawEdges) {
  for (const id of [e.ids[0], e.ids[e.ids.length - 1]]) if (!parent.has(id)) parent.set(id, id);
  const a = find(e.ids[0]);
  const b = find(e.ids[e.ids.length - 1]);
  if (a !== b) parent.set(a, b);
}
const compSize = new Map();
for (const id of parent.keys()) compSize.set(find(id), (compSize.get(find(id)) || 0) + 1);
const mainRoot = [...compSize.entries()].sort((a, b) => b[1] - a[1])[0][0];
const edgesMain = rawEdges.filter((e) => find(e.ids[0]) === mainRoot);
console.log(`OSM: ${ways.length} walkable ways -> ${rawEdges.length} edges, main component keeps ${edgesMain.length}`);

// Index vertices
const vIndex = new Map();
const vertices = [];
for (const e of edgesMain) {
  for (const id of [e.ids[0], e.ids[e.ids.length - 1]]) {
    if (!vIndex.has(id)) {
      const n = osmNodes.get(id);
      vIndex.set(id, vertices.length);
      vertices.push([r6(n.lat), r6(n.lon)]);
    }
  }
}

const elev = await fetchElevations(vertices);
const missing = elev.filter((v) => v === undefined).length;
if (missing) console.warn(`WARNING: ${missing} vertices have no elevation; their grade is treated as 0.`);

function edgeRecord(e) {
  const t = e.way.tags;
  const pts = e.ids.map((id) => osmNodes.get(id));
  let d = 0;
  for (let i = 1; i < pts.length; i++) d += haversine(pts[i - 1].lat, pts[i - 1].lon, pts[i].lat, pts[i].lon);
  const a = vIndex.get(e.ids[0]);
  const b = vIndex.get(e.ids[e.ids.length - 1]);
  const ea = elev[a];
  const eb = elev[b];
  let rise = ea !== undefined && eb !== undefined ? eb - ea : 0;
  // The 3DEP DEM is bare-earth: bridges, decks and tunnels are not in it. Treat those as level.
  const layer = parseInt(String(t.layer || '0').split(';')[0], 10) || 0;
  if (t.highway !== 'steps' && (t.bridge && t.bridge !== 'no' || layer !== 0 || (t.tunnel && t.tunnel !== 'no'))) rise = 0;
  const kind =
    t.highway === 'steps' ? 'steps'
    : t.footway === 'crossing' ? 'crossing'
    : t.highway === 'service' ? 'service'
    : t.highway === 'pedestrian' ? 'pedestrian'
    : t.highway === 'path' ? 'path'
    : 'footway';
  const rec = { a, b, d: r1(Math.max(d, 0.5)), r: r2(rise), k: kind };
  const s = surfaceClass(t.surface);
  if (s !== 'u') rec.s = s;
  if (t.covered && t.covered !== 'no') rec.c = 1;
  if (t.tunnel && t.tunnel !== 'no') rec.c = 1;
  if (t.indoor === 'yes' || t.highway === 'corridor') rec.c = 1;
  if (t.name) rec.n = t.name;
  else if (t.footway === 'sidewalk') rec.n = 'sidewalk';
  if (kind === 'steps') {
    const sc = parseInt(t.step_count, 10);
    rec.sc = Number.isFinite(sc) ? sc : Math.max(3, Math.round(Math.abs(rise) / 0.17) || Math.round(d / 0.35));
    if (t.handrail === 'yes') rec.hr = 1;
  }
  if (t.wheelchair) rec.wc = t.wheelchair;
  if (t.incline && /%/.test(t.incline)) rec.inc = parseFloat(t.incline);
  // Raised kerbs on any node of this edge are a hard barrier for wheels
  if (pts.some((p) => p.tags?.barrier === 'kerb' && p.tags?.kerb === 'raised') || pts.some((p) => p.tags?.kerb === 'raised')) rec.kr = 1;
  if (pts.length > 2) rec.g = pts.slice(1, -1).map((p) => [r6(p.lat), r6(p.lon)]);
  rec.osm = e.way.id;
  return rec;
}

const edges = edgesMain.map(edgeRecord);

// ---------- 4. curated connectors (elevators, indoor routes) ----------
const curated = fs.existsSync(CURATED) ? JSON.parse(fs.readFileSync(CURATED, 'utf8')) : { connectors: [] };
function nearestVertex(lat, lng) {
  let best = -1;
  let bd = Infinity;
  for (let i = 0; i < vertices.length; i++) {
    const dd = haversine(lat, lng, vertices[i][0], vertices[i][1]);
    if (dd < bd) {
      bd = dd;
      best = i;
    }
  }
  return { index: best, dist: bd };
}
for (const c of curated.connectors) {
  const A = nearestVertex(c.from[0], c.from[1]);
  const B = nearestVertex(c.to[0], c.to[1]);
  if (A.dist > 25 || B.dist > 25) console.warn(`Connector ${c.id}: snapped ${A.dist.toFixed(0)}m / ${B.dist.toFixed(0)}m from requested points`);
  const rise = (elev[B.index] ?? 0) - (elev[A.index] ?? 0);
  const rec = {
    a: A.index,
    b: B.index,
    d: c.length_m ?? r1(haversine(...vertices[A.index], ...vertices[B.index]) + 10),
    r: c.kind === 'elevator' ? 0 : r2(rise),
    k: c.kind,
    n: c.name,
    c: 1,
    s: 's',
    id: c.id
  };
  if (c.via) rec.g = c.via.map((p) => [r6(p[0]), r6(p[1])]);
  edges.push(rec);
  console.log(`Connector ${c.id}: v${A.index} (${elev[A.index]}m) <-> v${B.index} (${elev[B.index]}m), rise ${r2(rise)}m`);
}

const stepsCount = edges.filter((e) => e.k === 'steps').length;
const out = {
  meta: {
    generated: new Date().toISOString(),
    bbox: BBOX,
    sources: ['OpenStreetMap contributors (ODbL) via Overpass API', 'USGS 3DEP 1 m lidar via EPQS', 'CampusNav curated indoor connectors'],
    vertices: vertices.length,
    edges: edges.length,
    staircases: stepsCount,
    total_steps: edges.filter((e) => e.k === 'steps').reduce((s, e) => s + (e.sc || 0), 0),
    walkway_km: r1(edges.reduce((s, e) => s + e.d, 0) / 1000)
  },
  v: vertices.map((p, i) => [p[0], p[1], elev[i] ?? 0]),
  e: edges
};
fs.writeFileSync(OUT, JSON.stringify(out));
console.log(`Wrote ${path.relative(ROOT, OUT)}: ${out.meta.vertices} vertices, ${out.meta.edges} edges, ${stepsCount} staircases (${out.meta.total_steps} steps), ${out.meta.walkway_km} km, ${(fs.statSync(OUT).size / 1024).toFixed(0)} KB`);
