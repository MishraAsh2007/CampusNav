#!/usr/bin/env node
/**
 * Rehearses the judge demo against the real graph without a browser:
 *   node scripts/check-demo.mjs
 * Student Union -> Campus Center upper terrace, wheelchair profile, elevator working vs broken.
 */
import fs from 'node:fs';
import { prepareGraph, computeRoutes } from '../src/services/routingEngine.ts';
import { UMASS_BUILDINGS } from '../src/data/mockBuildings.ts';
import { INITIAL_CLOSURES, DEMO_ELEVATOR_REPORT } from '../src/data/mockClosures.ts';

const G = prepareGraph(JSON.parse(fs.readFileSync(new URL('../public/data/campusGraph.json', import.meta.url), 'utf8')));
const prefs = {
  mobility_preset: 'manual_wheelchair', wheelchair_required: true, no_stairs: true, max_grade_pct: 6,
  avoid_rough_surfaces: true, prefer_indoor: false, handrails_required: false, need_automatic_door: true,
  need_accessible_restroom: false, avoid_construction: true, minimize_crossings: false
};
const su = UMASS_BUILDINGS.find((b) => b.id === 'student-union');
const landmarks = UMASS_BUILDINGS.map((b) => ({ name: `the ${b.name}`, lat: b.location.lat, lng: b.location.lng }));
const q = {
  starts: su.entrances.filter((e) => e.step_free).map((e) => ({ lat: e.lat, lng: e.lng, label: `Student Union, ${e.name}`, id: e.id })),
  standardStarts: su.entrances.map((e) => ({ lat: e.lat, lng: e.lng, label: `Student Union, ${e.name}`, id: e.id })),
  ends: [{ lat: 42.391519, lng: -72.526563, label: 'Campus Center upper terrace' }],
  originLabel: 'Student Union', destLabel: 'Campus Center upper terrace', prefs, landmarks
};
const show = (label, r) => {
  const a = r.accessible?.summary;
  console.log(`\n== ${label}`);
  if (!a) return console.log('  NO accessible route:', r.failure);
  console.log(`  accessible: ${a.total_distance_m} m, ${Math.round(a.total_duration_s / 60)} min, max ${a.max_grade_pct}%, stairs ${a.stair_count}, elevators [${a.elevators_used}] in ${a.compute_ms} ms`);
  console.log(`  standard:   ${r.standard?.summary.total_distance_m} m, ${r.standard?.summary.stair_count} steps`);
  for (const w of a.warnings) console.log('  warn:', w);
  for (const x of r.accessible.avoided ?? []) console.log('  avoided:', x.kind, x.label);
  for (const s of r.accessible.steps) console.log('   -', s.instruction);
};
const t = performance.now();
show('Elevator working', computeRoutes(G, { ...q, closures: INITIAL_CLOSURES }));
show('Elevator broken', computeRoutes(G, { ...q, closures: [...INITIAL_CLOSURES, { id: 'demo', radius: 12, type: 'elevator', status: 'closed', source: 'community', start_time: '', last_confirmed: '', confirmations_count: 1, ...DEMO_ELEVATOR_REPORT }] }));
console.log(`\nboth plans in ${Math.round(performance.now() - t)} ms (cold)`);
