import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, browse, getFacets, getMeta, search, type CatalogItem, type CatalogMeta, type FacetResponse, type Kind } from './lib/api';
import { DEFAULT_DISCOVERY, PAGE_SIZE, SEARCH_LIMIT, parseDiscovery, pushDiscovery, replaceDiscovery, type DiscoveryState } from './lib/searchState';
import { DiscoveryFilters } from './components/DiscoveryFilters';
import { AIFoodDiscovery } from './components/AIFoodDiscovery';
import { LiveRestaurantDiscovery, type LivePrefill } from './components/LiveRestaurantDiscovery';
import { Icon } from './components/Icon';
import { ItemCard } from './components/ItemCard';
import { DetailDialog } from './components/DetailDialog';

export function App() {
  const [discovery, setDiscovery] = useState<DiscoveryState>(() => parseDiscovery(window.location.search));
  const stateRef = useRef(discovery);
  const [draft, setDraft] = useState(discovery.q);
  const [meta, setMeta] = useState<CatalogMeta | null>(null);
  const [facets, setFacets] = useState<FacetResponse | null>(null);
  const [facetsError, setFacetsError] = useState(false);
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loadedKey, setLoadedKey] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<CatalogItem | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [livePrefill, setLivePrefill] = useState<LivePrefill | null>(null);
  const searchBox = useRef<HTMLInputElement>(null);
  const isSearch = Boolean(discovery.q);
  // A stale page count must not rewrite a newly restored URL during popstate.
  const requestKey = JSON.stringify([
    discovery.kind, discovery.q, discovery.city, discovery.cuisine,
    discovery.maxPriceTier, isSearch ? null : discovery.page, retry,
  ]);

  const changeDiscovery = useCallback((patch: Partial<DiscoveryState>) => {
    const next = { ...stateRef.current, ...patch };
    stateRef.current = next;
    pushDiscovery(next);
    setDiscovery(next);
  }, []);

  useEffect(() => {
    const onPop = () => {
      const next = parseDiscovery(window.location.search);
      stateRef.current = next;
      setDiscovery(next);
      setSelected(null);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  useEffect(() => { setDraft(discovery.q); }, [discovery.q]);

  useEffect(() => {
    const controller = new AbortController();
    getMeta(controller.signal).then(setMeta).catch((e: unknown) => {
      if (!controller.signal.aborted) setError(e instanceof ApiError ? e.message : 'Catalog metadata is unavailable.');
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setFacets(null);
    setFacetsError(false);
    getFacets(discovery.kind, controller.signal).then(data => {
      if (!controller.signal.aborted) setFacets(data);
    }).catch(() => { if (!controller.signal.aborted) setFacetsError(true); });
    return () => controller.abort();
  }, [discovery.kind]);

  // Browsing is server-paginated. Ranked search is capped at the API's top 100
  // and paginated locally without changing the backend's result order.
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError('');
    setItems([]);
    setLoadedKey('');
    const filters = {
      city: discovery.kind === 'restaurant' ? discovery.city : '',
      cuisine: discovery.cuisine,
      maxPriceTier: discovery.kind === 'restaurant' ? discovery.maxPriceTier : null,
    };
    const promise = discovery.q
      ? search(discovery.q, discovery.kind, filters, controller.signal)
        .then(data => ({ items: data.results.map(row => row.item), total: data.results.length }))
      : browse(discovery.kind, (discovery.page - 1) * PAGE_SIZE, filters, controller.signal)
        .then(data => ({ items: data.items, total: data.total }));
    promise.then(data => {
      if (!controller.signal.aborted) { setItems(data.items); setTotal(data.total); setLoadedKey(requestKey); }
    }).catch((e: unknown) => {
      if (!controller.signal.aborted) {
        setItems([]);
        setTotal(0);
        setLoadedKey(requestKey);
        setError(e instanceof ApiError ? e.message : 'Unable to load food records.');
      }
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [discovery.kind, discovery.q, discovery.city, discovery.cuisine, discovery.maxPriceTier,
    // Search paging uses the already-ranked 100-result window; avoid refetching on page changes.
    discovery.q ? 0 : discovery.page, retry]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const safePage = Math.min(discovery.page, pageCount);
  const shownItems = isSearch ? items.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE) : items;
  // Correct stale external page links only after results arrive.
  useEffect(() => {
    if (!busy && !error && loadedKey === requestKey && discovery.page > pageCount) {
      const next = { ...stateRef.current, page: pageCount };
      stateRef.current = next;
      replaceDiscovery(next);
      setDiscovery(next);
    }
  }, [busy, error, loadedKey, requestKey, discovery.page, pageCount]);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    changeDiscovery({ q: draft.trim(), page: 1 });
    document.getElementById('explore')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const changeKind = (kind: Kind) => changeDiscovery({ kind, city: '', cuisine: '', maxPriceTier: null, page: 1 });
  const clearFilters = () => changeDiscovery({ city: '', cuisine: '', maxPriceTier: null, page: 1 });
  const reset = () => { setDraft(''); changeDiscovery(DEFAULT_DISCOVERY); searchBox.current?.focus(); };
  const start = (safePage - 1) * PAGE_SIZE;

  return <div className="site-wrap">
    <div className="top-strip"><div className="layout-width"><span><span className="status-dot"/> Independent food discovery</span><span className="top-note">Recorded sources. Clear limitations. Better decisions.</span></div></div>
    <header className="site-header"><div className="layout-width header-inner">
      <a className="wordmark" href="/app/" aria-label="SavoRoute home"><span className="wordmark-mark"><Icon name="leaf" size={19}/></span><span>savo<span className="wordmark-light">route</span><b>.</b></span></a>
      <nav id="main-navigation" className={`main-nav ${menuOpen ? 'nav-open' : ''}`} aria-label="Primary navigation">
        <a href="#explore" onClick={() => setMenuOpen(false)}>Explore</a>
        <a href="#how-it-works" onClick={() => setMenuOpen(false)}>Our approach</a>
        <a href="/" className="legacy-nav" onClick={() => setMenuOpen(false)}>Research interface <Icon name="arrow-up-right" size={14}/></a>
      </nav>
      <div className="header-actions"><a className="header-cta" href="#explore">Browse food <Icon name="arrow" size={17}/></a><button className="menu-toggle icon-button" aria-label={menuOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={menuOpen} aria-controls="main-navigation" onClick={() => setMenuOpen(x => !x)}><Icon name={menuOpen ? 'close' : 'menu'}/></button></div>
    </div></header>
    <main id="content">
      <section className="hero"><div className="layout-width hero-grid"><div className="hero-left">
        <p className="eyebrow"><span className="eyebrow-line"/> FOOD DISCOVERY, WITH CONTEXT</p>
        <h1>Find your next <em>good</em> food decision<span className="title-period">.</span></h1>
        <p className="hero-description">Discover places and recipes using the information actually recorded. Explore what fits your craving, and see what remains unknown.</p>
        <form className="search-form" onSubmit={submitSearch} role="search"><label className="sr-only" htmlFor="food-query">Search food records</label><Icon name="search" size={22}/><input type="search" id="food-query" ref={searchBox} value={draft} onChange={e => setDraft(e.target.value)} placeholder="Try spicy noodles, Italian, or cozy brunch" maxLength={500}/><button type="submit">Search <Icon name="arrow" size={18}/></button></form>
        <div className="quick-row"><span className="quick-label">I'm looking for</span><div role="group" aria-label="Food type" className="kind-switch"><button className={discovery.kind === 'restaurant' ? 'active' : ''} onClick={() => changeKind('restaurant')} aria-pressed={discovery.kind === 'restaurant'} type="button"><Icon name="utensils" size={16}/> Places to eat</button><button className={discovery.kind === 'recipe' ? 'active' : ''} onClick={() => changeKind('recipe')} aria-pressed={discovery.kind === 'recipe'} type="button"><Icon name="book" size={16}/> Recipes</button></div></div>
        <p className="hero-footnote"><Icon name="info" size={15}/> Not live availability, pricing, or dietary verification.</p>
      </div><div className="hero-right" aria-hidden="true"><div className="editorial-card"><div className="editorial-circle circle-1"/><div className="editorial-circle circle-2"/><div className="editorial-plate"><div className="plate-ring"><div className="plate-center"><Icon name="leaf" size={67}/></div></div></div><span className="editorial-word">GOOD FOOD<br/>BETTER CONTEXT</span><span className="editorial-index">SR / 001</span></div><div className="floating-note"><Icon name="check" size={16}/><div><strong>Clearer choices</strong><span>Source first. Guesswork last.</span></div></div></div></div></section>
      <div className="layout-width">
        <AIFoodDiscovery onUseSearch={(query, cuisine) => {
          setDraft(query);
          changeDiscovery({ q: query, cuisine, kind: 'restaurant', maxPriceTier: null, page: 1 });
          document.getElementById('explore')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }} onDiscoverLive={(query, cuisine) => {
          setLivePrefill({ query, cuisine, sequence: Date.now() });
          document.getElementById('live-discovery')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }}/>
        <LiveRestaurantDiscovery prefill={livePrefill}/>
      </div>
      <div className="value-strip"><div className="layout-width value-inner"><div><span className="value-number">01</span><span>Explore with intent</span></div><span className="value-rule"/><div><span className="value-number">02</span><span>Understand the evidence</span></div><span className="value-rule"/><div><span className="value-number">03</span><span>Choose with confidence</span></div></div></div>
      <section id="explore" className="explore-section layout-width"><div className="section-title-row"><div><p className="eyebrow"><span className="eyebrow-line"/> THE COLLECTION</p><h2>{discovery.q ? `Matches for “${discovery.q}”` : discovery.kind === 'restaurant' ? 'Places to explore' : 'Recipes to discover'}</h2><p>Every entry is a catalog record, not a guarantee of current information.</p></div><button className="outline-cta" type="button" onClick={reset}>Reset search <Icon name="arrow" size={17}/></button></div>
        <div className="collection-bar"><div className="collection-status"><span className="status-dot"/><span>{meta ? `${meta.dataset_name} · ${meta.catalog_items} records` : 'Connecting to catalog'}</span>{meta?.catalog_synthetic && <span className="demo-label">FICTIONAL DEMO</span>}</div><div className="collection-kind"><button aria-pressed={discovery.kind === 'restaurant'} className={discovery.kind === 'restaurant' ? 'active' : ''} onClick={() => changeKind('restaurant')}>Restaurants</button><button aria-pressed={discovery.kind === 'recipe'} className={discovery.kind === 'recipe' ? 'active' : ''} onClick={() => changeKind('recipe')}>Recipes</button></div></div>
        <DiscoveryFilters state={discovery} facets={facets} facetsError={facetsError} onChange={changeDiscovery} onClear={clearFilters}/>
        <div role="status" aria-live="polite" aria-atomic="true" className="results-status">{busy ? 'Loading records…' : error || (isSearch ? `${total} ranked matches${total === SEARCH_LIMIT ? ' (100-result API cap)' : ''}` : `${total} recorded entries`)} </div>
        {busy ? <div className="card-grid" aria-label="Loading results">{[0, 1, 2].map(i => <div className="loading-card" key={i}/>)}</div>
          : error ? <div className="empty-state"><Icon name="info" size={27}/><h3>We couldn't load the records.</h3><p>{error}</p><button className="text-action" onClick={() => setRetry(x => x + 1)} type="button">Try again <Icon name="arrow" size={17}/></button></div>
            : shownItems.length ? <><div className="card-grid">{shownItems.map((item, index) => <ItemCard key={item.item_id} item={item} index={start + index} onView={setSelected}/>)}</div>
              {total > PAGE_SIZE && <nav className="pagination" aria-label="Result pages"><button className="outline-cta" disabled={safePage === 1} onClick={() => changeDiscovery({ page: safePage - 1 })} type="button">Previous</button><span>Page {safePage} of {pageCount} · {start + 1}–{Math.min(start + PAGE_SIZE, total)} of {total}</span><button className="outline-cta" disabled={safePage >= pageCount} onClick={() => changeDiscovery({ page: safePage + 1 })} type="button">Next <Icon name="arrow" size={16}/></button></nav>}
              {isSearch && total === SEARCH_LIMIT && <p className="search-limit-note">Only the first 100 ranked matches are available from this search endpoint. Refine your query or filters for more specific results.</p>}
              </>
              : <div className="empty-state"><Icon name="search" size={30}/><h3>No matching records yet.</h3><p>Try a broader term or remove a filter. Missing metadata is not evidence that a place does not meet your needs.</p><button className="text-action" onClick={reset} type="button">View all records <Icon name="arrow" size={17}/></button></div>}
      </section>
      <section id="how-it-works" className="approach-section"><div className="layout-width approach-grid"><div><p className="eyebrow eyebrow-light">A DIFFERENT KIND OF DISCOVERY</p><h2>Good recommendations start with <em>honest information.</em></h2></div><div className="approach-right"><p>We distinguish what's recorded from what's verified, so you can make informed decisions. No invented ratings, no implied real-time availability, and no hidden claims of dietary safety.</p><a href="/docs" className="approach-link">Explore the underlying API <Icon name="arrow-up-right" size={17}/></a></div></div></section>
      <div className="layout-width bottom-note"><Icon name="info" size={19}/><p>{meta?.catalog_synthetic ? 'This is a fictional demonstration catalog. Restaurant and recipe entries here do not represent verified real-world recommendations.' : 'Catalog entries may be incomplete or stale. Always verify critical details with the original provider.'}</p></div>
    </main>
    <footer className="footer"><div className="layout-width footer-inner"><span className="footer-brand">savoroute<span>.</span></span><span>Food discovery with context</span><a href="/">Developer interface <Icon name="arrow-up-right" size={14}/></a></div></footer>
    <DetailDialog item={selected} onClose={() => setSelected(null)}/>
  </div>;
}
