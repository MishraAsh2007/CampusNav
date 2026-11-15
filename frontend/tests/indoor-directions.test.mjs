import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {after, test} from 'node:test';
import {createServer} from 'vite';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

const server = await createServer({root: fileURLToPath(new URL('../', import.meta.url)),
  configFile: false, envFile: false, esbuild: {jsx: 'automatic'},
  server: {middlewareMode: true, watch: null, hmr: false}, appType: 'custom'});
after(() => server.close());
const {measuredDisplayMap, adaptIndoorDirections} = await server.ssrLoadModule('/src/components/indoor/backendIndoor.js');
const raw = JSON.parse(await readFile(new URL('../../data/indoor/ilc.json', import.meta.url), 'utf8'));

test('ILC instructions include the corridor approach, elevator ride, and exit approach verbatim', () => {
  const model = measuredDisplayMap(raw);
  const ids = ['ilc-entrance-south', 'ilc-junction-f1', 'ilc-elev-east-f1', 'ilc-elev-east-f2', 'ilc-junction-f2', 'ilc-source-n211-f2'];
  const instructions = ['Follow the mapped corridor to the junction.', 'Turn right toward the East Elevator.',
    'Use ILC East Elevator from 1st Floor to 2nd Floor.', 'Leave the elevator and follow the corridor.', 'Continue to N211.'];
  const steps = ids.slice(1).map((id, i) => {
    const a = model.nodes.get(ids[i]), b = model.nodes.get(id);
    return {kind: a.floor !== b.floor ? 'elevator' : 'corridor',
      from_node_id: a.id, to_node_id: b.id, from_floor: a.floor, to_floor: b.floor,
      geometry: a.floor === b.floor ? {coordinates: [[a.x, a.y], [b.x, b.y]]} : undefined,
      instruction: instructions[i]};
  });
  const route = adaptIndoorDirections(model, {steps, node_path: ids}, ids.at(-1));
  assert.deepEqual(route.steps.slice(0, -1).map(step => step.text), instructions);
  assert.equal(route.steps[0].fromNodeId, 'ilc-entrance-south');
  assert.equal(route.steps[2].kind, 'elevator');
  assert.ok(route.paths['1'].length > 2 && route.paths['2'].length > 2);
});

test('a floor lobby ends at the elevator actually selected by the backend', () => {
  const model = measuredDisplayMap(raw);
  const end = 'ilc-elev-west-f2';
  const route = adaptIndoorDirections(model, {node_path: [end], steps: []}, '2:@lobby');
  assert.deepEqual(route.steps.at(-1).pts, [model.nodes.get(end).px]);
});

test('directions show a current instruction and next control without opening all steps', async () => {
  const {Directions} = await server.ssrLoadModule('/src/components/Directions.tsx');
  const html = renderToStaticMarkup(React.createElement(Directions, {steps: [
    {instruction: 'Follow the corridor to the elevator.', distance_m: 0, grade_pct: 0},
    {instruction: 'Take the elevator to floor 2.', distance_m: 0, grade_pct: 0},
  ], onFocusStep() {}}));
  assert.match(html, /Directions/);
  assert.match(html, /Follow the corridor to the elevator/);
  assert.match(html, /Next step/);
  assert.match(html, /Show all steps/);
  assert.doesNotMatch(html, /Take the elevator to floor 2/);
});

test('regular route card and map line remain hidden until comparison is requested', async () => {
  const {RouteSummary} = await server.ssrLoadModule('/src/components/RouteSummary.tsx');
  const {buildScene} = await server.ssrLoadModule('/src/components/map/scene.ts');
  const route = {summary: {total_duration_s: 60, total_distance_m: 70, max_grade_pct: 3,
    warnings: [], stair_count: 0, elevation_gain_m: null}, steps: [], features: [{
      geometry: {type: 'LineString', coordinates: [[-72.528, 42.39], [-72.527, 42.39]]},
      properties: {is_step: false, grade: 0},
    }]};
  const props = {accessible: route, standard: route, showStandard: false, tab: 'accessible',
    onTab() {}, onToggleStandard() {}, notes: [], prefs: {}, arrivalEntrance: null,
    destinationBuilding: null, engine: 'remote', graphEdges: 10, loading: false};
  const hidden = renderToStaticMarkup(React.createElement(RouteSummary, props));
  assert.match(hidden, /Works for you/);
  assert.match(hidden, /Compare on map/);
  assert.doesNotMatch(hidden, /Regular map/);
  const shown = renderToStaticMarkup(React.createElement(RouteSummary, {...props, showStandard: true}));
  assert.match(shown, /Regular map/);
  const sceneProps = {...props, buildings: [], closures: [], incidents: [], highContrast: false,
    origin: null, destination: null, chosenEntranceIds: [], selectedBuildingId: null};
  assert.equal(buildScene(sceneProps).lines.some(line => line.id.startsWith('std-')), false);
  assert.equal(buildScene({...sceneProps, showStandard: true}).lines.some(line => line.id.startsWith('std-')), true);
});
