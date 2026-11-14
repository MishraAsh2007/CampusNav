import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Building, Closure, Place, RouteResponse, UserPreferences, UserReportPayload } from './types';
import { closuresSignature, confirmClosure, getBuildings, getClosures, getHealth, planRoutes, submitUserReport, type Health, type PlanResult } from './services/api';
import { DEFAULT_PREFERENCES } from './data/profiles';
import { buildingPlaces } from './data/places';
import { MapView } from './components/MapView';
import { TopBar } from './components/TopBar';
import { TripPlanner } from './components/TripPlanner';
import { NeedsMenu } from './components/NeedsMenu';
import { RouteSummary } from './components/RouteSummary';
import { Narrator } from './components/Narrator';
import { Directions } from './components/Directions';
import { OutageList } from './components/OutageList';
import { BuildingSheet } from './components/BuildingSheet';
import { ClosureSheet } from './components/ClosureSheet';
import { ReportSheet } from './components/ReportSheet';
import { AboutSheet } from './components/AboutSheet';
import { SourcePanel } from './components/SourcePanel';
import { useMapProvider } from './components/map/MapsProvider';

const placeFor = (b: Building): Place => ({name: b.name, ...b.location, building_id: b.id});
const message = (e: unknown) => e instanceof Error ? e.message : 'The request failed.';
export function App() {
  const {provider} = useMapProvider();
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [realClosures, setRealClosures] = useState<Closure[]>([]);
  const [simulation, setSimulation] = useState<Closure | null>(null);
  const closures = useMemo(() => simulation ? [...realClosures, simulation] : realClosures, [realClosures, simulation]);
  const [health, setHealth] = useState<Health | null>(null);
  const [live, setLive] = useState(false);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [dataError, setDataError] = useState('');
  const [actionError, setActionError] = useState('');
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const [prefs, setPrefs] = useState<UserPreferences>({...DEFAULT_PREFERENCES, max_grade_pct: 5, need_automatic_door: false, avoid_rough_surfaces: false});
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<'accessible' | 'standard'>('accessible');
  const [showStandard, setShowStandard] = useState(true);
  const [needsOpen, setNeedsOpen] = useState(false);
  const [ghost, setGhost] = useState<RouteResponse | null>(null);
  const [rerouted, setRerouted] = useState(false);
  const seq = useRef(0);
  const last = useRef<{sig: string; trip: string; route: RouteResponse | null}>({sig: '', trip: '', route: null});
  const [selectedBuilding, setSelectedBuilding] = useState<Building | null>(null);
  const [selectedClosure, setSelectedClosure] = useState<Closure | null>(null);
  const [focusEntranceId, setFocusEntranceId] = useState<string | null>(null);
  const [picking, setPicking] = useState<'origin' | 'destination' | 'report' | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportBuildingId, setReportBuildingId] = useState<string | null>(null);
  const [reportPoint, setReportPoint] = useState<{lat: number; lng: number} | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);
  const [hc, setHc] = useState(false);
  const [largeText, setLargeText] = useState(false);
  const [focus, setFocus] = useState<{lat: number; lng: number; key: number} | null>(null);
  const sync = useCallback(async () => {
    const result = await getClosures();
    setRealClosures(old => closuresSignature(old) === closuresSignature(result.closures) ? old : result.closures);
    setLive(result.live); setDataError(result.error);
    if (!result.error) setLastSync(Date.now());
  }, []);
  useEffect(() => {
    let mounted = true;
    Promise.all([getBuildings(), getHealth()]).then(([bs, h]) => {
      if (!mounted) return;
      setBuildings(bs); setHealth(h);
      const a = bs.find(b => b.id === 'campus-center'); const b = bs.find(b => b.id === 'library');
      if (a) setOrigin(placeFor(a)); if (b) setDestination(placeFor(b));
    }).catch(e => mounted && setActionError(message(e)));
    void sync(); const interval = setInterval(sync, 15000);
    return () => {mounted = false; clearInterval(interval);};
  }, [sync]);
  useEffect(() => {
    document.documentElement.classList.toggle('hc', hc);
    document.documentElement.classList.toggle('text-large', largeText);
  }, [hc, largeText]);
  useEffect(() => {
    if (!origin || !destination || !buildings.length) return;
    const id = ++seq.current; setLoading(true); setPlan(null);
    const timer = setTimeout(() => {
      planRoutes(origin, destination, prefs, closures).then(p => {
        if (id !== seq.current) return;
        const trip = JSON.stringify([origin, destination, prefs]); const sig = closuresSignature(closures);
        if (last.current.trip === trip && last.current.sig !== sig && last.current.route && JSON.stringify(last.current.route.features) !== JSON.stringify(p.accessible?.features)) {
          setGhost(last.current.route); setRerouted(true);
          setTimeout(() => {setGhost(null); setRerouted(false);}, 4000);
        }
        last.current = {trip, sig, route: p.accessible}; setPlan(p); setLoading(false);
      }).catch(e => {
        if (id !== seq.current) return;
        setPlan({accessible: null, standard: null, failure: message(e), notes: [], ms: 0, graphEdges: health?.edges || 0, engine: 'remote'}); setLoading(false);
      });
    }, 150);
    return () => {clearTimeout(timer); ++seq.current;};
  }, [origin, destination, prefs, closures, buildings, health]);
  const report = async (payload: UserReportPayload) => {await submitUserReport(payload); await sync();};
  const mutate = async (fn: () => Promise<unknown>) => {
    setActionError(''); try {await fn(); await sync(); setSelectedClosure(null);} catch (e) {setActionError(message(e));}
  };
  const selectedEntrance = selectedBuilding?.entrances.find(e => e.id === focusEntranceId);
  const buildingPlace = (b: Building): Place => selectedEntrance && selectedBuilding?.id === b.id
    ? {...placeFor(b), lat: selectedEntrance.lat, lng: selectedEntrance.lng, entrance_id: selectedEntrance.id} : placeFor(b);
  const destBuilding = buildings.find(b => b.id === destination?.building_id) ?? null;
  const arrival = destBuilding?.entrances.find(e => e.id === plan?.endEndpointId);
  const activeRoute = tab === 'accessible' ? plan?.accessible : plan?.standard;
  const simulate = () => {
    const points = plan?.accessible?.features.flatMap(f => f.geometry.coordinates); if (!points?.length) return;
    const index = Math.min(points.length - 2, Math.floor((points.length - 1) * 0.6));
    const lng = (points[index][0] + points[index + 1][0]) / 2;
    const lat = (points[index][1] + points[index + 1][1]) / 2; const now = new Date().toISOString();
    setSimulation({id: 'demo-path', lat, lng, radius: 2, type: 'path', status: 'closed', source: 'community',
      title: 'SIMULATION: blocked path', description: 'This browser only; not a real report.', start_time: now,
      end_time: new Date(Date.now() + 3600000).toISOString(), last_confirmed: now, confirmations_count: 0});
  };
  return <div className="fixed inset-0 overflow-hidden bg-canvas">
    <MapView buildings={buildings.filter(b => b.in_routing_area)} closures={closures}
      accessible={loading ? null : plan?.accessible ?? null} standard={loading ? null : plan?.standard ?? null}
      ghost={ghost} showStandard={showStandard} origin={origin} destination={destination}
      chosenEntranceIds={[plan?.startEndpointId, plan?.endEndpointId].filter(Boolean) as string[]}
      selectedBuildingId={selectedBuilding?.id ?? null} highContrast={hc} pickMode={!!picking} focus={focus}
      onSelectBuilding={b => {setSelectedBuilding(b); setFocusEntranceId(null);}}
      onSelectEntrance={(b, e) => {setSelectedBuilding(b); setFocusEntranceId(e.id);}}
      onSelectClosure={setSelectedClosure} onMapClick={(lat, lng) => {
        if (picking === 'report') {setReportPoint({lat, lng}); setReportOpen(true);}
        else if (picking === 'origin') setOrigin({name: 'Map pin', lat, lng});
        else if (picking === 'destination') setDestination({name: 'Map pin', lat, lng}); setPicking(null);
      }} />
    <TopBar activeIssues={realClosures.length} live={live} lastSync={lastSync}
      onReport={() => {setReportBuildingId(null); setReportPoint(null); setReportOpen(true);}}
      onAbout={() => setAboutOpen(true)} onJudge={() => setDemoOpen(v => !v)} judgeOpen={demoOpen}
      highContrast={hc} onHighContrast={() => setHc(v => !v)} largeText={largeText} onLargeText={() => setLargeText(v => !v)} />
    {picking && <div className="fixed left-1/2 top-20 z-40 -translate-x-1/2 rounded-full bg-ink px-4 py-2 text-white" role="status">
      Tap the map to set {picking === 'report' ? 'the problem location' : picking}. <button className="underline" onClick={() => setPicking(null)}>Cancel</button>
    </div>}
    <aside className="glass fixed z-20 flex flex-col overflow-hidden inset-x-0 bottom-0 max-h-[58vh] rounded-t-4xl lg:inset-x-auto lg:bottom-4 lg:left-4 lg:top-[84px] lg:max-h-none lg:w-[400px] lg:rounded-4xl" aria-label="Trip planner">
      <div className="scroll-soft flex-1 space-y-4 overflow-y-auto p-4">
        {(dataError || actionError) && <p className="rounded-xl bg-warn-soft p-3 text-sm" role="alert">{dataError || actionError} Saved information may be incomplete.</p>}
        <TripPlanner origin={origin} destination={destination} options={buildingPlaces(buildings.filter(b => b.in_routing_area))}
          onOrigin={setOrigin} onDestination={setDestination} onSwap={() => {setOrigin(destination); setDestination(origin);}}
          picking={picking === 'report' ? null : picking} onPick={setPicking} />
        {demoOpen && <section className="rounded-2xl bg-lift-soft p-3 text-sm" aria-label="Routing simulation">
          <p className="font-semibold">Path closure simulation</p><p>Try Campus Center to the library to see a detour. Other trips may have no feasible alternative. This is never saved as a real outage.</p>
          <button className="btn-quiet mt-2" disabled={!plan?.accessible || !!simulation || loading} onClick={simulate}>Simulate blocked path</button>
          {simulation && <button className="btn-quiet mt-2" onClick={() => setSimulation(null)}>Clear simulation</button>}
        </section>}
        {simulation && <p role="status" className="rounded-xl bg-lift-soft p-3 text-sm">Simulation active: the marked path is blocked in this browser.</p>}
        <NeedsMenu prefs={prefs} onChange={setPrefs} open={needsOpen} onToggle={() => setNeedsOpen(v => !v)} />
        {origin && destination && <RouteSummary accessible={plan?.accessible ?? null} standard={plan?.standard ?? null}
          failure={plan?.failure} notes={plan?.notes ?? []} tab={tab} onTab={setTab} showStandard={showStandard}
          onToggleStandard={() => setShowStandard(v => !v)} prefs={prefs}
          arrivalEntrance={arrival && destBuilding ? {building: destBuilding, name: arrival.name, door: arrival.door_type} : null}
          destinationBuilding={destBuilding} engine="remote" graphEdges={health?.edges ?? 0} loading={loading} justRerouted={rerouted} />}
        {rerouted && <p role="status" className="rounded-xl bg-lift-soft p-3 text-sm">Route recalculated after a closure changed.</p>}
        {tab === 'accessible' && plan?.accessible && origin && destination && <Narrator route={plan.accessible} originName={origin.name} destinationName={destination.name} prefs={prefs} />}
        {activeRoute && <Directions steps={activeRoute.steps} onFocusStep={s => s.at && setFocus({lat: s.at[1], lng: s.at[0], key: Date.now()})} />}
        <OutageList closures={realClosures} onSelect={setSelectedClosure} live={live} lastSync={lastSync} /><SourcePanel />
      </div>
    </aside>
    <BuildingSheet building={selectedBuilding} closures={realClosures} focusEntranceId={focusEntranceId} onSelectEntrance={setFocusEntranceId}
      onClose={() => setSelectedBuilding(null)} onStart={b => {setOrigin(buildingPlace(b)); setSelectedBuilding(null);}}
      onGo={b => {setDestination(buildingPlace(b)); setSelectedBuilding(null);}}
      onReport={b => {setReportBuildingId(b.id); setReportPoint(null); setReportOpen(true); setSelectedBuilding(null);}} />
    <ClosureSheet closure={selectedClosure} onClose={() => setSelectedClosure(null)}
      onConfirm={c => {void mutate(() => confirmClosure(c.id));}}
      onResolve={c => {void mutate(() => submitUserReport({lat: c.lat, lng: c.lng, type: c.type, status: 'working', title: c.title, description: 'Reported restored', connector_id: c.connector_id, asset_id: c.asset_id, building_id: c.building_id, floor_id: c.floor_id, timestamp: new Date().toISOString()}));}} />
    <ReportSheet open={reportOpen} onClose={() => setReportOpen(false)} buildings={buildings} initialBuildingId={reportBuildingId}
      pickedPoint={reportPoint} onPickOnMap={() => {setReportOpen(false); setPicking('report');}} onSubmit={report} />
    <AboutSheet open={aboutOpen} onClose={() => setAboutOpen(false)} graphMeta={health} provider={provider} />
  </div>;
}
