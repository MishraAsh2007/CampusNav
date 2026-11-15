import type { RouteResponse, UserPreferences } from '../types';
import { profileLabel } from '../data/profiles';

const GEMINI_KEY: string = import.meta.env.VITE_GEMINI_API_KEY || '';
// gemini-2.0-flash has been shut down; 3.8 Flash is GA as of Nov 2026. Override with VITE_GEMINI_MODEL.
const GEMINI_MODEL: string = import.meta.env.VITE_GEMINI_MODEL || 'gemini-3.8-flash';

export const geminiConfigured = !!GEMINI_KEY;

/** Instant, deterministic narration. Always shown first; Gemini only replaces it if it answers in time. */
export function generateTemplateNarration(route: RouteResponse, originName: string, destinationName: string, prefs: UserPreferences): string {
  const s = route.summary;
  const min = Math.max(1, Math.round(s.total_duration_s / 60));
  const parts: string[] = [];
  if (!s.is_step_free) {
    const stairs = s.stair_count === null ? 'stairs' : `${s.stair_count} steps`;
    const slope = s.max_grade_pct !== null && s.max_grade_pct > prefs.max_grade_pct ? ` and slopes up to ${s.max_grade_pct}%` : '';
    return `This is the route a regular map would give you: ${s.total_distance_m} m with ${stairs}${slope}. It is not usable with a wheelchair.`;
  }
  parts.push(`About ${min} min (${s.total_distance_m} m) from ${originName} to ${destinationName} with no stairs.`);
  if (s.max_grade_pct === null) parts.push('The steepest grade is unknown.');
  else parts.push(`The steepest part is ${s.max_grade_pct}%${s.max_grade_pct <= 5 ? ', a gentle grade' : ''}.`);
  if (s.elevators_used?.length) parts.push(`You'll use the ${s.elevators_used[0]}.`);
  const reroute = s.warnings.find((w) => w.startsWith('Rerouted'));
  if (reroute) parts.push(`${reroute}.`);
  const stairs = route.avoided?.filter((a) => a.kind === 'stairs').reduce((n, a) => n + (a.step_count ?? 0), 0) ?? 0;
  if (stairs) parts.push(`It skips ${stairs} steps a regular map would send you up.`);
  if ((s.covered_m ?? 0) > 40) parts.push(`${s.covered_m} m is covered.`);
  return parts.join(' ');
}

export async function getGeminiEnhancedNarration(
  route: RouteResponse,
  originName: string,
  destinationName: string,
  prefs: UserPreferences
): Promise<{ narration: string; source: 'gemini' | 'template'; latencyMs: number }> {
  const t0 = performance.now();
  const template = generateTemplateNarration(route, originName, destinationName, prefs);
  if (!GEMINI_KEY) return { narration: template, source: 'template', latencyMs: 0 };

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 2500);
  try {
    const s = route.summary;
    const prompt = `You are a calm campus guide at UMass Amherst. In 2-3 short sentences (under 60 words), describe this walking route for someone using: ${profileLabel(prefs.mobility_preset)}.
Mention the one or two moments that need attention (elevator, slope, reroute). No greetings, no markdown.
From: ${originName}
To: ${destinationName}
Distance: ${s.total_distance_m} m, about ${Math.round(s.total_duration_s / 60)} min
Stairs: ${s.stair_count ?? 'present, count unknown'}; steepest slope: ${s.max_grade_pct === null ? 'unknown' : `${s.max_grade_pct}%`}; elevators: ${s.elevators_used?.join(', ') || 'none recorded'}
Today's changes: ${s.warnings.join('; ') || 'none'}
Barriers avoided vs a regular map: ${route.avoided?.map((a) => a.label).join('; ') || 'none'}
Directions: ${route.steps.map((x) => x.instruction).join(' | ')}`;

    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-goog-api-key': GEMINI_KEY },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.3, maxOutputTokens: 160 }
      }),
      signal: ctrl.signal
    });
    if (res.ok) {
      const data = await res.json();
      const text: string | undefined = data.candidates?.[0]?.content?.parts?.map((p: { text?: string }) => p.text ?? '').join('');
      if (text && text.trim().length > 20) {
        return { narration: text.trim(), source: 'gemini', latencyMs: Math.round(performance.now() - t0) };
      }
    }
  } catch {
    // timeout or offline: the template is already on screen
  } finally {
    clearTimeout(timer);
  }
  return { narration: template, source: 'template', latencyMs: Math.round(performance.now() - t0) };
}

/** Turns "I'm on crutches and it's icy" into router settings. Runs locally, no network. */
export function parseNaturalLanguageQuery(query: string): Partial<UserPreferences> | null {
  const q = query.toLowerCase();
  const p: Partial<UserPreferences> = {};
  if (/power (wheel)?chair|electric (wheel)?chair|scooter/.test(q)) Object.assign(p, { mobility_preset: 'power_wheelchair', wheelchair_required: true, no_stairs: true, max_grade_pct: 8.3 });
  else if (/wheelchair|chair user|wheel chair/.test(q)) Object.assign(p, { mobility_preset: 'manual_wheelchair', wheelchair_required: true, no_stairs: true, max_grade_pct: 7, avoid_rough_surfaces: true });
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
