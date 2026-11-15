#!/usr/bin/env node
/**
 * Builds public/data/busRoutes.json: PVTA bus routes that run through central campus, clipped to campus.
 * The UI uses it to name the bus routes a road closure blocks.
 *
 *   node scripts/build-bus-routes.mjs            (uses scripts/cache/bus-osm.json when present)
 *   node scripts/build-bus-routes.mjs --refresh
 *
 * Route data © OpenStreetMap contributors (ODbL).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CACHE = path.join(ROOT, 'scripts', 'cache', 'bus-osm.json');
const OUT = path.join(ROOT, 'frontend', 'public', 'data', 'busRoutes.json');
const REFRESH = process.argv.includes('--refresh');
// Same box as the walkway graph, slightly padded
const [S, W, N, E] = [42.3840, -72.5345, 42.3955, -72.5215];

async function loadOsm() {
  if (!REFRESH && fs.existsSync(CACHE)) return JSON.parse(fs.readFileSync(CACHE, 'utf8'));
  const q = `[out:json][timeout:90];
relation["type"="route"]["route"="bus"](${S},${W},${N},${E});
out body;
way(r)(${S},${W},${N},${E});
out body geom;`;
  console.log('Downloading bus routes from Overpass...');
  const res = await fetch('https://overpass-api.de/api/interpreter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'CampusNav/1.0 (HackUMass 2026)' },
    body: 'data=' + encodeURIComponent(q)
  });
  if (!res.ok) throw new Error(`Overpass HTTP ${res.status}`);
  const data = await res.json();
  fs.mkdirSync(path.dirname(CACHE), { recursive: true });
  fs.writeFileSync(CACHE, JSON.stringify(data));
  return data;
}

const inBox = (p) => p.lat >= S && p.lat <= N && p.lon >= W && p.lon <= E;
const r6 = (x) => Math.round(x * 1e6) / 1e6;

const osm = await loadOsm();
const ways = new Map(osm.elements.filter((e) => e.type === 'way').map((w) => [w.id, w]));
const relations = osm.elements.filter((e) => e.type === 'relation' && e.tags?.ref);

// Merge both directions of a route under one ref
const byRef = new Map();
for (const r of relations) {
  const ref = r.tags.ref.trim();
  const entry = byRef.get(ref) ?? { ref, name: r.tags.name ?? `Route ${ref}`, operator: r.tags.operator ?? r.tags.network ?? 'PVTA', wayIds: new Set() };
  for (const m of r.members ?? []) if (m.type === 'way' && ways.has(m.ref)) entry.wayIds.add(m.ref);
  byRef.set(ref, entry);
}

// Store each road segment once, and the refs that use it
const segments = new Map(); // way id -> { name, path, refs }
for (const entry of byRef.values()) {
  for (const id of entry.wayIds) {
    const w = ways.get(id);
    const pts = (w.geometry ?? []).filter(inBox);
    if (pts.length < 2) continue;
    const seg = segments.get(id) ?? { name: w.tags?.name ?? null, path: pts.map((p) => [r6(p.lat), r6(p.lon)]), refs: new Set() };
    seg.refs.add(entry.ref);
    segments.set(id, seg);
  }
}

const routes = [...byRef.values()]
  .filter((r) => [...segments.values()].some((s) => s.refs.has(r.ref)))
  .map((r) => ({ ref: r.ref, name: r.name, operator: r.operator }))
  .sort((a, b) => a.ref.localeCompare(b.ref, undefined, { numeric: true }));

const out = {
  meta: { generated: new Date().toISOString(), source: 'OpenStreetMap contributors (ODbL) via Overpass API', bbox: [S, W, N, E] },
  routes,
  segments: [...segments.values()].map((s) => ({ name: s.name, refs: [...s.refs].sort(), path: s.path }))
};
fs.writeFileSync(OUT, JSON.stringify(out));
console.log(`Wrote ${path.relative(ROOT, OUT)}: ${routes.length} routes (${routes.map((r) => r.ref).join(', ')}), ${out.segments.length} road segments, ${(fs.statSync(OUT).size / 1024).toFixed(0)} KB`);
const names = [...new Set(out.segments.map((s) => s.name).filter(Boolean))].sort();
console.log('Roads:', names.join(' | '));
