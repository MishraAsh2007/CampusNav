import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { after, afterEach, test } from 'node:test';
import { createServer } from 'vite';

const server = await createServer({
  root: fileURLToPath(new URL('../', import.meta.url)), configFile: false, envFile: false,
  server: { middlewareMode: true, watch: null, hmr: false }, appType: 'custom',
});
after(() => server.close());
const api = await server.ssrLoadModule('/src/services/api.ts');
const fetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = fetch; });

const utc = (offset = 0) => new Date(Date.now() + offset).toISOString();
const official = {id: 'notice-1', lat: 42.39, lng: -72.528, radius: 4, type: 'elevator',
  source: 'official', status: 'closed', start_time: utc(-1000), last_confirmed: utc(),
  asset_id: 'ilc-elevator-east', building_id: 'ilc', floor_id: '1'};
const wire = {type: 'Feature', geometry: {type: 'LineString', coordinates: [[-72.528, 42.39], [-72.527, 42.39]]},
  properties: {total_distance: 80, max_grade: null, uses_stairs: false, uses_elevator: false,
    directions: ['Continue on the path.'], warnings: ['Slope is unknown.'], snapped_end: {lat: 42.39, lng: -72.527}}};
const response = (value, init) => new Response(JSON.stringify(value), init);
const start = {name: 'Campus Center', building_id: 'campus-center', lat: 42.39, lng: -72.528};
const end = {name: 'ILC', building_id: 'ilc', lat: 42.39, lng: -72.527};
const prefs = {max_grade_pct: 6, wheelchair_required: true, need_automatic_door: false};
const mockRouting = handle => {
  globalThis.fetch = async (url, init) => url === '/health'
    ? response({routes: ['/plan', '/navigation/plan', '/navigation/arrive', '/indoor/status']})
    : handle(url, init);
};

test('route adapter preserves unknown grade and the router directions', () => {
  const route = api.adaptWireRoute(wire, 10);
  assert.equal(route.summary.max_grade_pct, null);
  assert.equal(route.summary.stair_count, 0);
  assert.deepEqual(route.summary.warnings, ['Slope is unknown.']);
  assert.equal(route.steps[0].instruction, 'Continue on the path.');
});

test('turn-by-turn metadata preserves turn icons, map focus points, and leg distances', () => {
  const route = api.adaptWireRoute({...wire, properties: {...wire.properties, maneuvers: [
    {maneuver: 'left', instruction: 'Turn left onto the mapped path, then continue 20 m.',
      distance_m: 20, at: [-72.528, 42.39], grade_pct: null, geometry: []},
    {maneuver: 'arrive', instruction: 'Arrive at the mapped endpoint.', distance_m: 0,
      at: [-72.527, 42.39], grade_pct: null, geometry: []},
  ]}}, 3);
  assert.equal(route.steps[0].icon, 'turn-left');
  assert.equal(route.steps[0].distance_m, 20);
  assert.deepEqual(route.steps[0].at, [-72.528, 42.39]);
  assert.equal(route.steps[1].icon, 'destination');
});

test('the outdoor route carries an exact indoor entrance into the arrival view', async () => {
  mockRouting(() => response({accessible: wire, standard: wire, notes: [],
    end_entrance: {id: 'door-b', ...end},
    indoor_arrival: {node_id: 'ilc-entrance-south', portal_id: 'ilc-portal-south', label: 'South entrance'},
  }));
  const plan = await api.planRoutes(start, end, prefs, [], []);
  assert.equal(plan.arrivalPoint.indoorNodeId, 'ilc-entrance-south');
  assert.equal(plan.arrivalPoint.portalId, 'ilc-portal-south');
  assert.equal(plan.arrivalPoint.label, 'South entrance');
});

