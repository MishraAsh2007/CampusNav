import {useEffect, useMemo, useRef, useState} from 'react';
import {ChevronLeft, ChevronRight, DoorOpen, LocateFixed, LocateOff, Volume2, VolumeX, X} from 'lucide-react';
import type {RouteResponse} from '../types';
import {displayInstruction, formatDistance} from '../services/displayUnits';
import {gpsProgress, routeGeometry, usableFix, type Fix} from '../services/outdoorProgress';
import {routeStepPosition} from '../services/routeSteps';
import {setVoiceMuted, speak, stop} from '../services/voiceEngine';
import {StepIcon, tone} from './Directions';
import {cx} from './ui';

interface Props {
  route: RouteResponse | null; loading?: boolean; active: number; destinationName: string;
  locationEnabled: boolean; onToggleLocation: () => void;
  canGoInside: boolean; onGoInside: () => void; onStep: (index: number) => void;
  onFocus: (lat: number, lng: number) => void;
  onRerouteFrom: (lat: number, lng: number) => void; onStop: () => void;
}

function useGps(on: boolean) {
  const [fix, setFix] = useState<Fix | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setFix(null); setError(null);
    if (!on) return;
    if (!navigator.geolocation) {setError('Location is unavailable in this browser.'); return;}
    if (!window.isSecureContext) {setError('Open CampusNav over HTTPS to use location.'); return;}
    const watch = navigator.geolocation.watchPosition(position => {
      setError(null);
      setFix({lat: position.coords.latitude, lng: position.coords.longitude,
        accuracy: position.coords.accuracy, timestamp: position.timestamp});
    }, error => {setFix(null); setError(error.code === 1 ? 'Location permission was denied.' : 'Waiting for a location fix.');},
    {enableHighAccuracy: true, maximumAge: 2000, timeout: 20000});
    return () => navigator.geolocation.clearWatch(watch);
  }, [on]);
  return {fix, error};
}

