import { useCallback, useEffect, useRef, useState } from 'react';
import { POS } from './layout';

/**
 * First-person indoor simulation at seated (wheelchair) eye height, drawn on a canvas.
 * Used when a step has no 360° photo, or the photo fails to load.
 *
 * Controls: hold ↑ / W (or the Roll button) to move, ↓ / S to back up, ← → to turn at a turn,
 * Space / Enter for doors and elevators. "Auto" drives the whole step hands-free.
 *
 * Props
 *   step        current route step (see mockIndoorData.js)
 *   onComplete  called once the step is physically finished (parent moves to the next step)
 *   highContrast
 *   auto, onAutoChange  hands-free driving; owned by the parent so it survives step changes
 */

const FT = 0.3048;
const EYE = 1.15; // m, seated eye height
const CEIL = 2.8;
const HALF = 1.6; // corridor half width, m
const SPEED = 1.1; // m/s, typical manual wheelchair cruising speed
const FEATURE_RUN = 4; // m of approach for doors, turns, elevators

function approachLength(step) {
  if (step.kind === 'straight') return Math.max(2, (step.distanceFt || 20) * FT);
  return FEATURE_RUN;
}

function needsAction(step) {
  return step.kind === 'door' || step.kind === 'elevator' || step.kind === 'turn-left' || step.kind === 'turn-right';
}

function actionLabel(step) {
  if (step.kind === 'door') return step.door === 'manual' ? 'Push door' : 'Press push plate';
  if (step.kind === 'elevator') return 'Call elevator';
  if (step.kind === 'turn-left') return 'Turn left';
  if (step.kind === 'turn-right') return 'Turn right';
  return null;
}

// Speckle texture for carpet, built once
let carpetPattern = null;
function getCarpet(ctx) {
  if (carpetPattern) return carpetPattern;
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = '#5b4a63';
  g.fillRect(0, 0, 64, 64);
  for (let i = 0; i < 900; i++) {
    const v = Math.random();
    g.fillStyle = v > 0.5 ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.12)';
    g.fillRect(Math.random() * 64, Math.random() * 64, 1.5, 1.5);
  }
  carpetPattern = ctx.createPattern(c, 'repeat');
  return carpetPattern;
}

// Zoom survives step changes (the simulation remounts per step)
const viewPrefs = { zoom: 1 };
const ZOOM_MIN = 0.6;
const ZOOM_MAX = 2.4;