test('automatic-door failure is preserved without silently relaxing route requirements', async () => {
  const requests = [];
  mockRouting((url, init) => {
    const body = JSON.parse(init.body);
    requests.push(body);
    return response(body.need_automatic_door
      ? {accessible: null, standard: wire, notes: [], failure: 'Automatic doors are required.',
        failure_code: 'automatic_door_unconfirmed'}
      : {accessible: wire, standard: wire, notes: []});
  });
  const strict = await api.planRoutes(start, end, {...prefs, need_automatic_door: true}, [], []);
  assert.equal(strict.accessible, null);
  assert.equal(strict.failureCode, 'automatic_door_unconfirmed');
  assert.equal(requests.length, 1);
  const relaxed = await api.planRoutes(start, end, {...prefs, need_automatic_door: false}, [], []);
  assert.ok(relaxed.accessible);
  assert.equal(requests[1].no_stairs, requests[0].no_stairs);
  assert.equal(requests[1].max_grade, requests[0].max_grade);
});

test('drawing journeys are enabled by default and retain the itinerary and server-owned closures', async () => {
  let payload;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/journey');
    payload = JSON.parse(init.body);
    return response({complete: true, total_distance: null, warnings: ['Drawing only'], legs: [
      {kind: 'indoor', building_id: 'north-d', steps: [{instruction: 'Follow the hall to the elevator.'}]},
      {kind: 'portal', building_id: 'north-d', entrance_id: 'entrance-50', indoor_node_id: 'exit-threshold-1'},
      {kind: 'outdoor', route: wire},
    ]});
  };
  const plan = await api.planRoutes(start, end, prefs, [official], [], {
    origin: {kind: 'drawing', building_id: 'north-d', node_id: 'apartment-513-5'},
    residentAccess: true,
  });
  assert.equal(payload.accept_drawing_only, true);
  assert.equal(payload.resident_access_confirmed, true);
  assert.deepEqual(payload.closures, []);
  assert.equal(plan.journey.legs[0].steps[0].instruction, 'Follow the hall to the elevator.');
  assert.equal(plan.journey.total_distance, null);
  assert.ok(plan.notes.some(note => note.includes('distance is unknown')));
});

test('catalog preserves empty entrance lists and the existing building ID', () => {
  const building = api.normalizeBuilding({id: 'campus-center', name: 'Lincoln Campus Center',
    lat: 42.39, lng: -72.528, entrances: []});
  assert.equal(building.id, 'campus-center');
  assert.deepEqual(building.entrances, []);
});

test('stale and disconnected closure feeds are labeled, and schedules stay separate', async () => {
  globalThis.fetch = async url => {
    if (url === '/closures') return response([official], {headers: {'X-Closures-Stale': 'true'}});
    if (url === '/notices') return response([official, {...official, id: 'scheduled-1', scheduled: true, start_time: utc(60000)}]);
    throw new Error('Unexpected URL ' + url);
  };
  const stale = await api.getClosures();
  assert.equal(stale.live, false);
  assert.equal(stale.received, true);
  assert.deepEqual(stale.closures.map(c => c.asset_id), ['ilc-elevator-east']);
  assert.equal(stale.closures[0].floor_id, '1');
  assert.deepEqual(stale.scheduled.map(c => c.id), ['scheduled-1']);
  globalThis.fetch = async () => {throw new Error('Network offline');};
  const disconnected = await api.getClosures();
  assert.equal(disconnected.live, false);
  assert.equal(disconnected.received, false);
  assert.deepEqual(disconnected.closures, stale.closures);
});

test('outdoor planning lets the server choose entrances and load active closures', async () => {
  mockRouting((url, init) => {
    assert.equal(url, '/plan');
    const body = JSON.parse(init.body);
    assert.equal(body.no_stairs, true);
    assert.deepEqual(body.closures, []);
    assert.equal(body.origin.building_id, 'campus-center');
    return response({accessible: wire, standard: wire, start_entrance: {id: 'exit-a'},
      end_entrance: {id: 'door-b', lat: end.lat, lng: end.lng}, notes: []});
  });
  const plan = await api.planRoutes(start, end, prefs, [official], []);
  assert.equal(plan.engine, 'remote');
  assert.equal(plan.startEndpointId, 'exit-a');
  assert.equal(plan.arrivalPoint.entranceId, 'door-b');
});

