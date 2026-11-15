import { ReactNode, RefObject, useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(' ');
}

export function useClickOutside(ref: RefObject<HTMLElement>, onOutside: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOutside();
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onOutside();
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [ref, onOutside, active]);
}

export function Switch({
  checked,
  onChange,
  label,
  hint,
  icon,
  disabled
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
  icon?: ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className={cx('flex items-center gap-3 py-2.5 cursor-pointer select-none', disabled && 'opacity-50 cursor-not-allowed')}>
      {icon && <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-black/[0.04] text-ink-2">{icon}</span>}
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] text-ink">{label}</span>
        {hint && <span className="block text-[12px] leading-snug text-ink-3">{hint}</span>}
      </span>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx(
          'relative h-[26px] w-[44px] shrink-0 rounded-full transition-colors duration-300 ease-soft',
          checked ? 'bg-go' : 'bg-black/15'
        )}
      >
        <span
          className={cx(
            'absolute top-[2px] left-[2px] h-[22px] w-[22px] rounded-full bg-white shadow transition-transform duration-300 ease-soft',
            checked && 'translate-x-[18px]'
          )}
        />
      </button>
    </label>
  );
}

/** Side sheet on desktop, bottom sheet on mobile. */
export function Sheet({
  open,
  onClose,
  title,
  eyebrow,
  children,
  side = 'right',
  footer,
  labelledBy
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  eyebrow?: ReactNode;
  children: ReactNode;
  side?: 'right' | 'center';
  footer?: ReactNode;
  labelledBy?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    ref.current?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-stretch" role="presentation">
      <div className="absolute inset-0 bg-black/20 backdrop-blur-[2px] animate-fade" onClick={onClose} />
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy ?? titleId}
        className={cx(
          'relative flex w-full flex-col bg-white shadow-lift outline-none animate-rise',
          'max-h-[88vh] rounded-t-4xl sm:max-h-none',
          side === 'right'
            ? 'sm:absolute sm:right-4 sm:top-4 sm:bottom-4 sm:w-[420px] sm:rounded-4xl'
            : 'sm:m-auto sm:h-auto sm:max-h-[86vh] sm:w-[480px] sm:rounded-4xl'
        )}
      >
        <div className="flex items-start gap-3 px-6 pt-6 pb-3">
          <div className="min-w-0 flex-1">
            {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
            <h2 id={titleId} className="font-display text-[22px] font-semibold leading-tight tracking-tight text-ink">
              {title}
            </h2>
          </div>
          <button onClick={onClose} className="btn-quiet h-8 w-8 !p-0" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="scroll-soft flex-1 overflow-y-auto px-6 pb-6">{children}</div>
        {footer && <div className="border-t border-hairline px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: 'go' | 'stop' | 'warn' | 'lift' }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] text-ink-3">{label}</div>
      <div
        className={cx(
          'text-[14px] font-semibold tabular-nums',
          tone === 'go' && 'text-go-ink',
          tone === 'stop' && 'text-stop-ink',
          tone === 'warn' && 'text-warn-ink',
          tone === 'lift' && 'text-lift-ink',
          !tone && 'text-ink'
        )}
      >
        {value}
      </div>
    </div>
  );
}
