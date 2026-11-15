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

test('ILC drawing uses the original image coordinate frame and separates floor routes', async () => {
  const {drawingDisplayMap} = await server.ssrLoadModule('/src/components/indoor/backendIndoor.js');
  const {default: SourceRoutePlan} = await server.ssrLoadModule('/src/components/indoor/SourceRoutePlan.jsx');
  const plan = JSON.parse(await readFile(new URL('../../data/plan_wayfinding/ilc.json', import.meta.url), 'utf8'));
  const model = drawingDisplayMap(plan);
  assert.equal(model.floors.length, 2);
  assert.equal(model.floorById.get('1').routeAligned, true);
  assert.equal(model.nodes.get('ilc-entrance-south').floor, '2');
  assert.equal(model.nodes.get('ilc-entrance-south').kind, 'entrance');
  assert.deepEqual(model.nodes.get('ilc-entrance-south').px, [508, 943]);
  assert.equal(model.rooms.length, 21);
  for (const floor of model.floors) {
    assert.equal(floor.vectorPlan.lifts.length, 4);
    assert.ok(floor.vectorPlan.lifts.some(lift => lift.id === 'east'));
  }
  assert.ok(model.rooms.some(room => room.id === 'ilc-door-s241-f2'));
  assert.ok(model.rooms.some(room => room.id === 'ilc-door-s225-f2'));
  const route = {room: {floor:'2', doorX:549, doorY:454}, steps:[
    {floor:'1', kind:'straight', pts:[[500,443],[511,416]]},
    {floor:'1', kind:'elevator', pts:[[511,416]]},
    {floor:'2', kind:'straight', pts:[[511,416],[549,454]]}]};
  const html = renderToStaticMarkup(React.createElement(SourceRoutePlan, {
    floor:model.floorById.get('1'), route, active:0, image:'/original.png', zoom:100}));
  assert.match(html, /500,443 511,416/);
  assert.doesNotMatch(html, /511,416 549,454/);
  assert.match(html, /selected step, not GPS/);
  const {default: IndoorGuide} = await server.ssrLoadModule('/src/components/indoor/IndoorGuide.jsx');
  const guide = renderToStaticMarkup(React.createElement(IndoorGuide, {
    model, route: {...route, room: {...route.room, name:'N255'},
      steps: route.steps.map(s => ({...s, text:'Continue to the next mapped landmark.'}))}, active:0,
    onGo() {}, onExit() {}, onChangeDestination() {},
  }));
  assert.match(guide, /Simplified floor plan/);
  assert.match(guide, /North Pleasant Street elevator/);
  assert.doesNotMatch(guide, /<image|<img/);
  assert.doesNotMatch(guide, /No usable floor-plan image/);
  assert.match(guide, /Room outlines traced from the UMass plans/);
  assert.match(guide, /aria-label="Indoor floor map"/);
  assert.match(guide, /aria-label="Current route directions"/);
  assert.match(guide, /width:100%;height:100%/);
  assert.doesNotMatch(guide, />Then<|guide-tabs|guide-footer|guide-directions/);
  const original = renderToStaticMarkup(React.createElement(SourceRoutePlan, {
    floor:model.floorById.get('1'), route, active:0, image:'/original.png', zoom:100, simplified:false}));
  assert.match(original, /<image href="\/original.png"/);
  const changed = structuredClone(plan);
  changed.floor_sources['1'].source_sha256 = 'different-edition';
  assert.equal(drawingDisplayMap(changed).floorById.get('1').vectorPlan, undefined);
});