test('unavailable and no-route responses stay visible in the Role 2 planner', async () => {
  const plan = () => api.planRoutes(start, end, prefs, [], []);
  mockRouting(() => response({detail: {message: 'Graph unavailable'}}, {status: 503}));
  assert.equal((await plan()).failure, 'Graph unavailable');
  mockRouting(() => response({accessible: null, standard: wire, failure: 'No mapped route'}));
  const result = await plan();
  assert.equal(result.failure, 'No mapped route');
  assert.equal(result.accessible, null);
  assert.equal(result.engine, 'remote');
});

test('a reviewed room route retains the portal selected by the Python router', async () => {
  mockRouting((url, init) => {
    if (url === '/plan') return response({standard: wire});
    assert.equal(url, '/navigation/plan');
    assert.deepEqual(JSON.parse(init.body).destination, {building_id: 'ilc', node_id: 'ilc-source-n151-f2'});
    return response({status: 'route_ready', arrival_context: {building_id: 'ilc', portal_id: 'ilc-portal-south'},
      journey: {legs: [{kind: 'outdoor', route: wire}], warnings: []}});
  });
  const result = await api.planRoutes(start, end, prefs, [], [],
    {reviewedBuildingId: 'ilc', nodeId: 'ilc-source-n151-f2'});
  assert.equal(result.arrivalPoint.portalId, 'ilc-portal-south');
  assert.equal(result.failure, undefined);
});

test('a standalone Data API is detected without sending unsupported routing POSTs', async () => {
  const older = await server.ssrLoadModule('/src/services/api.ts?standalone');
  const paths = [];
  const graph = await readFile(new URL('../public/data/campusGraph.json', import.meta.url), 'utf8');
  globalThis.fetch = async (url, init) => {
    paths.push([url, init?.method]);
    if (url === '/health') return response({status: 'ok'});
    if (url === '/openapi.json') return response({paths: {'/community-reports': {post: {}}}});
    if (url === '/data/campusGraph.json') return new Response(graph);
    return response({detail: 'Not Found'}, {status: 404});
  };
  const intent = {reviewedBuildingId: 'ilc', nodeId: 'ilc-source-n151-f2'};
  for (let i = 0; i < 2; i++) {
    const plan = await older.planRoutes(start, end, prefs, [], [], intent);
    assert.equal(plan.engine, 'remote');
    assert.equal(plan.accessible, null);
    assert.match(plan.failure, /routing service unavailable/i);
  }
  assert.deepEqual(paths, [['/health', undefined], ['/openapi.json', undefined]]);
});

test('if a server changes mid-session the missing navigation endpoint is tried once', async () => {
  const older = await server.ssrLoadModule('/src/services/api.ts?changed');
  let guidedCalls = 0;
  mockRouting(url => {
    if (url === '/navigation/plan') {
      guidedCalls++;
      return response({detail: 'Not Found'}, {status: 404});
    }
    return response({accessible: wire, end_entrance: {id: 'entry', ...wire.properties.snapped_end}, notes: []});
  });
  const intent = {reviewedBuildingId: 'ilc', nodeId: 'ilc-source-n151-f2'};
  for (let i = 0; i < 2; i++) assert.equal((await older.planRoutes(start, end, prefs, [], [], intent)).arrivalPoint.entranceId, 'entry');
  assert.equal(guidedCalls, 1);
});

test('a backend without source routing does not substitute the alternate browser graph', async () => {
  const legacy = await server.ssrLoadModule('/src/services/api.ts?legacy');
  const graph = await readFile(new URL('../public/data/campusGraph.json', import.meta.url), 'utf8');
  const posts = [];
  globalThis.fetch = async (url, init) => {
    if (url === '/health') return response({status: 'ok'});
    if (url === '/openapi.json') return response({paths: {'/api/route': {post: {}}}});
    if (url === '/data/campusGraph.json') return new Response(graph);
    posts.push(url);
    return response({step_free: api.adaptWireRoute(wire, 10), destination: {end, entrance_id: 'legacy-door'}});
  };
  const result = await legacy.planRoutes(start, end, prefs, [], []);
  assert.equal(result.engine, 'remote');
  assert.equal(result.accessible, null);
  assert.match(result.failure, /routing service unavailable/i);
  assert.deepEqual(posts, []);
});

