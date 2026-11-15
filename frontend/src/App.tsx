import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { displayInstruction, formatDistance } from './services/displayUnits';
import { routeStepPosition } from './services/routeSteps';
import type { Building, BuildingEntrance, Closure, Place, RouteResponse, RouteStep, UserPreferences, UserReportPayload } from './types';
import {
  closuresSignature,
  confirmClosure,
  getBuildings,
  getSourceBuildings,
  sourceRoutingAvailable,
  getClosures,
  markClosureResolved,
  planRoutes,
  PlanResult,
  type IndoorIntent,
  DEMO_MODE,
  resetClosures,
  submitUserReport,
  addLocalOfficialNotice
} from './services/api';
import { loadCampusGraph, CampusGraph, getDistanceMeters } from './services/routingEngine';
import { BusRouteData, groupIncidents, Incident, loadBusRoutes } from './services/incidents';
import { UMASS_BUILDINGS } from './data/mockBuildings';
import { DEMO_ELEVATOR_OFFICIAL, DEMO_ELEVATOR_REPORT, INITIAL_CLOSURES } from './data/mockClosures';
import { DEFAULT_PREFERENCES } from './data/profiles';
import { buildingPlaces, DEMO_TRIP, SPOTS } from './data/places';
import { MapView } from './components/MapView';
import { TopBar } from './components/TopBar';
import { TripPlanner } from './components/TripPlanner';
import { MobileTripSheet } from './components/MobileTripSheet';
import { NeedsMenu } from './components/NeedsMenu';
import { RouteSummary } from './components/RouteSummary';
import { Narrator } from './components/Narrator';
import { Directions } from './components/Directions';
import { OutdoorGuide } from './components/OutdoorGuide';
import { IndoorDirectionsSheet, type IndoorLeg, useIndoorDirectionsAvailable } from './components/IndoorDirectionsSheet';
import { SourcePanel } from './components/SourcePanel';
import type { JourneyEndpoint, JourneyLeg } from './services/api';
import { OutageList } from './components/OutageList';
import { BuildingSheet } from './components/BuildingSheet';
import { ClosureSheet } from './components/ClosureSheet';
import { ReportSheet } from './components/ReportSheet';
import { JudgePanel, DemoLogEntry } from './components/JudgePanel';
import { AboutSheet } from './components/AboutSheet';
import { useMapProvider } from './components/map/MapsProvider';
import { cx } from './components/ui';
import IndoorFlow, { type ViewState } from './components/indoor/IndoorFlow';
import { IndoorCatalogContext, useIndoorCatalog } from './components/indoor/indoorCatalog';
import DestinationInput, { type DestinationTarget } from './components/indoor/DestinationInput';

function routeKey(r: RouteResponse | null): string {
  if (!r) return '';
  const c = r.features.flatMap((f) => f.geometry.coordinates);
  return `${r.summary.total_distance_m}:${c.length}:${c[Math.floor(c.length / 2)]?.join(',')}`;
}

