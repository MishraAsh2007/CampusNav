import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, ArrowUp, ChevronDown, Flag, Focus, Layers, Minus, MoveVertical, Plus, RotateCcw, Volume2, VolumeX, X } from 'lucide-react';
import { displayInstruction } from '../../services/displayUnits';
import { isVoiceSupported, setVoiceMuted, speak, stop } from '../../services/voiceEngine';
import { availableMapStyles, resolveMapStyle } from './mapStyles';
import SourceRoutePlan from './SourceRoutePlan';
import InteractivePlan from './InteractivePlan';
import { isWithdrawnIndoorMap } from './indoorMapPolicy';

/** The map stays visible; the current instruction lives in the navigation card. */
export default function IndoorGuide({ model, route, active, onGo, onExit, onChangeDestination }) {
  const step = route.steps[active];
  const [floorId, setFloorId] = useState(step?.floor || model.floors[0]?.id);
  const [failedImages, setFailedImages] = useState([]);
  const [zoom, setZoom] = useState(100);
  const [mapStyle, setMapStyle] = useState('detailed');
  const [focusStep, setFocusStep] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches);
  const [showOptions, setShowOptions] = useState(false);
  const [showSteps, setShowSteps] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [sheetCollapsed, setSheetCollapsed] = useState(false);
  const [sheetHeight, setSheetHeight] = useState(null);
  const sheetGesture = useRef(null);
  const sheetExpandedHeight = useRef(300);
  const suppressSheetClick = useRef(false);
  const voiceSupported = isVoiceSupported();
  const voiceOn = voiceEnabled && voiceSupported;
  useEffect(() => {
    setVoiceMuted(false);
    return () => { stop(); setVoiceMuted(false); };
  }, []);
  useEffect(() => { if (step?.floor) setFloorId(step.floor); }, [step?.floor]);
  useEffect(() => setZoom(100), [floorId]);
  const startSheetDrag = event => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    const height = event.currentTarget.closest('.guide-direction-card').getBoundingClientRect().height;
    if (!sheetCollapsed) sheetExpandedHeight.current = height;
    sheetGesture.current = {id: event.pointerId, y: event.clientY, height, collapsed: sheetCollapsed, delta: 0};
    suppressSheetClick.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveSheetDrag = event => {
    const gesture = sheetGesture.current;
    if (!gesture || gesture.id !== event.pointerId) return;
    gesture.delta = event.clientY - gesture.y;
    if (Math.abs(gesture.delta) < 8) return;
    suppressSheetClick.current = true;
    setSheetHeight(Math.max(116, Math.min(sheetExpandedHeight.current, gesture.height - gesture.delta)));
  };
  const endSheetDrag = event => {
    const gesture = sheetGesture.current;
    if (!gesture || gesture.id !== event.pointerId) return;
    if (event.type === 'pointerup' && Math.abs(gesture.delta) > 36) {
      setSheetCollapsed(gesture.delta > 0);
      setShowSteps(false);
    }
    sheetGesture.current = null;
    setSheetHeight(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  if (!step) return null;
  if (isWithdrawnIndoorMap(model)) return <section className="indoor-guide p-6" role="alert">
    <h1 className="text-xl font-semibold">This ILC map has been replaced</h1>
    <p className="my-4">The old Main Corridor directions are withdrawn. Return to the trip planner and load the floor-plan map for floors 1–2.</p>
    <button className="guide-next max-w-sm" onClick={onExit}>Return to trip planner</button>
  </section>;
  const floor = model.floorById.get(floorId);
  // imageUrl may be a generated schematic; only use the actual published image.
  const original = floor?.rawImage;
  const styles = availableMapStyles(floor);
  const selectedStyle = resolveMapStyle(floor, mapStyle, failedImages);
  const image = selectedStyle?.image;
  const simplified = selectedStyle?.id === 'simple';
  const imageFailed = () => setFailedImages(previous => [...new Set([...previous, image])]);
  const sourceUrl = /^https?:\/\//i.test(original || '') ? original : null;
  const last = active === route.steps.length - 1;
  const Icon = step.kind === 'elevator' ? MoveVertical : last ? Flag : ArrowUp;
  const go = index => {
    setShowSteps(false);
    // Speak inside the tap event so phone browsers retain user activation.
    if (voiceOn) speak(displayInstruction(route.steps[index]?.text), {priority:true});
    onGo(index);
  };
  const toggleVoice = () => {
    const enabled = !voiceEnabled;
    setVoiceEnabled(enabled);
    setVoiceMuted(!enabled);
    if (enabled) speak(displayInstruction(step.text), {priority:true});
  };
  const toggleFocus = () => {
    setFocusStep(!focusStep); setZoom(100);
    if (!focusStep) setFloorId(step.floor);
  };
  return <section className="indoor-guide" aria-label="Indoor navigation">
    <header className="guide-header">
      <button className="guide-icon-button" onClick={onExit} aria-label="Return to outdoor navigation"><ArrowLeft size={22} /></button>
      <h1 className="min-w-0 flex-1 truncate text-base font-semibold sm:text-lg">{model.name}</h1>
      <button className="guide-text-button shrink-0" aria-label="Change room" onClick={onChangeDestination}><span className="hidden sm:inline">Change </span><span className="capitalize sm:normal-case">room</span></button>
    </header>
    <div className="guide-workspace">
      <main className="guide-map" aria-label="Indoor floor map">
        <div className="guide-map-toolbar">
          <div className="guide-map-tools">
            {floor?.routeAligned && <button className="guide-map-tool" aria-label={focusStep ? 'Show full floor' : 'Focus this step'} title={focusStep ? 'Show full floor' : 'Focus this step'} aria-pressed={focusStep} onClick={toggleFocus}><Focus size={20} /><span className="hidden sm:inline">{focusStep ? 'Full floor' : 'Focus step'}</span></button>}
            <div className="guide-zoom" aria-label="Map zoom">
              <button aria-label="Zoom out" title="Zoom out" disabled={zoom === 100} onClick={() => setZoom(Math.max(100, zoom - 25))}><Minus size={19} /></button>
              <button aria-label="Zoom in" title="Zoom in" disabled={zoom === 300} onClick={() => setZoom(Math.min(300, zoom + 25))}><Plus size={19} /></button>
            </div>
            <button className="guide-map-tool" aria-label="Map options and sources" title="Map options and sources" aria-expanded={showOptions} aria-controls="indoor-map-options" onClick={() => setShowOptions(!showOptions)}><Layers size={20} /></button>
          </div>
        </div>
        {showOptions && <section className="guide-map-popover" id="indoor-map-options" aria-label="Map options and sources">
          <div className="flex items-center justify-between"><h2 className="font-semibold">Map options</h2><button className="guide-icon-button" aria-label="Close map options" onClick={() => setShowOptions(false)}><X size={18} /></button></div>
          <label className="mt-2 flex items-center justify-between gap-3 text-sm font-semibold">View floor<select className="guide-floor-select" aria-label="Map floor" value={floorId} onChange={e => {setFloorId(e.target.value); setFocusStep(false);}}>{model.floors.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}</select></label>
          {styles.length > 1 && <div className="guide-map-options mt-2 grid gap-2" role="group" aria-label="Map style">{styles.map(style => <button key={style.id} aria-pressed={selectedStyle?.id === style.id} onClick={() => setMapStyle(style.id)}>{style.label}</button>)}</div>}
          <p className="mt-3 text-sm text-slate-600">Room outlines are traced from the UMass plans; dimensions are approximate. Blue marks the selected instruction landmark, not live GPS. Red marks your destination.</p>
          <details className="guide-details"><summary>Source information and access</summary><p className="text-sm">Directions follow mapped landmarks. Current physical access has not been field verified.</p>{[...(model.sourceWarnings || []), ...(route.warnings || [])].map((warning, i) => <p className="mt-2 text-sm" key={i}>{warning}</p>)}</details>
          {sourceUrl && <a className="guide-text-button inline-flex items-center text-emerald-800 underline" href={sourceUrl} target="_blank" rel="noreferrer">Open original source</a>}
        </section>}
        {image || simplified ? floor.routeAligned
          ? <SourceRoutePlan floor={floor} route={route} active={active} image={image} zoom={zoom} onZoom={setZoom} mapStyle={selectedStyle.id} focusStep={focusStep} onImageError={imageFailed} />
          : <InteractivePlan key={floorId} viewBox={`0 0 ${floor.width} ${floor.height}`} zoom={zoom} onZoom={setZoom} label={`${model.name}, ${floor?.label}: published floor plan`}><image href={image} width={floor.width} height={floor.height} onError={imageFailed} /></InteractivePlan>
          : <div className="guide-empty-map"><h2 className="font-semibold">No usable floor-plan image for this floor</h2><p className="mt-2 text-sm leading-relaxed text-slate-600">Follow the landmark directions. A graph connection does not tell us the shape of a corridor, so we do not draw it as one.</p></div>}
        <p className="guide-map-caption">{floor?.routeAligned ? <><span className="hidden sm:inline">{selectedStyle?.label} · </span>Blue: selected step · Red: destination</> : 'Published floor plan for reference. Route positions are not aligned to this image.'}</p>
      </main>
      <aside className="guide-navigation" aria-label="Current route directions">
        <section className={`guide-direction-card${sheetCollapsed ? ' is-collapsed' : ''}${sheetHeight !== null ? ' is-resizing' : ''}`} aria-label="Indoor directions" style={{height: sheetHeight ?? undefined}}>
          <button className="guide-sheet-handle" aria-expanded={!sheetCollapsed} aria-controls="indoor-current-directions"
            aria-label={sheetCollapsed ? 'Expand indoor directions' : 'Collapse indoor directions to show more map'}
            onPointerDown={startSheetDrag} onPointerMove={moveSheetDrag} onPointerUp={endSheetDrag}
            onPointerCancel={endSheetDrag} onLostPointerCapture={endSheetDrag}
            onClick={() => {if (!suppressSheetClick.current) {setSheetCollapsed(!sheetCollapsed); setShowSteps(false);} suppressSheetClick.current = false;}}>
            <span className="guide-sheet-grip" /><span>{sheetCollapsed ? 'Show directions' : 'More map'}<ChevronDown size={16} className={sheetCollapsed ? 'rotate-180' : ''} /></span>
          </button>
          <div className="guide-collapsed-direction"><button onClick={() => setSheetCollapsed(false)} aria-label="Expand current instruction"><span>Step {active + 1} of {route.steps.length}</span><strong>{displayInstruction(step.text)}</strong></button><button className="guide-next" aria-label={last ? 'Finish indoor navigation' : 'Next step'} onClick={last ? onExit : () => go(active + 1)}>{last ? 'Finish' : 'Next'}<ArrowRight size={18} /></button></div>
          <div className="guide-direction-content" id="indoor-current-directions">
          <div className="guide-card-heading"><div className="min-w-0 flex-1"><h2 className="font-bold text-emerald-800">Indoor directions</h2><p className="text-xs text-slate-500">Step {active + 1} of {route.steps.length} · {model.floorById.get(step.floor)?.label}</p></div><button className="guide-voice-toggle" disabled={!voiceSupported} aria-pressed={voiceOn} aria-label={!voiceSupported ? 'Voice unavailable in this browser' : voiceOn ? 'Voice on. Turn off spoken steps' : 'Voice off. Turn on spoken steps'} title={!voiceSupported ? 'Voice unavailable in this browser' : voiceOn ? 'Voice on' : 'Voice off'} onClick={toggleVoice}>{voiceOn ? <Volume2 size={19} /> : <VolumeX size={19} />}</button><button className="guide-text-button flex shrink-0 items-center gap-1" aria-expanded={showSteps} aria-controls="indoor-all-steps" onClick={() => setShowSteps(!showSteps)}>All steps<ChevronDown size={16} className={showSteps ? 'rotate-180' : ''} /></button></div>
          <div className="guide-current-step" aria-live="polite" aria-atomic="true"><span className="guide-step-icon"><Icon size={23} /></span><p>{displayInstruction(step.text)}</p></div>
          <div className="guide-step-controls">
            <button className="guide-back" disabled={active === 0} onClick={() => go(active - 1)}><ArrowLeft size={18} /><span>Back</span></button>
            <button className="guide-next" onClick={last ? onExit : () => go(active + 1)}>{last ? 'Finish' : 'Next step'}<ArrowRight size={18} /></button>
            <button className="guide-icon-button disabled:opacity-40" disabled={!voiceOn} aria-label="Repeat this step aloud" title="Repeat this step aloud" onClick={() => speak(displayInstruction(step.text), {priority:true})}><RotateCcw size={20} /></button>
          </div>
          <p className="guide-progress-note">Use Next at each landmark. Your position is not tracked indoors.</p>
          {floorId !== step.floor && <p className="mt-2 text-xs font-medium text-slate-600">Map preview: {floor?.label}. <button className="min-h-11 underline" onClick={() => {setFloorId(step.floor); setFocusStep(true); setZoom(100);}}>Return to this step’s floor</button></p>}
          </div>
        </section>
        <section id="indoor-all-steps" hidden={!showSteps} className="guide-step-list" aria-label="All directions"><div className="flex items-center justify-between"><h2 className="truncate font-semibold">To {route.room.name}</h2><button className="guide-icon-button" aria-label="Close all directions" onClick={() => setShowSteps(false)}><X size={18} /></button></div><ol>{route.steps.map((s, i) => <li key={i}><button className="guide-list-step" aria-current={i === active ? 'step' : undefined} onClick={() => go(i)}><span>{i + 1}</span>{displayInstruction(s.text)}</button></li>)}</ol></section>
      </aside>
    </div>
  </section>;
}
