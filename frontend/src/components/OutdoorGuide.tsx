import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, DoorOpen, LocateFixed, LocateOff, Volume2, VolumeX, X } from 'lucide-react';
import type { RouteResponse, RouteStep } from '../types';
import { getDistanceMeters } from '../services/routingEngine';
import { setVoiceMuted, speak, stop as stopVoice } from '../services/voiceEngine';
import { StepIcon, tone } from './Directions';
import { cx } from './ui';

/**
 * Guided outdoor navigation: one step at a time, spoken, with the map on the current step.
 * GPS is opt-in: it moves forward when you reach the next step and offers a reroute if you leave the route.
 * Arriving at a building with an indoor map offers "Go inside", which continues in the indoor viewer.
 */

const ADVANCE_M = 10;        // reaching within this of the next step's start moves to it
const ARRIVE_M = 15;         // this close to the end counts as arrived
const OFF_ROUTE_M = 25;      // farther than this (plus GPS accuracy) is off the route...
const OFF_ROUTE_MS = 10000;  // ...for this long before offering a reroute

interface Props {
  route: RouteResponse | null;
  routeId: string;
  destinationName: string;
  canGoInside: boolean;
  onGoInside: () => void;
  onFocus: (lat: number, lng: number) => void;
  onRerouteFrom: (lat: number, lng: number) => void;
  onStop: () => void;
}

type Fix = { lat: number; lng: number; accuracy: number };

function useGps(on: boolean) {
  const [fix, setFix] = useState<Fix | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!on) {
      setFix(null);
      setError(null);
      return;
    }
    if (!('geolocation' in navigator)) {
      setError('This browser has no location support.');
      return;
    }
    if (!window.isSecureContext) {
      setError('Location needs HTTPS on phones. Run "npm run dev:phone" and open the https:// address.');
      return;
    }
    const id = navigator.geolocation.watchPosition(
      (p) => {
        setError(null);
        setFix({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy });
      },
      (e) => setError(e.code === 1 ? 'Location permission was denied.' : 'No location fix yet.'),
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 }
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [on]);
  return { fix, error };
}

/** The route line as [lat, lng] points with distance along it, and where each step starts. */
export function routeGeometry(route: RouteResponse | null) {
  const pts: { lat: number; lng: number; d: number }[] = [];
  const stepStart: number[] = [];
  let d = 0;
  for (const f of route?.features ?? []) {
    const cs = f.geometry.coordinates as [number, number][];
    stepStart.push(d);
    for (const [lng, lat] of cs) {
      const prev = pts[pts.length - 1];
      if (prev) d += getDistanceMeters(prev.lat, prev.lng, lat, lng);
      pts.push({ lat, lng, d });
    }
  }
  stepStart.push(d); // the arrival step
  return { pts, stepStart, total: d };
}

/** Nearest point on the route between distances [from, to]: { along, off } in metres. */
export function locate(geo: ReturnType<typeof routeGeometry>, p: Fix, from: number, to: number) {
  const mLat = 111320;
  const mLng = 111320 * Math.cos((p.lat * Math.PI) / 180);
  let best: { along: number; off: number } | null = null;
  for (let i = 1; i < geo.pts.length; i++) {
    const a = geo.pts[i - 1];
    const b = geo.pts[i];
    if (b.d < from || a.d > to) continue;
    const ax = (a.lng - p.lng) * mLng, ay = (a.lat - p.lat) * mLat;
    const bx = (b.lng - p.lng) * mLng, by = (b.lat - p.lat) * mLat;
    const dx = bx - ax, dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2)) : 0;
    const off = Math.hypot(ax + t * dx, ay + t * dy);
    if (!best || off < best.off) best = { along: a.d + t * (b.d - a.d), off };
  }
  return best;
}

const feet = (m: number) => (m >= 160 ? `${(m / 1609.34).toFixed(1)} mi` : `${Math.max(10, Math.round((m * 3.281) / 10) * 10)} ft`);

