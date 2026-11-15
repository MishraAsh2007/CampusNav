import { useEffect, useState } from 'react';
import { getExternalReports, getExternalStatus, getNoticeStatus, getUpcomingNotices, type SourceStatus } from '../services/api';
import type { Closure } from '../types';
export function SourcePanel() {
  const [status, setStatus] = useState<SourceStatus | null>(null);
  const [notices, setNotices] = useState<Closure[]>([]);
  const [reports, setReports] = useState<Awaited<ReturnType<typeof getExternalReports>>>([]);
  const [error, setError] = useState('');
  const [external, setExternal] = useState<Awaited<ReturnType<typeof getExternalStatus>> | null>(null);
  useEffect(() => {
    let mounted = true;
    const refresh = async () => {
      const [s, n, r, x] = await Promise.allSettled([getNoticeStatus(), getUpcomingNotices(), getExternalReports(), getExternalStatus()]);
      if (!mounted) return;
      if (s.status === 'fulfilled') setStatus(s.value);
      setError([s.status === 'rejected' ? 'Source status unavailable.' : '', n.status === 'rejected' ? 'Upcoming notices could not refresh.' : '', r.status === 'rejected' ? 'Public reports could not refresh.' : ''].filter(Boolean).join(' '));
      if (n.status === 'fulfilled') setNotices(n.value.filter(x => x.scheduled));
      if (r.status === 'fulfilled') setReports(r.value);
      if (x.status === 'fulfilled') setExternal(x.value);
    };
    void refresh(); const timer = setInterval(refresh, 60000);
    return () => {mounted = false; clearInterval(timer);};
  }, []);
  return <section className="space-y-2 rounded-2xl bg-black/[0.03] p-3 text-[12px]" aria-label="Sources and notices">
    <h3 className="eyebrow">Sources and upcoming notices</h3>
    {error && <p role="alert">{error}</p>}
    {Object.entries(status?.source_status ?? {}).map(([id, s]) => <p key={id}>UMass maintenance: <strong>{s.mode === 'live' ? 'last refresh fetched live' : s.mode.replace('_', ' ')}</strong>. Observed {new Date(s.observed_at).toLocaleString()}.</p>)}
    {status?.stale && <p className="text-warn-ink">Notice data needs attention: {status.status}. Missing coverage is not an all-clear.</p>}
    {!!status?.counts?.review && <p>{status.counts.review} official notice(s) need review before they can be placed on the routing graph.</p>}
      <p>Building access: UMass map (August 2022) + OpenStreetMap entrances. Indoor coverage is limited to sourced pilots; current door and elevator access is unverified.</p>
    {notices.map(n => <p key={n.id}><strong>{n.title}</strong><br />Starts {new Date(n.start_time).toLocaleString()}{n.end_time ? `; ends ${new Date(n.end_time).toLocaleString()}` : ''}. Upcoming; does not block routes yet.</p>)}
    <details><summary className="cursor-pointer">Public-source reports awaiting review ({reports.length})</summary>
      {Object.entries(external?.sources ?? {}).map(([id, s]) => <p className="mt-2 text-ink-3" key={id}>{id}: {s.state.replace(/_/g, ' ')}{s.state !== 'live' && s.message ? ` — ${s.message}` : ''}.</p>)}
      {reports.map(r => <p className="mt-2" key={r.id}><a className="underline" href={r.url} target="_blank" rel="noreferrer">{r.title}</a> — {r.source_name}. {r.published_at ? `Posted ${new Date(r.published_at).toLocaleString()}.` : 'Posting time unknown.'} Not used as a routing closure.</p>)}
    </details>
  </section>;
}