export function App() {
  const { provider, reason } = useMapProvider();

  // ---------- data ----------
  const [baseBuildings, setBuildings] = useState<Building[]>(() => DEMO_MODE ? UMASS_BUILDINGS : getSourceBuildings());
  // Reviewed indoor maps and built-in samples, matched to the outdoor buildings.
  // Buildings that only exist as an indoor map are added to the map too.
  const indoorCatalog = useIndoorCatalog(baseBuildings);
  const buildings = useMemo(
    () => (indoorCatalog.extraBuildings.length ? [...baseBuildings, ...indoorCatalog.extraBuildings] : baseBuildings),
    [baseBuildings, indoorCatalog.extraBuildings]
  );
  const [closures, setClosures] = useState<Closure[]>(DEMO_MODE ? INITIAL_CLOSURES : []);
  const [routingConnected, setRoutingConnected] = useState<boolean | null>(DEMO_MODE ? true : null);
  const [scheduled, setScheduled] = useState<Closure[]>([]);
  const [live, setLive] = useState(false);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [graph, setGraph] = useState<CampusGraph | null>(null);
  const [busData, setBusData] = useState<BusRouteData | null>(null);
  // Official notices + student reports of the same problem, merged and ranked
  const incidents = useMemo(() => groupIncidents(closures, busData), [closures, busData]);
  const listedIncidents = useMemo(() => [
    ...incidents,
    ...scheduled.flatMap(c => groupIncidents([{...c, title: `Scheduled · ${c.title}`}], busData)),
  ], [incidents, scheduled, busData]);
  const closuresSig = useRef(closuresSignature(DEMO_MODE ? INITIAL_CLOSURES : []));

  const applyClosures = useCallback((list: Closure[]) => {
    const sig = closuresSignature(list);
    if (sig !== closuresSig.current) {
      closuresSig.current = sig;
      setClosures(list);
    }
  }, []);

  const syncClosures = useCallback(async () => {
    const [r, connected] = await Promise.all([getClosures(), sourceRoutingAvailable()]);
    setRoutingConnected(connected);
    applyClosures(r.closures);
    setLive(r.live);
    setScheduled(previous => r.scheduled ?? previous.filter(c => Date.parse(c.start_time) > Date.now()));
    if (r.received) setLastSync(Date.now());
    return r;
  }, [applyClosures]);

  const lastVisitRefresh = useRef(0);
  const refreshOnVisit = useCallback(() => {
    const now = Date.now();
    // A tab focus can coincide with startup or opening the arrival dialog.
    if (document.hidden || now - lastVisitRefresh.current < 2000) return;
    lastVisitRefresh.current = now;
    void syncClosures();
  }, [syncClosures]);

  useEffect(() => {
    if (DEMO_MODE) loadCampusGraph().then(setGraph);
    loadBusRoutes().then(setBusData);
    getBuildings().then(setBuildings);
    refreshOnVisit();
    window.addEventListener('focus', refreshOnVisit);
    document.addEventListener('visibilitychange', refreshOnVisit);
    return () => {
      window.removeEventListener('focus', refreshOnVisit);
      document.removeEventListener('visibilitychange', refreshOnVisit);
    };
  }, [refreshOnVisit]);

  // ---------- trip ----------
  const [origin, setOrigin] = useState<Place | null>(DEMO_TRIP.origin);
  const [destination, setDestination] = useState<Place | null>(DEMO_TRIP.destination);
  const [prefs, setPrefs] = useState<UserPreferences>(DEFAULT_PREFERENCES);
  const [tab, setTab] = useState<'accessible' | 'standard'>('accessible');
  const [showStandard, setShowStandard] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<'directions' | 'trip'>('directions');
  const [needsOpen, setNeedsOpen] = useState(false);
  const [ghost, setGhost] = useState<RouteResponse | null>(null);
  const [justRerouted, setJustRerouted] = useState(false);
  const lastPlanCtx = useRef<{ trip: string; sig: string; key: string; route: RouteResponse | null }>({ trip: '', sig: '', key: '', route: null });
  const onPlanned = useRef<((p: PlanResult) => void) | null>(null);

  // Room / floor picked in the destination search bar, handed to the indoor flow on arrival
  const [indoorTarget, setIndoorTarget] = useState<DestinationTarget | null>(null);
  const [originTarget, setOriginTarget] = useState<DestinationTarget | null>(null);
  const [residentAccess, setResidentAccess] = useState(false);
  const [inspectedLeg, setInspectedLeg] = useState<JourneyLeg | null>(null);
  // Tell the routing engine what happens inside: a room on another floor means an elevator is needed,
  // so it prefers the entrance closest to a working one
  const destIndoorMap = indoorCatalog.forBuilding(destination?.building_id);
  const indoorIntent = useMemo<IndoorIntent>(() => {
    const endpoint = (target: DestinationTarget | null, id?: string): JourneyEndpoint | undefined => {
      const model = indoorCatalog.forBuilding(id);
      if (!model || model.source !== 'api' || !target?.roomId || target.buildingId !== id) return undefined;
      const floor = /^(.+):@lobby$/.exec(target.roomId);
      const node = floor ? [...model.nodes.values()].find(n => n.floor === floor[1] && n.kind === 'elevator_stop')?.id : target.roomId;
      return {kind: model.routingKind || 'indoor', building_id: model.id, node_id: node || target.roomId};
    };
    const from = endpoint(originTarget, origin?.building_id);
    const to = endpoint(indoorTarget, destination?.building_id);
    if (!from && destIndoorMap?.source === 'api' && destIndoorMap.status === 'reviewed' && !destIndoorMap.routingKind) {
      return {reviewedBuildingId: destIndoorMap.id, nodeId: to && to.kind !== 'outdoor' ? to.node_id : undefined};
    }
    return {origin: from, destination: to,
      residentAccess, preferIndoorEntrance: destIndoorMap?.routingKind === 'drawing'};
  }, [indoorCatalog, originTarget, indoorTarget, origin?.building_id, destination?.building_id, residentAccess]);
  const intentKey = JSON.stringify(indoorIntent);
  // Match results to all inputs during render, before the next effect starts.
  // A previous trip's failure (or successful route) is not the new trip's result.
  const planRequest = useMemo(() => ({origin, destination, prefs, closures, buildings, graph, intentKey}),
    [origin, destination, prefs, closures, buildings, graph, intentKey]);
  const [completedPlan, setCompletedPlan] = useState<{request: typeof planRequest; result: PlanResult} | null>(null);
  const plan = completedPlan?.request === planRequest ? completedPlan.result : null;
  const loading = !!origin && !!destination && !plan;

  useEffect(() => {
    if (!origin || !destination || (DEMO_MODE && !graph)) return;
    let cancelled = false;
    planRoutes(origin, destination, prefs, closures, buildings, indoorIntent).then((p) => {
      if (cancelled) return;
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
      setCompletedPlan({request: planRequest, result: p});
      onPlanned.current?.(p);
      onPlanned.current = null;
    }).catch(error => {
      if (cancelled) return;
      setCompletedPlan({request: planRequest, result: {accessible: null, standard: null, engine: 'remote', ms: 0, notes: [],
        failure: error instanceof Error ? error.message : 'Could not calculate this journey.'}});
    });
    // Also ignore in-flight results when either endpoint is cleared or on unmount.
    return () => {cancelled = true;};
    // All planning inputs, including indoorIntent via intentKey, are in planRequest.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planRequest]);

  // ---------- selection & sheets ----------
  const [selectedBuilding, setSelectedBuilding] = useState<Building | null>(null);
  const [focusEntranceId, setFocusEntranceId] = useState<string | null>(null);
  // Keep the id, not the object, so the open sheet updates when new reports arrive
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);
  const selectedIncident = useMemo(
    () => (selectedIncidentId ? listedIncidents.find((i) => i.id === selectedIncidentId || i.all.some((c) => c.id === selectedIncidentId)) ?? null : null),
    [listedIncidents, selectedIncidentId]
  );
  const [picking, setPicking] = useState<'origin' | 'destination' | 'report' | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportBuildingId, setReportBuildingId] = useState<string | null>(null);
  const [reportPoint, setReportPoint] = useState<{ lat: number; lng: number } | null>(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [guiding, setGuiding] = useState(false);
  const [indoorDirOpen, setIndoorDirOpen] = useState(false);
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
      rep.browserOnly ? 'kept in this browser' : `stored in backend · ${rep.ms} ms`,
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
    return rep;
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
    const list = resetClosures();
    applyClosures(list);
    setDemoLog([]);
    demoLoadTrip();
  };

  // ---------- derived ----------
  const pickOptions = useMemo(() => [...buildingPlaces(buildings), ...SPOTS], [buildings]);
  const activeRoute = tab === 'accessible' ? plan?.accessible ?? null : plan?.standard ?? null;
  const [routeProgress, setRouteProgress] = useState<{route: RouteResponse; index: number} | null>(null);
  const activeStep = routeProgress?.route === activeRoute ? routeProgress?.index ?? 0 : 0;
  const stepPosition = useMemo(() => routeStepPosition(activeRoute, activeStep), [activeRoute, activeStep]);
  const destBuilding = destination?.building_id ? buildings.find((b) => b.id === destination.building_id) ?? null : null;
  const arrival = useMemo(() => {
    if (!destBuilding || !plan?.endEndpointId) return null;
    const e = destBuilding.entrances.find((x) => x.id === plan.endEndpointId);
    return e ? { building: destBuilding, name: e.name, door: e.door_type === 'push-button' ? 'push-button' : e.door_type } : null;
  }, [destBuilding, plan?.endEndpointId]);
  // The door the outdoor route actually ends at (chosen by the routing engine when it answered).
  // The indoor route starts from this point instead of the floor plan's default entrance.
  const indoorEntrance = useMemo(() => {
    const ap = plan?.accessible ? plan.arrivalPoint : undefined;
    if (!ap) return null;
    const e = destBuilding?.entrances.find((x) => x.id === ap.entranceId);
    return {
      id: ap.entranceId,
      portalId: ap.portalId,
      indoorNodeId: ap.indoorNodeId,
      handoffMessage: ap.handoffMessage,
      // Exactly the coordinate the engine returned; names come from our building data when the id matches
      lat: ap.lat,
      lng: ap.lng,
      name: ap.label || e?.name || 'Entrance',
      door: (e?.door_type === 'manual' ? 'manual' : 'automatic') as 'manual' | 'automatic',
      source: ap.source
    };
  }, [plan, destBuilding]);
  const chosenEntranceIds = useMemo(() => [plan?.endEndpointId, plan?.startEndpointId].filter(Boolean) as string[], [plan?.endEndpointId, plan?.startEndpointId]);
  const indoorDirAvailable = useIndoorDirectionsAvailable();
  const arriveLeg: IndoorLeg | null = destBuilding ? {buildingId: destBuilding.id, buildingName: destBuilding.name,
    door: indoorEntrance ? {lat: indoorEntrance.lat, lng: indoorEntrance.lng, name: indoorEntrance.name} : null} : null;
  const originBuilding = buildings.find(b => b.id === origin?.building_id);
  const exitDoor = originBuilding?.entrances.find(e => e.id === plan?.startEndpointId);
  const leaveLeg: IndoorLeg | null = originBuilding ? {buildingId: originBuilding.id, buildingName: originBuilding.name,
    door: exitDoor ? {lat: exitDoor.lat, lng: exitDoor.lng, name: exitDoor.name} : null} : null;
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

  // ---------- indoor view state machine ----------
  // 'outdoor' -> 'transition_modal' -> 'indoor_2d' <-> 'indoor_3d' -> 'outdoor'
  // The outdoor map stays mounted underneath; indoor views render on top of it.
  const indoorBuildingId = destIndoorMap ? destination?.building_id ?? null : null;
  const [viewState, setViewState] = useState<ViewState>('outdoor');
  useEffect(() => {
    if (viewState === 'transition_modal') refreshOnVisit();
  }, [viewState, refreshOnVisit]);
  // ?indoor=<building id or map id> jumps straight to the arrival modal (demo / testing).
  // Waits for the catalog, since map files and the indoor API load after the first render.
  const indoorParamDone = useRef(false);
  useEffect(() => {
    if (indoorParamDone.current) return;
    const id = new URLSearchParams(location.search).get('indoor');
    if (!id) {
      indoorParamDone.current = true;
      return;
    }
    const entry = indoorCatalog.entries.find((e) => e.buildingId === id || e.model.id === id);
    const b = entry ? buildings.find((x) => x.id === entry.buildingId) : null;
    if (b) {
      indoorParamDone.current = true;
      setDestination({ name: b.name, lat: b.location.lat, lng: b.location.lng, building_id: b.id });
      setViewState('transition_modal');
    } else if (!indoorCatalog.loading) indoorParamDone.current = true;
  }, [indoorCatalog, buildings]);
  // Changing to a destination without an indoor map closes any indoor view (not on first render)
  const prevIndoorId = useRef(indoorBuildingId);
  useEffect(() => {
    if (prevIndoorId.current !== indoorBuildingId && !indoorBuildingId) setViewState('outdoor');
    prevIndoorId.current = indoorBuildingId;
  }, [indoorBuildingId]);
  const arrivedAtIndoorBuilding = !!indoorBuildingId && !!plan?.accessible && viewState === 'outdoor';
  const indoorHandoffReady = !!(indoorEntrance?.indoorNodeId || indoorEntrance?.portalId);
  const indoorActionLabel = indoorHandoffReady ? `At ${destination?.name}? Go inside` : 'Indoor connection unavailable — view details';
  const inspectedSteps = (inspectedLeg?.steps || []) as {from_node_id: string; to_node_id: string}[];
  const viewBuildingId = inspectedLeg?.building_id || indoorBuildingId;
  const viewModel = inspectedLeg ? indoorCatalog.forBuilding(inspectedLeg.building_id) : destIndoorMap;
  const viewTargetId = inspectedLeg ? inspectedSteps[inspectedSteps.length - 1]?.to_node_id : indoorTarget?.roomId;
  const viewStartId = inspectedLeg ? inspectedSteps[0]?.from_node_id : undefined;

  // Picking a different destination elsewhere (the To field, a building pin) drops a stale room
  useEffect(() => {
    if (indoorTarget && destination?.building_id !== indoorTarget.buildingId) setIndoorTarget(null);
  }, [destination?.building_id, indoorTarget]);
  useEffect(() => {if (originTarget && originTarget.buildingId !== origin?.building_id) setOriginTarget(null);}, [origin?.building_id, originTarget]);
  useEffect(() => {setInspectedLeg(null);}, [plan]);
  const onDestinationSearch = (t: DestinationTarget) => {
    const b = buildings.find((x) => x.id === t.buildingId);
    setDestination({ name: b?.name ?? t.buildingName, lat: b?.location.lat ?? t.lat, lng: b?.location.lng ?? t.lng, building_id: t.buildingId });
    setIndoorTarget(t.type === 'building' ? null : t);
    setTab('accessible');
  };

  const focusStep = (s: RouteStep, index: number) => {
    if (!activeRoute) return;
    setRouteProgress({route: activeRoute, index});
    const point = routeStepPosition(activeRoute, index);
    if (point) setFocus({lat: point.lat, lng: point.lng, key: Date.now()});
    // Tapping the last outdoor step ("Arrive at ...") at a supported building offers the indoor route
    if (s.icon === 'destination' && indoorBuildingId && !guiding) {
      setViewState('transition_modal');
      return;
    }
  };

  const handleReportSubmit = async (p: UserReportPayload) => {
    const result = await afterReport('user', p);
    setReportPoint(null);
    return result;
  };

  return (
    <IndoorCatalogContext.Provider value={indoorCatalog}>
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
        stepPosition={stepPosition}
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

      {activeRoute && viewState === 'outdoor' && !guiding && (
        <div className="fixed right-4 top-[152px] z-30 hidden max-h-[calc(100dvh-176px)] w-[360px] overflow-y-auto rounded-3xl lg:block" aria-label="Current route directions">
          <Directions key={routeKey(activeRoute)} steps={activeRoute.steps} activeStep={activeStep} onFocusStep={focusStep} />
          <button type="button" className="btn btn-primary mt-2 w-full justify-center" onClick={() => setGuiding(true)}>Start guided directions</button>
        </div>
      )}

      {picking && (
        <div className="fixed left-1/2 top-[120px] z-40 -translate-x-1/2 rounded-full bg-ink lg:top-[140px] px-4 py-2 text-[13px] text-white shadow-lift animate-pop" role="status">
          Tap the map to set {picking === 'report' ? 'the problem location' : picking === 'origin' ? 'your start' : 'your destination'} ·{' '}
          <button className="underline" onClick={() => setPicking(null)}>
            cancel
          </button>
        </div>
      )}

      {!guiding && <MobileTripSheet hasRoute={!!activeRoute} picking={!!picking}
        title={activeRoute ? `Step ${activeStep + 1} of ${activeRoute.steps.length}` : loading ? 'Finding a route…' : 'Trip details'}
        detail={activeRoute?.steps[activeStep] ? displayInstruction(activeRoute.steps[activeStep].instruction) : destination ? `To ${destination.name}` : 'Choose your start and destination'}
        onNext={activeRoute && activeStep < activeRoute.steps.length - 1
          ? () => focusStep(activeRoute.steps[activeStep + 1], activeStep + 1)
          : arrivedAtIndoorBuilding ? () => {setInspectedLeg(null); setViewState('transition_modal');} : undefined}
        nextLabel={activeRoute && activeStep < activeRoute.steps.length - 1 ? 'Next' : 'Go inside'}>
        {activeRoute && <div className="flex shrink-0 gap-2 border-b border-slate-200 px-4 py-2 lg:hidden" aria-label="Trip panel view">
          <button className={cx('min-h-11 flex-1 rounded-xl text-sm font-semibold', mobilePanel === 'directions' && 'bg-emerald-100 text-emerald-900')} aria-pressed={mobilePanel === 'directions'} onClick={() => setMobilePanel('directions')}>Directions</button>
          <button className={cx('min-h-11 flex-1 rounded-xl text-sm font-semibold', mobilePanel === 'trip' && 'bg-emerald-100 text-emerald-900')} aria-pressed={mobilePanel === 'trip'} onClick={() => setMobilePanel('trip')}>Trip details</button>
        </div>}
        <div className="trip-scroll scroll-soft min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
          {activeRoute && mobilePanel === 'directions' && <div className="space-y-3 lg:hidden">
            <p className="text-sm font-semibold">To {destination?.name} <span className="font-normal text-slate-600"> · {formatDistance(activeRoute.summary.total_distance_m)}</span></p>
            <Directions key={routeKey(activeRoute)} steps={activeRoute.steps} activeStep={activeStep} onFocusStep={focusStep} />
            <button type="button" className="btn btn-primary w-full justify-center" onClick={() => setGuiding(true)}>Start guided directions</button>
            {arrivedAtIndoorBuilding && <button type="button" className="min-h-11 w-full rounded-xl bg-emerald-700 px-3 py-3 text-sm font-semibold text-white" onClick={() => {setInspectedLeg(null); setViewState('transition_modal');}}>{indoorActionLabel}</button>}
          </div>}
          <div className={cx('space-y-4', activeRoute && mobilePanel === 'directions' && 'hidden lg:block')}>
          {arrivedAtIndoorBuilding && <button type="button" className="w-full rounded-xl bg-emerald-700 px-3 py-2 text-sm font-semibold text-white lg:hidden" onClick={() => {setInspectedLeg(null); setViewState('transition_modal');}}>{indoorActionLabel}</button>}
          {routingConnected === false && <p role="status" className="rounded-2xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">Routing backend unavailable. Showing our saved UMass building data. Outdoor routes and source indoor maps will be available when the backend connects.</p>}
          <TripPlanner
            origin={origin}
            destination={destination}
            options={pickOptions}
            onOrigin={setOrigin}
            onDestination={setDestination}
            onSwap={() => {
              setOriginTarget(indoorTarget);
              setIndoorTarget(originTarget);
              setOrigin(destination);
              setDestination(origin);
            }}
            picking={picking === 'origin' || picking === 'destination' ? picking : null}
            onPick={setPicking}
          />
          <details className="space-y-2">
            <summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold">Indoor starting place (optional)</summary>
            <DestinationInput placeholder="Start at a building, floor or landmark" value={originTarget?.label}
              onSelect={target => {const b = buildings.find(b => b.id === target.buildingId); if (b) setOrigin({name: b.name, building_id: b.id, ...b.location}); setOriginTarget(target.type === 'building' ? null : target);}} />
            {originTarget && <button className="text-xs underline" onClick={() => setOriginTarget(null)}>Start outdoors instead</button>}
            <label className="flex gap-2 text-xs"><input type="checkbox" checked={residentAccess} onChange={e => setResidentAccess(e.target.checked)} />I have permission/keycard access for the selected residence.</label>
          </details>
          {plan?.journey && <section className="space-y-3 rounded-2xl border border-emerald-200 p-3" aria-label="Complete journey directions">
            <h2 className="font-semibold">Indoor and outdoor journey</h2>
            {plan.journey.total_distance === null && <p className="text-xs">Indoor distance is unknown; the map shows the outdoor portion.</p>}
            {plan.journey.legs.map((leg, i) => <details key={i} open={leg.kind === 'indoor'}>
              <summary className="text-sm font-semibold">{i + 1}. {leg.kind}{leg.building_id ? ` · ${leg.building_id}` : ''}</summary>
              {leg.kind === 'indoor' && <><ol className="my-2 space-y-1 text-sm">{((leg.steps || []) as {instruction: string}[]).map((step, n) => <li key={n}>{step.instruction}</li>)}</ol><button className="rounded-xl bg-emerald-700 px-3 py-2 text-sm text-white" onClick={() => {setInspectedLeg(leg); setViewState('indoor_2d');}}>View this floor route</button></>}
              {leg.kind === 'portal' && <p className="text-sm">{String(leg.instruction || '')}</p>}
            </details>)}
          </section>}
          <NeedsMenu prefs={prefs} onChange={setPrefs} open={needsOpen} onToggle={() => setNeedsOpen((o) => !o)} />
          {origin && destination && (
            <RouteSummary
              accessible={plan?.accessible ?? null}
              standard={plan?.standard ?? null}
              failure={plan?.failure}
              failureCode={plan?.failureCode}
              onAllowUnverifiedDoors={() => setPrefs(current => ({...current, need_automatic_door: false}))}
              notes={[...(plan?.notes ?? []), ...busStopNotes]}
              tab={tab}
              onTab={(next) => {
                setTab(next);
                if (next === 'standard') setShowStandard(true);
              }}
              showStandard={showStandard}
              onToggleStandard={() => {
                if (showStandard) setTab('accessible');
                setShowStandard(!showStandard);
              }}
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
          <OutageList incidents={listedIncidents} onSelect={onSelectIncident} live={live} lastSync={lastSync} />
          {indoorDirAvailable && plan?.accessible && (arriveLeg || leaveLeg) && <button type="button" className="btn btn-quiet w-full justify-center" onClick={() => setIndoorDirOpen(true)}>Indoor directions</button>}
          {!DEMO_MODE && <SourcePanel />}
          {provider === 'osm' && reason && (
            <p className="px-1 text-[11px] text-ink-4">
              Basemap: OpenStreetMap ({reason.toLowerCase()}). Add VITE_GOOGLE_MAPS_API_KEY to use Google Maps.
            </p>
          )}
          </div>
        </div>
      </MobileTripSheet>}

      {guiding && viewState === 'outdoor' && <OutdoorGuide route={activeRoute} loading={loading}
        active={activeStep} destinationName={destination?.name || 'your destination'}
        canGoInside={tab === 'accessible' && !!indoorBuildingId && indoorHandoffReady}
        onGoInside={() => {setGuiding(false); setInspectedLeg(null); setViewState('transition_modal');}}
        onStep={index => {if (activeRoute?.steps[index]) setRouteProgress({route: activeRoute, index});}}
        onFocus={(lat, lng) => setFocus({lat, lng, key: Date.now()})}
        onRerouteFrom={(lat, lng) => {setOriginTarget(null); setOrigin({name: 'Your location', lat, lng});}}
        onStop={() => setGuiding(false)} />}

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
        onConfirm={async (c) => {
          try {
            applyClosures(await confirmClosure(c.id));
            setSelectedIncidentId(null);
          } catch (error) { log('confirm', String(error), 'warn'); }
        }}
        onResolve={async (inc) => {
          try {
            for (const c of inc.all) applyClosures(await markClosureResolved(c.id));
            setSelectedIncidentId(null);
          } catch (error) { log('resolve', String(error), 'warn'); }
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
      <IndoorDirectionsSheet open={indoorDirOpen} onClose={() => setIndoorDirOpen(false)}
        arrive={arriveLeg} leave={leaveLeg} prefs={prefs} closures={closures}
        initialRoom={indoorTarget?.buildingId === destination?.building_id ? indoorTarget?.label.replace(/^\S+\s/, '') : undefined}
        initialFloor={indoorTarget?.buildingId === destination?.building_id ? indoorTarget?.floorId : null} />

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

      {arrivedAtIndoorBuilding && !guiding && (
        <button
          type="button"
          onClick={() => {setInspectedLeg(null); setViewState('transition_modal');}}
          className="fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-2 rounded-full bg-emerald-600 px-5 py-3 text-[15px] font-semibold text-white shadow-lift ring-4 ring-white/80 transition hover:bg-emerald-500 active:scale-95 max-lg:hidden lg:left-[calc(50%+210px)]"
        >
          <span aria-hidden="true">🏛️</span> {indoorActionLabel}
        </button>
      )}

      {/* Universal destination search (buildings, floors and rooms with indoor maps) */}
      <div className="fixed inset-x-3 top-[64px] z-30 sm:inset-x-auto sm:left-1/2 sm:w-[380px] sm:-translate-x-1/2 lg:left-[432px] lg:top-[84px] lg:translate-x-0">
        <DestinationInput onSelect={onDestinationSearch} value={indoorTarget ? indoorTarget.label : undefined} />
      </div>

      <IndoorFlow
        viewState={viewState}
        onViewStateChange={setViewState}
        map={viewModel}
        buildingId={viewBuildingId}
        targetRoomId={viewTargetId || null}
        startNodeId={viewStartId}
        consent={{resident: residentAccess}}
        entrance={inspectedLeg ? null : indoorEntrance}
        closures={closures}
        preferences={prefs}
        highContrast={hc}
      />
    </div>
    </IndoorCatalogContext.Provider>
  );
}