test('arrival handoff never falls back to a location picker without an explicit choice', async () => {
  const {drawingDisplayMap} = await server.ssrLoadModule('/src/components/indoor/backendIndoor.js');
  const {default: IndoorStartControl} = await server.ssrLoadModule('/src/components/indoor/IndoorStartControl.jsx');
  const plan = JSON.parse(await readFile(new URL('../../data/plan_wayfinding/ilc.json', import.meta.url), 'utf8'));
  const model = drawingDisplayMap(plan);
  const props = {model, manualStart:'', onManualStart() {}, onPlanOutdoor() {}};
  const arrived = renderToStaticMarkup(React.createElement(IndoorStartControl, {...props,
    entrance:{indoorNodeId:'ilc-entrance-south', name:'Southwest entrance', portalId:'ilc-southwest-floor-2'}}));
  assert.match(arrived, /From your outdoor arrival/);
  assert.match(arrived, /Southwest entrance - floor 2/);
  assert.doesNotMatch(arrived, /<select/);
  const direct = renderToStaticMarkup(React.createElement(IndoorStartControl, props));
  assert.match(direct, /without an outdoor arrival/);
  assert.match(direct, /Plan outdoor route to this building/);
  assert.doesNotMatch(direct, /<select/);
  assert.match(direct, /Start a separate indoor route from a known landmark/);
  const unmatched = renderToStaticMarkup(React.createElement(IndoorStartControl, {...props,
    entrance:{name:'Different door', indoorNodeId:'unknown'}}));
  assert.match(unmatched, /no matched doorway/);
  assert.doesNotMatch(unmatched, /<select/);
  assert.match(unmatched, /Indoor connection unavailable for this arrival/);
  const manual = renderToStaticMarkup(React.createElement(IndoorStartControl, {...props,
    manualEnabled:true}));
  assert.match(manual, /<select/);
  assert.match(manual, /Starting landmark/);
});

test('indoor launch requires a usable start even when a room is already selected', async () => {
  const {default: BuildingTransitionModal} = await server.ssrLoadModule('/src/components/indoor/BuildingTransitionModal.jsx');
  const props = {open:true, buildingName:'ILC', allow3D:false,
    rooms:[{id:'n155', name:'N155', floorLabel:'Floor 1'}], initialRoomId:'n155'};
  const blocked = renderToStaticMarkup(React.createElement(BuildingTransitionModal, {...props, startReady:false}));
  assert.match(blocked, /<button[^>]*disabled=""[^>]*>.*?Start indoor directions/s);
  const ready = renderToStaticMarkup(React.createElement(BuildingTransitionModal, {...props, startReady:true}));
  assert.doesNotMatch(ready, /disabled=""/);
});

test('source indoor guide keeps graph geometry out of the floor-plan reference', async () => {
  const {default: IndoorGuide} = await server.ssrLoadModule('/src/components/indoor/IndoorGuide.jsx');
  const model = measuredDisplayMap({...raw, building_id: 'fixture-building'});
  const route = {room: {name: 'N211'}, steps: [
    {floor: '1', text: 'Follow the corridor 20 m toward the East Elevator.', kind: 'straight'},
    {floor: '1', text: 'Take the East Elevator to floor 2.', kind: 'elevator'}]};
  const props = {model, route, active: 0, onGo() {}, onExit() {}, onChangeDestination() {}};
  const html = renderToStaticMarkup(React.createElement(IndoorGuide, props));
  assert.match(html, /Follow the corridor 66 ft toward the East Elevator/);
  assert.match(html, /Take the East Elevator to floor 2/);
  assert.match(html, /Your position is not tracked indoors/);
  assert.match(html, /No usable floor-plan image/);
  assert.doesNotMatch(html, /data:image|Current location|<polyline|<img/);
  const published = structuredClone({...raw, building_id: 'fixture-building'});
  published.floors.find(f => f.id === '1').image_url = 'https://example.com/published-floor.png';
  const imageHtml = renderToStaticMarkup(React.createElement(IndoorGuide, {...props, model: measuredDisplayMap(published)}));
  assert.match(imageHtml, /href="https:\/\/example.com\/published-floor.png"/);
  assert.match(imageHtml, /Route positions are not aligned/);
  assert.doesNotMatch(imageHtml, /<polyline|data:image/);
});

test('withdrawn ILC topology is rejected even if a stale server still calls it reviewed', async () => {
  const {resolveCatalog} = await server.ssrLoadModule('/src/components/indoor/indoorCatalog.js');
  const {drawingDisplayMap} = await server.ssrLoadModule('/src/components/indoor/backendIndoor.js');
  const {default: IndoorGuide} = await server.ssrLoadModule('/src/components/indoor/IndoorGuide.jsx');
  const old = measuredDisplayMap({...raw, status:'reviewed'});
  const buildings = [{id:'ilc',name:'Integrative Learning Center'}];
  assert.equal(resolveCatalog([old], buildings).entries.length, 0);
  const current = drawingDisplayMap(JSON.parse(await readFile(new URL('../../data/plan_wayfinding/ilc.json', import.meta.url), 'utf8')));
  assert.equal(resolveCatalog([old,current], buildings).forBuilding('ilc'), current);
  const html = renderToStaticMarkup(React.createElement(IndoorGuide, {model:old,
    route:{steps:[{floor:'1',text:'Follow the mapped corridor 65 ft to Main Corridor.'}]}, active:0,onExit(){}}));
  assert.match(html, /This ILC map has been replaced/);
  assert.doesNotMatch(html, /Follow the mapped corridor 65 ft|No usable floor-plan image/);
});

