import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import BuildingTransitionModal from './BuildingTransitionModal';
import IndoorNavigator2D from './IndoorNavigator2D';
import IndoorNavigator from './IndoorNavigator';
import IndoorStepPanel from './IndoorStepPanel';
import RouteWarningsPanel from './RouteWarningsPanel';
import { SAMPLE_WEATHER, surfacesFromSteps } from './mockIndoorData';
import DestinationInput from './DestinationInput';
import { speak } from '../../services/voiceEngine';
import { nextStepFromGps, progressOnStep, snapToPolyline, useGeolocation } from './indoorGps';
import { destinationsOf } from './indoorModel';
import { entranceNear, findTarget, nearestNode, routeFromPoint, routeIndoor } from './indoorRouter';
import { reviewedRoute } from './reviewedRoute';
import { requestIndoorDirections } from './backendIndoor';
import { closuresSignature } from '../../services/api';
import { useAltitudeFloor } from './altitudeFloor';
import { POS } from './layout';

/**
 * Indoor half of the app's view state machine:
 *   'outdoor' -> 'transition_modal' -> 'indoor_2d' <-> 'indoor_3d' -> 'outdoor'
 *
 * The parent owns `viewState` (so the outdoor map never unmounts); this component owns the chosen room
 * and the active step. One <IndoorStepPanel> (text + voice) is rendered for both 2D and 3D, so switching
 * views keeps your place in the directions and the voice keeps going.
 *
 * Works for any building with an indoor map (indoorCatalog.js); nothing here is building-specific.
 *
 * Props
 *   viewState         'outdoor' | 'transition_modal' | 'indoor_2d' | 'indoor_3d'
 *   onViewStateChange (next) => void
 *   map               indoor map model (indoorModel.js), from the catalog for the destination building
 *   buildingId        the outdoor building id (scopes the room search)
 *   weather           { condition, tempF } for RouteWarningsPanel (defaults to a mocked snow day)
 *   highContrast      boolean
 *   targetRoomId      room (or "<floor>:@lobby") picked in the outdoor search bar; preselected in the modal
 *   entrance          { lat, lng, name, door, source } where the outdoor route ends (the routing engine's
 *                     entrance when it answered). The indoor route starts at the nearest entrance.
 *   closures          live closures; elevators reported out of service are avoided
 */

// Off route for this long before rerouting, so one jumpy GPS fix can't trigger it
const OFF_ROUTE_MS = 4000;
// After a reroute, wait at least this long before the next one
const REROUTE_COOLDOWN_MS = 10000;
const NO_CLOSURES = [];