export function OutdoorGuide({ route, routeId, destinationName, canGoInside, onGoInside, onFocus, onRerouteFrom, onStop }: Props) {
  const steps: RouteStep[] = route?.steps ?? [];
  const geo = useMemo(() => routeGeometry(route), [routeId]); // eslint-disable-line react-hooks/exhaustive-deps
  const [active, setActive] = useState(0);
  const [muted, setMuted] = useState(false);
  const [gpsOn, setGpsOn] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [offSince, setOffSince] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const { fix, error } = useGps(gpsOn);
  const last = steps.length - 1;
  const step = steps[Math.min(active, last)];
  const arrived = active >= last;

  // Voice on/off for the whole app's voice engine while guiding
  useEffect(() => {
    setVoiceMuted(muted);
    if (muted) stopVoice();
  }, [muted]);
  useEffect(() => () => {
    stopVoice();
    setVoiceMuted(false);
  }, []);

  // A new route while guiding (new outage report, or a reroute): stay on the matching step and say so
  const prevRoute = useRef(routeId);
  const prevAt = useRef<[number, number] | undefined>(undefined);
  useEffect(() => {
    if (prevRoute.current === routeId) return;
    prevRoute.current = routeId;
    if (!steps.length) return;
    const at = prevAt.current;
    let i = 0;
    if (at) {
      let best = Infinity;
      steps.forEach((s, k) => {
        if (!s.at) return;
        const dd = getDistanceMeters(at[1], at[0], s.at[1], s.at[0]);
        if (dd < best) {
          best = dd;
          i = k;
        }
      });
    }
    setActive(i);
    setNotice('Route updated');
    if (!muted) speak(`Route updated. ${steps[i].instruction}`, { priority: true });
    const t = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(t);
  }, [routeId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Each new step: speak it and show it on the map. If GPS skipped short steps (a 5 m jog), say them too.
  const spokenFor = useRef<string>('');
  const prevActive = useRef(0);
  useEffect(() => {
    if (!step) return;
    prevAt.current = step.at;
    if (step.at) onFocus(step.at[1], step.at[0]);
    const key = `${routeId}:${active}`;
    const from = prevActive.current;
    prevActive.current = active;
    if (spokenFor.current !== key) {
      spokenFor.current = key;
      const skipped = active > from + 1 ? steps.slice(from + 1, active).map((s) => s.instruction) : [];
      const now = arrived ? `You have arrived at ${destinationName}.` : step.instruction;
      const text = skipped.length ? [...skipped, now].join(', then ') : now;
      if (!muted) speak(text, { priority: true });
    }
  }, [active, routeId]); // eslint-disable-line react-hooks/exhaustive-deps

  // GPS: move forward when the next step is reached; note when off the route
  const where = useMemo(() => {
    if (!fix || !geo.pts.length) return null;
    const from = (geo.stepStart[Math.max(0, active - 1)] ?? 0) - 30;
    const to = (geo.stepStart[Math.min(active + 3, geo.stepStart.length - 1)] ?? geo.total) + 30;
    return locate(geo, fix, from, to);
  }, [fix, geo, active]);
  useEffect(() => {
    if (!where || !fix) return;
    const offLimit = OFF_ROUTE_M + Math.min(fix.accuracy, 40);
    if (where.off > offLimit) {
      setOffSince((t) => t ?? Date.now());
      return;
    }
    setOffSince(null);
    if (where.along >= geo.total - ARRIVE_M) {
      setActive(last);
      return;
    }
    let next = active;
    while (next + 1 < last && geo.stepStart[next + 1] <= where.along + ADVANCE_M) next++;
    if (next > active) setActive(next);
  }, [where]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (offSince == null) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [offSince]);
  const offRoute = offSince != null && now - offSince >= OFF_ROUTE_MS;

  if (!route || !steps.length) {
    return (
      <div className="fixed inset-x-3 bottom-3 z-30 rounded-3xl bg-white p-4 shadow-lift sm:left-1/2 sm:w-[440px] sm:-translate-x-1/2" role="status">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[14px] text-ink">No route right now. The trip panel explains why.</p>
          <button type="button" className="btn btn-quiet" onClick={onStop}>Close</button>
        </div>
      </div>
    );
  }

  const toNext = !arrived ? Math.max(0, (geo.stepStart[active + 1] ?? geo.total) - (where && !offRoute ? Math.max(where.along, geo.stepStart[active]) : geo.stepStart[active])) : 0;
  const remaining = Math.max(0, geo.total - (where && !offRoute ? where.along : geo.stepStart[active] ?? 0));

  return (
    <div
      className="fixed inset-x-3 bottom-3 z-30 overflow-hidden rounded-3xl bg-white shadow-lift sm:left-1/2 sm:w-[460px] sm:-translate-x-1/2"
      role="region"
      aria-label="Guided directions"
    >
      {notice && <div className="bg-lift-soft px-4 py-1.5 text-[12px] font-semibold text-lift-ink" role="status">{notice}</div>}
      {offRoute && fix && (
        <div className="flex items-center justify-between gap-3 bg-warn-soft px-4 py-2 text-[13px] text-warn-ink" role="alert">
          <span>You seem to be off the route.</span>
          <button type="button" className="btn btn-quiet !py-1" onClick={() => { setOffSince(null); onRerouteFrom(fix.lat, fix.lng); }}>
            Reroute from here
          </button>
        </div>
      )}
      <div className="flex items-start gap-3 p-4">
        <span className={cx('flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl', tone(step))}>
          <StepIcon icon={arrived ? 'destination' : step.icon} />
        </span>
        <div className="min-w-0 flex-1" aria-live="polite">
          <div className="text-[18px] font-semibold leading-snug text-ink">
            {arrived ? `You have arrived at ${destinationName}` : step.instruction}
          </div>
          <div className="mt-1 text-[12px] text-ink-3">
            {arrived ? 'End of the outdoor route' : `Step ${active + 1} of ${last} · next in about ${feet(toNext)} · ${feet(remaining)} to go`}
          </div>
        </div>
        <button type="button" onClick={onStop} className="btn-quiet h-9 w-9 !p-0" aria-label="Stop guided directions">
          <X className="h-4 w-4" />
        </button>
      </div>
      {arrived && canGoInside && (
        <div className="px-4 pb-3">
          <button type="button" className="btn btn-primary w-full justify-center" onClick={onGoInside}>
            <DoorOpen className="h-4 w-4" /> Go inside
          </button>
        </div>
      )}
      <div className="flex items-center gap-2 border-t border-hairline px-3 py-2">
        <button type="button" className="btn btn-quiet" onClick={() => setActive((a) => Math.max(0, a - 1))} disabled={active === 0} aria-label="Previous step">
          <ChevronLeft className="h-4 w-4" /> Back
        </button>
        <button
          type="button"
          className={cx('btn btn-quiet', gpsOn && '!bg-lift-soft !text-lift-ink')}
          onClick={() => setGpsOn((v) => !v)}
          aria-pressed={gpsOn}
          title={error ?? (gpsOn ? 'Following your location' : 'Use my location to move through the steps')}
        >
          {gpsOn ? <LocateFixed className="h-4 w-4" /> : <LocateOff className="h-4 w-4" />}
          {gpsOn ? (error ? 'No fix' : fix ? `±${Math.round(fix.accuracy)} m` : 'Locating…') : 'Follow me'}
        </button>
        <button type="button" className="btn btn-quiet" onClick={() => setMuted((m) => !m)} aria-pressed={muted} aria-label={muted ? 'Unmute voice' : 'Mute voice'}>
          {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
        </button>
        <button type="button" className="btn btn-primary ml-auto" onClick={() => setActive((a) => Math.min(last, a + 1))} disabled={arrived} aria-label="Next step">
          Next <ChevronRight className="h-4 w-4" />
        </button>
      </div>
      {gpsOn && error && <div className="px-4 pb-2 text-[11px] text-stop-ink">{error}</div>}
    </div>
  );
}
