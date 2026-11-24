import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  ApiError, discoverLive, getLiveStatus,
  type LiveParams, type LiveResult, type LiveStatus,
} from '../lib/api';

export type LivePrefill = { query: string; cuisine: string; sequence: number };

type Props = { prefill: LivePrefill | null };

/** Live leads never get inserted into the catalog or inherit its provenance. */
export function LiveRestaurantDiscovery({ prefill }: Props) {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [query, setQuery] = useState('');
  const [cuisine, setCuisine] = useState('');
  const [city, setCity] = useState('');
  const [region, setRegion] = useState('');
  const [country, setCountry] = useState('');
  const [scope, setScope] = useState<'city' | 'nearby'>('city');
  const [nearbyText, setNearbyText] = useState('');
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState<LiveResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getLiveStatus(controller.signal).then(setStatus).catch(() => {
      if (!controller.signal.aborted) setStatus({
        enabled: false, consent_required: true, limitations: 'Live search is not available.',
      });
    });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (prefill) {
      setQuery(prefill.query);
      setCuisine(prefill.cuisine);
      setResult(null);
    }
  }, [prefill]);
  useEffect(() => () => controllerRef.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!status?.enabled || busy || !consent || !city.trim() || !cuisine.trim()) return;
    const nearby = nearbyText.split(',').map(value => value.trim()).filter(Boolean);
    if (scope === 'nearby' && (!nearby.length || nearby.length > 12 || !region.trim() || !country.trim())) {
      setError('Select 1–12 additional cities and specify the region and country.');
      return;
    }
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setBusy(true);
    setError('');
    setResult(null);
    const params: LiveParams = {
      query, cuisine, city, region, country,
      geography_scope: scope, nearby_cities: scope === 'nearby' ? nearby : [],
    };
    try {
      const response = await discoverLive(params, consent, controller.signal);
      if (!controller.signal.aborted) setResult(response);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof ApiError ?
        failure.status === 429 ? 'Live search limit reached. Try again later.' :
        failure.status === 503 ? 'The live web provider is unavailable.' :
        'Could not complete live discovery.' :
        failure instanceof Error ? failure.message : 'Live discovery failed.');
    } finally {
      if (!controller.signal.aborted) { setBusy(false); setConsent(false); }
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }

  return <section id="live-discovery" className="live-discovery" aria-labelledby="live-title">
    <p className="eyebrow">OPTIONAL LIVE WEB DISCOVERY</p>
    <h2 id="live-title">Find restaurants beyond the local catalog.</h2>
    <p>Specify your cuisine and search cities. Expand to nearby municipalities only when you
      choose them explicitly. Online suggestions include source links; current menus, operating
      status and dishes have not been independently confirmed.</p>
    {status === null ? <p role="status">Checking live search availability…</p> :
      !status.enabled ? <p role="status">Live web discovery is disabled on this server. Catalog search remains available.</p> :
      <form className="live-form" onSubmit={submit}>
        <label htmlFor="live-cuisine">Required cuisine</label>
        <input id="live-cuisine" required maxLength={80} value={cuisine}
          onChange={e => { setCuisine(e.target.value); setResult(null); }} placeholder="Persian"/>
        <label htmlFor="live-city">Required city</label>
        <input id="live-city" required maxLength={80} value={city}
          onChange={e => { setCity(e.target.value); setResult(null); }} placeholder="Boston"/>
        <label htmlFor="live-geography-scope">Geographic coverage</label>
        <select id="live-geography-scope" value={scope} onChange={e => {
          setScope(e.target.value as 'city' | 'nearby'); setResult(null);
        }}>
          <option value="city">Exact city only</option>
          <option value="nearby">City plus explicitly selected nearby municipalities</option>
        </select>
        {scope === 'nearby' && <>
          <label htmlFor="live-nearby-cities">Selected nearby cities (comma separated)</label>
          <textarea id="live-nearby-cities" required rows={2} maxLength={960}
            value={nearbyText} onChange={e => { setNearbyText(e.target.value); setResult(null); }}
            placeholder="Cambridge, Somerville, Brookline, Newton" />
          {city.trim().toLocaleLowerCase() === 'boston' &&
            <button type="button" className="live-preset" onClick={() => {
              setNearbyText('Cambridge, Somerville, Brookline, Newton, Watertown, Medford, Quincy');
              setRegion('MA'); setCountry('United States'); setResult(null);
            }}>Use suggested nearby Boston municipalities (editable)</button>}
          <p className="live-help">This is a named-city search, not a distance radius.
            Each city remains a required location filter. No coordinates are guessed.</p>
        </>}
        <div className="live-row">
          <div><label htmlFor="live-region">State / region (optional)</label>
            <input id="live-region" maxLength={80} value={region} onChange={e => { setRegion(e.target.value); setResult(null); }} placeholder="MA"/></div>
          <div><label htmlFor="live-country">Country (optional)</label>
            <input id="live-country" maxLength={80} value={country} onChange={e => { setCountry(e.target.value); setResult(null); }} placeholder="United States"/></div>
        </div>
        <label htmlFor="live-query">Additional request (optional)</label>
        <input id="live-query" maxLength={180} value={query}
          onChange={e => { setQuery(e.target.value); setResult(null); }} placeholder="Traditional food or kebab"/>
        <p className="live-help">Additional words influence search order; they do not prove a
          restaurant serves a requested dish or meets dietary restrictions.</p>
        <label className="ai-consent"><input type="checkbox" checked={consent} disabled={busy}
          onChange={e => setConsent(e.target.checked)}/>
          I agree to send my search terms and selected cities to the external web-search provider.</label>
        <button className="ai-submit" disabled={busy || !consent || !city.trim() || !cuisine.trim() ||
          (scope === 'nearby' && (!nearbyText.trim() || !region.trim() || !country.trim()))} type="submit">
          {busy ? 'Searching the web…' : 'Discover online'}
        </button>
        {error && <p className="ai-error" role="alert">{error}</p>}
      </form>}
    {result && <div className="live-results" aria-live="polite">
      <h3>Results for {result.requested_cuisine} in {
        (result.requested_cities?.length ?? 0) > 1
          ? result.requested_cities?.join(', ') : result.requested_city}</h3>
      {result.catalog_synthetic && <p>Catalog results come from a synthetic example dataset.</p>}
      {result.catalog_results.length > 0 && <div className="live-group">
        <h4>Recorded catalog matches</h4>
        <ul>{result.catalog_results.map(item => <li key={item.item_id}>
          <strong>{item.title}</strong> · {item.city} · {item.cuisines.join(', ')}
          {item.source_url && <a href={item.source_url} target="_blank" rel="noopener noreferrer">Catalog source</a>}
          {(result.linked_sources ?? []).filter(link => link.catalog_item_id === item.item_id).map(link =>
            <a key={link.source_url} href={link.source_url} target="_blank" rel="noopener noreferrer">
              Additional web source: {link.source_title}</a>)}
        </li>)}</ul>
      </div>}
      {result.web_results.length > 0 && <div className="live-group">
        <h4>{result.human_review_required ?
          "Web sources reviewed by a human (current status not guaranteed)" :
          "Web-discovered candidates (unverified)"}</h4>
        <ul>{result.web_results.map(item => <li key={`${item.name}:${item.source_url}`}>
          <strong>{item.name}</strong> · {[item.city, item.region, item.country].filter(Boolean).join(', ')} · source-reported {item.cuisine}
          {' · '}<a href={item.source_url} target="_blank" rel="noopener noreferrer">
            Source: {item.source_title}</a>
        </li>)}</ul>
      </div>}
      {result.catalog_results.length === 0 && result.web_results.length === 0 &&
        <p>{result.human_review_required ?
          "No currently human-reviewed matches for the requested cuisine and selected cities." :
          "No source-supported matches found for the requested cuisine and selected cities."}
          We do not substitute unrelated restaurants.</p>}
      <p className="live-limitations">{result.limitations}</p>
    </div>}
  </section>;
}