export default function IndoorFlow({ viewState, onViewStateChange, map: model, buildingId, weather = SAMPLE_WEATHER, highContrast = false, targetRoomId = null, entrance = null, closures = NO_CLOSURES, preferences, startNodeId = null, consent = {} }) {
  // Rooms plus "whole floor" entries (arrive at that floor's elevator lobby)
  const rooms = useMemo(() => destinationsOf(model), [model]);
  const [roomId, setRoomId] = useState(null);
  const [active, setActive] = useState(0);
  const [verifiedRoute, setVerifiedRoute] = useState(null);
  const [verifiedError, setVerifiedError] = useState(null);
  const reviewed = model?.source === 'api';
  const [manualStart, setManualStart] = useState('');
  const serverStart = startNodeId || entrance?.indoorNodeId || manualStart;
  useEffect(() => {setManualStart('');}, [model]);
  const requestSequence = useRef(0);
  // GPS is opt-in; Next / Back always work, with or without it
  const [gpsOn, setGpsOn] = useState(false);
  const [follow, setFollow] = useState(true);
  const geo = useGeolocation(gpsOn && !reviewed && viewState !== 'outdoor' && viewState !== 'transition_modal');

  // New building or a room picked in the search bar: start from that room (or none)
  useEffect(() => {
    setRoomId(targetRoomId && findTarget(model, targetRoomId) ? targetRoomId : null);
    setActive(0);
    setVerifiedRoute(null);
    setVerifiedError(null);
    ++requestSequence.current;
  }, [model, targetRoomId]);

  // The door the outdoor route ends at: the map's entrance nearest to it (else the map's default door)
  const entranceKey = entrance ? `${entrance.lat.toFixed(6)},${entrance.lng.toFixed(6)}` : '';
  const startEntrance = useMemo(() => (entrance && model ? entranceNear(model, entrance.lat, entrance.lng) : null), [model, entranceKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Only elevator closures matter indoors; keep the route stable while other reports change
  const elevatorClosures = useMemo(() => closures.filter((c) => c.type === 'elevator' && c.status !== 'repaired'), [closures]);
  const closureKey = closuresSignature(closures);
  const planned = useMemo(
    () => (!reviewed && roomId && model ? routeIndoor(model, roomId, { entrance: startEntrance, closures: elevatorClosures }) : null),
    [model, reviewed, roomId, startEntrance, closureKey] // eslint-disable-line react-hooks/exhaustive-deps
  );
  const baseRoute = reviewed ? verifiedRoute : planned && !planned.blocked ? planned : null;
  const blockedReason = reviewed ? verifiedError : planned?.blocked ? `No step-free route to ${planned.room.name}: ${planned.reason}` : null;

  const stepRef = useRef(null);
  stepRef.current = verifiedRoute?.steps[active];
  const liveClosureKey = useRef(closureKey);
  useEffect(() => {
    if (liveClosureKey.current === closureKey) return;
    liveClosureKey.current = closureKey;
    if (!reviewed || !verifiedRoute || viewState === 'outdoor' || viewState === 'transition_modal') return;
    const from = stepRef.current?.fromNodeId;
    const seq = ++requestSequence.current;
    setVerifiedRoute(null);
    setVerifiedError('An outage changed. Recalculating from your current instruction landmark.');
    if (!from) return;
    requestIndoorDirections(model, from, roomId, closures, {...consent, preferences})
      .then(next => {if (seq === requestSequence.current) {setVerifiedRoute(next); setVerifiedError(null); setActive(0);}})
      .catch(error => {if (seq === requestSequence.current) setVerifiedError(error.message);});
  }, [closureKey]); // Route changes must not restart this effect.

  // A GPS reroute replaces the route until you pick another room
  const [reroute, setReroute] = useState(null);
  const [notice, setNotice] = useState(null);
  useEffect(() => setReroute(null), [baseRoute]);
  const route = reroute ?? baseRoute;
  const floors = useMemo(
    () =>
      model?.floors.map((f) => ({
        id: f.id,
        label: f.label,
        short: f.short,
        level: f.level,
        imageUrl: f.imageUrl,
        width: f.width,
        height: f.height,
        rooms: model.rooms.filter((r) => r.floor === f.id)
      })) ?? [],
    [model]
  );
  const surfaces = useMemo(() => (route ? surfacesFromSteps(route.steps) : []), [route]);

  // ---- Floor from GPS altitude (Floor 1 when the phone reports none) ----
  const altFloor = useAltitudeFloor(gpsOn ? geo.fix : null, model, { atEntrance: active === 0 && !reroute });
  const altFromGps = gpsOn && altFloor.source === 'altitude';

  // ---- GPS -> floor pixels, snapped to the route on the floor you are on ----
  const gps = useMemo(() => {
    if (!route || !geo.fix || !model) return null;
    const stepFloor = route.steps[active]?.floor;
    const floorId = altFromGps && model.floorById.has(altFloor.floorId) ? altFloor.floorId : stepFloor;
    const fl = model.floorById.get(floorId);
    // A floor needs a lat/lng reference (corner bounds, or entrances / elevators with coordinates)
    if (!fl?.georef) return { unreferenced: true, floorId };
    const raw = fl.georef.toPx(geo.fix.lat, geo.fix.lng);
    const pxPerM = 1 / fl.georef.mPerPx;
    const margin = 15 * pxPerM;
    const inside = raw[0] >= -margin && raw[0] <= fl.width + margin && raw[1] >= -margin && raw[1] <= fl.height + margin;
    const path = route.paths[floorId];
    const snap = path ? snapToPolyline(raw, path) : null;
    const offRoute = !snap || snap.dist > 20 * pxPerM;
    const pos = inside ? (offRoute ? raw : snap.point) : null;
    const acc = Math.round(geo.fix.accuracy);
    const floorLabel = altFromGps ? ` · ${fl.label}` : '';
    return {
      raw,
      pos,
      floorId,
      pxPerM,
      onStepFloor: floorId === stepFloor,
      inside,
      offRoute,
      accuracyM: acc,
      accuracyPx: geo.fix.accuracy * pxPerM,
      label: `Current location · ±${acc} m${floorLabel}${offRoute && inside ? ' · off route' : ''}`,
      follow
    };
  }, [route, geo.fix, model, active, follow, altFromGps, altFloor.floorId]);

  // Follow mode: move to the next step as you walk. Without altitude, never past an elevator.
  useEffect(() => {
    if (!follow || !gps?.pos || !route || !gps.onStepFloor) return;
    const next = nextStepFromGps(route.steps, active, gps.pos, 5 * gps.pxPerM);
    if (next !== active) setActive(next);
  }, [follow, gps, route, active]);

  // Altitude says you changed floor (e.g. got out of the elevator): jump to the first step on that floor
  useEffect(() => {
    if (!follow || !altFromGps || !route) return;
    const here = route.steps[active];
    if (!here || here.floor === altFloor.floorId) return;
    const i = route.steps.findIndex((s, k) => k > active && s.floor === altFloor.floorId);
    if (i > active) setActive(i);
  }, [follow, altFromGps, altFloor.floorId, route]); // eslint-disable-line react-hooks/exhaustive-deps

  // The 2D map switches to the detected floor whenever it changes (Floor 1 if there is no altitude)
  const floorHint = useMemo(
    () => (gpsOn && geo.fix ? { floorId: altFloor.floorId, key: `${altFloor.source}:${altFloor.floorId}` } : null),
    [gpsOn, !!geo.fix, altFloor.source, altFloor.floorId] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const gpsTraveledM = useMemo(() => {
    if (!follow || !gps?.pos || !route || !gps.onStepFloor) return null;
    const pr = progressOnStep(gps.pos, route.steps[active]);
    return pr ? pr.alongPx / gps.pxPerM : null;
  }, [follow, gps, route, active]);

  // ---- Layout: keep controls above the step panel ----
  const [panelBox, setPanelBox] = useState({ fromBottom: 0, fullWidth: false });
  const onPanelBox = useCallback((b) => setPanelBox((p) => (p.fromBottom === b.fromBottom && p.fullWidth === b.fullWidth ? p : b)), []);
  const [searchOpen, setSearchOpen] = useState(false);
  const [warningsOpen, setWarningsOpen] = useState(false);

  // ---- Live rerouting ----
  // Latest values for the timer callback, without restarting the 4-second countdown on every GPS fix
  const live = useRef({ gps, route, active });
  live.current = { gps, route, active };
  const lastRerouteAt = useRef(0);
  const noticeTimer = useRef(0);

  const flash = useCallback((text, ms = 3500) => {
    setNotice(text);
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), ms);
  }, []);
  useEffect(() => () => window.clearTimeout(noticeTimer.current), []);

  const recalculateRoute = useCallback(async () => {
    const { gps: g, route: r, active: i } = live.current;
    const step = r?.steps[i];
    if (!g?.raw || !g.inside || !r || !step || !model) return;
    lastRerouteAt.current = Date.now();
    speak('Recalculating route.', { priority: true });
    flash('Recalculating route…', 6000);
    // Start on the altitude floor if the phone reports it, or use the current step's floor.
    const seq = requestSequence.current;
    const next = reviewed ? await reviewedRoute(model, r.room.id, preferences, {
      startNode: nearbyReviewedNode(model, g.floorId ?? step.floor, g.raw),
    }).catch(() => null) : routeFromPoint(model, g.floorId ?? step.floor, g.raw, r.room.id, elevatorClosures);
    if (seq !== requestSequence.current) return;
    if (next) {
      setReroute(next);
      setActive(0); // the step panel then speaks the new first step, right after the announcement
      flash('New route from your current location');
    } else {
      flash("Couldn't find a new route. Use Next / Back.", 5000);
    }
  }, [model, flash, elevatorClosures, reviewed, preferences]);

  // Off route for OFF_ROUTE_MS in a row -> reroute. Any fix back on the route cancels the countdown.
  // Only while Follow is on: with Follow off you are stepping manually and may be ahead of your position.
  const offRoute = !!(follow && gps?.inside && gps?.offRoute && route && route.steps[active]?.kind !== 'arrive');
  useEffect(() => {
    if (!offRoute) return;
    const cooldownLeft = REROUTE_COOLDOWN_MS - (Date.now() - lastRerouteAt.current);
    const t = window.setTimeout(recalculateRoute, Math.max(OFF_ROUTE_MS, cooldownLeft));
    return () => window.clearTimeout(t);
  }, [offRoute, recalculateRoute]);

  const exit = useCallback(() => {
    ++requestSequence.current;
    setVerifiedRoute(null);
    setVerifiedError(null);
    onViewStateChange('outdoor');
  }, [onViewStateChange]);
  const go = useCallback((i) => setActive(Math.max(0, Math.min((route?.steps.length ?? 1) - 1, i))), [route]);

  if (!model || viewState === 'outdoor') return null;
  const building = model;

  if (viewState === 'transition_modal' || !route) {
    return (
      <BuildingTransitionModal
        open
        allow3D={!reviewed}
        startControl={reviewed ? <div className="mb-4 space-y-2 text-sm">
          {(serverStart || entrance?.portalId) ? <p className="rounded-xl bg-emerald-50 p-3 text-emerald-900">Starting at {model.nodes.get(serverStart)?.label || entrance?.name || "your routed entrance"}. Directions include the approach to the elevator.</p> : <label>Where are you now?<select aria-label="Current indoor landmark" className="mt-1 w-full rounded-xl border p-2" value={manualStart} onChange={e => setManualStart(e.target.value)}><option value="">Choose a mapped landmark</option>{[...model.nodes.values()].map(n => <option key={n.id} value={n.id}>{n.label} · floor {n.floor}</option>)}</select></label>}
          {model.routingKind === "drawing" && !consent.drawing && <p>Accept drawing-based directions in the trip planner first.</p>}
          {model.residentAccessRequired && !consent.resident && <p>Confirm residence/keycard permission in the trip planner first.</p>}
        </div> : null}
        buildingName={building.name}
        rooms={rooms}
        initialRoomId={roomId}
        error={blockedReason}
        mapNote={model.sample ? 'Sample layout, not a surveyed plan.' : model.status === 'draft' ? 'Draft indoor map: check signs as you go.' : null}
        onClose={exit}
        onLaunch={async (mode, id) => {
          setReroute(null);
          setRoomId(id);
          setActive(0);
          if (reviewed) {
            const request = ++requestSequence.current;
            setVerifiedError(null);
            try {
              const next = model.routingKind === 'drawing' || !entrance?.portalId
                ? await requestIndoorDirections(model, serverStart, id, closures, {...consent, preferences})
                : await reviewedRoute(model, id, preferences, {portalId: entrance.portalId});
              if (request !== requestSequence.current) return;
              setVerifiedRoute(next);
            } catch (error) {
              if (request === requestSequence.current) setVerifiedError(error.message);
              return;
            }
          }
          onViewStateChange(!reviewed && mode === '3d' ? 'indoor_3d' : 'indoor_2d');
        }}
      />
    );
  }

  const destination = { name: route.room.name, x: route.room.doorX, y: route.room.doorY, floor: route.room.floor };
  const warnings = <div className="max-w-sm space-y-2"><RouteWarningsPanel weather={reviewed ? null : weather} surfaces={reviewed ? [] : surfaces} compact />
    {reviewed && <details className="rounded-2xl bg-amber-50 p-3 text-sm text-amber-950"><summary className="cursor-pointer font-semibold">Source-based directions · access unverified</summary>
      <p className="mt-2">Follow the mapped approach to the named elevator. Use Next / Back as you walk; indoor GPS is unavailable.</p>
      {(route.warnings || []).map((warning, i) => <p className="mt-2" key={i}>{warning}</p>)}
    </details>}
  </div>;
  const panelVars = {
    '--indoor-panel-h': `${panelBox.fromBottom || 16}px`,
    '--indoor-right-inset': `${panelBox.fullWidth ? panelBox.fromBottom : 16}px`
  };
  const pickRoom = async (id) => {
    if (reviewed) {
      const step = route.steps[active];
      const request = ++requestSequence.current;
      try {
        const startNode = nearbyReviewedNode(model, step.floor, gps?.pos && gps.floorId === step.floor ? gps.pos : step.pts?.[0]);
        const next = await requestIndoorDirections(model, route.steps[active]?.fromNodeId || startNode, id, closures, {...consent, preferences});
        if (request !== requestSequence.current) return;
        setVerifiedRoute(next);
      } catch (error) {
        if (request === requestSequence.current) flash(error.message);
        return;
      }
    }
    setReroute(null);
    setRoomId(id);
    setActive(0);
  };
  const seg = 'flex h-10 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] font-semibold transition';

  return (
    <div className="fixed inset-0 z-[60] bg-slate-950" style={panelVars} role="region" aria-label={`Indoor navigation in ${building.name}`}>
      {viewState === 'indoor_3d' ? (
        <IndoorNavigator
          mode="auto"
          steps={route.steps}
          building={building.name}
          destination={route.destination}
          activeStep={active}
          onStepChange={(i) => go(i)}
          showPanel={false}
          onExit={exit}
          overlay={warnings}
          highContrast={highContrast}
          gpsTraveledM={gpsTraveledM}
          gpsLabel={gps?.pos ? gps.label : null}
          onSwitch2D={() => onViewStateChange('indoor_2d')}
        />
      ) : (
        <IndoorNavigator2D
          floors={floors}
          paths={route.paths}
          steps={route.steps}
          active={active}
          destination={destination}
          building={building.name}
          gps={gps?.pos ? gps : null}
          onSwitch3D={reviewed ? undefined : () => onViewStateChange('indoor_3d')}
          onExit={exit}
          onSelectRoom={(r) => pickRoom(r.id)}
          overlay={warnings}
          floorHint={floorHint}
          bottomInset={panelBox.fullWidth ? panelBox.fromBottom : 0}
        />
      )}

      {/* Shared across both views: same step, same voice */}
      <IndoorStepPanel steps={route.steps} active={active} onGo={go} onDone={exit} onBox={onPanelBox} />

      {/* One pill toolbar for location, follow, room and (on small screens) warnings, under the header */}
      <div className="pointer-events-none absolute inset-x-0 z-[1001] flex justify-center px-3" style={{ top: POS.toolbarTop }}>
        <div className="pointer-events-auto relative max-w-full">
          <div role="toolbar" aria-label="Location and destination" className="flex max-w-full items-center gap-0.5 overflow-x-auto rounded-full bg-white/95 p-1 text-slate-900 shadow-lg ring-1 ring-black/10 backdrop-blur [scrollbar-width:none]">
            <button
              type="button"
              disabled={reviewed}
              onClick={() => setGpsOn((v) => !v)}
              aria-pressed={gpsOn}
              title={gpsOn ? 'Stop using your location' : 'Use my location'}
              className={`${seg} ${gpsOn ? 'bg-blue-600 text-white' : 'hover:bg-slate-100'}`}
            >
              <span aria-hidden="true">📍</span>
              <span className="whitespace-nowrap">{gpsOn ? gpsStatusText(geo, gps) : 'Locate'}</span>
            </button>
            {gpsOn && gps?.pos && (
              <button
                type="button"
                onClick={() => setFollow((v) => !v)}
                aria-pressed={follow}
                title="Move through the steps automatically as you walk"
                className={`${seg} ${follow ? 'bg-slate-950 text-white' : 'hover:bg-slate-100'}`}
              >
                Follow
              </button>
            )}
            {gpsOn && altFromGps && (
              <span
                className="flex h-10 shrink-0 items-center whitespace-nowrap rounded-full bg-slate-100 px-2.5 text-[12px] font-semibold text-slate-700"
                title={`Floor estimated from GPS altitude (${Math.round(altFloor.altitude ?? 0)} m; ground ${Math.round(altFloor.groundAltitude)} m${altFloor.calibrated ? ', set at the entrance' : ''})`}
              >
                Fl {altFloor.floorId}
              </span>
            )}
            <button
              type="button"
              onClick={() => {
                setSearchOpen((o) => !o);
                setWarningsOpen(false);
              }}
              aria-expanded={searchOpen}
              aria-label={`Change room. Current: ${route.room.name}`}
              className={`${seg} min-w-0 ${searchOpen ? 'bg-slate-950 text-white' : 'hover:bg-slate-100'}`}
            >
              <span aria-hidden="true">🔎</span>
              {/* With GPS on, phones show just the icon so the whole toolbar fits */}
              <span className={`max-w-[5.5rem] truncate sm:inline sm:max-w-[9rem] ${gpsOn ? 'hidden' : ''}`}>{route.room.name}</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setWarningsOpen((o) => !o);
                setSearchOpen(false);
              }}
              aria-expanded={warningsOpen}
              aria-label="Show route warnings"
              title="Route warnings"
              className={`${seg} lg:hidden ${warningsOpen ? 'bg-amber-400 text-slate-950' : 'hover:bg-slate-100'}`}
            >
              <span aria-hidden="true">⚠️</span>
            </button>
          </div>

          {searchOpen && (
            <div className="absolute left-1/2 top-full mt-2 w-[min(320px,calc(100vw-1.5rem))] -translate-x-1/2">
              <DestinationInput
                compact
                autoFocus
                scopeBuildingId={buildingId}
                value={route.room.name}
                onSelect={(t) => {
                  pickRoom(t.roomId);
                  setSearchOpen(false);
                }}
                onDismiss={() => setSearchOpen(false)}
              />
            </div>
          )}
          {warningsOpen && (
            <div className="absolute left-1/2 top-full mt-2 max-h-[45vh] w-[min(320px,calc(100vw-1.5rem))] -translate-x-1/2 overflow-y-auto rounded-3xl lg:hidden">
              {warnings}
            </div>
          )}
        </div>
      </div>

      {!searchOpen && !warningsOpen && (
        <Notice
          tone={notice ? 'blue' : gpsOn && geo.error ? 'amber' : gpsOn && gps && (gps.unreferenced || !gps.inside) ? 'dark' : offRoute ? 'amber' : null}
          assertive={!!notice}
        >
          {notice
            ? `🔄 ${notice}`
            : gpsOn && geo.error
              ? `${geo.error} Next / Back still work without GPS.`
              : gpsOn && gps?.unreferenced
                ? `This floor's map has no location reference yet, so GPS can't place you on it. Use Next / Back.`
                : gpsOn && gps && !gps.inside
                  ? `GPS puts you outside ${building.name}. Use Next / Back, or walk in and wait for a better fix.`
                  : offRoute
                    ? 'Off route. Rerouting in a few seconds unless you head back.'
                    : null}
        </Notice>
      )}
    </div>
  );
}

