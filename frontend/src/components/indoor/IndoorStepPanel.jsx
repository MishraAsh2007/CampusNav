import { useEffect, useMemo, useRef, useState } from 'react';
import { useSpeech } from './useSpeech';
import { setVoiceMuted } from '../../services/voiceEngine';

/**
 * Turn-by-turn text panel + spoken directions, shared by the 2D floor plan and the 3D view so the
 * active step and the voice carry on when you switch views.
 *
 * Props
 *   steps, active, onGo(index)
 *   onDone       called by "Done" on the last step
 *   autoSpeak    read each new step aloud (default true)
 *   className    positioning (defaults to a bottom sheet on phones, bottom-left card on larger screens)
 *   onBox        ({ fromBottom, fullWidth }) => void   screen space the panel covers, updated on resize
 */

export const STEP_ICON = {
  straight: '⬆',
  'turn-left': '↰',
  'turn-right': '↱',
  door: '🚪',
  elevator: '🛗',
  arrive: '🏁'
};

export default function IndoorStepPanel({ steps, active, onGo, onDone, autoSpeak = true, className, onBox }) {
  const [muted, setMuted] = useState(!autoSpeak);
  // Phones: just the current step; the full list is one tap away
  const [listOpen, setListOpen] = useState(() => typeof window === 'undefined' || window.innerWidth >= 640);
  const ref = useRef(null);

  // Tell the parent how much of the screen bottom the panel covers, so controls can sit above it
  useEffect(() => {
    const el = ref.current;
    if (!el || !onBox) return;
    const report = () => {
      const r = el.getBoundingClientRect();
      onBox({ fromBottom: Math.max(0, Math.round(window.innerHeight - r.top)), fullWidth: r.width >= window.innerWidth - 48 });
    };
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    window.addEventListener('resize', report);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', report);
    };
  }, [onBox]);
  const { supported, speaking, speak, stop } = useSpeech();
  const step = steps[active];
  const last = active === steps.length - 1;

  useEffect(() => {
    if (!step) return;
    // 'Voice off' also silences announcements like 'Recalculating route.' Set it before speaking.
    setVoiceMuted(muted);
    // The engine strips numbering anyway; only the action is spoken
    if (!muted) speak(step.text);
  }, [active, step, muted, speak]);

  useEffect(() => () => setVoiceMuted(false), []);

  // N / P to move between steps, R to repeat (arrow keys are reserved for driving in 3D)
  useEffect(() => {
    const onKey = (e) => {
      if (e.target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
      if (e.key === 'n' || e.key === 'N') onGo(Math.min(steps.length - 1, active + 1));
      else if (e.key === 'p' || e.key === 'P') onGo(Math.max(0, active - 1));
      else if (e.key === 'r' || e.key === 'R') step && speak(step.text);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, onGo, speak, step, steps.length]);

  const totalM = useMemo(() => steps.reduce((n, s) => n + (s.distanceM || 0), 0), [steps]);
  const leftM = useMemo(() => steps.slice(active).reduce((n, s) => n + (s.distanceM || 0), 0), [steps, active]);
  if (!step) return null;

  return (
    <section
      ref={ref}
      aria-label="Indoor directions"
      style={className ? undefined : { bottom: 'max(12px, env(safe-area-inset-bottom, 0px))' }}
      className={
        className ??
        'absolute inset-x-3 z-[1000] flex max-h-[55%] flex-col overflow-hidden rounded-3xl bg-white text-slate-950 shadow-2xl ring-1 ring-black/10 sm:inset-x-auto sm:left-4 sm:w-[400px]'
      }
    >
      <div className="flex items-center justify-between gap-2 px-4 pt-3 sm:pt-3.5">
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-600 sm:text-[12px]">
          Step {active + 1} of {steps.length}
          {totalM > 0 && <span className="normal-case tracking-normal text-slate-500"> · {Math.round(leftM)} m left</span>}
        </span>
        <div className="flex items-center gap-1">
          {supported && (
            <button
              type="button"
              onClick={() => setMuted((m) => !m)}
              aria-pressed={!muted}
              className={`rounded-full px-3 py-1.5 text-[12px] font-semibold transition ${muted ? 'bg-slate-100 text-slate-700' : 'bg-blue-600 text-white'}`}
            >
              {muted ? '🔇 Voice off' : speaking ? '🔊 Speaking' : '🔊 Voice on'}
            </button>
          )}
          <button
            type="button"
            onClick={() => setListOpen((o) => !o)}
            aria-expanded={listOpen}
            className="rounded-full bg-slate-100 px-3 py-1.5 text-[12px] font-semibold text-slate-700"
          >
            {listOpen ? 'Hide steps' : 'All steps'}
          </button>
        </div>
      </div>

      <div className="mx-4 mt-2 flex gap-1" aria-hidden="true">
        {steps.map((s, i) => (
          <span key={s.id} className={`h-1.5 flex-1 rounded-full ${i < active ? 'bg-emerald-500' : i === active ? 'bg-blue-600' : 'bg-slate-200'}`} />
        ))}
      </div>

      <div className="flex items-start gap-3 px-4 py-2.5 sm:py-3" aria-live="polite">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-blue-600 text-[20px] text-white sm:h-12 sm:w-12 sm:text-[24px]" aria-hidden="true">
          {STEP_ICON[step.kind] ?? '⬆'}
        </span>
        <p className="pt-0.5 text-[16px] font-semibold leading-snug sm:text-[19px]">{step.text}</p>
      </div>

      {listOpen && (
        <ol className="min-h-0 max-h-[22vh] flex-1 overflow-y-auto border-t border-slate-200 px-2 py-2">
          {steps.map((s, i) => {
            const isActive = i === active;
            return (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => onGo(i)}
                  aria-current={isActive ? 'step' : undefined}
                  className={`flex w-full items-start gap-2.5 rounded-xl px-2 py-1.5 text-left text-[14px] transition ${
                    isActive ? 'bg-blue-50 font-semibold text-slate-950 ring-2 ring-blue-600' : i < active ? 'text-slate-400 line-through decoration-slate-300' : 'text-slate-500 hover:bg-slate-50'
                  }`}
                >
                  <span className="w-5 shrink-0 text-right tabular-nums">{i + 1}.</span>
                  <span>{s.text}</span>
                </button>
              </li>
            );
          })}
        </ol>
      )}

      <div className="flex items-center gap-2 border-t border-slate-200 p-2.5 sm:p-3">
        <button
          type="button"
          onClick={() => onGo(active - 1)}
          disabled={active === 0}
          className="rounded-full bg-slate-100 px-4 py-2 text-[14px] font-semibold text-slate-800 transition hover:bg-slate-200 disabled:opacity-40 sm:py-2.5"
        >
          Back
        </button>
        <button
          type="button"
          onClick={() => speak(step.text)}
          disabled={!supported}
          className="rounded-full bg-slate-100 px-4 py-2 text-[14px] font-semibold text-slate-800 transition hover:bg-slate-200 disabled:opacity-40 sm:py-2.5"
        >
          Repeat
        </button>
        <button
          type="button"
          onClick={() => (last ? onDone?.() : onGo(active + 1))}
          disabled={last && !onDone}
          className="ml-auto rounded-full bg-slate-950 px-5 py-2 text-[14px] font-semibold text-white transition hover:bg-slate-800 disabled:opacity-40 sm:py-2.5"
        >
          {last ? 'Done' : 'Next step'}
        </button>
      </div>
    </section>
  );
}