test('an unavailable backend uses our sourced building catalog and no seeded outage reports', async () => {
  const isolated = await server.ssrLoadModule('/src/services/api.ts?source-only');
  globalThis.fetch = async () => response({detail: 'Not Found'}, {status: 404});
  const buildings = await isolated.getBuildings();
  assert.ok(buildings.some(b => b.id === 'north-d'));
  assert.ok(buildings.some(b => b.id === 'old-chapel'));
  assert.ok(buildings.some(b => b.id === 'library'));
  assert.deepEqual((await isolated.getClosures()).closures, []);
});

test('report creation, confirmation and resolution use the service endpoints', async () => {
  const calls = [];
  const created = {...official, id: 'community-1', source: 'community', confirmations_count: 1};
  globalThis.fetch = async (url, init) => {
    calls.push([url, init.method]);
    if (url === '/reports') {
      assert.equal(JSON.parse(init.body).connector_id, 'ilc-elevator-east');
      return response(created, {status: 201});
    }
    if (init.method === 'POST') return response({...created, confirmations_count: 2});
    return new Response(null, {status: 204});
  };
  const saved = await api.submitUserReport({...created, connector_id: created.asset_id, status: 'broken', timestamp: utc()});
  assert.equal(saved.closure.id, created.id);
  const confirmed = await api.confirmClosure(created.id);
  assert.equal(confirmed.find(c => c.id === created.id).confirmations_count, 2);
  await api.markClosureResolved(official.id);
  const resolved = await api.markClosureResolved(created.id);
  assert.equal(resolved.some(c => c.id === created.id), false);
  assert.deepEqual(calls, [['/reports', 'POST'], ['/reports/community-1/confirm', 'POST'],
    ['/api/data/community-reports/community-1', 'DELETE']]);
});

test('a slow backend startup stays pending before returning its route', async () => {
  const cold = await server.ssrLoadModule('/src/services/api.ts?slow-startup');
  let resolveHealth, healthSignal, finished = false;
  globalThis.fetch = async (url, init) => {
    if (url === '/health') {
      healthSignal = init.signal;
      return new Promise((resolve, reject) => {
        resolveHealth = () => resolve(response({routes: ['/plan']}));
        init.signal.addEventListener('abort', () => reject(new Error('aborted')), {once: true});
      });
    }
    return response({accessible: wire, notes: []});
  };
  const pending = cold.planRoutes(start, end, prefs, [], []).then(plan => {finished = true; return plan;});
  try {
    // Longer than the old discovery deadline: no premature unavailable result.
    await new Promise(resolve => setTimeout(resolve, 1700));
    assert.equal(healthSignal.aborted, false);
    assert.equal(finished, false);
  } finally {
    resolveHealth();
  }
  assert.ok((await pending).accessible);
});

test('Ash indoor directions retain the outdoor doorway and filter expired reports', async () => {
  let sent;
  globalThis.fetch = async (url, init) => {
    assert.equal(url,'/api/indoor-route');
    sent=JSON.parse(init.body);
    return response({status:'ok',entrance:{name:'Southwest',lat:end.lat,lng:end.lng},steps:['Enter the building.']});
  };
  const req={buildingId:'ilc',door:end,room:'N211',direction:'to_room',prefs,
    closures:[official,{...official,id:'expired',end_time:utc(-1000)},{...official,id:'fixed',status:'repaired'}]};
  assert.equal((await api.getIndoorDirections(req)).status,'ok');
  assert.equal(sent.closures.length,1);
  assert.deepEqual(sent.entrance,end);
  globalThis.fetch = async () => response({status:'ok',entrance:{name:'Other door',lat:end.lat+0.001,lng:end.lng},steps:['Use a different entrance.']});
  const mismatch=await api.getIndoorDirections(req);
  assert.equal(mismatch.status,'no_route');
  assert.match(mismatch.message,/different doorway/);
  globalThis.fetch = async () => response({detail:'Unavailable'},{status:503});
  assert.equal((await api.getIndoorDirections(req)).status,'unavailable');
});
