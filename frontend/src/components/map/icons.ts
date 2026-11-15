/** Tiny inline SVG icons for map markers (Lucide-style strokes). */
const svg = (inner: string) => `<svg class="au-svg" viewBox="0 0 24 24" aria-hidden="true">${inner}</svg>`;

export const ICONS = {
  elevator: svg('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="m9 9 3-3 3 3"/><path d="m9 15 3 3 3-3"/>'),
  stairs: svg('<path d="M4 20h4v-4h4v-4h4V8h4"/>'),
  alert: svg('<path d="M12 8v5"/><path d="M12 16.5v.01"/><path d="M10.3 3.9 2.6 17.3A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.7L13.7 3.9a2 2 0 0 0-3.4 0Z"/>'),
  door: svg('<path d="M13 4h3a2 2 0 0 1 2 2v14"/><path d="M2 20h3"/><path d="M13 20h9"/><path d="M10 12v.01"/><path d="M13 4.6v15.8a.6.6 0 0 1-.8.6L5 19V5.6a1 1 0 0 1 .7-1L12.2 3a.6.6 0 0 1 .8.6Z"/>'),
  cone: svg('<path d="M9.3 6.2 12 2l2.7 4.2"/><path d="M7 11h10"/><path d="M5.5 16h13"/><path d="M3 21h18L14.7 6.2H9.3Z"/>'),
  path: svg('<path d="M3 17c3-2 5-2 8 0s5 2 8 0"/><path d="M3 11c3-2 5-2 8 0s5 2 8 0"/>'),
  check: svg('<path d="m5 12 5 5L20 7"/>'),
  bus: svg('<rect x="4" y="3" width="16" height="15" rx="3"/><path d="M4 11h16"/><path d="M8 21v-3"/><path d="M16 21v-3"/><path d="M8 7h8"/>'),
  shield: svg('<path d="M12 3 5 6v5c0 4.5 3 8.2 7 10 4-1.8 7-5.5 7-10V6Z"/><path d="m9 12 2 2 4-4"/>'),
  slope: svg('<path d="M3 20 21 6"/><path d="M3 20h18"/>')
};

export function closureIcon(type: string): string {
  switch (type) {
    case 'elevator':
      return ICONS.elevator;
    case 'automatic_door':
      return ICONS.door;
    case 'construction':
      return ICONS.cone;
    case 'ramp':
      return ICONS.slope;
    default:
      return ICONS.path;
  }
}
