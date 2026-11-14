import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Building, BuildingEntrance, Closure, Place, RouteResponse, RouteStep, UserPreferences, UserReportPayload } from './types';
import {
  checkBackendHealth,
  closuresSignature,
  confirmClosure,
  getBuildings,
  getClosures,
  getLocalBuildings,
  getLocalClosures,
  markClosureResolved,
  planRoutes,
  PlanResult,
  resetClosures,
  submitUserReport,
  postCommunityReport,
  addLocalOfficialNotice
} from './services/api';
import { loadCampusGraph, CampusGraph, getDistanceMeters } from './services/routingEngine';
import { BusRouteData, groupIncidents, Incident, loadBusRoutes } from './services/incidents';
import { DEMO_ELEVATOR_OFFICIAL, DEMO_ELEVATOR_REPORT } from './data/mockClosures';
import { DEFAULT_PREFERENCES } from './data/profiles';
import { buildingPlaces, DEMO_TRIP, SPOTS } from './data/places';
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
import { JudgePanel, DemoLogEntry } from './components/JudgePanel';
import { AboutSheet } from './components/AboutSheet';
import { useMapProvider } from './components/map/MapsProvider';
import { cx } from './components/ui';

const POLL_MS = 5 * 60 * 1000;

function routeKey(r: RouteResponse | null): string {
  if (!r) return '';
  const c = r.features.flatMap((f) => f.geometry.coordinates);
  return `${r.summary.total_distance_m}:${c.length}:${c[Math.floor(c.length / 2)]?.join(',')}`;
}

