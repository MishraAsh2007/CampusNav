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

export function StepIcon({ icon }: { icon?: RouteStep['icon'] }) {
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

export const tone = (s: RouteStep) =>
  s.icon === 'elevator'
    ? 'bg-lift-soft text-lift-ink'
    : s.icon === 'stairs'
      ? 'bg-stop-soft text-stop-ink'
      : s.icon === 'destination'
        ? 'bg-go text-white'
        : s.grade_pct >= 5
          ? 'bg-warn-soft text-warn-ink'
          : 'bg-black/[0.05] text-ink-2';

interface Props {
  steps: RouteStep[];
  onFocusStep: (s: RouteStep) => void;
}

export function Directions({ steps, onFocusStep }: Props) {
  const [open, setOpen] = useState(true);
  if (!steps.length) return null;
  return (
    <section aria-labelledby="dir-h">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between px-1 py-1">
        <h3 id="dir-h" className="eyebrow">
          Directions · {steps.length - 1} steps
        </h3>
        <ChevronDown className={cx('h-4 w-4 text-ink-4 transition-transform duration-300', open && 'rotate-180')} />
      </button>
      {open && (
        <ol className="mt-1.5 space-y-0.5 animate-fade">
          {steps.map((s, i) => (
            <li key={i}>
              <button
                onClick={() => onFocusStep(s)}
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
