import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import BuildingTransitionModal from './BuildingTransitionModal';
import IndoorGuide from './IndoorGuide';
import IndoorStartControl from './IndoorStartControl';
import IndoorNavigator2D from './IndoorNavigator2D';
import IndoorNavigator from './IndoorNavigator';
import IndoorStepPanel from './IndoorStepPanel';
import RouteWarningsPanel from './RouteWarningsPanel';
import { SAMPLE_WEATHER, surfacesFromSteps } from './mockIndoorData';
import DestinationInput from './DestinationInput';
import { destinationsOf } from './indoorModel';
import { entranceNear, findTarget, nearestNode, routeIndoor } from './indoorRouter';
import { reviewedRoute } from './reviewedRoute';
import { requestIndoorDirections } from './backendIndoor';
import { closuresSignature } from '../../services/api';
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
  const [manualEnabled, setManualEnabled] = useState(false);
  const arrivalStart = entrance?.indoorNodeId && model?.nodes.has(entrance.indoorNodeId) ? entrance.indoorNodeId : null;
  const serverStart = (model?.nodes.has(startNodeId) ? startNodeId : '') || arrivalStart || (manualEnabled ? manualStart : '');
  const startReady = !reviewed || !!serverStart || (model?.routingKind !== 'drawing' && !!entrance?.portalId);
  useEffect(() => {setManualStart(''); setManualEnabled(false);}, [model, entrance?.id, entrance?.portalId]);
  const requestSequence = useRef(0);

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
  const route = reviewed ? verifiedRoute : planned && !planned.blocked ? planned : null;
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

  const [notice, setNotice] = useState(null);
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

  // ---- Layout: keep controls above the step panel ----
  const [panelBox, setPanelBox] = useState({ fromBottom: 0, fullWidth: false });
  const onPanelBox = useCallback((b) => setPanelBox((p) => (p.fromBottom === b.fromBottom && p.fullWidth === b.fullWidth ? p : b)), []);
  const [searchOpen, setSearchOpen] = useState(false);
  const [warningsOpen, setWarningsOpen] = useState(false);

  const noticeTimer = useRef(0);

  const flash = useCallback((text, ms = 3500) => {
    setNotice(text);
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), ms);
  }, []);
  useEffect(() => () => window.clearTimeout(noticeTimer.current), []);

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
        hasOutdoorArrival={!!entrance}
        startReady={startReady}
        startControl={reviewed ? <div className="mb-4 space-y-2 text-sm">
          <IndoorStartControl model={model} entrance={entrance} startNodeId={startNodeId} manualStart={manualStart} onManualStart={setManualStart} onPlanOutdoor={exit} manualEnabled={manualEnabled} onEnableManual={() => setManualEnabled(true)} />
          {model.residentAccessRequired && !consent.resident && <p>Confirm residence/keycard permission in the trip planner first.</p>}
        </div> : null}
        buildingName={building.name}
        rooms={rooms}
        initialRoomId={roomId}
        error={blockedReason}
        mapNote={model.sample ? 'Sample layout, not a surveyed plan.' : model.status === 'draft' ? 'Draft indoor map: check signs as you go.' : null}
        onClose={exit}
        onLaunch={async (mode, id) => {
          if (!startReady) return;
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

  if (reviewed) return <IndoorGuide model={model} route={route} active={active} onGo={go} onExit={exit}
    onChangeDestination={() => onViewStateChange('transition_modal')} />;

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
        const startNode = nearbyReviewedNode(model, step.floor, step.pts?.[0]);
        const next = await requestIndoorDirections(model, route.steps[active]?.fromNodeId || startNode, id, closures, {...consent, preferences});
        if (request !== requestSequence.current) return;
        setVerifiedRoute(next);
      } catch (error) {
        if (request === requestSequence.current) flash(error.message);
        return;
      }
    }
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
          onSwitch3D={reviewed ? undefined : () => onViewStateChange('indoor_3d')}
          onExit={exit}
          onSelectRoom={(r) => pickRoom(r.id)}
          overlay={warnings}
          bottomInset={panelBox.fullWidth ? panelBox.fromBottom : 0}
        />
      )}

      {/* Shared across both views: same step, same voice */}
      <IndoorStepPanel steps={route.steps} active={active} onGo={go} onDone={exit} onBox={onPanelBox} />

      {/* Toolbar for room search and (on small screens) warnings, under the header */}
      <div className="pointer-events-none absolute inset-x-0 z-[1001] flex justify-center px-3" style={{ top: POS.toolbarTop }}>
        <div className="pointer-events-auto relative max-w-full">
          <div role="toolbar" aria-label="Indoor directions controls" className="flex max-w-full items-center gap-0.5 overflow-x-auto rounded-full bg-white/95 p-1 text-slate-900 shadow-lg ring-1 ring-black/10 backdrop-blur [scrollbar-width:none]">
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
              <span className="max-w-[5.5rem] truncate sm:max-w-[9rem]">{route.room.name}</span>
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

      {!searchOpen && !warningsOpen && notice && <Notice>{notice}</Notice>}
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

function Notice({ children }) {
  return (
    <p
      role="status"
      aria-live="assertive"
      className="absolute left-1/2 z-[1001] w-max max-w-[calc(100vw-1.5rem)] -translate-x-1/2 rounded-2xl bg-blue-600 px-4 py-2 text-center text-[13px] font-semibold text-white shadow-lg"
      style={{ top: POS.noticeTop }}
    >
      🔄 {children}
    </p>
  );
}