export function App() {
  const { provider, reason } = useMapProvider();

  // ---------- data ----------
  const [buildings, setBuildings] = useState<Building[]>(getLocalBuildings);
  const [closures, setClosures] = useState<Closure[]>(getLocalClosures);
  const [live, setLive] = useState(false);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [graph, setGraph] = useState<CampusGraph | null>(null);
  const [busData, setBusData] = useState<BusRouteData | null>(null);
  // Official notices + student reports of the same problem, merged and ranked
  const incidents = useMemo(() => groupIncidents(closures, busData), [closures, busData]);
  const closuresSig = useRef(closuresSignature(closures));

  const applyClosures = useCallback((list: Closure[]) => {
    const sig = closuresSignature(list);
    if (sig !== closuresSig.current) {
      closuresSig.current = sig;
      setClosures(list);
    }
  }, []);

  const syncClosures = useCallback(async () => {
    const r = await getClosures();
    applyClosures(r.closures);
    setLive(r.live);
    setLastSync(Date.now());
    return r;
  }, [applyClosures]);

  useEffect(() => {
    loadCampusGraph().then(setGraph);
    loadBusRoutes().then(setBusData);
    const refresh = () => {
      getBuildings().then(setBuildings);
      checkBackendHealth();
      void syncClosures();
    };
    // Deferring the initial fetch lets StrictMode clean up its first effect.
    const initialFetch = setTimeout(refresh, 0);
    const poll = setInterval(refresh, POLL_MS);
    return () => {
      clearTimeout(initialFetch);
      clearInterval(poll);
    };
  }, [syncClosures]);

  // ---------- trip ----------
  const [origin, setOrigin] = useState<Place | null>(DEMO_TRIP.origin);
  const [destination, setDestination] = useState<Place | null>(DEMO_TRIP.destination);
  const [prefs, setPrefs] = useState<UserPreferences>(DEFAULT_PREFERENCES);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<'accessible' | 'standard'>('accessible');
  const [showStandard, setShowStandard] = useState(true);
  const [needsOpen, setNeedsOpen] = useState(false);
  const [ghost, setGhost] = useState<RouteResponse | null>(null);
  const [justRerouted, setJustRerouted] = useState(false);
  const planSeq = useRef(0);
  const lastPlanCtx = useRef<{ trip: string; sig: string; key: string; route: RouteResponse | null }>({ trip: '', sig: '', key: '', route: null });
  const onPlanned = useRef<((p: PlanResult) => void) | null>(null);

  useEffect(() => {
    if (!origin || !destination || !graph) return;
    const seq = ++planSeq.current;
    setLoading(true);
    planRoutes(origin, destination, prefs, closures, buildings).then((p) => {
      if (seq !== planSeq.current) return;
      const trip = `${origin.lat},${origin.lng}>${destination.lat},${destination.lng}|${JSON.stringify(prefs)}`;
      const key = routeKey(p.accessible);
      const prev = lastPlanCtx.current;
      // Same trip, new outage data, different line: that's a live reroute. Keep a ghost of the old line.
      if (prev.trip === trip && prev.sig !== closuresSig.current && prev.key && key !== prev.key) {
        setGhost(prev.route);
        setJustRerouted(true);
        setTimeout(() => setGhost(null), 4000);
        setTimeout(() => setJustRerouted(false), 1200);
      }
      lastPlanCtx.current = { trip, sig: closuresSig.current, key, route: p.accessible };
      setPlan(p);
      setLoading(false);
      onPlanned.current?.(p);
      onPlanned.current = null;
    });
  }, [origin, destination, prefs, closures, buildings, graph]);

  // ---------- selection & sheets ----------
  const [selectedBuilding, setSelectedBuilding] = useState<Building | null>(null);
  const [focusEntranceId, setFocusEntranceId] = useState<string | null>(null);
  // Keep the id, not the object, so the open sheet updates when new reports arrive
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const selectedIncident = useMemo(
    () => (selectedIncidentId ? incidents.find((i) => i.id === selectedIncidentId || i.all.some((c) => c.id === selectedIncidentId)) ?? null : null),
    [incidents, selectedIncidentId]
  );
  const [picking, setPicking] = useState<'origin' | 'destination' | 'report' | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportBuildingId, setReportBuildingId] = useState<string | null>(null);
  const [reportPoint, setReportPoint] = useState<{ lat: number; lng: number } | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [focus, setFocus] = useState<{ lat: number; lng: number; key: number } | null>(null);

  const onSelectBuilding = useCallback((b: Building) => {
    setSelectedBuilding(b);
    setFocusEntranceId(null);
  }, []);
  const onSelectEntrance = useCallback((b: Building, e: BuildingEntrance) => {
    setSelectedBuilding(b);
    setFocusEntranceId(e.id);
  }, []);
  const onSelectIncident = useCallback((inc: Incident) => setSelectedIncidentId(inc.id), []);

  const onMapClick = useCallback(
    (lat: number, lng: number) => {
      if (picking === 'origin') setOrigin({ name: 'Dropped pin', lat, lng });
      else if (picking === 'destination') setDestination({ name: 'Dropped pin', lat, lng });
      else if (picking === 'report') {
        setReportPoint({ lat, lng });
        setReportOpen(true);
      } else return;
      setPicking(null);
    },
    [picking]
  );

  // ---------- accessibility display ----------
  const [hc, setHc] = useState(false);
  const [largeText, setLargeText] = useState(false);
  useEffect(() => {
    document.documentElement.classList.toggle('hc', hc);
    document.documentElement.classList.toggle('text-large', largeText);
  }, [hc, largeText]);

  // ---------- judge demo ----------
  const [judgeOpen, setJudgeOpen] = useState(() => new URLSearchParams(location.search).has('demo'));
  const [demoLog, setDemoLog] = useState<DemoLogEntry[]>([]);
  const [demoBusy, setDemoBusy] = useState(false);
  const log = (label: string, detail: string, tone: DemoLogEntry['tone']) => setDemoLog((l) => [...l, { t: Date.now(), label, detail, tone }]);
  const elevatorBroken = closures.some((c) => c.status === 'closed' && c.connector_id === DEMO_ELEVATOR_REPORT.connector_id);
  const officialConfirmed = closures.some(
    (c) => c.status === 'closed' && c.source === 'official' && c.connector_id === DEMO_ELEVATOR_REPORT.connector_id
  );

  const demoConfirmOfficial = () => {
    applyClosures(addLocalOfficialNotice(DEMO_ELEVATOR_OFFICIAL));
    log('official', 'Facilities posts a matching notice (simulated) · ranked High alert', 'warn');
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || e.metaKey || e.ctrlKey) return;
      if (e.key === 'j' || e.key === 'J') setJudgeOpen((o) => !o);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const demoLoadTrip = () => {
    setPrefs(DEFAULT_PREFERENCES);
    setOrigin(DEMO_TRIP.origin);
    setDestination(DEMO_TRIP.destination);
    setTab('accessible');
    setShowStandard(true);
    log('trip', 'Student Union → Campus Center upper terrace, manual wheelchair', 'route');
  };

  const afterReport = async (label: string, payload: UserReportPayload) => {
    const before = plan?.accessible?.summary;
    const t0 = performance.now();
    const rep = await submitUserReport(payload);
    log(
      rep.browserOnly ? 'local' : 'POST /reports',
      rep.browserOnly ? 'kept in this browser (backend has no fix endpoint yet)' : `${rep.live ? 'stored in backend' : 'backend offline, stored locally'} · ${rep.ms} ms`,
      'net'
    );
    onPlanned.current = (p) => {
      const a = p.accessible?.summary;
      const delta = a && before ? a.total_distance_m - before.total_distance_m : 0;
      log(
        'route',
        a
          ? `recomputed in ${a.compute_ms ?? '?'} ms · ${a.total_distance_m} m (${delta >= 0 ? '+' : ''}${delta} m) · ${a.elevators_used?.length ? 'via elevator' : 'no elevator'} · ${Math.round(performance.now() - t0)} ms end to end`
          : `no step-free route: ${p.failure}`,
        'route'
      );
    };
    const r = await syncClosures();
    log('GET /closures', `${r.closures.filter((c) => c.status !== 'repaired').length} active · ${r.live ? 'live' : 'local'} · ${r.ms} ms`, 'ok');
    void label;
  };

  const demoBreak = async () => {
    setDemoBusy(true);
    if (!origin || origin.name !== DEMO_TRIP.origin.name) demoLoadTrip();
    await afterReport('break', {
      ...DEMO_ELEVATOR_REPORT,
      type: 'elevator',
      status: 'broken',
      reporter_device_id: 'judge-demo',
      timestamp: new Date().toISOString()
    });
    setDemoBusy(false);
  };

  const demoFix = async () => {
    setDemoBusy(true);
    await afterReport('fix', {
      ...DEMO_ELEVATOR_REPORT,
      title: 'Campus Center concourse elevator working again',
      description: 'Rode it up just now.',
      type: 'elevator',
      status: 'working',
      reporter_device_id: 'judge-demo',
      timestamp: new Date().toISOString()
    });
    setDemoBusy(false);
  };

  const demoReset = () => {
    if (elevatorBroken) {
      // Tell a live backend too, otherwise the next poll would bring the outage back
      void submitUserReport({ ...DEMO_ELEVATOR_REPORT, type: 'elevator', status: 'working', description: 'Demo reset', timestamp: new Date().toISOString() });
    }
    const list = resetClosures();
    applyClosures(list);
    setDemoLog([]);
    demoLoadTrip();
  };

  // ---------- derived ----------
  const pickOptions = useMemo(() => [...buildingPlaces(buildings), ...SPOTS], [buildings]);
  const activeRoute = tab === 'accessible' ? plan?.accessible ?? null : plan?.standard ?? null;
  const destBuilding = destination?.building_id ? buildings.find((b) => b.id === destination.building_id) ?? null : null;
  const arrival = useMemo(() => {
    if (!destBuilding || !plan?.endEndpointId) return null;
    const e = destBuilding.entrances.find((x) => x.id === plan.endEndpointId);
    return e ? { building: destBuilding, name: e.name, door: e.door_type === 'push-button' ? 'push-button' : e.door_type } : null;
  }, [destBuilding, plan?.endEndpointId]);
  const chosenEntranceIds = useMemo(() => [plan?.endEndpointId, plan?.startEndpointId].filter(Boolean) as string[], [plan?.endEndpointId, plan?.startEndpointId]);
  const activeIssues = incidents.length;
  const highAlerts = incidents.filter((i) => i.severity === 'high').length;

  // Starting or ending at a bus stop on a closed road: warn that buses may skip it
  const busStopNotes = useMemo(() => {
    const notes: string[] = [];
    for (const p of [origin, destination]) {
      const spot = p && SPOTS.find((s) => s.kind === 'bus' && s.name === p.name);
      if (!spot) continue;
      for (const inc of incidents) {
        if (!inc.bus?.certain) continue;
        if (getDistanceMeters(spot.lat, spot.lng, inc.primary.lat, inc.primary.lng) <= Math.max(60, inc.primary.radius + 40)) {
          notes.push(`${spot.name}: routes ${inc.bus.routes.join(', ')} are detoured (${inc.primary.title}). Buses may skip this stop.`);
        }
      }
    }
    return notes;
  }, [origin, destination, incidents]);

  const focusStep = (s: RouteStep) => s.at && setFocus({ lat: s.at[1], lng: s.at[0], key: Date.now() });

  const handleReportSubmit = async (p: UserReportPayload) => {
    await postCommunityReport(p);
    applyClosures(getLocalClosures());
    setReportPoint(null);
  };

  return (
    <div className="fixed inset-0 overflow-hidden bg-canvas">
      <MapView
        buildings={buildings}
        closures={closures}
        accessible={plan?.accessible ?? null}
        standard={plan?.standard ?? null}
        ghost={ghost}
        showStandard={showStandard}
        origin={origin}
        destination={destination}
        chosenEntranceIds={chosenEntranceIds}
        selectedBuildingId={selectedBuilding?.id ?? null}
        highContrast={hc}
        pickMode={!!picking}
        focus={focus}
        onSelectBuilding={onSelectBuilding}
        incidents={incidents}
        onSelectIncident={onSelectIncident}
        onSelectEntrance={onSelectEntrance}
        onMapClick={onMapClick}
      />

      <TopBar
        activeIssues={activeIssues}
        highAlerts={highAlerts}
        live={live}
        lastSync={lastSync}
        onReport={() => {
          setReportBuildingId(null);
          setReportOpen(true);
        }}
        onAbout={() => setAboutOpen(true)}
        onJudge={() => setJudgeOpen((o) => !o)}
        judgeOpen={judgeOpen}
        highContrast={hc}
        onHighContrast={() => setHc((v) => !v)}
        largeText={largeText}
        onLargeText={() => setLargeText((v) => !v)}
      />

      {picking && (
        <div className="fixed left-1/2 top-20 z-40 -translate-x-1/2 rounded-full bg-ink px-4 py-2 text-[13px] text-white shadow-lift animate-pop" role="status">
          Tap the map to set {picking === 'report' ? 'the problem location' : picking === 'origin' ? 'your start' : 'your destination'} ·{' '}
          <button className="underline" onClick={() => setPicking(null)}>
            cancel
          </button>
        </div>
      )}

      <aside
        className={cx(
          'glass fixed z-20 flex flex-col overflow-hidden',
          'inset-x-0 bottom-0 max-h-[58vh] rounded-t-4xl',
          'lg:inset-x-auto lg:bottom-4 lg:left-4 lg:top-[84px] lg:max-h-none lg:w-[400px] lg:rounded-4xl'
        )}
        aria-label="Trip planner"
      >
        <div className="mx-auto mt-2 h-1 w-9 rounded-full bg-black/15 lg:hidden" aria-hidden />
        <div className="scroll-soft flex-1 space-y-4 overflow-y-auto p-4">
          <TripPlanner
            origin={origin}
            destination={destination}
            options={pickOptions}
            onOrigin={setOrigin}
            onDestination={setDestination}
            onSwap={() => {
              setOrigin(destination);
              setDestination(origin);
            }}
            picking={picking === 'origin' || picking === 'destination' ? picking : null}
            onPick={setPicking}
          />
          <NeedsMenu prefs={prefs} onChange={setPrefs} open={needsOpen} onToggle={() => setNeedsOpen((o) => !o)} />
          {origin && destination && (
            <RouteSummary
              accessible={plan?.accessible ?? null}
              standard={plan?.standard ?? null}
              failure={plan?.failure}
              notes={[...(plan?.notes ?? []), ...busStopNotes]}
              tab={tab}
              onTab={setTab}
              showStandard={showStandard}
              onToggleStandard={() => setShowStandard((v) => !v)}
              prefs={prefs}
              arrivalEntrance={arrival}
              destinationBuilding={destBuilding}
              engine={plan?.engine ?? 'local'}
              graphEdges={graph?.e.length ?? 0}
              loading={loading}
              justRerouted={justRerouted}
            />
          )}
          {tab === 'accessible' && plan?.accessible && origin && destination && (
            <Narrator route={plan.accessible} originName={origin.name} destinationName={destination.name} prefs={prefs} />
          )}
          {activeRoute && <Directions steps={activeRoute.steps} onFocusStep={focusStep} />}
          <OutageList incidents={incidents} onSelect={onSelectIncident} live={live} lastSync={lastSync} />
          {provider === 'osm' && reason && (
            <p className="px-1 text-[11px] text-ink-4">
              Basemap: OpenStreetMap ({reason.toLowerCase()}). Add VITE_GOOGLE_MAPS_API_KEY to use Google Maps.
            </p>
          )}
        </div>
      </aside>

      <BuildingSheet
        building={selectedBuilding}
        closures={closures}
        focusEntranceId={focusEntranceId}
        onClose={() => setSelectedBuilding(null)}
        onStart={(b) => {
          setOrigin({ name: b.name, lat: b.location.lat, lng: b.location.lng, building_id: b.id });
          setSelectedBuilding(null);
        }}
        onGo={(b) => {
          setDestination({ name: b.name, lat: b.location.lat, lng: b.location.lng, building_id: b.id });
          setSelectedBuilding(null);
        }}
        onReport={(b) => {
          setReportBuildingId(b.id);
          setSelectedBuilding(null);
          setReportOpen(true);
        }}
      />

      <ClosureSheet
        incident={selectedIncident}
        onClose={() => setSelectedIncidentId(null)}
        onConfirm={(c) => {
          applyClosures(confirmClosure(c.id));
          setSelectedIncidentId(null);
        }}
        onResolve={async (inc) => {
          // Fixed means every report of this problem is fixed, official and student alike
          let list: Closure[] = [];
          for (const c of inc.all) list = markClosureResolved(c.id);
          applyClosures(list);
          setSelectedIncidentId(null);
          const c = inc.primary;
          await submitUserReport({
            lat: c.lat,
            lng: c.lng,
            type: c.type,
            status: 'working',
            title: `${c.title} (fixed)`,
            description: '',
            connector_id: c.connector_id,
            timestamp: new Date().toISOString()
          });
        }}
      />

      <ReportSheet
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        buildings={buildings}
        initialBuildingId={reportBuildingId}
        pickedPoint={reportPoint}
        onPickOnMap={() => {
          setReportOpen(false);
          setPicking('report');
        }}
        onSubmit={handleReportSubmit}
      />

      <AboutSheet open={aboutOpen} onClose={() => setAboutOpen(false)} graphMeta={graph?.meta ?? null} provider={provider} />

      <JudgePanel
        open={judgeOpen}
        onClose={() => setJudgeOpen(false)}
        elevatorBroken={elevatorBroken}
        busy={demoBusy}
        log={demoLog}
        onLoadTrip={demoLoadTrip}
        onBreak={demoBreak}
        onConfirmOfficial={demoConfirmOfficial}
        officialConfirmed={officialConfirmed}
        onFix={demoFix}
        onReset={demoReset}
        live={live}
      />
    </div>
  );
}
