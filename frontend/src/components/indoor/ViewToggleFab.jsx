/**
 * Round floating button that switches between the 2D floor plan and the 3D view.
 * Shows the view you would switch TO: "3D" while in 2D, "2D" while in 3D.
 */
export default function ViewToggleFab({ to, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={to === '3d' ? 'Switch to 3D view' : 'Switch to 2D map'}
      title={to === '3d' ? 'Switch to 3D view' : 'Switch to 2D map'}
      className="flex h-14 w-14 items-center justify-center rounded-full bg-slate-950 text-[17px] font-bold tracking-tight text-white shadow-2xl ring-4 ring-white/80 transition hover:bg-slate-800 active:scale-95"
    >
      {to === '3d' ? '3D' : '2D'}
    </button>
  );
}
