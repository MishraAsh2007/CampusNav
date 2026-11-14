import { useCallback, useEffect, useState } from 'react';
import PanoramaView from './PanoramaView';
import IndoorSimulation from './IndoorSimulation';
import IndoorStepPanel from './IndoorStepPanel';
import ViewToggleFab from './ViewToggleFab';
import { SAMPLE_INDOOR_ROUTE } from './mockIndoorData';
import { POS } from './layout';

/**
 * 3D immersive indoor navigation.
 *
 * Shows a 360° photosphere behind the step panel. If there is no photo (or it fails to load) it switches
 * to a simulated first-person view at wheelchair eye height that you can actually drive through.
 *
 * Props
 *   imageUrl      generic equirectangular 360° image URL (a step's own `panorama` overrides it)
 *   steps         route steps, see mockIndoorData.js (defaults to a sample ILC route)
 *   building      building name for the header
 *   destination   destination name for the header
 *   mode          'auto' (photo if available, else simulation) | 'photo' | 'simulation'
 *   autoSpeak     read each new step aloud (default true)
 *   initialStep   index to start at (uncontrolled)
 *   activeStep    index of the active step (controlled; pair with onStepChange)
 *   onStepChange  (index, step) => void
 *   showPanel     render the built-in step panel + voice (default true). Set false when a parent
 *                 renders a shared <IndoorStepPanel> across the 2D and 3D views.
 *   onExit        () => void   back to the outdoor map
 *   overlay       optional node shown top-left (e.g. <RouteWarningsPanel compact />)
 *   toolbar       optional node shown in the top bar
 *   onSwitch2D    shows the round "2D" button (bottom right, above the zoom controls)
 *   highContrast  boolean
 *   gpsTraveledM  metres along the current straight step from GPS (null = drive manually)
 *   gpsLabel      text for the current-location pointer, e.g. 'Current location · ±12 m'
 */

const YAW = { 'turn-left': -90, 'turn-right': 90 };

export default function IndoorNavigator({
  imageUrl,
  steps = SAMPLE_INDOOR_ROUTE.steps,
  building = SAMPLE_INDOOR_ROUTE.building,
  destination = SAMPLE_INDOOR_ROUTE.destination,
  mode = 'auto',
  autoSpeak = true,
  initialStep = 0,
  activeStep,
  onStepChange,
  showPanel = true,
  onExit,
  overlay,
  toolbar,
  onSwitch2D,
  highContrast = false,
  gpsTraveledM = null,
  gpsLabel = null
}) {
  const [internal, setInternal] = useState(Math.min(initialStep, Math.max(0, steps.length - 1)));
  const active = Math.max(0, Math.min(steps.length - 1, activeStep ?? internal));
  const [photoFailed, setPhotoFailed] = useState(null);
  const [photoLoaded, setPhotoLoaded] = useState(false);
  const [autoDrive, setAutoDrive] = useState(false);

  const step = steps[active];
  const panorama = step?.panorama || imageUrl;
  const usePhoto = mode !== 'simulation' && !!panorama && !photoFailed;
  const last = active === steps.length - 1;

  useEffect(() => {
    setPhotoFailed(null);
    setPhotoLoaded(false);
  }, [panorama]);

  const go = useCallback(
    (i) => {
      const next = Math.max(0, Math.min(steps.length - 1, i));
      if (activeStep === undefined) setInternal(next);
      onStepChange?.(next, steps[next]);
    },
    [steps, onStepChange, activeStep]
  );

  // In photo mode the arrow keys step through directions; Escape leaves
  useEffect(() => {
    const onKey = (e) => {
      if (e.target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
      if (usePhoto && e.key === 'ArrowRight') go(active + 1);
      else if (usePhoto && e.key === 'ArrowLeft') go(active - 1);
      else if (e.key === 'Escape') onExit?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, go, usePhoto, onExit]);

  if (!step) return null;
  const fab = onSwitch2D ? <ViewToggleFab to="2d" onClick={onSwitch2D} /> : null;

  return (
    <div className={`relative h-full w-full overflow-hidden bg-slate-950 text-white ${highContrast ? 'contrast-125' : ''}`}>
      {usePhoto ? (
        <>
          <PanoramaView url={panorama} yaw={YAW[step.kind] ?? 0} onLoad={() => setPhotoLoaded(true)} onError={(msg) => setPhotoFailed(msg)} />
          {!photoLoaded && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950/80" role="status">
              <span className="rounded-full bg-white/10 px-4 py-2 text-[14px]">Loading 360° view…</span>
            </div>
          )}
        </>
      ) : (
        <IndoorSimulation
          key={step.id}
          step={step}
          highContrast={highContrast}
          auto={autoDrive}
          onAutoChange={setAutoDrive}
          gpsTraveledM={gpsTraveledM}
          gpsLabel={gpsLabel}
          fab={fab}
          onComplete={() => (last ? setAutoDrive(false) : go(active + 1))}
        />
      )}
      {usePhoto && fab && (
        <div className="absolute right-3 z-30 sm:right-4" style={{ bottom: POS.aboveRight }}>
          {fab}
        </div>
      )}

      {/* Compact header: back, title (truncated). The distance HUD sits on the right of this row. */}
      <header className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-center gap-2 px-3 pr-[7.5rem] sm:px-4 sm:pr-36" style={{ paddingTop: POS.headerTop }}>
        {onExit && (
          <button
            type="button"
            onClick={onExit}
            aria-label="Back to outdoor map"
            title="Back to outdoor map"
            className="pointer-events-auto flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white text-[20px] font-semibold text-slate-950 shadow-lg ring-2 ring-white/50 transition hover:bg-slate-100"
          >
            ←
          </button>
        )}
        <div className="pointer-events-auto min-w-0 rounded-2xl bg-black/65 px-3 py-1.5 backdrop-blur">
          <div className="truncate text-[10px] font-medium uppercase tracking-wider text-white/70 sm:text-[11px]">{building}</div>
          <div className="truncate text-[14px] font-semibold leading-tight sm:text-[15px]">To {destination}</div>
        </div>
        {toolbar}
      </header>

      {overlay && (
        <div className="absolute left-4 z-10 hidden w-[300px] lg:block" style={{ top: POS.noticeTop }}>
          {overlay}
        </div>
      )}

      {photoFailed && mode !== 'simulation' && (
        <p className="absolute left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-full bg-amber-400 px-4 py-1.5 text-[12px] font-semibold text-slate-950 shadow" style={{ top: POS.noticeTop }} role="status">
          360° photo unavailable · showing simulated view
        </p>
      )}

      {showPanel && <IndoorStepPanel steps={steps} active={active} onGo={go} onDone={onExit} autoSpeak={autoSpeak} />}
    </div>
  );
}
