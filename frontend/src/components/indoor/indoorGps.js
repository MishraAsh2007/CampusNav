import { useEffect, useRef, useState } from 'react';

/**
 * GPS for the indoor views: route geometry helpers and the browser geolocation hook.
 *
 * Converting lat/lng to floor pixels is per floor (`floor.georef` in indoorModel.js): from the floor's
 * corner bounds, or fitted through entrances and elevators with known coordinates. That shows which
 * part of the building you are in, not which room: indoors, phone GPS is usually ±10–50 m.
 * Floors come from GPS altitude when the phone reports it (altitudeFloor.js), else from the current step.
 */

// ---------- geometry on the route ----------

function projectOnSegment(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  const q = [a[0] + t * dx, a[1] + t * dy];
  return { point: q, t, dist: Math.hypot(p[0] - q[0], p[1] - q[1]), len: Math.sqrt(len2) };
}

/** Nearest point on a polyline. */
export function snapToPolyline(p, pts) {
  let best = null;
  for (let i = 1; i < pts.length; i++) {
    const r = projectOnSegment(p, pts[i - 1], pts[i]);
    if (!best || r.dist < best.dist) best = { ...r, seg: i - 1 };
  }
  return best;
}

/** Position along a straight step: { t (0..1), alongPx, dist } */
export function progressOnStep(p, step) {
  if (step?.kind !== 'straight' || step.pts?.length < 2) return null;
  const r = projectOnSegment(p, step.pts[0], step.pts[1]);
  return { t: r.t, alongPx: r.t * r.len, dist: r.dist, len: r.len };
}

/**
 * Which step should be active, given where GPS puts you. Conservative so a jumpy fix cannot skip ahead:
 *   - on a "Go straight" step, advance when you are within `nearPx` of its end
 *   - on a door / turn step, advance once you are 15% into the next straight segment
 *   - elevators and arrival never auto-advance (GPS cannot see floors)
 */
export function nextStepFromGps(steps, active, p, nearPx) {
  const step = steps[active];
  const next = steps[active + 1];
  if (!step || !next || step.kind === 'elevator' || step.kind === 'arrive') return active;
  if (step.kind === 'straight') {
    const end = step.pts[1];
    return Math.hypot(p[0] - end[0], p[1] - end[1]) <= nearPx ? active + 1 : active;
  }
  if (next.kind === 'straight') {
    const pr = progressOnStep(p, next);
    return pr && pr.t >= 0.15 && pr.dist <= nearPx * 2 ? active + 1 : active;
  }
  if (next.kind === 'door' || next.kind === 'arrive') {
    const q = next.pts[0];
    return Math.hypot(p[0] - q[0], p[1] - q[1]) <= nearPx ? active + 1 : active;
  }
  return active;
}

// ---------- browser geolocation ----------

/**
 * watchPosition wrapper.
 * status: 'off' | 'unsupported' | 'insecure' | 'locating' | 'ok' | 'denied' | 'unavailable' | 'timeout'
 */
export function useGeolocation(enabled) {
  const [state, setState] = useState({ status: 'off', fix: null, error: null });
  const watchId = useRef(null);

  useEffect(() => {
    if (!enabled) {
      setState((s) => ({ ...s, status: 'off' }));
      return;
    }
    if (!('geolocation' in navigator)) {
      setState({ status: 'unsupported', fix: null, error: 'This browser has no location support.' });
      return;
    }
    if (!window.isSecureContext) {
      setState({ status: 'insecure', fix: null, error: 'Location needs HTTPS. Run "npm run dev:phone" and open the https:// address.' });
      return;
    }
    setState((s) => ({ ...s, status: s.fix ? 'ok' : 'locating', error: null }));
    watchId.current = navigator.geolocation.watchPosition(
      (pos) =>
        setState({
          status: 'ok',
          error: null,
          fix: {
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
            heading: Number.isFinite(pos.coords.heading) ? pos.coords.heading : null,
            // Metres above the WGS84 ellipsoid; null on most laptops and many phone browsers
            altitude: Number.isFinite(pos.coords.altitude) ? pos.coords.altitude : null,
            altitudeAccuracy: Number.isFinite(pos.coords.altitudeAccuracy) ? pos.coords.altitudeAccuracy : null,
            at: pos.timestamp
          }
        }),
      (err) =>
        setState((s) => ({
          ...s,
          status: err.code === 1 ? 'denied' : err.code === 3 ? 'timeout' : 'unavailable',
          error: err.code === 1 ? 'Location permission was denied. Allow it in your browser settings.' : err.message || 'No location fix yet.'
        })),
      { enableHighAccuracy: true, maximumAge: 1500, timeout: 20000 }
    );
    return () => {
      if (watchId.current != null) navigator.geolocation.clearWatch(watchId.current);
      watchId.current = null;
    };
  }, [enabled]);

  return state;
}
