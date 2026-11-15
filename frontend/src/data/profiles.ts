import { MobilityProfile, UserPreferences } from '../types';

export const MAX_SLOPE_PCT = 12;

export interface ProfileOption {
  id: MobilityProfile;
  label: string;
  hint: string;
  prefs: Partial<UserPreferences>;
}

const BASE: UserPreferences = {
  mobility_preset: 'manual_wheelchair',
  wheelchair_required: true,
  no_stairs: true,
  max_grade_pct: 7,
  avoid_rough_surfaces: true,
  prefer_indoor: false,
  handrails_required: false,
  need_automatic_door: true,
  need_accessible_restroom: false,
  avoid_construction: true,
  minimize_crossings: false
};

/**
 * The project default is a configurable 7% routing cutoff. Grades are terrain
 * estimates, not measured ramp grades or a certification of physical access.
 */
export const PROFILES: ProfileOption[] = [
  {
    id: 'manual_wheelchair',
    label: 'Manual wheelchair',
    hint: 'No stairs, up to 7% estimated slope, smooth surfaces',
    prefs: { wheelchair_required: true, no_stairs: true, max_grade_pct: 7, avoid_rough_surfaces: true, need_automatic_door: true, handrails_required: false, prefer_indoor: false, minimize_crossings: false }
  },
  {
    id: 'power_wheelchair',
    label: 'Power chair or scooter',
    hint: 'No stairs or kerbs, handles ramps up to 8.3%',
    prefs: { wheelchair_required: true, no_stairs: true, max_grade_pct: 8.3, avoid_rough_surfaces: false, need_automatic_door: true, handrails_required: false, prefer_indoor: false, minimize_crossings: false }
  },
  {
    id: 'crutches',
    label: 'Crutches or injury',
    hint: 'Avoids stairs, prefers covered paths when wet',
    prefs: { wheelchair_required: false, no_stairs: true, max_grade_pct: 5, avoid_rough_surfaces: true, need_automatic_door: true, handrails_required: true, prefer_indoor: true, minimize_crossings: false }
  },
  {
    id: 'walker_cane',
    label: 'Walker or cane',
    hint: 'Short stair runs with handrails only, gentle slopes',
    prefs: { wheelchair_required: false, no_stairs: false, max_grade_pct: 5, avoid_rough_surfaces: true, need_automatic_door: false, handrails_required: true, prefer_indoor: false, minimize_crossings: false }
  },
  {
    id: 'stroller',
    label: 'Stroller, cart or luggage',
    hint: 'No stairs, kerb cuts only',
    prefs: { wheelchair_required: false, no_stairs: true, max_grade_pct: 8.3, avoid_rough_surfaces: false, need_automatic_door: false, handrails_required: false, prefer_indoor: false, minimize_crossings: false }
  },
  {
    id: 'low_vision',
    label: 'Low vision or guide dog',
    hint: 'Fewer street crossings, handrails on stairs',
    prefs: { wheelchair_required: false, no_stairs: false, max_grade_pct: 10, avoid_rough_surfaces: false, need_automatic_door: false, handrails_required: true, prefer_indoor: false, minimize_crossings: true }
  }
];

export function applyProfile(current: UserPreferences, id: MobilityProfile): UserPreferences {
  const p = PROFILES.find((x) => x.id === id);
  return { ...current, ...(p?.prefs ?? {}), mobility_preset: id };
}

/** Clearing a preset keeps the individual controls available as custom needs. */
export function toggleProfile(current: UserPreferences, id: MobilityProfile): UserPreferences {
  return current.mobility_preset === id
    ? {...current, mobility_preset: 'custom'}
    : applyProfile(current, id);
}

/** Restore the user's slope when enabling accessibility after the automatic 12% setting. */
export function updateNeeds(current: UserPreferences, patch: Partial<UserPreferences>, previousSlope?: number): UserPreferences {
  const next = {...current, ...patch};
  if (patch.wheelchair_required === true) next.no_stairs = true;
  const enabling = Object.entries(patch).some(([key, value]) => value === true
    && current[key as keyof UserPreferences] !== true);
  if (patch.max_grade_pct !== undefined) return next;
  if (enabling) {
    next.max_grade_pct = previousSlope
      ?? PROFILES.find(profile => profile.id === current.mobility_preset)?.prefs.max_grade_pct
      ?? BASE.max_grade_pct;
  } else if ((patch.wheelchair_required === false || patch.no_stairs === false)
      && !next.wheelchair_required && !next.no_stairs) next.max_grade_pct = MAX_SLOPE_PCT;
  return next;
}

export const DEFAULT_PREFERENCES: UserPreferences = applyProfile(BASE, 'manual_wheelchair');

export function profileLabel(id: MobilityProfile): string {
  return PROFILES.find((p) => p.id === id)?.label ?? 'Custom needs';
}

/** Short chips summarising what the router is enforcing. */
export function needsSummary(p: UserPreferences): string[] {
  const out: string[] = [];
  if (p.wheelchair_required) out.push('Wheelchair');
  if (p.no_stairs || p.wheelchair_required) out.push('No stairs');
  else if (p.handrails_required) out.push('Handrails');
  out.push(`≤ ${p.max_grade_pct}% slope`);
  if (p.avoid_rough_surfaces) out.push('Smooth');
  if (p.prefer_indoor) out.push('Covered');
  if (p.need_automatic_door) out.push('Auto doors');
  if (p.need_accessible_restroom) out.push('Restroom');
  if (p.minimize_crossings) out.push('Few crossings');
  return out;
}