export default function IndoorSimulation({ step, onComplete, highContrast = false, auto = false, onAutoChange, fab = null }) {
  const canvasRef = useRef(null);
  const wrapRef = useRef(null);
  const sim = useRef({ traveled: 0, vel: 0, phase: 'approach', anim: 0, yaw: 0, fwd: false, back: false, left: false, right: false, camX: 0, zoom: viewPrefs.zoom, auto: false });
  const stepRef = useRef(step);
  const doneRef = useRef(onComplete);
  const [hud, setHud] = useState({ remaining: 0, phase: 'approach' });
  const [hint, setHint] = useState(null);
  const [zoom, setZoomState] = useState(viewPrefs.zoom);
  doneRef.current = onComplete;

  const setZoom = useCallback((z) => {
    const v = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
    viewPrefs.zoom = v;
    sim.current.zoom = v;
    setZoomState(v);
  }, []);


  // New step: start at its beginning
  useEffect(() => {
    stepRef.current = step;
    Object.assign(sim.current, { traveled: 0, vel: 0, phase: 'approach', anim: 0, yaw: 0, camX: 0 });
    setHint(null);
  }, [step]);

  useEffect(() => {
    sim.current.auto = auto;
  }, [auto]);

  const act = useCallback((dir) => {
    const s = sim.current;
    const st = stepRef.current;
    if (s.phase !== 'ready') {
      if (s.phase === 'approach' && needsAction(st)) setHint('Roll closer first');
      return;
    }
    if (st.kind === 'turn-left' || st.kind === 'turn-right') {
      const want = st.kind === 'turn-left' ? 'left' : 'right';
      if (dir && dir !== want) {
        setHint(`Wrong way: turn ${want}`);
        return;
      }
    }
    setHint(null);
    s.phase = 'acting';
    s.anim = 0;
  }, []);

  // Keyboard
  useEffect(() => {
    const down = (e) => {
      if (e.target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
      const k = e.key;
      const s = sim.current;
      const turnReady = s.phase === 'ready' && (stepRef.current.kind === 'turn-left' || stepRef.current.kind === 'turn-right');
      if (k === 'ArrowUp' || k === 'w' || k === 'W') s.fwd = true;
      else if (k === 'ArrowDown' || k === 's' || k === 'S') s.back = true;
      // A / D (and arrows) steer inside the corridor, and make the turn when you reach one
      else if (k === 'ArrowLeft' || k === 'a' || k === 'A') turnReady ? act('left') : (s.left = true);
      else if (k === 'ArrowRight' || k === 'd' || k === 'D') turnReady ? act('right') : (s.right = true);
      else if (k === ' ' || k === 'Enter') act(null);
      else if (k === '+' || k === '=') setZoom(s.zoom * 1.15);
      else if (k === '-' || k === '_') setZoom(s.zoom / 1.15);
      else return;
      e.preventDefault();
    };
    const up = (e) => {
      if (e.key === 'ArrowUp' || e.key === 'w' || e.key === 'W') sim.current.fwd = false;
      if (e.key === 'ArrowDown' || e.key === 's' || e.key === 'S') sim.current.back = false;
      if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') sim.current.left = false;
      if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') sim.current.right = false;
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
  }, [act, setZoom]);

  // Mouse wheel / trackpad pinch zooms the view, like a map
  useEffect(() => {
    const el = wrapRef.current;
    const onWheel = (e) => {
      e.preventDefault();
      setZoom(sim.current.zoom * Math.exp(-e.deltaY * 0.0015));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [setZoom]);

  // Render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    let raf = 0;
    let last = performance.now();
    let lastHud = 0;

    const resize = () => {
      const r = wrapRef.current.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(r.width * dpr));
      canvas.height = Math.max(1, Math.round(r.height * dpr));
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrapRef.current);

    const frame = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const s = sim.current;
      const st = stepRef.current;
      const L = approachLength(st);

      // --- physics
      // Steering: A / D slide you across the corridor, like nudging the push rims
      const steer = (s.right ? 1 : 0) - (s.left ? 1 : 0);
      if (s.phase === 'approach') s.camX = Math.max(-(HALF - 0.45), Math.min(HALF - 0.45, s.camX + steer * 0.9 * dt));
      if (s.phase === 'approach') {
        const target = s.fwd || s.auto ? SPEED : s.back ? -SPEED * 0.5 : 0;
        s.vel += (target - s.vel) * Math.min(1, dt * 4);
        s.traveled = Math.max(0, Math.min(L, s.traveled + s.vel * dt));
        if (s.traveled >= L - 0.01) {
          s.vel = 0;
          if (needsAction(st)) {
            s.phase = 'ready';
            if (s.auto) {
              s.phase = 'acting';
              s.anim = 0;
            }
          } else {
            s.phase = 'done';
          }
        }
      } else if (s.phase === 'acting') {
        const dur = st.kind === 'elevator' ? 4.2 : st.kind === 'door' ? (st.door === 'manual' ? 2.2 : 1.4) : 1.1;
        s.anim = Math.min(1, s.anim + dt / dur);
        if (st.kind === 'turn-left' || st.kind === 'turn-right') s.yaw = (st.kind === 'turn-left' ? -1 : 1) * easeInOut(s.anim);
        if (s.anim >= 1) s.phase = 'done';
      }
      if (s.phase === 'done') {
        s.phase = 'finished';
        setTimeout(() => doneRef.current?.(), 250);
      }

      draw(ctx, canvas.width, canvas.height, st, s, L, highContrast);

      if (now - lastHud > 120) {
        lastHud = now;
        setHud({ remaining: Math.max(0, (L - s.traveled) / FT), phase: s.phase });
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [highContrast]);

  const label = actionLabel(step);
  const holdOn = () => (sim.current.fwd = true);
  const holdOff = () => (sim.current.fwd = false);

  return (
    <div ref={wrapRef} className="absolute inset-0 select-none bg-slate-900">
      <canvas
        ref={canvasRef}
        className="h-full w-full"
        role="img"
        aria-label={`Simulated first-person view at wheelchair eye level: ${step.label || step.text}`}
      />

      {/* Driving controls: bottom-left, just above the step panel */}
      <div className="absolute left-3 z-30 flex max-w-[calc(100%-5.5rem)] flex-wrap items-center gap-2 sm:left-4" style={{ bottom: POS.aboveLeft }}>
        {hint && (
          <span className="rounded-full bg-amber-400 px-3 py-1.5 text-[13px] font-semibold text-slate-950 shadow" role="status">
            {hint}
          </span>
        )}
        <button
          type="button"
          onClick={() => onAutoChange?.(!auto)}
          aria-pressed={auto}
          className={`rounded-full px-4 py-2.5 text-[14px] font-semibold shadow-lg ring-2 transition ${auto ? 'bg-emerald-400 text-slate-950 ring-emerald-200' : 'bg-white/90 text-slate-900 ring-white/40 hover:bg-white'}`}
          title="Drive each step hands-free"
        >
          {auto ? 'Auto: on' : 'Auto'}
        </button>
        <button
          type="button"
          onPointerDown={holdOn}
          onPointerUp={holdOff}
          onPointerLeave={holdOff}
          onPointerCancel={holdOff}
          disabled={hud.phase !== 'approach'}
          className="rounded-full bg-white px-5 py-2.5 text-[14px] font-semibold text-slate-950 shadow-lg ring-2 ring-white/40 transition active:scale-95 disabled:opacity-40"
          aria-label="Hold to roll forward"
        >
          ⬆ Hold to roll
        </button>
        {label && (
          <button
            type="button"
            onClick={() => act(step.kind === 'turn-left' ? 'left' : step.kind === 'turn-right' ? 'right' : null)}
            disabled={hud.phase !== 'ready'}
            className="rounded-full bg-blue-500 px-5 py-2.5 text-[14px] font-semibold text-white shadow-lg ring-2 ring-blue-200 transition active:scale-95 disabled:opacity-40"
          >
            {label}
          </button>
        )}
      </div>

      {/* Distance HUD */}
      <div className="pointer-events-none absolute right-3 rounded-2xl bg-black/60 px-3 py-1.5 text-right text-white backdrop-blur sm:right-4" style={{ top: POS.headerTop }}>
        <div className="text-[11px] font-medium uppercase tracking-wider text-white/70">
          {hud.phase === 'approach' ? 'Ahead' : hud.phase === 'ready' ? 'Action' : hud.phase === 'acting' ? (step.kind === 'elevator' ? 'Elevator' : 'Moving') : 'Done'}
        </div>
        <div className="text-[18px] font-semibold tabular-nums leading-tight sm:text-[20px]">
          {hud.phase === 'approach' ? `${Math.ceil(hud.remaining)} ft` : hud.phase === 'ready' ? label : hud.phase === 'acting' ? '…' : '✓'}
        </div>
      </div>
      {/* Simulated step position */}
      <div
        className="pointer-events-none absolute left-1/2 z-20 flex -translate-x-1/2 flex-col items-center"
        style={{ bottom: 'calc(var(--indoor-panel-h, 16px) + 72px)' }}
        aria-live="polite"
      >
        <span className="rounded-full bg-white/90 px-3 py-1.5 text-[13px] font-semibold text-slate-900 shadow-lg">
          📍 Simulated position
        </span>
        <span className="h-3 w-0.5 bg-white/90" />
        <span className="relative flex h-4 w-4">
          <span className="relative inline-flex h-4 w-4 rounded-full border-2 border-white bg-slate-700" />
        </span>
      </div>

      {/* Right column: 2D button above the zoom controls */}
      <div className="absolute right-3 z-30 flex flex-col items-center gap-3 sm:right-4" style={{ bottom: POS.aboveRight }}>
      {fab}
      <div className="flex flex-col overflow-hidden rounded-2xl bg-white/95 text-slate-900 shadow-lg ring-1 ring-black/10">
        <button type="button" onClick={() => setZoom(zoom * 1.2)} disabled={zoom >= ZOOM_MAX} aria-label="Zoom in on 3D view" className="h-11 w-11 text-[20px] font-semibold hover:bg-slate-100 disabled:opacity-30">
          +
        </button>
        <span className="border-y border-slate-200 py-0.5 text-center text-[10px] font-semibold tabular-nums text-slate-500">{zoom.toFixed(1)}×</span>
        <button type="button" onClick={() => setZoom(zoom / 1.2)} disabled={zoom <= ZOOM_MIN} aria-label="Zoom out of 3D view" className="h-11 w-11 text-[22px] font-semibold hover:bg-slate-100 disabled:opacity-30">
          −
        </button>
      </div>
      </div>

      <p className="pointer-events-none absolute right-4 hidden rounded-full bg-black/55 px-3 py-1 text-[11px] font-medium text-white/85 xl:block" style={{ top: POS.noticeTop }}>
        Simulated view · seated eye height · W/S roll · A/D steer &amp; turn · Space doors · scroll to zoom
      </p>
    </div>
  );
}

function floorName(step, n) {
  if (n === step.floorFrom && step.floorFromLabel) return step.floorFromLabel;
  if (n === step.floorTo && step.floorToLabel) return step.floorToLabel;
  return String(n);
}

function easeInOut(t) {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

// ------------------------------------------------------------------ drawing

function draw(ctx, w, h, step, s, L, hc) {
  const f = h * 0.95 * (s.zoom || 1);
  const cy = h * 0.47;
  const cx = w / 2 - s.yaw * w * 0.9; // turning slides the corridor sideways
  const near = 0.35;
  const isFeature = step.kind !== 'straight';
  const far = Math.max(0.9, Math.min(45, L - s.traveled + (isFeature ? 0.9 : 7)));
  const camX = s.camX || 0;
  const P = (x, y, z) => {
    const zz = Math.max(z, near);
    return [cx + (f * (x - camX)) / zz, cy - (f * (y - EYE)) / zz];
  };
  const quad = (a, b, c, d, fill) => {
    ctx.beginPath();
    ctx.moveTo(...a);
    ctx.lineTo(...b);
    ctx.lineTo(...c);
    ctx.lineTo(...d);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
  };

  const C = hc
    ? { ceil: '#e5e5e5', wallL: '#d4d4d4', wallR: '#c8c8c8', end: '#bdbdbd', tile: '#f5f5f5', grout: '#111', door: '#1d4ed8', line: '#000' }
    : { ceil: '#e9e6df', wallL: '#d9d3c7', wallR: '#cfc8bb', end: '#c7c0b2', tile: '#d8d4cc', grout: 'rgba(60,55,50,0.35)', door: '#8a6a4a', line: 'rgba(0,0,0,0.25)' };

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#20232a';
  ctx.fillRect(0, 0, w, h);

  // Shells
  quad(P(-HALF, CEIL, near), P(HALF, CEIL, near), P(HALF, CEIL, far), P(-HALF, CEIL, far), C.ceil);
  quad(P(-HALF, 0, near), P(-HALF, CEIL, near), P(-HALF, CEIL, far), P(-HALF, 0, far), C.wallL);
  quad(P(HALF, 0, near), P(HALF, CEIL, near), P(HALF, CEIL, far), P(HALF, 0, far), C.wallR);

  // Floor by surface
  const floorPoly = [P(-HALF, 0, near), P(HALF, 0, near), P(HALF, 0, far), P(-HALF, 0, far)];
  if (step.surface === 'carpet') {
    quad(...floorPoly, getCarpet(ctx));
    // pile shading toward the distance
    const g = ctx.createLinearGradient(0, h, 0, cy);
    g.addColorStop(0, 'rgba(0,0,0,0)');
    g.addColorStop(1, 'rgba(0,0,0,0.35)');
    quad(...floorPoly, g);
  } else {
    quad(...floorPoly, C.tile);
    ctx.strokeStyle = C.grout;
    ctx.lineWidth = Math.max(1, h / 700);
    const tile = 0.6;
    const off = s.traveled % tile;
    for (let z = tile - off; z < far; z += tile) {
      if (z < near) continue;
      ctx.beginPath();
      ctx.moveTo(...P(-HALF, 0, z));
      ctx.lineTo(...P(HALF, 0, z));
      ctx.stroke();
    }
    for (let x = -HALF; x <= HALF + 0.01; x += tile) {
      ctx.beginPath();
      ctx.moveTo(...P(x, 0, near));
      ctx.lineTo(...P(x, 0, far));
      ctx.stroke();
    }
    if (step.surface === 'wet-tile') drawWet(ctx, P, f, s, far, w, h, cy);
  }

  // Baseboards
  ctx.strokeStyle = C.line;
  ctx.lineWidth = Math.max(1.5, h / 400);
  for (const x of [-HALF, HALF]) {
    ctx.beginPath();
    ctx.moveTo(...P(x, 0.12, near));
    ctx.lineTo(...P(x, 0.12, far));
    ctx.stroke();
  }

  // Ceiling light panels
  const spacing = 3;
  const lo = s.traveled % spacing;
  for (let z = spacing - lo; z < far - 0.3; z += spacing) {
    if (z < near + 0.2) continue;
    quad(P(-0.45, CEIL - 0.01, z), P(0.45, CEIL - 0.01, z), P(0.45, CEIL - 0.01, z + 0.6), P(-0.45, CEIL - 0.01, z + 0.6), hc ? '#fff' : '#fffdf5');
  }

  // Side doors passing by
  const dSpace = 6.5;
  const dOff = s.traveled % dSpace;
  for (let z = 2.5 - dOff; z < far - 1.5; z += dSpace) {
    for (const [x, zz] of [[-HALF, z], [HALF, z + 3.2]]) {
      if (zz < near || zz + 1 > far - 0.2) continue;
      quad(P(x, 0, zz), P(x, 2.15, zz), P(x, 2.15, zz + 1.0), P(x, 0, zz + 1.0), C.door);
      const [hx, hy] = P(x, 1.0, zz + 0.85);
      ctx.fillStyle = '#d6d3cc';
      ctx.fillRect(hx - 3, hy - 2, 6, 4);
    }
  }

  // Turn opening near the end
  if (step.kind === 'turn-left' || step.kind === 'turn-right') {
    const x = step.kind === 'turn-left' ? -HALF : HALF;
    const z0 = Math.max(near, far - 2.4);
    quad(P(x, 0, z0), P(x, CEIL, z0), P(x, CEIL, far), P(x, 0, far), hc ? '#fff' : '#f3efe6');
    quad(P(x, 0, z0), P(x * 1.0, 0, far), P(x * 2.2, 0, far), P(x * 2.2, 0, z0), C.tile);
  }

  // End wall
  quad(P(-HALF, 0, far), P(HALF, 0, far), P(HALF, CEIL, far), P(-HALF, CEIL, far), C.end);
  drawEndFeature(ctx, P, step, s, far, hc);

  // Hanging sign
  if (step.label) drawSign(ctx, P, f, step, Math.min(far - 0.4, 7.5), hc);

  // Depth haze
  const haze = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * 0.75);
  haze.addColorStop(0, 'rgba(255,255,255,0)');
  haze.addColorStop(1, 'rgba(0,0,0,0.38)');
  ctx.fillStyle = haze;
  ctx.fillRect(0, 0, w, h);

  // Turn fade
  if (Math.abs(s.yaw) > 0.6) {
    ctx.fillStyle = `rgba(15,17,22,${(Math.abs(s.yaw) - 0.6) * 2.2})`;
    ctx.fillRect(0, 0, w, h);
  }

  drawElevatorRide(ctx, step, s, w, h);
  drawWheelchair(ctx, w, h, s.traveled);
}

function drawWet(ctx, P, f, s, far, w, h, cy) {
  // Glossy reflection of ceiling lights
  const g = ctx.createLinearGradient(0, cy, 0, h);
  g.addColorStop(0, 'rgba(255,255,255,0.35)');
  g.addColorStop(0.5, 'rgba(255,255,255,0.08)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  const [ax] = P(-0.5, 0, 1);
  const [bx] = P(0.5, 0, 1);
  ctx.fillRect(ax, cy, bx - ax, h - cy);
  // Puddles fixed to the floor
  const puddles = [[-0.6, 1.8, 0.45], [0.5, 3.4, 0.6], [-0.2, 5.6, 0.5], [0.7, 7.9, 0.4]];
  for (const [x, z0, r] of puddles) {
    const z = z0 - s.traveled;
    if (z < 0.5 || z > far) continue;
    const [px, py] = P(x, 0, z);
    const rx = (f * r) / z;
    const ry = (rx * EYE) / z;
    ctx.beginPath();
    ctx.ellipse(px, py, rx, Math.max(1, ry), 0, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(160,190,215,0.55)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.6)';
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  // Yellow wet-floor sign
  const z = 2.6 - s.traveled;
  if (z > 0.8 && z < far) {
    const [bx1, by1] = P(1.05, 0, z);
    const [, ty] = P(1.05, 0.65, z);
    const half = (f * 0.18) / z;
    ctx.beginPath();
    ctx.moveTo(bx1 - half, by1);
    ctx.lineTo(bx1, ty);
    ctx.lineTo(bx1 + half, by1);
    ctx.closePath();
    ctx.fillStyle = '#facc15';
    ctx.fill();
    ctx.strokeStyle = '#1f2937';
    ctx.lineWidth = Math.max(1, half / 10);
    ctx.stroke();
    ctx.fillStyle = '#111';
    ctx.font = `700 ${Math.max(8, half * 0.5)}px Inter, system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.fillText('!', bx1, by1 - (by1 - ty) * 0.3);
  }
}

function drawEndFeature(ctx, P, step, s, far, hc) {
  const box = (x0, y0, x1, y1, fill, stroke) => {
    const [ax, ay] = P(x0, y1, far);
    const [bx, by] = P(x1, y0, far);
    ctx.fillStyle = fill;
    ctx.fillRect(ax, ay, bx - ax, by - ay);
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 2;
      ctx.strokeRect(ax, ay, bx - ax, by - ay);
    }
    return [ax, ay, bx - ax, by - ay];
  };
  const opening = s.phase === 'acting' || s.phase === 'finished' ? easeInOut(s.anim) : 0;

  if (step.kind === 'door' || step.kind === 'arrive') {
    box(-1.0, 0, 1.0, 2.3, '#3b3f46');
    if (step.kind === 'door' && step.door === 'automatic') {
      // Glass sliding doors + blue push plate on the right wall
      const slide = 0.9 * opening;
      box(-0.95 - slide, 0, -0.02 - slide, 2.2, 'rgba(170,205,230,0.55)', '#6b7280');
      box(0.02 + slide, 0, 0.95 + slide, 2.2, 'rgba(170,205,230,0.55)', '#6b7280');
      const [px, py] = P(HALF - 0.01, 1.0, far - 0.6);
      const [px2, py2] = P(HALF - 0.01, 1.25, far - 0.45);
      ctx.fillStyle = '#1d4ed8';
      ctx.fillRect(Math.min(px, px2), Math.min(py, py2), Math.abs(px2 - px) + 4, Math.abs(py2 - py));
      ctx.fillStyle = '#fff';
      ctx.font = `700 ${Math.max(9, Math.abs(py2 - py) * 0.55)}px Inter, system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText('♿', (px + px2) / 2, (py + py2) / 2 + Math.abs(py2 - py) * 0.2);
    } else {
      // Heavy wooden door(s) that swing open slowly
      const swing = 1 - opening * 0.85;
      const [x, y, wd, ht] = box(-0.95, 0, -0.95 + 1.9 * swing, 2.2, hc ? '#1d4ed8' : '#7a5636', '#3f2a18');
      ctx.fillStyle = '#c9c4ba';
      ctx.fillRect(x + wd * 0.82, y + ht * 0.5, Math.max(4, wd * 0.12), Math.max(3, ht * 0.025));
      if (step.kind === 'door') {
        ctx.fillStyle = '#fff';
        ctx.font = `700 ${Math.max(10, ht * 0.06)}px Inter, system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillText('PUSH', x + wd / 2, y + ht * 0.4);
      }
      if (step.kind === 'arrive') {
        // Door plaque: room number, or a check mark for named rooms; the full name is on the hanging sign
        const [rx, ry, rw, rh] = box(1.15, 1.45, 1.55, 1.75, '#047857');
        const short = (step.label || '').replace(/^Room\s*/i, '');
        const text = short.length <= 5 ? short : '✓';
        ctx.fillStyle = '#fff';
        ctx.font = `700 ${Math.max(10, rh * 0.62)}px Inter, system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(text, rx + rw / 2, ry + rh / 2);
        ctx.textBaseline = 'alphabetic';
      }
    }
  } else if (step.kind === 'elevator') {
    box(-1.2, 0, 1.2, 2.45, '#9ca3af');
    const gap = 0.55 * opening;
    box(-1.05 - gap, 0, -0.01 - gap, 2.2, hc ? '#e5e5e5' : '#cbd2db', '#6b7280');
    box(0.01 + gap, 0, 1.05 + gap, 2.2, hc ? '#e5e5e5' : '#c3cad4', '#6b7280');
    if (gap > 0.02) box(-gap, 0, gap, 2.2, '#f8f5e8');
    const [ix, iy, iw, ih] = box(-0.3, 2.28, 0.3, 2.42, '#111827');
    ctx.fillStyle = '#f87171';
    ctx.font = `700 ${Math.max(9, ih * 0.75)}px ui-monospace, monospace`;
    ctx.textAlign = 'center';
    ctx.fillText(`${(step.floorTo ?? 1) >= (step.floorFrom ?? 1) ? '▲' : '▼'} ${floorName(step, step.floorFrom ?? 1)}`, ix + iw / 2, iy + ih * 0.8);
    const [bx, by] = P(1.35, 1.05, far);
    ctx.beginPath();
    ctx.arc(bx, by, Math.max(4, iw * 0.09), 0, Math.PI * 2);
    ctx.fillStyle = s.phase === 'acting' ? '#fbbf24' : '#e5e7eb';
    ctx.fill();
  } else if (step.kind === 'turn-left' || step.kind === 'turn-right') {
    const [x, y, wd, ht] = box(-0.55, 1.4, 0.55, 1.95, hc ? '#000' : '#1f2937');
    ctx.fillStyle = '#fff';
    ctx.font = `700 ${Math.max(12, ht * 0.75)}px Inter, system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.fillText(step.kind === 'turn-left' ? '←' : '→', x + wd / 2, y + ht * 0.78);
  }
}

function drawSign(ctx, P, f, step, z, hc) {
  if (z < 1) return;
  const [ax, ay] = P(-0.75, 2.6, z);
  const [bx, by] = P(0.75, 2.3, z);
  ctx.fillStyle = hc ? '#000' : '#14532d';
  ctx.fillRect(ax, ay, bx - ax, by - ay);
  ctx.fillStyle = '#fff';
  const size = Math.max(9, (by - ay) * 0.45);
  ctx.font = `600 ${size}px Inter, system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  let text = step.label;
  while (ctx.measureText(text).width > (bx - ax) * 0.92 && text.length > 4) text = text.slice(0, -2);
  ctx.fillText(text === step.label ? text : `${text}…`, (ax + bx) / 2, (ay + by) / 2);
  ctx.textBaseline = 'alphabetic';
  // hanging wires
  ctx.strokeStyle = 'rgba(0,0,0,0.4)';
  ctx.lineWidth = 1;
  const [, cyTop] = P(0, 2.8, z);
  for (const x of [ax + (bx - ax) * 0.15, bx - (bx - ax) * 0.15]) {
    ctx.beginPath();
    ctx.moveTo(x, ay);
    ctx.lineTo(x, cyTop);
    ctx.stroke();
  }
  void f;
}

function drawElevatorRide(ctx, step, s, w, h) {
  if (step.kind !== 'elevator' || s.phase === 'approach' || s.phase === 'ready') return;
  // After the doors open: ride overlay counting floors
  const t = Math.max(0, (s.anim - 0.35) / 0.65);
  if (t <= 0) return;
  ctx.fillStyle = `rgba(12,14,18,${Math.min(0.85, t * 2)})`;
  ctx.fillRect(0, 0, w, h);
  const from = step.floorFrom ?? 1;
  const to = step.floorTo ?? from + 1;
  const floor = Math.round(from + (to - from) * Math.min(1, t * 1.15));
  ctx.fillStyle = '#f87171';
  ctx.font = `700 ${h * 0.16}px ui-monospace, monospace`;
  ctx.textAlign = 'center';
  ctx.fillText(`${to >= from ? '▲' : '▼'} ${floorName(step, floor)}`, w / 2, h * 0.52);
  ctx.fillStyle = 'rgba(255,255,255,0.8)';
  ctx.font = `500 ${h * 0.03}px Inter, system-ui, sans-serif`;
  ctx.fillText(`${step.label || 'Elevator'} · ${floorName(step, from)} to ${floorName(step, to)}`, w / 2, h * 0.62);
}

function drawWheelchair(ctx, w, h, traveled) {
  // Seated foreground: knees/footplate and the two push rims, which turn as you roll
  ctx.save();
  ctx.fillStyle = 'rgba(17,24,39,0.92)';
  ctx.beginPath();
  ctx.moveTo(w * 0.36, h);
  ctx.quadraticCurveTo(w * 0.42, h * 0.86, w * 0.5, h * 0.87);
  ctx.quadraticCurveTo(w * 0.58, h * 0.86, w * 0.64, h);
  ctx.closePath();
  ctx.fill();
  const r = h * 0.2;
  for (const side of [-1, 1]) {
    const cxw = w / 2 + side * w * 0.46;
    const cyw = h * 1.02;
    ctx.lineWidth = Math.max(4, h * 0.018);
    ctx.strokeStyle = 'rgba(30,41,59,0.95)';
    ctx.beginPath();
    ctx.arc(cxw, cyw, r, Math.PI, Math.PI * 2);
    ctx.stroke();
    ctx.strokeStyle = 'rgba(203,213,225,0.9)';
    ctx.lineWidth = Math.max(2, h * 0.007);
    ctx.beginPath();
    ctx.arc(cxw, cyw, r * 0.86, Math.PI, Math.PI * 2);
    ctx.stroke();
    // spokes rotate with distance travelled
    const rot = (traveled / 0.3) * side;
    ctx.strokeStyle = 'rgba(148,163,184,0.6)';
    ctx.lineWidth = 1.5;
    for (let k = 0; k < 6; k++) {
      const a = rot + (k * Math.PI) / 3;
      const sa = Math.sin(a);
      if (sa > 0.05) continue;
      ctx.beginPath();
      ctx.moveTo(cxw, cyw);
      ctx.lineTo(cxw + Math.cos(a) * r * 0.84, cyw + sa * r * 0.84);
      ctx.stroke();
    }
  }
  ctx.restore();
}
