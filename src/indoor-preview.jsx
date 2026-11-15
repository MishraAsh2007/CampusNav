/**
 * Standalone preview for the indoor components: http://localhost:5173/indoor.html
 * Does not touch the outdoor map or App.tsx. It shows the intended pattern:
 *
 *   {view === 'Indoor' ? <IndoorNavigator onExit={() => setView('Outdoor')} /> : <OutdoorMap />}
 */
import React, { useMemo, useState } from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import IndoorNavigator from './components/indoor/IndoorNavigator';
import RouteWarningsPanel from './components/indoor/RouteWarningsPanel';
import { INDOOR_ROUTES, surfacesFromSteps } from './components/indoor/mockIndoorData';

const WEATHER = [
  { condition: 'Snowing', tempF: 27 },
  { condition: 'Freezing Rain', tempF: 31 },
  { condition: 'Raining', tempF: 46 },
  { condition: 'Clear', tempF: 58 }
];
// Pannellum's public sample photosphere (CORS-enabled). Swap for a real ILC 360° photo.
const SAMPLE_PHOTO = 'https://pannellum.org/images/alma.jpg';

function Preview() {
  const params = new URLSearchParams(location.search);
  const [view, setView] = useState(params.get('view') === 'outdoor' ? 'Outdoor' : 'Indoor');
  const [weatherIdx, setWeatherIdx] = useState(Number(params.get('weather') ?? 0) || 0);
  const [mode, setMode] = useState(params.get('mode') === 'photo' ? 'photo' : 'simulation');
  const [buildingId, setBuildingId] = useState(INDOOR_ROUTES[params.get('building')] ? params.get('building') : 'ilc');
  const route = INDOOR_ROUTES[buildingId];
  const weather = WEATHER[weatherIdx];
  const surfaces = useMemo(() => surfacesFromSteps(route.steps), [route]);

  return (
    <div className="fixed inset-0 bg-slate-950">
      {view === 'Indoor' ? (
        <IndoorNavigator
          key={`${buildingId}-${mode}`}
          mode={mode}
          steps={route.steps}
          building={route.building}
          destination={route.destination}
          imageUrl={mode === 'photo' ? SAMPLE_PHOTO : undefined}
          onExit={() => setView('Outdoor')}
          overlay={<RouteWarningsPanel weather={weather} surfaces={surfaces} compact />}
        />
      ) : (
        <div className="flex h-full flex-col items-center justify-center gap-6 p-6 text-white">
          <p className="text-[15px] text-white/70">&lt;OutdoorMap /&gt; renders here in the app.</p>
          <RouteWarningsPanel weather={weather} surfaces={surfaces} className="w-full max-w-md" />
          <button onClick={() => setView('Indoor')} className="rounded-full bg-white px-6 py-3 text-[15px] font-semibold text-slate-950">
            Enter {route.building} (indoor view)
          </button>
        </div>
      )}

      {/* Preview-only controls */}
      <div className="absolute right-3 top-[8.5rem] z-40 flex max-w-[calc(100vw-1.5rem)] flex-wrap items-center justify-end gap-1.5 rounded-2xl bg-black/70 p-1.5 text-[12px] text-white backdrop-blur sm:right-4">
        <span className="px-1.5 text-white/60">Preview</span>
        <select value={buildingId} onChange={(e) => setBuildingId(e.target.value)} className="rounded-lg bg-white/15 px-2 py-1" aria-label="Building">
          {Object.entries(INDOOR_ROUTES).map(([id, r]) => (
            <option key={id} value={id} className="text-black">
              {r.building}
            </option>
          ))}
        </select>
        <select value={weatherIdx} onChange={(e) => setWeatherIdx(Number(e.target.value))} className="rounded-lg bg-white/15 px-2 py-1" aria-label="Mock weather">
          {WEATHER.map((w, i) => (
            <option key={w.condition} value={i} className="text-black">
              {w.condition}
            </option>
          ))}
        </select>
        <button onClick={() => setMode((m) => (m === 'photo' ? 'simulation' : 'photo'))} className="rounded-lg bg-white/15 px-2 py-1">
          {mode === 'photo' ? 'Photo 360°' : 'Simulation'}
        </button>
        <button onClick={() => setView((v) => (v === 'Indoor' ? 'Outdoor' : 'Indoor'))} className="rounded-lg bg-white/15 px-2 py-1">
          {view}
        </button>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Preview />
  </React.StrictMode>
);
