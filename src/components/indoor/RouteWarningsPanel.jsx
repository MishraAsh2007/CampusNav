import { useMemo } from 'react';

/**
 * Environmental and physical friction warnings for a route.
 *
 * Props
 *   weather   { condition: string, tempF?: number }   e.g. { condition: 'Snowing', tempF: 27 }
 *   surfaces  string[]  indoor friction on the route: 'heavy-door' | 'carpet' | 'wet-tile'
 *   compact   boolean   tighter layout for overlays
 *   className string
 *
 * Wet tile is added automatically when there is rain, freezing rain or snow outside,
 * because entrances get slippery even if the route itself was dry when it was mapped.
 */

const PRECIP = /(rain|drizzle|shower|sleet|snow|freezing|ice|wintry)/i;

function weatherAlert(weather) {
  const c = (weather?.condition || '').toLowerCase();
  const cold = typeof weather?.tempF === 'number' && weather.tempF <= 32;
  if (/freezing rain|sleet|ice|glaze/.test(c)) {
    return {
      level: 'high',
      title: 'Alert: Ramps and sidewalks may be glazed with ice.',
      body: 'Freezing rain leaves clear ice that is hard to see. Use covered routes and allow extra time; consider the UMass Accessible Van Service.'
    };
  }
  if (/snow|flurr|blizzard|wintry/.test(c)) {
    return {
      level: 'high',
      title: 'Alert: Exposed ramps may be icy. Proceed with caution.',
      body: 'Snow can hide curb cuts and pile up at ramp bottoms. Indoor connectors are prioritized where possible.'
    };
  }
  if (/rain|drizzle|shower|storm/.test(c)) {
    return {
      level: cold ? 'high' : 'medium',
      title: cold ? 'Alert: Rain near freezing. Ramps may ice over.' : 'Caution: Wet ramps and paths.',
      body: 'Wet metal plates and painted lines are slippery for crutch tips and wheelchair tires.'
    };
  }
  if (cold) {
    return { level: 'medium', title: 'Caution: Below freezing.', body: 'Shaded ramps may hold overnight ice.' };
  }
  return null;
}

const SURFACE_INFO = {
  'heavy-door': {
    emoji: '🚪',
    label: 'Heavy Manual Doors',
    detail: 'No automatic opener. A major barrier for wheelchairs and crutches.',
    tone: 'border-amber-300 bg-amber-50 text-amber-950'
  },
  carpet: {
    emoji: '🛑',
    label: 'High-Pile Carpet',
    detail: 'Increases wheelchair rolling resistance.',
    tone: 'border-orange-300 bg-orange-50 text-orange-950'
  },
  'wet-tile': {
    emoji: '⚠️',
    label: 'Wet Tile Hazard',
    detail: 'Entrance tile is slippery for crutches when it is wet outside.',
    tone: 'border-sky-300 bg-sky-50 text-sky-950'
  }
};

export default function RouteWarningsPanel({ weather, surfaces = [], compact = false, className = '' }) {
  const alert = weatherAlert(weather);
  const tags = useMemo(() => {
    const set = new Set(surfaces);
    if (PRECIP.test(weather?.condition || '')) set.add('wet-tile');
    return ['heavy-door', 'carpet', 'wet-tile'].filter((t) => set.has(t));
  }, [surfaces, weather]);
  const wetBecauseWeather = tags.includes('wet-tile') && !surfaces.includes('wet-tile');

  return (
    <section aria-label="Route warnings" className={`rounded-3xl bg-white/95 text-slate-900 shadow-xl ring-1 ring-black/10 backdrop-blur ${compact ? 'p-3' : 'p-4'} ${className}`}>
      <header className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-slate-600">Route conditions</h2>
        {weather?.condition && (
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[12px] font-medium text-slate-800">
            {weather.condition}
            {typeof weather.tempF === 'number' && <span className="tabular-nums"> · {Math.round(weather.tempF)}°F</span>}
          </span>
        )}
      </header>

      {alert ? (
        <div
          role={alert.level === 'high' ? 'alert' : 'status'}
          className={`mb-3 rounded-2xl border-2 px-4 py-3 ${alert.level === 'high' ? 'border-red-700 bg-red-700 text-white' : 'border-amber-500 bg-amber-100 text-amber-950'}`}
        >
          <p className="flex items-start gap-2 text-[15px] font-semibold leading-snug">
            <span aria-hidden="true">{alert.level === 'high' ? '❄️' : '💧'}</span>
            {alert.title}
          </p>
          {!compact && <p className={`mt-1 pl-7 text-[13px] leading-snug ${alert.level === 'high' ? 'text-white/90' : 'text-amber-900'}`}>{alert.body}</p>}
        </div>
      ) : (
        <p className="mb-3 rounded-2xl bg-emerald-50 px-4 py-2.5 text-[13px] font-medium text-emerald-900">Weather is not affecting this route.</p>
      )}

      <h3 className="mb-2 text-[12px] font-semibold text-slate-600">Indoor surfaces on this route</h3>
      {tags.length ? (
        <ul className="flex flex-col gap-2">
          {tags.map((t) => {
            const s = SURFACE_INFO[t];
            return (
              <li key={t} className={`flex items-start gap-2.5 rounded-2xl border px-3 py-2 ${s.tone}`}>
                <span aria-hidden="true" className="text-[18px] leading-none">
                  {s.emoji}
                </span>
                <span>
                  <span className="block text-[14px] font-semibold leading-tight">{s.label}</span>
                  {!compact && (
                    <span className="block text-[12px] leading-snug opacity-80">
                      {t === 'wet-tile' && wetBecauseWeather ? `It is ${weather.condition.toLowerCase()} outside: entrance tile will be slippery for crutches.` : s.detail}
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-[13px] text-slate-600">No heavy doors, carpet or wet floors reported.</p>
      )}
    </section>
  );
}
