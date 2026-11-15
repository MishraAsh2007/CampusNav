import { useState } from 'react';
import {
  Accessibility,
  ArrowRightLeft,
  Bath,
  ChevronDown,
  DoorOpen,
  Footprints,
  Grip,
  Mountain,
  Sparkles,
  Umbrella,
  Waves
} from 'lucide-react';
import type { MobilityProfile, UserPreferences } from '../types';
import { applyProfile, needsSummary, PROFILES, profileLabel } from '../data/profiles';
import { parseNaturalLanguageQuery } from '../services/geminiService';
import { cx, Switch } from './ui';

interface Props {
  prefs: UserPreferences;
  onChange: (p: UserPreferences) => void;
  open: boolean;
  onToggle: () => void;
}

function isEdited(p: UserPreferences): boolean {
  const base = PROFILES.find((x) => x.id === p.mobility_preset);
  if (!base) return false;
  return Object.entries(base.prefs).some(([k, v]) => p[k as keyof UserPreferences] !== v);
}

export function NeedsMenu({ prefs, onChange, open, onToggle }: Props) {
  const [text, setText] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const set = (patch: Partial<UserPreferences>) => onChange({ ...prefs, ...patch });
  const chips = needsSummary(prefs);
  const stairsBlocked = prefs.wheelchair_required || prefs.no_stairs;

  const applyText = () => {
    const parsed = parseNaturalLanguageQuery(text);
    if (!parsed) {
      setNotice('Try words like "crutches", "power chair", "icy", or "no hills".');
      return;
    }
    const base = parsed.mobility_preset ? applyProfile(prefs, parsed.mobility_preset) : prefs;
    const next = { ...base, ...parsed };
    onChange(next);
    setNotice(`Set to ${profileLabel(next.mobility_preset).toLowerCase()} · ${needsSummary(next).slice(1).join(' · ')}`);
    setText('');
  };

  return (
    <div className="rounded-3xl bg-black/[0.03]">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls="needs-panel"
        className="flex w-full items-center gap-3 rounded-3xl px-3.5 py-3 text-left transition hover:bg-black/[0.02]"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-white text-ink shadow-ring">
          <Accessibility className="h-[18px] w-[18px]" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] font-medium text-ink">
            {profileLabel(prefs.mobility_preset)}
            {isEdited(prefs) && <span className="font-normal text-ink-3"> · edited</span>}
          </span>
          <span className="block text-[12px] text-ink-3">{chips.filter((c) => c !== 'Wheelchair').join(' · ')}</span>
        </span>
        <ChevronDown className={cx('h-4 w-4 text-ink-3 transition-transform duration-300 ease-soft', open && 'rotate-180')} />
      </button>

      {open && (
        <div id="needs-panel" className="space-y-4 px-3.5 pb-4 animate-rise">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              applyText();
            }}
            className="flex items-center gap-2 rounded-2xl bg-white px-3 py-1.5 shadow-ring"
          >
            <Sparkles className="h-4 w-4 shrink-0 text-lift" />
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Describe it: “sprained ankle, it’s icy”"
              aria-label="Describe your mobility needs"
              className="min-w-0 flex-1 bg-transparent py-1.5 text-[13px] outline-none placeholder:text-ink-4"
            />
            <button type="submit" className="btn-quiet !px-3 !py-1 text-[12px]" disabled={!text.trim()}>
              Apply
            </button>
          </form>
          {notice && <p className="-mt-2 px-1 text-[12px] text-go-ink animate-fade">{notice}</p>}

          <fieldset>
            <legend className="eyebrow mb-2 px-1">I get around with</legend>
            <div className="grid grid-cols-2 gap-1.5" role="radiogroup">
              {PROFILES.map((p) => {
                const on = prefs.mobility_preset === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    onClick={() => onChange(applyProfile(prefs, p.id as MobilityProfile))}
                    className={cx(
                      'rounded-2xl px-3 py-2.5 text-left transition duration-200 ease-soft',
                      on ? 'bg-ink text-white shadow-float' : 'bg-white text-ink shadow-ring hover:shadow-float'
                    )}
                  >
                    <span className="block text-[13px] font-medium leading-tight">{p.label}</span>
                    <span className={cx('mt-0.5 block text-[11px] leading-snug', on ? 'text-white/70' : 'text-ink-3')}>{p.hint}</span>
                  </button>
                );
              })}
            </div>
          </fieldset>

          <div className="rounded-2xl bg-white px-3.5 py-3 shadow-ring">
            <div className="flex items-baseline justify-between">
              <label htmlFor="max-slope" className="text-[14px] text-ink">
                Steepest slope I can manage
              </label>
              <span className="text-[15px] font-semibold tabular-nums text-ink">{prefs.max_grade_pct}%</span>
            </div>
            <input
              id="max-slope"
              type="range"
              min={2}
              max={12}
              step={0.5}
              value={prefs.max_grade_pct}
              onChange={(e) => set({ max_grade_pct: parseFloat(e.target.value) })}
              className="mt-2 w-full accent-ink"
              aria-describedby="slope-help"
            />
            <div id="slope-help" className="mt-1 flex justify-between text-[11px] text-ink-3">
              <span>2% flat</span>
              <span className={cx(prefs.max_grade_pct <= 5 && 'text-go-ink font-medium')}>5% ADA walkway</span>
              <span className={cx(prefs.max_grade_pct > 8.33 && 'text-stop-ink font-medium')}>8.3% ramp max</span>
            </div>
          </div>

          <div className="rounded-2xl bg-white px-3.5 py-1 shadow-ring divide-y divide-hairline">
            <Switch
              icon={<Accessibility className="h-4 w-4" />}
              label="Wheelchair required"
              hint="Blocks stairs and raised kerbs; slope limit is strict"
              checked={prefs.wheelchair_required}
              onChange={(v) => set({ wheelchair_required: v, no_stairs: v ? true : prefs.no_stairs })}
            />
            <Switch
              icon={<Footprints className="h-4 w-4" />}
              label="Avoid all stairs"
              checked={stairsBlocked}
              disabled={prefs.wheelchair_required}
              onChange={(v) => set({ no_stairs: v })}
            />
            <Switch
              icon={<Grip className="h-4 w-4" />}
              label="Handrails on any stairs"
              hint="From OpenStreetMap handrail tags"
              checked={prefs.handrails_required}
              disabled={stairsBlocked}
              onChange={(v) => set({ handrails_required: v })}
            />
            <Switch
              icon={<Waves className="h-4 w-4" />}
              label="Smooth surfaces"
              hint="Avoid brick pavers, gravel and dirt"
              checked={prefs.avoid_rough_surfaces}
              onChange={(v) => set({ avoid_rough_surfaces: v })}
            />
            <Switch
              icon={<Umbrella className="h-4 w-4" />}
              label="Prefer covered paths"
              hint="Useful in rain, snow and ice"
              checked={prefs.prefer_indoor}
              onChange={(v) => set({ prefer_indoor: v })}
            />
            <Switch
              icon={<DoorOpen className="h-4 w-4" />}
              label="Require automatic doors"
              hint="Only entrances with a documented opener; unknown door types are excluded"
              checked={prefs.need_automatic_door}
              onChange={(v) => set({ need_automatic_door: v })}
            />
            <Switch
              icon={<Bath className="h-4 w-4" />}
              label="Accessible restroom at destination"
              checked={prefs.need_accessible_restroom}
              onChange={(v) => set({ need_accessible_restroom: v })}
            />
            <Switch
              icon={<ArrowRightLeft className="h-4 w-4" />}
              label="Fewer street crossings"
              hint="For low vision and guide dogs"
              checked={prefs.minimize_crossings}
              onChange={(v) => set({ minimize_crossings: v })}
            />
          </div>
          <p className="flex items-start gap-1.5 px-1 text-[11px] leading-snug text-ink-3">
            <Mountain className="mt-px h-3.5 w-3.5 shrink-0" />
            Slopes come from USGS 1 m lidar; stairs, handrails and surfaces from OpenStreetMap.
          </p>
        </div>
      )}
    </div>
  );
}