test('display distances use feet and miles without altering floors, rooms, or grades', async () => {
  const {displayInstruction, formatDistance} = await server.ssrLoadModule('/src/services/displayUnits.ts');
  assert.equal(displayInstruction('Continue 100 m to N211 on floor 2; grade 4%.'), 'Continue 328 ft to N211 on floor 2; grade 4%.');
  assert.equal(formatDistance(1609.344), '1.0 mi');
});

test('live catalog rejects sample maps even when the backend is unavailable', async () => {
  const {resolveCatalog} = await server.ssrLoadModule('/src/components/indoor/indoorCatalog.js');
  const model = measuredDisplayMap(raw);
  const buildings = [{id: 'ilc', name: 'Integrative Learning Center', code: 'ILC', location: {lat: 42.39, lng: -72.526}}];
  assert.equal(resolveCatalog([{...model, source: 'sample', sample: true}], buildings).entries.length, 0);
  assert.equal(resolveCatalog([{...model, synthetic: true}], buildings).entries.length, 0);
  assert.equal(resolveCatalog([model], buildings).entries.length, 0); // Withdrawn ILC draft.
  const libraryRaw = JSON.parse(await readFile(new URL('../../data/indoor/library.json', import.meta.url), 'utf8'));
  assert.equal(resolveCatalog([measuredDisplayMap(libraryRaw)], []).entries.length, 1);
});

test('ILC instructions include the corridor approach, elevator ride, and exit approach verbatim', () => {
  const model = measuredDisplayMap(raw);
  // Adapter mechanics only: a supplied route is not proof that these links are reviewed.
  const ids = ['ilc-source-n111-f1', 'ilc-junction-f1', 'ilc-elev-east-f1', 'ilc-elev-east-f2', 'ilc-junction-f2', 'ilc-source-n211-f2'];
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
  assert.equal(route.steps[0].fromNodeId, 'ilc-source-n111-f1');
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
  assert.match(html, /Turn-by-turn directions/);
  assert.match(html, /Follow the corridor to the elevator/);
  assert.match(html, /Next step/);
  assert.match(html, /Show all steps/);
  assert.doesNotMatch(html, /Take the elevator to floor 2/);
});

test('outdoor directions and marker use the same selected step, including Back and arrival', async () => {
  const {Directions} = await server.ssrLoadModule('/src/components/Directions.tsx');
  const {routeStepPosition} = await server.ssrLoadModule('/src/services/routeSteps.ts');
  const {buildScene, withRouteStep} = await server.ssrLoadModule('/src/components/map/scene.ts');
  const points = [[-72.528, 42.39], [-72.5275, 42.3905], [-72.527, 42.391]];
  const route = {summary: {total_distance_m: 140}, features: [{
    geometry: {coordinates: points}, properties: {is_step: false}}], steps: [
    {instruction:'Start on the path.', at:points[0], icon:'start'},
    {instruction:'Turn right by the pond.', at:points[1], icon:'turn-right'},
    {instruction:'Arrive at the entrance.', at:points[2], icon:'destination'},
  ]};
  const base = {accessible:route, standard:null, ghost:null, showStandard:false,
    origin:{lat:42.39,lng:-72.528,name:'Start'}, destination:{lat:42.391,lng:-72.527,name:'End'},
    buildings:[],closures:[],incidents:[],chosenEntranceIds:[],highContrast:false};
  const initial = buildScene({...base, stepPosition:routeStepPosition(route, 0)});
  let scene = initial;
  for (const index of [1, 2, 1, 0]) {
    scene = withRouteStep(scene, routeStepPosition(route, index));
    const marker = scene.markers.find(m => m.id === 'route-step');
    assert.deepEqual(marker.position, [points[index][1], points[index][0]]);
    assert.match(marker.title, /not live GPS/);
    assert.match(marker.html, new RegExp(`Step ${index + 1}`));
    assert.deepEqual(scene.markers.find(m => m.id === 'pin-a'), initial.markers.find(m => m.id === 'pin-a'));
    assert.equal(scene.fitKey, initial.fitKey); // Stepping does not reframe the full trip.
    assert.equal(scene.lines, initial.lines); // No route redraw during Next/Back.
    assert.equal(scene.circles, initial.circles);
    assert.equal(scene.bounds, initial.bounds);
    assert.equal(scene.markers.filter(m => m.id === 'route-step').length, 1);
    const html = renderToStaticMarkup(React.createElement(Directions, {steps:route.steps,activeStep:index,onFocusStep(){}}));
    assert.match(html, new RegExp(`Step ${index + 1} of 3`));
    assert.ok(html.includes(route.steps[index].instruction));
  }
  const cleared = withRouteStep(scene, null);
  assert.ok(!cleared.markers.some(m => m.id === 'route-step'));
  assert.equal(cleared.lines, initial.lines);
  assert.equal(initial.markers.find(m => m.id === 'route-step').title.startsWith('Step 1:'), true);
});

