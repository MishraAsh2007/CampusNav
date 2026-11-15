import { useState } from 'react';
import {
  ArrowDownRight,
  ArrowUp,
  ArrowUpLeft,
  ArrowUpRight,
  ChevronDown,
  CircleDot,
  CornerUpLeft,
  CornerUpRight,
  Flag,
  Footprints,
  MoveVertical,
  TrendingUp,
  Umbrella
} from 'lucide-react';
import type { RouteStep } from '../types';
import { cx } from './ui';
import { speak } from '../services/voiceEngine';

function StepIcon({ icon }: { icon?: RouteStep['icon'] }) {
  const cls = 'h-4 w-4';
  switch (icon) {
    case 'start':
      return <CircleDot className={cls} />;
    case 'turn-left':
      return <CornerUpLeft className={cls} />;
    case 'turn-right':
      return <CornerUpRight className={cls} />;
    case 'slight-left':
      return <ArrowUpLeft className={cls} />;
    case 'slight-right':
      return <ArrowUpRight className={cls} />;
    case 'ramp-up':
      return <TrendingUp className={cls} />;
    case 'ramp-down':
      return <ArrowDownRight className={cls} />;
    case 'elevator':
      return <MoveVertical className={cls} />;
    case 'stairs':
      return <Footprints className={cls} />;
    case 'crossing':
      return <span className="text-[10px] font-bold tracking-tighter">≡</span>;
    case 'indoor':
      return <Umbrella className={cls} />;
    case 'destination':
      return <Flag className={cls} />;
    default:
      return <ArrowUp className={cls} />;
  }
}

const tone = (s: RouteStep) =>
  s.icon === 'elevator'
    ? 'bg-lift-soft text-lift-ink'
    : s.icon === 'stairs'
      ? 'bg-stop-soft text-stop-ink'
      : s.icon === 'destination'
        ? 'bg-go text-white'
        : s.grade_pct !== null && s.grade_pct >= 5
          ? 'bg-warn-soft text-warn-ink'
          : 'bg-black/[0.05] text-ink-2';

interface Props {
  steps: RouteStep[];
  onFocusStep: (s: RouteStep) => void;
}

export function Directions({ steps, onFocusStep }: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  if (!steps.length) return null;
  const index = Math.min(active, steps.length - 1);
  const current = steps[index];
  const go = (next: number) => {
    setActive(next);
    onFocusStep(steps[next]);
  };
  return (
    <section aria-labelledby="dir-h" className="rounded-3xl border-2 border-emerald-600 bg-white p-4 shadow-lg">
      <h2 id="dir-h" className="text-lg font-bold text-emerald-800">Turn-by-turn directions</h2>
      <p className="mt-1 text-xs text-ink-3">Step {index + 1} of {steps.length} · Advance as you walk</p>
      <div className="my-3 flex items-start gap-3" aria-live="polite">
        <span className={cx('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl', tone(current))}><StepIcon icon={current.icon} /></span>
        <p className="text-base font-semibold leading-snug">{current.instruction}</p>
      </div>
      <div className="mb-3 flex gap-2">
        <button type="button" disabled={index === 0} onClick={() => go(index - 1)} className="flex-1 rounded-xl bg-slate-100 px-3 py-2 text-sm font-semibold disabled:opacity-40">Back</button>
        <button type="button" disabled={index === steps.length - 1} onClick={() => go(index + 1)} className="flex-1 rounded-xl bg-emerald-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">Next step</button>
      </div>
      <button type="button" onClick={() => speak(current.instruction, {priority: true})} className="mb-2 text-sm font-semibold text-emerald-800 underline">Read this step aloud</button>
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between px-1 py-1">
        <span className="text-sm font-semibold">{open ? 'Hide all steps' : 'Show all steps'}</span>
        <ChevronDown className={cx('h-4 w-4 text-ink-4 transition-transform duration-300', open && 'rotate-180')} />
      </button>
      {open && (
        <ol className="mt-1.5 max-h-[28vh] space-y-0.5 overflow-y-auto animate-fade">
          {steps.map((s, i) => (
            <li key={i}>
              <button
                onClick={() => go(i)}
                aria-current={i === index ? 'step' : undefined}
                className="group flex w-full items-start gap-3 rounded-2xl px-1.5 py-2 text-left transition hover:bg-black/[0.03]"
              >
                <span className={cx('flex h-8 w-8 shrink-0 items-center justify-center rounded-xl', tone(s))}>
                  <StepIcon icon={s.icon} />
                </span>
                <span className="min-w-0 flex-1 pt-1">
                  <span className="block text-[14px] leading-snug text-ink">{s.instruction}</span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
