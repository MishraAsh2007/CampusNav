import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source = (await readFile(new URL('../src/services/api.ts', import.meta.url), 'utf8'))
  .replaceAll('import.meta.env', '({})');
const compiled = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ES2022}}).outputText;
const api = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const now = Date.now();
const closure = {id: 'a', lat: 42.39, lng: -72.528, radius: 4, type: 'path', status: 'closed',
  source: 'community', start_time: new Date(now-1000).toISOString(), end_time: null,
  last_confirmed: new Date(now).toISOString(), title: 'A blocked path'};
const wire = {type: 'Feature', geometry: {type: 'LineString', coordinates: [[-72.528,42.39],[-72.527,42.39]]},
  properties: {total_distance: 80, max_grade: null, uses_stairs: false, uses_elevator: false,
    directions: ['Continue on the path.'], warnings: ['Slope is unknown.'], start_snap_distance: 1, end_snap_distance: 2}};
const response = (value, status=200) => new Response(JSON.stringify(value), {status});

test('future, expired, and restored notices do not block requests', () => {
  const items = [closure, {...closure,id:'future',start_time:new Date(now+60000).toISOString()},
    {...closure,id:'expired',end_time:new Date(now-1).toISOString()}, {...closure,id:'restored',status:'repaired'}];
  assert.deepEqual(api.activeClosures(items, now).map(x=>x.id), ['a']);
});

test('closure adapter preserves indoor asset and floor scope', () => {
  const scoped = api.closureContract({...closure, asset_id:'lift-a', building_id:'library', floor_id:'E'});
  assert.equal(scoped.asset_id,'lift-a');
  assert.equal(scoped.building_id,'library');
  assert.equal(scoped.floor_id,'E');
});

test('route adapter preserves unknown grade and warnings', () => {
  const route=api.adaptRoute(wire, 10);
  assert.equal(route.summary.max_grade_pct, null);
  assert.equal(route.summary.stair_count, null);
  assert.deepEqual(route.summary.warnings, ['Slope is unknown.']);
  assert.equal(route.profile, undefined);
  assert.throws(()=>api.adaptRoute({...wire,type:'FeatureCollection'},0), /Invalid routing/);
});

test('plan request uses the backend contract with all active closures', async () => {
  const previous=globalThis.fetch;
  let sent;
  globalThis.fetch=async (url, init)=>{sent={url,body:JSON.parse(init.body)}; return response({
    accessible:wire, standard:wire, start_entrance:{id:'entrance-a'}, end_entrance:{id:'entrance-b'},
    notes:['Door access unverified.'], graph_edges:18});};
  try {
    const result=await api.planRoutes({name:'Start',lat:42.39,lng:-72.528,building_id:'cc'},
      {name:'End',lat:42.39,lng:-72.527}, {max_grade_pct:5,no_stairs:false,wheelchair_required:true,
        need_automatic_door:false}, [closure]);
    assert.equal(sent.url,'/plan');
    assert.equal(sent.body.no_stairs,true);
    assert.equal(sent.body.closures[0].end_time,null);
    assert.equal(sent.body.closures[0].title,undefined);
    assert.equal(result.startEndpointId,'entrance-a');
    assert.equal(result.engine,'remote');
  } finally {globalThis.fetch=previous;}
});

test('unavailable router returns an error without fabricated fallback routes', async () => {
  const previous=globalThis.fetch;
  globalThis.fetch=async ()=>response({detail:{message:'No mapped route'}},503);
  try {await assert.rejects(()=>api.planRoutes({}, {}, {max_grade_pct:5}, []), /No mapped route/);}
  finally {globalThis.fetch=previous;}
});

test('notice refresh failure preserves the last real cache and labels it stale', async () => {
  const previous=globalThis.fetch;
  globalThis.fetch=async url=>response(url.endsWith('/status')?{stale:false}:[closure]);
  try {
    assert.equal((await api.getClosures()).live,true);
    globalThis.fetch=async ()=>{throw new Error('Network offline');};
    const result=await api.getClosures();
    assert.equal(result.live,false);
    assert.equal(result.error,'Network offline');
    assert.deepEqual(result.closures,[closure]);
  } finally {globalThis.fetch=previous;}
});

test('room planning and arrival use the server-selected entrance without client closure overrides', async () => {
  const previous = globalThis.fetch;
  const calls = [];
  const portal = {building_id: 'ilc', portal_id: 'ilc-portal-south'};
  const ready = {status: 'route_ready', arrival_context: portal, journey: {warnings: [], legs: [
    {kind: 'outdoor', route: wire},
    {kind: 'portal', direction: 'enter', portal_id: portal.portal_id, entrance_label: 'South entrance'},
  ]}};
  globalThis.fetch = async (url, init) => {
    calls.push([url, JSON.parse(init.body)]);
    return response(url.endsWith('/plan') ? ready : {status: 'no_route', message: 'Elevator unavailable'});
  };
  try {
    const prefs = {max_grade_pct: 5, no_stairs: true};
    const result = await api.planRoom({name: 'Campus Center', building_id: 'campus-center', entrance_id: 'south'}, 'ilc', 'n151', prefs);
    assert.deepEqual(result.indoorArrival, portal);
    assert.equal(result.notes[0], 'Approach: South entrance.');
    assert.deepEqual(calls[0][1].origin, {building_id: 'campus-center'});
    assert.equal(calls[0][1].origin_entrance_id, 'south');
    assert.equal(calls[0][1].closures, undefined);
    const arrival = await api.confirmArrival(portal, 'n151', prefs);
    assert.equal(calls[1][0], '/navigation/arrive');
    assert.deepEqual(calls[1][1].destination, {building_id: 'ilc', node_id: 'n151'});
    assert.equal(calls[1][1].portal_id, portal.portal_id);
    assert.equal(calls[1][1].closures, undefined);
    assert.equal(arrival.status, 'no_route');
    assert.equal(calls.length, 2);
  } finally {globalThis.fetch = previous;}
});
