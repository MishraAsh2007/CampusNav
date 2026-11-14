import { Play, RotateCcw, Wrench, X, Zap } from 'lucide-react';
import { cx } from './ui';

export interface DemoLogEntry {
  t: number;
  label: string;
  detail: string;
  tone: 'net' | 'ok' | 'route' | 'warn';
}

interface Props {
  open: boolean;
  onClose: () => void;
  elevatorBroken: boolean;
  busy: boolean;
  log: DemoLogEntry[];
  onLoadTrip: () => void;
  onBreak: () => void;
  onFix: () => void;
  onReset: () => void;
  live: boolean;
}

export function JudgePanel({ open, onClose, elevatorBroken, busy, log, onLoadTrip, onBreak, onFix, onReset, live }: Props) {
  if (!open) return null;
  return (
    <div
      className="fixed bottom-4 left-1/2 z-40 w-[min(560px,calc(100vw-2rem))] -translate-x-1/2 rounded-4xl bg-ink/95 p-4 text-white shadow-lift backdrop-blur-xl animate-rise lg:left-auto lg:right-4 lg:translate-x-0"
      role="dialog"
      aria-label="Judge demo controls"
    >
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.1em] text-white/50">Judge mode</div>
          <div className="text-[15px] font-medium">Break an elevator, watch the route move</div>
        </div>
        <button onClick={onClose} className="btn h-8 w-8 !p-0 bg-white/10 hover:bg-white/20" aria-label="Close judge mode">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <button onClick={onLoadTrip} className="flex flex-col items-start gap-1 rounded-2xl bg-white/10 p-3 text-left transition hover:bg-white/15">
          <Play className="h-4 w-4 text-white/70" />
          <span className="text-[13px] font-medium">1 · Load trip</span>
          <span className="text-[11px] leading-snug text-white/55">Student Union to CC upper terrace, wheelchair</span>
        </button>
        <button
          onClick={onBreak}
          disabled={busy || elevatorBroken}
          className={cx(
            'flex flex-col items-start gap-1 rounded-2xl p-3 text-left transition disabled:opacity-40',
            'bg-stop hover:brightness-110'
          )}
        >
          <Zap className="h-4 w-4" />
          <span className="text-[13px] font-medium">2 · Break elevator</span>
          <span className="text-[11px] leading-snug text-white/80">POSTs a fake student report</span>
        </button>
        <button
          onClick={onFix}
          disabled={busy || !elevatorBroken}
          className="flex flex-col items-start gap-1 rounded-2xl bg-go p-3 text-left transition hover:brightness-110 disabled:opacity-40"
        >
          <Wrench className="h-4 w-4" />
          <span className="text-[13px] font-medium">3 · Fix it</span>
          <span className="text-[11px] leading-snug text-white/80">Report it working again</span>
        </button>
      </div>

      {log.length > 0 && (
        <ol className="mt-3 space-y-1 rounded-2xl bg-black/30 p-3 font-mono text-[11.5px] leading-relaxed" aria-live="polite">
          {log.slice(-5).map((e, i) => (
            <li key={`${e.t}-${i}`} className="flex gap-2 animate-fade">
              <span
                className={cx(
                  'shrink-0',
                  e.tone === 'net' && 'text-sky-300',
                  e.tone === 'ok' && 'text-emerald-300',
                  e.tone === 'route' && 'text-violet-300',
                  e.tone === 'warn' && 'text-amber-300'
                )}
              >
                {e.label}
              </span>
              <span className="text-white/70">{e.detail}</span>
            </li>
          ))}
        </ol>
      )}

      <div className="mt-3 flex items-center justify-between text-[11px] text-white/50">
        <span>{live ? 'Backend: live (localhost)' : 'Backend offline: in-browser store and router'} · no page refresh</span>
        <button onClick={onReset} className="flex items-center gap-1 hover:text-white">
          <RotateCcw className="h-3 w-3" /> Reset
        </button>
      </div>
    </div>
  );
}
