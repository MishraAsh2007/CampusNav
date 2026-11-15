import { useEffect, useRef, useState } from 'react';

/**
 * Which floor you are on, from GPS altitude.
 *
 *   level = groundLevel + round((altitude - groundAltitude) / floorHeight)
 *
 * Defaults: ground floor at 65 m (UMass campus), 4 m per floor. Override the ground altitude with
 * VITE_GROUND_ALTITUDE_M.
 *
 * Caveat: browsers report altitude above the WGS84 ellipsoid, which in Amherst is about 28 m below sea
 * level-based heights, and phone altitude is often ±10 m or worse. So the detector:
 *   - ignores fixes whose altitudeAccuracy is worse than MAX_ALT_ACCURACY_M
 *   - only changes floor after STABLE_FIXES fixes in a row agree (no flicker between floors)
 *   - can calibrate: the first good altitude while you are at the entrance becomes that building's
 *     ground altitude (saved in localStorage), which cancels the ellipsoid offset
 * With no altitude at all (common on mobile web) it reports Floor 1.
 */

const envGround = Number(import.meta.env?.VITE_GROUND_ALTITUDE_M);
export const ALTITUDE_DEFAULTS = {
  groundAltitude: Number.isFinite(envGround) && envGround !== 0 ? envGround : 65,
  floorHeight: 4
};
export const DEFAULT_FLOOR_ID = '1';
const MAX_ALT_ACCURACY_M = 12;
const STABLE_FIXES = 3;
const STORE_KEY = 'campusnav.groundAltitude.';

/**
 * Pure mapping from altitude to a floor id.
 *   floors        [{ id, level }]   (floorPlans.js floors)
 *   groundLevel   `level` of the floor at ground altitude (the building's entry floor)
 * Returns DEFAULT_FLOOR_ID ('1') when altitude is null; falls back to the ground floor if the
 * building has no floor '1'.
 */
export function floorFromAltitude(altitude, floors, { groundAltitude = ALTITUDE_DEFAULTS.groundAltitude, floorHeight = ALTITUDE_DEFAULTS.floorHeight, groundLevel = 1 } = {}) {
  if (!floors?.length) return DEFAULT_FLOOR_ID;
  const ground = floors.find((f) => f.level === groundLevel) ?? floors[0];
  if (altitude == null || !Number.isFinite(altitude)) {
    return floors.some((f) => f.id === DEFAULT_FLOOR_ID) ? DEFAULT_FLOOR_ID : ground.id;
  }
  const level = groundLevel + Math.round((altitude - groundAltitude) / floorHeight);
  // Nearest floor that exists (clamps above the roof / below the basement)
  let best = ground;
  for (const f of floors) if (Math.abs(f.level - level) < Math.abs(best.level - level)) best = f;
  return best.id;
}

export function loadGroundAltitude(buildingId) {
  try {
    const v = Number(localStorage.getItem(STORE_KEY + buildingId));
    return Number.isFinite(v) && v !== 0 ? v : null;
  } catch {
    return null;
  }
}

function saveGroundAltitude(buildingId, alt) {
  try {
    localStorage.setItem(STORE_KEY + buildingId, String(Math.round(alt * 10) / 10));
  } catch {
    /* private mode */
  }
}

/**
 * Floor detector over a stream of GPS fixes.
 *   fix          useGeolocation().fix (needs altitude, altitudeAccuracy)
 *   building     floorPlans.js building ({ id, floors, entryFloor })
 *   atEntrance   true while the active step is the entrance door: calibrates the ground altitude
 * Returns { floorId, source: 'altitude' | 'default', altitude, groundAltitude, calibrated }
 *   source 'default' means no usable altitude: floorId is Floor 1.
 */
export function useAltitudeFloor(fix, building, { atEntrance = false } = {}) {
  const floors = building?.floors;
  const groundLevel = floors?.find((f) => f.id === building?.entryFloor)?.level ?? 1;
  const [ground, setGround] = useState(() => (building ? loadGroundAltitude(building.id) : null));
  const [state, setState] = useState({ floorId: DEFAULT_FLOOR_ID, source: 'default' });
  const pending = useRef({ id: null, count: 0 });

  useEffect(() => {
    setGround(building ? loadGroundAltitude(building.id) : null);
    pending.current = { id: null, count: 0 };
    setState({ floorId: floorFromAltitude(null, floors, { groundLevel }), source: 'default' });
  }, [building?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const alt = fix?.altitude;
  const usable = alt != null && Number.isFinite(alt) && (fix.altitudeAccuracy == null || fix.altitudeAccuracy <= MAX_ALT_ACCURACY_M);

  // Standing at the entrance: this altitude is the ground floor
  useEffect(() => {
    if (!usable || !atEntrance || !building || ground != null) return;
    setGround(alt);
    saveGroundAltitude(building.id, alt);
  }, [usable, atEntrance, alt, building, ground]);

  useEffect(() => {
    if (!fix) return;
    if (!usable) {
      // No altitude from this device: Floor 1 (only until a usable altitude has been seen)
      setState((s) => (s.source === 'altitude' ? s : { floorId: floorFromAltitude(null, floors, { groundLevel }), source: 'default' }));
      return;
    }
    // Not calibrated yet but at the entrance: this fix is the ground floor by definition
    const g = ground ?? (atEntrance ? alt : ALTITUDE_DEFAULTS.groundAltitude);
    const id = floorFromAltitude(alt, floors, { groundAltitude: g, groundLevel });
    const p = pending.current;
    p.count = p.id === id ? p.count + 1 : 1;
    p.id = id;
    setState((s) => {
      if (s.source !== 'altitude') return { floorId: id, source: 'altitude' }; // first reading: use it
      if (s.floorId === id || p.count < STABLE_FIXES) return s;
      return { floorId: id, source: 'altitude' };
    });
  }, [fix, usable, alt, floors, ground, groundLevel, atEntrance]);

  return { ...state, altitude: usable ? alt : null, groundAltitude: ground ?? ALTITUDE_DEFAULTS.groundAltitude, calibrated: ground != null };
}