/** Ash's guided mode, sharing the existing selected-step marker and exact indoor handoff. */
export function OutdoorGuide(props: Props) {
  const {route, loading, active, destinationName, canGoInside, locationEnabled: gpsOn, onToggleLocation, onStop} = props;
  const steps = route?.steps ?? [], last = steps.length - 1;
  const index = Math.max(0, Math.min(active, last)), step = steps[index];
  const arrived = !!step && index === last;
  const geo = useMemo(() => routeGeometry(route), [route]);
  const [voice, setVoice] = useState(true);
  const [now, setNow] = useState(Date.now());
  const {fix, error} = useGps(gpsOn);
  const callbacks = useRef(props); callbacks.current = props;
  useEffect(() => {if (!gpsOn) return; const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer);}, [gpsOn]);
  const progress = gpsOn && !loading ? gpsProgress(geo, fix, index, now) : null;
  const offSince = useRef<number | null>(null);
  useEffect(() => {
    if (!progress?.offRoute) offSince.current = null;
    else if (offSince.current == null) offSince.current = now;
    if (progress && progress.next > index) callbacks.current.onStep(progress.next);
  }, [progress?.next, progress?.offRoute, index, route, now]);
  const offRoute = !!progress?.offRoute && offSince.current != null && now - offSince.current >= 10000;
  const previous = useRef({route, index});
  const spoken = useRef<{route: RouteResponse | null; index: number} | null>(null);
  useEffect(() => {
    if (!step || loading) {stop(); return;}
    const point = routeStepPosition(route, index);
    if (point) callbacks.current.onFocus(point.lat, point.lng);
    const old = previous.current;
    const skipped = old.route === route && index > old.index + 1 ? steps.slice(old.index + 1, index) : [];
    const text = [old.route && old.route !== route ? 'Route updated' : '',
      ...skipped.map(s => s.instruction), arrived ? `You have arrived at ${destinationName}.` : step.instruction].filter(Boolean).join('. ');
    previous.current = {route, index};
    if (voice && (spoken.current?.route !== route || spoken.current?.index !== index)) {
      spoken.current = {route, index};
      speak(displayInstruction(text), {priority: true});
    }
  }, [route, index, loading]);
  useEffect(() => {setVoiceMuted(!voice); if (!voice) stop();}, [voice]);
  useEffect(() => () => {stop(); setVoiceMuted(false);}, []);

  const go = (next: number) => {
    // Keep speech within the tap event for mobile browsers' user activation.
    if (voice && steps[next]) {
      spoken.current = {route, index: next};
      speak(displayInstruction(steps[next].instruction), {priority: true});
    }
    callbacks.current.onStep(next);
  };
  const toNext = Math.max(0, (geo.stepStart[index + 1] ?? geo.total)
    - (progress && !progress.offRoute ? progress.along : geo.stepStart[index] ?? 0));
  return <section className="fixed inset-x-3 bottom-3 z-30 overflow-hidden rounded-3xl bg-white shadow-lift lg:inset-x-auto lg:right-4 lg:top-[152px] lg:bottom-auto lg:w-[380px]" aria-label="Guided directions">
    {offRoute && fix && <div className="bg-warn-soft p-3 text-sm text-warn-ink" role="alert">
      You seem to be off the route.
      <button type="button" className="btn btn-quiet mt-2 w-full" onClick={() => {
        if (usableFix(fix)) {offSince.current = null; callbacks.current.onRerouteFrom(fix.lat, fix.lng);}
      }}>Reroute from here</button>
    </div>}
    <div className="flex items-start gap-3 p-4">
      {step && !loading && <span className={cx('flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl', tone(step))}><StepIcon icon={step.icon} /></span>}
      <div className="min-w-0 flex-1" aria-live="polite">
        <h2 className="text-lg font-semibold leading-snug">{loading ? 'Updating your route…' : !step ? 'No route available. Open trip details for more information.' : arrived ? `You have arrived at ${destinationName}` : displayInstruction(step.instruction)}</h2>
        {step && !loading && <p className="mt-1 text-xs text-ink-3">{arrived ? 'End of the outdoor route' : `Step ${index + 1} of ${steps.length} · ${formatDistance(toNext)} to next step`}</p>}
        <p className="mt-1 text-xs text-ink-3">Blue marker: selected instruction.</p>
      </div>
      <button type="button" className="btn btn-quiet min-h-11 min-w-11 !p-2" aria-label="Stop guided directions" onClick={onStop}><X size={18} /></button>
    </div>
    {arrived && !loading && canGoInside && <div className="px-4 pb-3"><button type="button" className="btn btn-primary min-h-11 w-full justify-center" onClick={props.onGoInside}><DoorOpen size={18} />Go inside</button></div>}
    <div className="grid grid-cols-4 gap-1 border-t border-hairline p-2">
      <button type="button" className="btn btn-quiet min-h-11 !px-1" disabled={loading || !step || index === 0} onClick={() => go(index - 1)}><ChevronLeft size={16} />Back</button>
      <button type="button" className="btn btn-quiet min-h-11 !gap-1 !px-1" aria-label="Use my location" aria-pressed={gpsOn} onClick={onToggleLocation}>
        {gpsOn ? <LocateFixed size={16} className="shrink-0" aria-hidden /> : <LocateOff size={16} className="shrink-0" aria-hidden />}
        <span className="text-xs leading-tight">{gpsOn ? 'Location on' : 'Use my location'}</span>
      </button>
      <button type="button" className="btn btn-quiet min-h-11 !px-1" aria-label={voice ? 'Mute voice' : 'Unmute voice'} aria-pressed={voice} onClick={() => {setVoiceMuted(voice); if (!voice && step) speak(displayInstruction(step.instruction), {priority: true}); setVoice(!voice);}}>{voice ? <Volume2 size={18} /> : <VolumeX size={18} />}</button>
      <button type="button" className="btn btn-primary min-h-11 !px-1" disabled={loading || !step || arrived} onClick={() => go(index + 1)}>Next<ChevronRight size={16} /></button>
    </div>
    {gpsOn && <p className="px-4 pb-3 text-xs text-ink-3" role="status">{error || (!usableFix(fix, now) ? 'Waiting for an accurate location. Use Next and Back meanwhile.' : `GPS accuracy: ${formatDistance(fix.accuracy)}. Steps advance near turns.`)}</p>}
  </section>;
}
