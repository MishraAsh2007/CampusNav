import type { UserPreferences } from '../types';
export function NeedsMenu({prefs, onChange, open, onToggle}: {prefs: UserPreferences; onChange: (p: UserPreferences) => void; open: boolean; onToggle: () => void}) {
  const set = (patch: Partial<UserPreferences>) => onChange({...prefs, ...patch});
  return <section className="rounded-2xl bg-black/[0.03] p-3">
    <button className="w-full text-left text-sm font-medium" aria-expanded={open} onClick={onToggle}>Route preferences · {prefs.no_stairs || prefs.wheelchair_required ? 'avoid stairs' : 'stairs allowed'} · max {prefs.max_grade_pct}%</button>
    {open && <div className="mt-3 space-y-4 text-sm">
      <label className="flex justify-between gap-3">Avoid stairs and paths tagged wheelchair-inaccessible
        <input type="checkbox" checked={prefs.no_stairs || prefs.wheelchair_required} onChange={e => set({no_stairs: e.target.checked, wheelchair_required: e.target.checked})} />
      </label>
      <label className="block" htmlFor="max-slope">Maximum estimated slope: {prefs.max_grade_pct}%</label>
      <input id="max-slope" className="w-full" type="range" min="2" max="12" step="0.5" value={prefs.max_grade_pct} onChange={e => set({max_grade_pct: Number(e.target.value)})} />
      <label className="flex justify-between gap-3">Require a source-documented powered entrance
        <input type="checkbox" checked={prefs.need_automatic_door} onChange={e => set({need_automatic_door: e.target.checked})} />
      </label>
      <p className="text-xs text-ink-3">Door type and step-free access may be unknown. Requiring a powered door can rule out buildings with incomplete entrance records. Slopes are terrain estimates.</p>
    </div>}
  </section>;
}