test('outdoor step positions do not invent coordinates for unmapped instructions', async () => {
  const {routeStepPosition} = await server.ssrLoadModule('/src/services/routeSteps.ts');
  const route = {features:[{geometry:{coordinates:[[-72.528,42.39],[-72.527,42.391]]}}],
    steps:[{instruction:'Start'}, {instruction:'Turn'}, {instruction:'Arrive',icon:'destination'}]};
  assert.equal(routeStepPosition(null, 0), null);
  assert.equal(routeStepPosition(route, 1), null);
  assert.equal(routeStepPosition(route, 9), null);
  assert.equal(routeStepPosition(route, 0).lng, -72.528);
  assert.equal(routeStepPosition(route, 2).lng, -72.527);
  route.steps[1].at = [NaN, 42.39];
  assert.equal(routeStepPosition(route, 1), null);
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

test('door-data failures explain the active requirement and offer an explicit choice', async () => {
  const {RouteSummary} = await server.ssrLoadModule('/src/components/RouteSummary.tsx');
  const props = {accessible: null, standard: null, loading: false, engine: 'remote',
    failure: 'Automatic doors are required.', failureCode: 'automatic_door_unconfirmed',
    prefs: {need_automatic_door: true}, onAllowUnverifiedDoors() {}};
  const html = renderToStaticMarkup(React.createElement(RouteSummary, props));
  assert.match(html, /Automatic-door access is not confirmed/);
  assert.match(html, /Allow manual or unverified doors/);
  assert.match(html, /stairs and slope limits stay unchanged/);
  assert.doesNotMatch(html, /No step-free route available/);
  const otherFailure = renderToStaticMarkup(React.createElement(RouteSummary,
    {...props, failureCode: 'no_route', failure: 'No path matches the slope limit.'}));
  assert.doesNotMatch(otherFailure, /Allow manual or unverified doors/);
});

test('pending routes hide previous failures and comparison routes until the result arrives', async () => {
  const {RouteSummary} = await server.ssrLoadModule('/src/components/RouteSummary.tsx');
  const props = {accessible: null, standard: {summary: {total_duration_s: 60, stair_count: 2}},
    loading: true, engine: 'remote', showStandard: true,
    failure: 'Previous trip had no route.', failureCode: 'automatic_door_unconfirmed',
    prefs: {need_automatic_door: true}};
  for (const standard of [null, props.standard]) {
    const html = renderToStaticMarkup(React.createElement(RouteSummary, {...props, standard}));
    assert.match(html, /Finding a route/);
    assert.match(html, /role="status"/);
    assert.doesNotMatch(html, /role="alert"|Previous trip|Could not plan|Automatic-door access|Van Service/);
  }
  // Even an old successful route must not look ready while it is being replaced.
  const stale = renderToStaticMarkup(React.createElement(RouteSummary, {...props, accessible: props.standard}));
  assert.match(stale, /Finding a route/);
  assert.doesNotMatch(stale, /Works for you/);
  const finished = renderToStaticMarkup(React.createElement(RouteSummary, {...props, loading: false}));
  assert.match(finished, /role="alert"/);
  assert.match(finished, /Previous trip had no route/);
  assert.doesNotMatch(finished, /Finding a route/);
});
