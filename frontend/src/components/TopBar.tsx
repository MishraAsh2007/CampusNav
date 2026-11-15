import { useRef, useState } from 'react';
import { AlertTriangle, Contrast, Info, Sparkles, Type } from 'lucide-react';
import { cx, useClickOutside } from './ui';
import { formatFreshness } from '../data/mockClosures';
import { DEMO_MODE } from '../services/api';

interface Props {
  activeIssues: number;
  highAlerts: number;
  live: boolean;
  lastSync: number | null;
  onReport: () => void;
  onAbout: () => void;
  onJudge: () => void;
  judgeOpen: boolean;
  highContrast: boolean;
  onHighContrast: () => void;
  largeText: boolean;
  onLargeText: () => void;
}

export function TopBar(p: Props) {
  const [menu, setMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useClickOutside(ref, () => setMenu(false), menu);

  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-30 flex items-start justify-between gap-2 p-3 sm:p-4">
      <button
        onClick={p.onAbout}
        className="glass pointer-events-auto flex items-center gap-2.5 rounded-full py-1.5 pl-1.5 pr-4 transition hover:shadow-lift"
        aria-label="About UMassNav"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand text-white">
          <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <circle cx="12" cy="4.5" r="1.8" />
            <path d="M12 8v5h4.5l2 5" />
            <path d="M8.5 11.2a5.5 5.5 0 1 0 7.3 7.8" />
          </svg>
        </span>
        <span className="text-left">
          <span className="block font-display text-[15px] font-semibold leading-tight tracking-tight text-ink">UMassNav</span>
          <span className="hidden text-[11px] leading-tight text-ink-3 sm:block">Routes that know what's broken today</span>
        </span>
      </button>

      <div className="pointer-events-auto flex items-center gap-1.5">
        <div
          className="glass hidden items-center gap-2 rounded-full px-3.5 py-2 text-[12px] text-ink-2 md:flex"
          title={p.live ? 'Connected to the UMassNav backend' : DEMO_MODE
            ? 'Backend unreachable: using cached reports and the in-browser router' : 'Official closure data is stale or unavailable'}
        >
          <span className="relative flex h-2 w-2">
            {p.live && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-go opacity-60" />}
            <span className={cx('relative inline-flex h-2 w-2 rounded-full', p.live ? 'bg-go' : 'bg-warn')} />
          </span>
          <span className="tabular-nums">
            {p.activeIssues} issue{p.activeIssues === 1 ? '' : 's'} today
            {p.lastSync ? ` · ${formatFreshness(new Date(p.lastSync).toISOString())}` : ''}
          </span>
          {p.highAlerts > 0 && (
            <span className="rounded-full bg-stop px-2 py-0.5 text-[11px] font-semibold text-white" title="Reported by both UMass Facilities and students">
              {p.highAlerts} high alert{p.highAlerts === 1 ? '' : 's'}
            </span>
          )}
        </div>

        <div ref={ref} className="relative">
          <button
            onClick={() => setMenu((m) => !m)}
            className="glass btn h-10 w-10 !p-0 text-ink"
            aria-label="Display options"
            aria-expanded={menu}
          >
            <Type className="h-4 w-4" />
          </button>
          {menu && (
            <div className="absolute right-0 top-12 w-56 rounded-3xl bg-white p-1.5 shadow-lift animate-pop" role="menu">
              <button role="menuitemcheckbox" aria-checked={p.largeText} onClick={p.onLargeText} className="flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-[14px] hover:bg-black/[0.04]">
                <Type className="h-4 w-4 text-ink-3" />
                <span className="flex-1">Larger text</span>
                {p.largeText && <span className="text-go">✓</span>}
              </button>
              <button role="menuitemcheckbox" aria-checked={p.highContrast} onClick={p.onHighContrast} className="flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-[14px] hover:bg-black/[0.04]">
                <Contrast className="h-4 w-4 text-ink-3" />
                <span className="flex-1">High contrast</span>
                {p.highContrast && <span className="text-go">✓</span>}
              </button>
              <button role="menuitem" onClick={p.onAbout} className="flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-[14px] hover:bg-black/[0.04]">
                <Info className="h-4 w-4 text-ink-3" />
                <span className="flex-1">About and sources</span>
              </button>
            </div>
          )}
        </div>

        <button
          onClick={p.onJudge}
          className={cx('glass btn h-10 !px-3 text-ink', p.judgeOpen && '!bg-ink !text-white')}
          aria-pressed={p.judgeOpen}
          title="Judge mode (J)"
        >
          <Sparkles className="h-4 w-4" />
          <span className="hidden sm:inline">Demo</span>
        </button>

        <button onClick={p.onReport} className="btn h-10 bg-stop !px-4 text-white shadow-float hover:brightness-105">
          <AlertTriangle className="h-4 w-4" />
          <span>Report</span>
        </button>
      </div>
    </header>
  );
}
