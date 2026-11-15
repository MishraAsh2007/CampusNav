import { createContext, ReactNode, useContext, useEffect, useState } from 'react';
import { APIProvider } from '@vis.gl/react-google-maps';
import { GOOGLE_MAPS_KEY } from './config';

interface MapProviderState {
  provider: 'google' | 'osm';
  /** Why Google is not in use, for a quiet notice. */
  reason?: string;
}

const Ctx = createContext<MapProviderState>({ provider: 'osm' });

export function useMapProvider() {
  return useContext(Ctx);
}

/** Wraps the app in Google's API loader when a key exists, and falls back to OSM if Google rejects it. */
export function MapsProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<MapProviderState>(
    GOOGLE_MAPS_KEY ? { provider: 'google' } : { provider: 'osm', reason: 'No Google Maps key configured' }
  );

  useEffect(() => {
    if (!GOOGLE_MAPS_KEY) {
      console.info('[CampusNav] Set VITE_GOOGLE_MAPS_API_KEY in .env to use the Google basemap. Using OpenStreetMap.');
      return;
    }
    // Google calls this global when the key is invalid or the referrer is not allowed
    window.gm_authFailure = () => setState({ provider: 'osm', reason: 'Google Maps rejected the API key' });
    return () => {
      window.gm_authFailure = undefined;
    };
  }, []);

  if (!GOOGLE_MAPS_KEY) return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
  return (
    <APIProvider
      apiKey={GOOGLE_MAPS_KEY}
      libraries={['marker', 'places']}
      onError={() => setState({ provider: 'osm', reason: 'Google Maps failed to load' })}
    >
      <Ctx.Provider value={state}>{children}</Ctx.Provider>
    </APIProvider>
  );
}
