import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, browse, getMeta, search, type CatalogItem, type CatalogMeta, type Kind } from './lib/api';
import { Icon } from './components/Icon';
import { ItemCard } from './components/ItemCard';
import { DetailDialog } from './components/DetailDialog';

export function App() {
  const [kind, setKind] = useState<Kind>('restaurant');
  const [query, setQuery] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [meta, setMeta] = useState<CatalogMeta | null>(null);
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<CatalogItem | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const searchBox = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    getMeta(controller.signal).then(setMeta).catch((e: unknown) => {
      if (!controller.signal.aborted) setError(e instanceof ApiError ? e.message : 'Catalog metadata is unavailable.');
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setError('');
    const promise = activeQuery ? search(activeQuery, kind, controller.signal)
      .then(data => ({ items: data.results.map(row => row.item), total: data.results.length }))
      : browse(kind, offset, controller.signal).then(data => ({ items: data.items, total: data.total }));
    promise.then(data => { if (!controller.signal.aborted) { setItems(data.items); setTotal(data.total); } })
      .catch((e: unknown) => { if (!controller.signal.aborted) { setItems([]); setError(e instanceof ApiError ? e.message : 'Unable to load food records.'); } })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [kind, activeQuery, offset]);

  const changeKind = (next: Kind) => { setKind(next); setOffset(0); setActiveQuery(''); setQuery(''); };
  const onSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!query.trim()) { setActiveQuery(''); setOffset(0); return; }
    if (query.trim().length > 500) { setError('Search must be at most 500 characters.'); return; }
    setOffset(0); setActiveQuery(query.trim());
    document.getElementById('explore')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
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
        <form className="search-form" onSubmit={onSearch} role="search"><label className="sr-only" htmlFor="food-query">Search food records</label><Icon name="search" size={22}/><input type="search" id="food-query" ref={searchBox} value={query} onChange={e => setQuery(e.target.value)} placeholder="Try spicy noodles, Italian, or cozy brunch" maxLength={500}/><button type="submit">Search <Icon name="arrow" size={18}/></button></form>
        <div className="quick-row"><span className="quick-label">I'm looking for</span><div role="group" aria-label="Food type" className="kind-switch"><button className={kind === 'restaurant' ? 'active' : ''} onClick={() => changeKind('restaurant')} aria-pressed={kind === 'restaurant'} type="button"><Icon name="utensils" size={16}/> Places to eat</button><button className={kind === 'recipe' ? 'active' : ''} onClick={() => changeKind('recipe')} aria-pressed={kind === 'recipe'} type="button"><Icon name="book" size={16}/> Recipes</button></div></div>
        <p className="hero-footnote"><Icon name="info" size={15}/> Not live availability, pricing, or dietary verification.</p>
      </div><div className="hero-right" aria-hidden="true"><div className="editorial-card"><div className="editorial-circle circle-1"/><div className="editorial-circle circle-2"/><div className="editorial-plate"><div className="plate-ring"><div className="plate-center"><Icon name="leaf" size={67}/></div></div></div><span className="editorial-word">GOOD FOOD<br/>BETTER CONTEXT</span><span className="editorial-index">SR / 001</span></div><div className="floating-note"><Icon name="check" size={16}/><div><strong>Clearer choices</strong><span>Source first. Guesswork last.</span></div></div></div></div></section>
      <div className="value-strip"><div className="layout-width value-inner"><div><span className="value-number">01</span><span>Explore with intent</span></div><span className="value-rule"/><div><span className="value-number">02</span><span>Understand the evidence</span></div><span className="value-rule"/><div><span className="value-number">03</span><span>Choose with confidence</span></div></div></div>
      <section id="explore" className="explore-section layout-width"><div className="section-title-row"><div><p className="eyebrow"><span className="eyebrow-line"/> THE COLLECTION</p><h2>{activeQuery ? `Matches for “${activeQuery}”` : kind === 'restaurant' ? 'Places to explore' : 'Recipes to discover'}</h2><p>Every entry is a catalog record, not a guarantee of current information.</p></div><button className="outline-cta" type="button" onClick={() => { setActiveQuery(''); setQuery(''); setOffset(0); searchBox.current?.focus(); }}>Reset search <Icon name="arrow" size={17}/></button></div>
        <div className="collection-bar"><div className="collection-status"><span className="status-dot"/><span>{meta ? `${meta.dataset_name} · ${meta.catalog_items} records` : 'Connecting to catalog'}</span>{meta?.catalog_synthetic && <span className="demo-label">FICTIONAL DEMO</span>}</div><div className="collection-kind"><button aria-pressed={kind === 'restaurant'} className={kind === 'restaurant' ? 'active' : ''} onClick={() => changeKind('restaurant')}>Restaurants</button><button aria-pressed={kind === 'recipe'} className={kind === 'recipe' ? 'active' : ''} onClick={() => changeKind('recipe')}>Recipes</button></div></div>
        <div role="status" aria-live="polite" className="results-status">{busy ? 'Loading records…' : error || `${total} ${activeQuery ? 'search matches' : 'recorded entries'}`}</div>
        {busy ? <div className="card-grid" aria-label="Loading results">{[0, 1, 2].map(i => <div className="loading-card" key={i}/>)}</div>
          : error ? <div className="empty-state"><Icon name="info" size={27}/><h3>We couldn't load the records.</h3><p>{error}</p><a href="/">Open the existing research interface <Icon name="arrow-up-right" size={16}/></a></div>
            : items.length ? <><div className="card-grid">{items.map((item, index) => <ItemCard key={item.item_id} item={item} index={offset + index} onView={setSelected}/>)}</div>{!activeQuery && total > 9 && <div className="pagination"><button className="outline-cta" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 9))} type="button">Previous</button><span>{offset + 1}–{Math.min(offset + 9, total)} of {total}</span><button className="outline-cta" disabled={offset + 9 >= total} onClick={() => setOffset(offset + 9)} type="button">Next <Icon name="arrow" size={16}/></button></div>}</>
              : <div className="empty-state"><Icon name="search" size={30}/><h3>No matching records yet.</h3><p>Try a broader term or switch between restaurants and recipes. Missing metadata is not evidence that a place does not meet your needs.</p><button className="text-action" onClick={() => {setActiveQuery('');setQuery('');}} type="button">View all records <Icon name="arrow" size={17}/></button></div>}
      </section>
      <section id="how-it-works" className="approach-section"><div className="layout-width approach-grid"><div><p className="eyebrow eyebrow-light">A DIFFERENT KIND OF DISCOVERY</p><h2>Good recommendations start with <em>honest information.</em></h2></div><div className="approach-right"><p>We distinguish what's recorded from what's verified, so you can make informed decisions. No invented ratings, no implied real-time availability, and no hidden claims of dietary safety.</p><a href="/docs" className="approach-link">Explore the underlying API <Icon name="arrow-up-right" size={17}/></a></div></div></section>
      <div className="layout-width bottom-note"><Icon name="info" size={19}/><p>{meta?.catalog_synthetic ? 'This is a fictional demonstration catalog. Restaurant and recipe entries here do not represent verified real-world recommendations.' : 'Catalog entries may be incomplete or stale. Always verify critical details with the original provider.'}</p></div>
    </main>
    <footer className="footer"><div className="layout-width footer-inner"><span className="footer-brand">savoroute<span>.</span></span><span>Food discovery with context</span><a href="/">Developer interface <Icon name="arrow-up-right" size={14}/></a></div></footer>
    <DetailDialog item={selected} onClose={() => setSelected(null)}/>
  </div>;
}
