import assert from 'node:assert/strict';
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

test('route adapter preserves unknown grade and the router directions', () => {
  const route = api.adaptWireRoute(wire, 10);
  assert.equal(route.summary.max_grade_pct, null);
  assert.equal(route.summary.stair_count, 0);
  assert.deepEqual(route.summary.warnings, ['Slope is unknown.']);
  assert.equal(route.steps[0].instruction, 'Continue on the path.');
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
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/plan');
    const body = JSON.parse(init.body);
    assert.equal(body.no_stairs, true);
    assert.deepEqual(body.closures, []);
    assert.equal(body.origin.building_id, 'campus-center');
    return response({accessible: wire, standard: wire, start_entrance: {id: 'exit-a'},
      end_entrance: {id: 'door-b', lat: end.lat, lng: end.lng}, notes: []});
  };
  const plan = await api.planRoutes(start, end, prefs, [official], []);
  assert.equal(plan.engine, 'remote');
  assert.equal(plan.startEndpointId, 'exit-a');
  assert.equal(plan.arrivalPoint.entranceId, 'door-b');
});

test('unavailable and no-route responses stay visible in the Role 2 planner', async () => {
  const plan = () => api.planRoutes(start, end, prefs, [], []);
  globalThis.fetch = async () => response({detail: {message: 'Graph unavailable'}}, {status: 503});
  assert.equal((await plan()).failure, 'Graph unavailable');
  globalThis.fetch = async () => response({accessible: null, standard: wire, failure: 'No mapped route'});
  const result = await plan();
  assert.equal(result.failure, 'No mapped route');
  assert.equal(result.accessible, null);
  assert.equal(result.engine, 'remote');
});

test('a reviewed room route retains the portal selected by the Python router', async () => {
  globalThis.fetch = async (url, init) => {
    if (url === '/plan') return response({standard: wire});
    assert.equal(url, '/navigation/plan');
    assert.deepEqual(JSON.parse(init.body).destination, {building_id: 'ilc', node_id: 'ilc-source-n151-f2'});
    return response({status: 'route_ready', arrival_context: {building_id: 'ilc', portal_id: 'ilc-portal-south'},
      journey: {legs: [{kind: 'outdoor', route: wire}], warnings: []}});
  };
  const result = await api.planRoutes(start, end, prefs, [], [],
    {reviewedBuildingId: 'ilc', nodeId: 'ilc-source-n151-f2'});
  assert.equal(result.arrivalPoint.portalId, 'ilc-portal-south');
  assert.equal(result.failure, undefined);
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
