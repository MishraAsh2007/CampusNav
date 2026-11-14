#!/usr/bin/env node
/**
 * Sanity checks for public/data/campusGraph.json and the in-browser router.
 *   node scripts/analyze-graph.mjs
 * Prints grade distribution, the staircases with the longest step-free detours, and building pairs where
 * a regular map would send a wheelchair user up stairs.
 */
import fs from 'node:fs';
import { prepareGraph, computeRoutes } from '../src/services/routingEngine.ts';

const raw = JSON.parse(fs.readFileSync(new URL('../public/data/campusGraph.json', import.meta.url), 'utf8'));
const G = prepareGraph(raw);
console.log('meta', raw.meta);

const grades = [...G.grade].filter((_, i) => G.e[i].k !== 'steps' && G.e[i].d > 8);
const pct = (p) => grades.slice().sort((a, b) => a - b)[Math.floor(grades.length * p)].toFixed(1);
console.log(`grade p50 ${pct(0.5)}%  p90 ${pct(0.9)}%  p97 ${pct(0.97)}%  >5%: ${grades.filter((g) => g > 5).length}  >8.3%: ${grades.filter((g) => g > 8.3).length} of ${grades.length}`);

const prefs = {
  mobility_preset: 'manual_wheelchair', wheelchair_required: true, no_stairs: true, max_grade_pct: 6,
  avoid_rough_surfaces: true, prefer_indoor: false, handrails_required: false, need_automatic_door: true,
  need_accessible_restroom: false, avoid_construction: true, minimize_crossings: false
};

// Staircases with the biggest step-free detour
const rows = [];
G.e.forEach((e, i) => {
  if (e.k !== 'steps' || (e.sc ?? 0) < 8) return;
  const A = G.v[e.a];
  const B = G.v[e.b];
  const res = computeRoutes(G, {
    starts: [{ lat: A[0], lng: A[1], label: 'bottom' }],
    ends: [{ lat: B[0], lng: B[1], label: 'top' }],
    originLabel: 'a', destLabel: 'b', prefs, closures: [], landmarks: []
  });
  rows.push({ i, sc: e.sc, rise: e.r, at: `${A[0]},${A[1]} -> ${B[0]},${B[1]}`, detour: res.accessible?.summary.total_distance_m ?? null, direct: e.d });
});
rows.sort((x, y) => (y.detour ?? 9999) - (x.detour ?? 9999));
console.log('\nStaircases (>=8 steps) by step-free detour length:');
for (const r of rows.slice(0, 25)) console.log(`  e${r.i} ${r.sc} steps rise ${r.rise}m  direct ${r.direct}m  step-free ${r.detour ?? 'NONE'}m  ${r.at}`);

// Building pairs
const { UMASS_BUILDINGS } = await import('../src/data/mockBuildings.ts').catch(() => ({ UMASS_BUILDINGS: [] }));
if (UMASS_BUILDINGS.length) {
  console.log('\nBuilding pairs (standard route has stairs):');
  for (const a of UMASS_BUILDINGS) {
    for (const b of UMASS_BUILDINGS) {
      if (a.id >= b.id) continue;
      const ep = (bld, all) => (all ? bld.entrances : bld.entrances.filter((x) => x.step_free)).map((x) => ({ lat: x.lat, lng: x.lng, label: `${bld.code} ${x.name}`, id: x.id }));
      const res = computeRoutes(G, {
        starts: ep(a, false), ends: ep(b, false), standardStarts: ep(a, true), standardEnds: ep(b, true),
        originLabel: a.code, destLabel: b.code, prefs, closures: [], landmarks: []
      });
      const s = res.standard?.summary;
      const ac = res.accessible?.summary;
      if (ac?.elevators_used?.length) {
        const broken = computeRoutes(G, {
          starts: ep(a, false), ends: ep(b, false), standardStarts: ep(a, true), standardEnds: ep(b, true),
          originLabel: a.code, destLabel: b.code, prefs, landmarks: [],
          closures: [{ id: 'x', lat: 0, lng: 0, radius: 10, type: 'elevator', status: 'closed', source: 'community', title: 'CC elevator', connector_id: 'cc-concourse-elevator', start_time: '', last_confirmed: '', confirmations_count: 1 }]
        });
        console.log(`  ELEVATOR ${a.code}->${b.code}: works ${ac.total_distance_m}m/${Math.round(ac.total_duration_s / 60)}min | broken ${broken.accessible?.summary.total_distance_m ?? 'NONE'}m/${Math.round((broken.accessible?.summary.total_duration_s ?? 0) / 60)}min  ${broken.accessible?.summary.warnings.join(' ')}`);
      }
      if (s && s.stair_count > 0) console.log(`  ${a.code}->${b.code}: standard ${s.total_distance_m}m ${s.stair_count} steps | accessible ${ac ? ac.total_distance_m + 'm max ' + ac.max_grade_pct + '%' + (ac.elevators_used?.length ? ' via ' + ac.elevators_used.join(',') : '') : 'NONE: ' + res.failure}`);
      else if (!ac) console.log(`  ${a.code}->${b.code}: NO accessible route (${res.failure})`);
    }
  }
}
