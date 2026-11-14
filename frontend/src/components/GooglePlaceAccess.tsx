import { useEffect, useState } from 'react';
import { useMapsLibrary } from '@vis.gl/react-google-maps';
import { ExternalLink } from 'lucide-react';
import type { Building } from '../types';
import { cx } from './ui';

interface Result {
  entrance: boolean | null;
  restroom: boolean | null;
  parking: boolean | null;
  seating: boolean | null;
  url?: string | null;
}

const cache = new Map<string, Result | 'none'>();

/**
 * Pulls Google Maps' own wheelchair data (Places API) for a building, so students see both
 * our live outage data and what Google already knows. Only rendered when a Google key is configured.
 */
export function GooglePlaceAccess({ building }: { building: Building }) {
  const places = useMapsLibrary('places');
  const key = building.google_place_query ?? `${building.name}, UMass Amherst`;
  const [res, setRes] = useState<Result | 'none' | null>(cache.get(key) ?? null);

  useEffect(() => {
    if (!places || cache.has(key)) {
      if (cache.has(key)) setRes(cache.get(key)!);
      return;
    }
    let live = true;
    places.Place.searchByText({
      textQuery: key,
      fields: ['displayName', 'accessibilityOptions', 'googleMapsURI'],
      locationBias: { lat: building.location.lat, lng: building.location.lng },
      maxResultCount: 1
    })
      .then(({ places: found }: { places: google.maps.places.Place[] }) => {
        const p = found[0];
        const a = p?.accessibilityOptions;
        const r: Result | 'none' = a
          ? {
              entrance: a.hasWheelchairAccessibleEntrance,
              restroom: a.hasWheelchairAccessibleRestroom,
              parking: a.hasWheelchairAccessibleParking,
              seating: a.hasWheelchairAccessibleSeating,
              url: p.googleMapsURI
            }
          : 'none';
        cache.set(key, r);
        if (live) setRes(r);
      })
      .catch(() => {
        cache.set(key, 'none');
        if (live) setRes('none');
      });
    return () => {
      live = false;
    };
  }, [places, key, building.location.lat, building.location.lng]);

  if (!res || res === 'none') return null;
  const items: [string, boolean | null][] = [
    ['Entrance', res.entrance],
    ['Restroom', res.restroom],
    ['Parking', res.parking],
    ['Seating', res.seating]
  ];
  return (
    <section className="rounded-2xl bg-black/[0.03] p-3.5">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="eyebrow">Google Maps says</h3>
        {res.url && (
          <a href={res.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[12px] text-sky-ink">
            Open <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map(([label, v]) => (
          <span key={label} className={cx('chip', v === true ? 'bg-go-soft text-go-ink' : v === false ? 'bg-stop-soft text-stop-ink' : 'bg-black/[0.05] text-ink-3')}>
            {v === true ? '✓' : v === false ? '✕' : '?'} {label}
          </span>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-ink-4">Google lists static features. It does not know when a door or elevator breaks.</p>
    </section>
  );
}