function nearbyReviewedNode(model, floorId, point) {
  if (!point) return null;
  const id = nearestNode(model, floorId, point);
  const node = model.nodes.get(id);
  const floor = model.floorById.get(floorId);
  return node && floor && Math.hypot(node.px[0] - point[0], node.px[1] - point[1]) <= 8 * floor.pxPerM ? id : null;
}

const NOTICE_TONE = {
  blue: 'bg-blue-600 text-white',
  amber: 'bg-amber-400 text-slate-950',
  dark: 'bg-slate-900 text-white'
};

/** One status line under the toolbar (reroutes, GPS problems). */
function Notice({ tone, assertive, children }) {
  if (!tone || !children) return null;
  return (
    <p
      role="status"
      aria-live={assertive ? 'assertive' : 'polite'}
      className={`absolute left-1/2 z-[1001] w-max max-w-[calc(100vw-1.5rem)] -translate-x-1/2 rounded-2xl px-4 py-2 text-center text-[13px] font-semibold shadow-lg ${NOTICE_TONE[tone]}`}
      style={{ top: POS.noticeTop }}
    >
      {children}
    </p>
  );
}

function gpsStatusText(geo, gps) {
  if (geo.status === 'locating') return 'Finding you…';
  if (geo.status === 'denied') return 'Location blocked';
  if (geo.status === 'insecure') return 'Needs HTTPS';
  if (geo.status === 'unsupported') return 'No GPS';
  const acc = geo.fix ? `±${Math.round(geo.fix.accuracy)} m` : null;
  if (geo.status === 'timeout' || geo.status === 'unavailable') return acc ?? 'No fix yet';
  if (gps && acc) return acc;
  return 'GPS on';
}
