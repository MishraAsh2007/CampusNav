import { Sheet } from './ui';
import type { Health } from '../services/api';
export function AboutSheet({open, onClose, graphMeta, provider}: {open: boolean; onClose: () => void; graphMeta: Health | null; provider: 'google' | 'osm'}) {
  return <Sheet open={open} onClose={onClose} side="center" eyebrow="About and sources" title="Campus routes with current notice data">
    <div className="space-y-4 text-sm">
      <p>Choose buildings or map pins. The Python routing engine compares outdoor routes with your stairs, slope, and entrance requirements.</p>
      <p>{graphMeta?.nodes.toLocaleString()} mapped points and {graphMeta?.edges.toLocaleString()} directed path segments from OpenStreetMap. Grades use terrain elevation estimates from Open Topo Data NED 10 m, not surveyed sidewalk slopes.</p>
      <p>Building footprints, access details, and elevator locations come from the UMass accessibility map (labeled August 2022). OpenStreetMap adds entrance positions. Unknown access is kept unknown; indoor floor and elevator connections are not yet mapped.</p>
      <p>The authenticated maintenance scraper refreshes notices separately. The app reads its saved results and sends active mapped closures with each route request. Public-source complaints remain in review.</p>
      <p>Basemap: {provider === 'google' ? 'Google Maps' : 'OpenStreetMap'}. Community reports are stored in the local backend and expire after 24 hours unless reconfirmed.</p>
      <a className="block underline" href="https://www.umass.edu/accessibility/accommodations-and-access" target="_blank" rel="noreferrer">UMass accessibility sources</a>
      <a className="block underline" href="/backend">Backend diagnostics</a>
    </div>
  </Sheet>;
}
