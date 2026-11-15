import {useId, useRef, useState, type PointerEvent, type ReactNode} from 'react';
import {ArrowRight, ChevronDown} from 'lucide-react';
import {cx} from './ui';

interface Props {
  children: ReactNode;
  hasRoute: boolean;
  picking: boolean;
  title: string;
  detail: string;
  onNext?: () => void;
  nextLabel?: string;
}

/** The desktop sidebar becomes a draggable, collapsible sheet on phones. */
export function MobileTripSheet({children, hasRoute, picking, title, detail, onNext, nextLabel = 'Next'}: Props) {
  const contentId = useId();
  const [collapsed, setCollapsed] = useState(false);
  const [dragHeight, setDragHeight] = useState<number | null>(null);
  const sheet = useRef<HTMLElement>(null);
  const gesture = useRef<{id: number; startY: number; height: number; delta: number} | null>(null);
  const suppressClick = useRef(false);
  const startDrag = (event: PointerEvent<HTMLButtonElement>) => {
    if (gesture.current || (event.pointerType === 'mouse' && event.button !== 0)) return;
    const height = sheet.current?.getBoundingClientRect().height;
    if (!height) return;
    gesture.current = {id: event.pointerId, startY: event.clientY, height, delta: 0};
    suppressClick.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveDrag = (event: PointerEvent<HTMLButtonElement>) => {
    const current = gesture.current;
    if (!current || current.id !== event.pointerId) return;
    current.delta = event.clientY - current.startY;
    if (Math.abs(current.delta) < 6) return;
    suppressClick.current = true;
    const maximum = window.innerHeight * (picking ? .24 : hasRoute ? .52 : .58);
    setDragHeight(Math.max(112, Math.min(maximum, current.height - current.delta)));
  };
  const endDrag = (event: PointerEvent<HTMLButtonElement>) => {
    const current = gesture.current;
    if (!current || current.id !== event.pointerId) return;
    if (event.type === 'pointerup' && Math.abs(current.delta) > 28) setCollapsed(current.delta > 0);
    gesture.current = null;
    setDragHeight(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  return <aside ref={sheet} aria-label="Trip planner" style={{height: dragHeight ?? undefined}}
    className={cx('glass trip-sheet fixed z-20 flex flex-col overflow-hidden inset-x-0 bottom-0 rounded-t-4xl',
      picking ? 'max-h-[24dvh]' : hasRoute ? 'max-h-[52dvh]' : 'max-h-[58dvh]',
      'lg:inset-x-auto lg:bottom-4 lg:left-4 lg:top-[84px] lg:max-h-none lg:w-[400px] lg:rounded-4xl',
      collapsed && 'is-collapsed', dragHeight !== null && 'is-dragging')}>
    <button type="button" className="trip-sheet-handle" aria-expanded={!collapsed} aria-controls={contentId}
      aria-label={collapsed ? 'Expand trip directions' : 'Collapse trip directions to show more map'}
      onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag}
      onPointerCancel={endDrag} onLostPointerCapture={endDrag}
      onClick={() => {if (!suppressClick.current) setCollapsed(value => !value); suppressClick.current = false;}}>
      <span className="trip-sheet-grip" aria-hidden="true" />
      <span>{collapsed ? 'Show directions' : 'More map'}<ChevronDown size={16} className={collapsed ? 'rotate-180' : ''} /></span>
    </button>
    <div className="trip-sheet-summary">
      <button type="button" className="trip-sheet-summary-text" onClick={() => setCollapsed(false)} aria-label="Expand trip details">
        <span>{title}</span><strong>{detail}</strong>
      </button>
      {onNext && <button type="button" className="guide-next" aria-label={nextLabel === 'Next' ? 'Next step' : nextLabel} onClick={onNext}>{nextLabel}<ArrowRight size={18} /></button>}
    </div>
    <div id={contentId} className="trip-sheet-expanded">{children}</div>
  </aside>;
}
