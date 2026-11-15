import type { RouteResponse, UserPreferences } from '../types';
import { profileLabel } from '../data/profiles';

// Gemini extraction runs only on the Python ingestion worker; no private key enters this bundle.
export const geminiConfigured = false;
export function generateTemplateNarration(route: RouteResponse, originName: string, destinationName: string, prefs: UserPreferences): string {
  const s = route.summary;
  const grade = s.max_grade_pct === null ? 'Slope is unknown on part of this route.' : `The maximum estimated slope is ${s.max_grade_pct.toFixed(1)}%.`;
  return `${s.total_distance_m} meters along mapped outdoor paths from ${originName} to ${destinationName}. ${s.is_step_free ? 'No stairs are mapped on this route.' : 'This route includes stairs.'} ${grade} Check the entrance-access notes before traveling.`;
}
export async function getGeminiEnhancedNarration(route: RouteResponse, originName: string, destinationName: string, prefs: UserPreferences): Promise<{narration: string; source: 'gemini' | 'template'; latencyMs: number}> {
  return {narration: generateTemplateNarration(route, originName, destinationName, prefs), source: 'template', latencyMs: 0};
}

/** Turns "I'm on crutches and it's icy" into router settings. Runs locally, no network. */
export function parseNaturalLanguageQuery(query: string): Partial<UserPreferences> | null {
  const q = query.toLowerCase();
  const p: Partial<UserPreferences> = {};
  if (/power (wheel)?chair|electric (wheel)?chair|scooter/.test(q)) Object.assign(p, { mobility_preset: 'power_wheelchair', wheelchair_required: true, no_stairs: true, max_grade_pct: 8.3 });
  else if (/wheelchair|chair user|wheel chair/.test(q)) Object.assign(p, { mobility_preset: 'manual_wheelchair', wheelchair_required: true, no_stairs: true, max_grade_pct: 6, avoid_rough_surfaces: true });
  else if (/crutch|sprain|ankle|knee|cast|boot|broken (leg|foot)|injur/.test(q)) Object.assign(p, { mobility_preset: 'crutches', wheelchair_required: false, no_stairs: true, max_grade_pct: 5, prefer_indoor: true, handrails_required: true });
  else if (/walker|cane|rollator/.test(q)) Object.assign(p, { mobility_preset: 'walker_cane', wheelchair_required: false, handrails_required: true, max_grade_pct: 5 });
  else if (/stroller|pram|cart|luggage|suitcase|dolly|equipment/.test(q)) Object.assign(p, { mobility_preset: 'stroller', wheelchair_required: false, no_stairs: true });
  else if (/blind|low vision|guide dog|visually/.test(q)) Object.assign(p, { mobility_preset: 'low_vision', minimize_crossings: true, handrails_required: true });

  if (/no stairs|avoid stairs|can'?t (do|climb) stairs/.test(q)) p.no_stairs = true;
  if (/flat|no hills?|avoid hills?|gentle|tired|fatigue|chronic|pots|asthma|heart/.test(q)) p.max_grade_pct = Math.min(p.max_grade_pct ?? 5, 4);
  if (/ice|icy|snow|rain|wet|cold|covered|indoor|inside/.test(q)) p.prefer_indoor = true;
  if (/bump|brick|cobble|smooth|pain/.test(q)) p.avoid_rough_surfaces = true;
  if (/automatic door|door opener|heavy door|push button/.test(q)) p.need_automatic_door = true;
  if (/restroom|bathroom|toilet/.test(q)) p.need_accessible_restroom = true;
  if (/handrail|rail/.test(q)) p.handrails_required = true;
  return Object.keys(p).length ? p : null;
}
